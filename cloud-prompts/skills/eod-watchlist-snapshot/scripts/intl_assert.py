#!/usr/bin/env python3
"""Build-time assertions for cron #05's international EOD artifact.

The artifact is a DIRECTORY: one ``<region>.csv`` per region (16 of them), ``summary.md``,
``_manifest.json``, ``_excluded.json`` and ``_carryover.json``.

This module checks the four contract assertions that the skill spec pins, so the checks are
run against the artifact instead of being re-derived by eye on every fire:

  1. **No unaccounted cap.** Every row's ``market_cap`` comes from its own line or from a
     ``cap_source_symbol`` that resolves to the same issuer. The carry must land on a
     ``common`` line of the same ticker root, and a published row never points at a
     ``cap_source_symbol`` that is not in the file.
  2. **Every excluded row has a reason** from the closed set, the manifest's per-reason counts
     equal ``_excluded.json``'s, and the reconciliation identity holds per region.
  3. **The summary's tables reconcile against the CSVs and the manifest** - every ticker in a
     published table exists in that region's CSV, and the row counts match the manifest.
  4. **Every mover row carries ``us_listing``** and every non-empty ``price_conflict`` parses.

Exit codes: ``0`` publishable, ``1`` a contract violation, ``2`` the artifact could not be read.

Usage::

    python3 intl_assert.py --dir /workspace/international-eod/2026-11-05
    python3 intl_assert.py --dir <dir> --json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------------------
# Contract constants - these mirror the skill spec. Keep the two in step.
# --------------------------------------------------------------------------------------

PROVENANCE_COLUMNS = ("cap_source_symbol", "share_class", "us_listing", "price_conflict")

SHARE_CLASSES = ("common", "preferred", "unit", "other")

US_LISTINGS = ("NYSE", "NASDAQ", "ADR", "OTC", "none")

EXCLUSION_REASONS = (
    "no_market_cap",
    "below_cap_floor",
    "below_volume",
    "issuer_unresolved",
    "cap_issuer_mismatch",
    "stale_venue_print",
)

#: summary.md sections that publish names, mapped to the manifest counter they must match.
SUMMARY_SECTIONS = {
    "Top movers": "mover_rows",
    "Below the gate": "below_gate_rows",
    "No catalyst": "no_catalyst_rows",
}

#: The published shape of a price conflict cell.
PRICE_CONFLICT_RE = re.compile(
    r"^official=(?P<official>\S+)\s+source=(?P<source>.+?)\s+"
    r"third_party=(?P<third>\S+)\s+delta=(?P<delta>\S+)"
)

#: A class phrase in a description: everything from here on describes the LINE, not the issuer.
_CLASS_MARKER_RE = re.compile(
    r"\b(cum|pref|preferred|unit|class|non-voting|nonvoting|depositary|ads|gdr)\b", re.I
)

_TICKER_RE = re.compile(r"`([A-Z0-9.\-]+:[A-Z0-9._\-]+)`")


# --------------------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------------------


class Finding:
    """One assertion outcome. ``severity`` is ``FAIL`` (blocking) or ``WARN`` (heuristic)."""

    __slots__ = ("severity", "check", "message")

    def __init__(self, severity: str, check: str, message: str):
        self.severity = severity
        self.check = check
        self.message = message

    def as_dict(self) -> dict:
        return {"severity": self.severity, "check": self.check, "message": self.message}

    def __str__(self) -> str:
        return f"{self.severity:<5} {self.check}: {self.message}"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def ticker_root(ticker: str) -> str:
    """``TSX:ENB.PR.B`` -> ``TSX:ENB``.

    The venue-qualified symbol up to the first share-class suffix. This is the deterministic
    half of the issuer key: the same root means the same issuer.
    """
    venue, sep, symbol = (ticker or "").partition(":")
    if not sep:
        venue, symbol = "", venue
    root = symbol.split(".")[0]
    return f"{venue}:{root}" if venue else root


def issuer_name(name: str) -> str:
    """The issuer part of a description: everything before the first class phrase."""
    match = _CLASS_MARKER_RE.search(name or "")
    if not match:
        return (name or "").strip()
    return (name or "")[: match.start()].strip()


def normalised(name: str) -> str:
    """A comparison form of the issuer name: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", issuer_name(name).lower())


def read_csv_rows(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_region_csvs(directory: Path) -> dict:
    """Every ``<region>.csv`` in the directory, keyed by region code."""
    regions = {}
    for path in sorted(directory.glob("*.csv")):
        regions[path.stem] = read_csv_rows(path)
    return regions


def parse_summary_tables(summary_text: str) -> dict:
    """Extract the published tables from ``summary.md``.

    Returns ``{section: [ {"region": ..., "ticker": ...}, ... ]}``. A row's region comes from
    the nearest ``###`` sub-heading, or from the row's first cell when the table carries a
    region column.
    """
    found = {section: [] for section in SUMMARY_SECTIONS}
    section = None
    region = None
    for line in summary_text.splitlines():
        heading = re.match(r"^(#{2,4})\s+(.*\S)\s*$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if level == 2:
                # A level-2 heading that is not a publishing section ENDS the current one.
                if title in SUMMARY_SECTIONS:
                    section = title
                    region = None
                else:
                    section = None
                    region = None
            elif section is not None:
                region = title
            continue
        if section is None or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or all(set(c) <= set("-: ") for c in cells):
            continue  # a separator row
        match = _TICKER_RE.search(line)
        if not match:
            continue  # a header row or a prose table
        row_region = region
        if row_region is None and cells:
            candidate = cells[0].strip("`")
            if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", candidate):
                row_region = candidate
        found[section].append({"region": row_region, "ticker": match.group(1), "cells": cells})
    return found


# --------------------------------------------------------------------------------------
# The four assertions
# --------------------------------------------------------------------------------------


def check_cap_provenance(regions: dict, findings: list) -> None:
    """Assertion 1 - no unaccounted cap."""
    for region, rows in regions.items():
        if not rows:
            continue
        header = rows[0].keys()
        missing = [c for c in PROVENANCE_COLUMNS if c not in header]
        if missing:
            findings.append(
                Finding(
                    "FAIL",
                    "cap-provenance",
                    f"{region}.csv is missing the provenance column(s) {', '.join(missing)} - "
                    f"the artifact predates the 18-column schema and must be rebuilt, not patched",
                )
            )
            continue

        by_ticker = {r.get("ticker"): r for r in rows}
        for row in rows:
            ticker = row.get("ticker", "")
            source = (row.get("cap_source_symbol") or "").strip()
            share_class = (row.get("share_class") or "").strip()
            us_listing = (row.get("us_listing") or "").strip()

            if not source:
                findings.append(
                    Finding("FAIL", "cap-provenance", f"{region}.csv {ticker}: empty cap_source_symbol")
                )
                continue

            if share_class not in SHARE_CLASSES:
                findings.append(
                    Finding(
                        "FAIL",
                        "cap-provenance",
                        f"{region}.csv {ticker}: share_class '{share_class}' is not one of "
                        f"{', '.join(SHARE_CLASSES)}",
                    )
                )
            if us_listing not in US_LISTINGS:
                findings.append(
                    Finding(
                        "FAIL",
                        "cap-provenance",
                        f"{region}.csv {ticker}: us_listing '{us_listing}' is not one of "
                        f"{', '.join(US_LISTINGS)}",
                    )
                )

            if source == ticker:
                if share_class and share_class != "common":
                    findings.append(
                        Finding(
                            "FAIL",
                            "cap-provenance",
                            f"{region}.csv {ticker}: a '{share_class}' line carries its own cap; "
                            f"a non-common line must carry the issuer's cap from the primary line",
                        )
                    )
                continue

            # A carried cap: it must land on a published common line of the same issuer.
            if source not in by_ticker:
                findings.append(
                    Finding(
                        "FAIL",
                        "cap-provenance",
                        f"{region}.csv {ticker}: cap_source_symbol '{source}' is not in the file - "
                        f"the issuer group was not resolved before the floor was applied",
                    )
                )
                continue
            source_row = by_ticker[source]
            if (source_row.get("share_class") or "").strip() != "common":
                findings.append(
                    Finding(
                        "FAIL",
                        "cap-provenance",
                        f"{region}.csv {ticker}: cap_source_symbol '{source}' is not a common line",
                    )
                )
            if ticker_root(source) != ticker_root(ticker):
                findings.append(
                    Finding(
                        "FAIL",
                        "cap-provenance",
                        f"{region}.csv {ticker}: cap carried from '{source}' - a different issuer "
                        f"(roots '{ticker_root(ticker)}' vs '{ticker_root(source)}')",
                    )
                )
            elif normalised(source_row.get("name", "")) != normalised(row.get("name", "")):
                findings.append(
                    Finding(
                        "WARN",
                        "cap-provenance",
                        f"{region}.csv {ticker}: carried from '{source}' but the descriptions "
                        f"'{row.get('name')}' / '{source_row.get('name')}' do not reduce to the "
                        f"same issuer name",
                    )
                )


def check_exclusions(directory: Path, manifest: dict, findings: list) -> None:
    """Assertion 2 - every excluded row has a reason, and the counts agree."""
    excluded_path = directory / "_excluded.json"
    excluded = {}
    if excluded_path.exists():
        try:
            excluded = json.loads(excluded_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a malformed file is a build defect
            findings.append(Finding("FAIL", "exclusions", f"_excluded.json is not valid JSON: {exc}"))
            return
    else:
        findings.append(Finding("FAIL", "exclusions", "_excluded.json is missing"))

    per_region = {}
    for region, rows in (excluded or {}).items():
        counts = {}
        for row in rows or []:
            reason = (row.get("reason") or "").strip()
            if not reason:
                findings.append(
                    Finding(
                        "FAIL",
                        "exclusions",
                        f"_excluded.json {region} {row.get('ticker', '?')}: empty reason",
                    )
                )
                continue
            if reason not in EXCLUSION_REASONS:
                findings.append(
                    Finding(
                        "FAIL",
                        "exclusions",
                        f"_excluded.json {region} {row.get('ticker', '?')}: reason '{reason}' is "
                        f"not one of {', '.join(EXCLUSION_REASONS)}",
                    )
                )
            counts[reason] = counts.get(reason, 0) + 1
        per_region[region] = counts

    regions = (manifest or {}).get("regions") or {}
    for region, stats in regions.items():
        manifest_counts = stats.get("excluded") or {}
        if not manifest_counts:
            findings.append(
                Finding(
                    "FAIL",
                    "exclusions",
                    f"_manifest.json {region}: no per-reason 'excluded' counts - the coverage "
                    f"table cannot be reconciled against _excluded.json",
                )
            )
            continue
        file_counts = per_region.get(region, {})
        for reason in EXCLUSION_REASONS:
            expected = manifest_counts.get(reason, 0) or 0
            actual = file_counts.get(reason, 0)
            if expected != actual:
                findings.append(
                    Finding(
                        "FAIL",
                        "exclusions",
                        f"{region}: manifest says {expected} '{reason}' but _excluded.json has {actual}",
                    )
                )

        unique = stats.get("unique_instruments")
        written = stats.get("written")
        if isinstance(unique, int) and isinstance(written, int):
            total_excluded = sum(v for v in (manifest_counts or {}).values() if isinstance(v, int))
            if unique != written + total_excluded:
                findings.append(
                    Finding(
                        "FAIL",
                        "exclusions",
                        f"{region}: unique_instruments ({unique}) != written ({written}) + "
                        f"excluded ({total_excluded}) - rows were lost or double-counted",
                    )
                )


def check_summary_reconciliation(
    directory: Path, regions: dict, manifest: dict, findings: list
) -> None:
    """Assertion 3 - the summary's tables reconcile against the CSVs and the manifest."""
    summary_path = directory / "summary.md"
    if not summary_path.exists():
        findings.append(Finding("FAIL", "summary", "summary.md is missing"))
        return

    tables = parse_summary_tables(summary_path.read_text(encoding="utf-8"))
    manifest_regions = (manifest or {}).get("regions") or {}

    for section, counter in SUMMARY_SECTIONS.items():
        rows = tables.get(section) or []
        if not rows:
            continue
        per_region = {}
        for row in rows:
            region = row["region"]
            if region is None:
                findings.append(
                    Finding(
                        "FAIL",
                        "summary",
                        f"summary.md '## {section}': a row for '{row['ticker']}' has no region - "
                        f"the table must be one per region",
                    )
                )
                continue
            per_region.setdefault(region, []).append(row["ticker"])

        for region, tickers in per_region.items():
            csv_rows = regions.get(region)
            if csv_rows is None:
                findings.append(
                    Finding(
                        "FAIL",
                        "summary",
                        f"summary.md '## {section}': region '{region}' has no {region}.csv",
                    )
                )
                continue
            known = {r.get("ticker") for r in csv_rows}
            for ticker in tickers:
                if ticker not in known:
                    findings.append(
                        Finding(
                            "FAIL",
                            "summary",
                            f"summary.md '## {section}': {region} '{ticker}' is not in "
                            f"{region}.csv - a published row the CSV does not contain is fabricated",
                        )
                    )
            expected = (manifest_regions.get(region) or {}).get(counter)
            if isinstance(expected, int) and expected != len(tickers):
                findings.append(
                    Finding(
                        "FAIL",
                        "summary",
                        f"summary.md '## {section}': {region} publishes {len(tickers)} names, "
                        f"the manifest says {expected}",
                    )
                )

    # Every mover row carries us_listing, and every price_conflict parses.
    for region, rows in regions.items():
        for row in rows:
            conflict = (row.get("price_conflict") or "").strip()
            if conflict and not PRICE_CONFLICT_RE.match(conflict):
                findings.append(
                    Finding(
                        "FAIL",
                        "price-conflict",
                        f"{region}.csv {row.get('ticker')}: price_conflict '{conflict}' does not "
                        f"parse as 'official=… source=… third_party=… delta=…'",
                    )
                )
            us_listing = (row.get("us_listing") or "").strip()
            if us_listing not in US_LISTINGS:
                findings.append(
                    Finding(
                        "FAIL",
                        "price-conflict",
                        f"{region}.csv {row.get('ticker')}: mover row without a valid us_listing",
                    )
                )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def assert_artifact(directory: Path) -> list:
    """Run every assertion against a built directory and return the findings."""
    findings: list = []
    if not directory.is_dir():
        return [Finding("FAIL", "artifact", f"{directory} is not a directory")]

    manifest_path = directory / "_manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding("FAIL", "artifact", f"_manifest.json is not valid JSON: {exc}"))
    else:
        findings.append(Finding("FAIL", "artifact", "_manifest.json is missing"))

    regions = read_region_csvs(directory)
    if not regions:
        findings.append(Finding("FAIL", "artifact", "no region CSVs found"))

    check_cap_provenance(regions, findings)
    check_exclusions(directory, manifest, findings)
    check_summary_reconciliation(directory, regions, manifest, findings)
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="the built artifact directory")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="treat a WARN as a failure (the heuristic checks become blocking)",
    )
    args = parser.parse_args(argv)

    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"intl_assert: {directory} is not a directory")
        return 2

    findings = assert_artifact(directory)
    failures = [f for f in findings if f.severity == "FAIL"]
    warnings = [f for f in findings if f.severity == "WARN"]

    if args.json:
        print(
            json.dumps(
                {
                    "dir": str(directory),
                    "failures": len(failures),
                    "warnings": len(warnings),
                    "findings": [f.as_dict() for f in findings],
                },
                indent=1,
            )
        )
    else:
        for finding in findings:
            print(finding)
        print(f"intl_assert: {len(failures)} failure(s), {len(warnings)} warning(s)")

    if failures:
        return 1
    if warnings and args.strict_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
check_breadth_artifact.py — assert the cron #10 breadth-snapshot artifact contract.

Do not eyeball it. The 2026-11-03 artifact was mechanically correct and reader-hostile:
the single most-watched breadth number in existence (the advance/decline tally) was
missing, and the routine said so in a caveat instead of publishing it; "65.19% of the
902 large caps are above their 20-DMA" was a number with no context (65% is unremarkable
in one regime and alarming in another); and the run's genuinely new finding — the broad
market healthy while the index posture was weak — was buried in a bullet instead of
being a named metric with its own row and its own line in the reply. This script turns
those acceptance criteria into machine assertions, so a run that breaks the contract
FAILS instead of shipping.

USAGE
    python3 check_breadth_artifact.py --md  daily-screens/<date>/breadth-snapshot.md \
                                      --csv daily-screens/<date>/breadth-snapshot.csv \
                                      [--json daily-screens/<date>/breadth-snapshot.json] \
                                      [--regime daily-screens/<date>/_regime-intraday.json] \
                                      [--reply /workspace/reply.txt]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

import argparse
import csv
import json
import os
import re
import sys

CONTRACT_VERSION = "breadth-artifact-v1"

# The published constants (they live in the skill spec; keep the two in sync).
DIVERGENCE_BANDS = {"BROAD", "MATCHED", "NARROW"}
PCTILE_BANDS = {"ABOVE_NORMAL", "NORMAL", "BELOW_NORMAL"}

# The section skeleton, in order. Matched by normalized heading text so a dated or
# annotated heading ("## Breadth — 2026-11-04 settled session") still satisfies it.
REQUIRED_SECTIONS = [
    "tldr",
    "breadth",
    "participation",
    "breadthpercentile",
    "breadthdivergence",
    "indexpositioning",
    "livetape",
    "volatility",
    "regime",
    "flags",
    "methodsourcehealthcaveats",
]

# The regime flags must be SEPARATE structured front-matter fields.
REQUIRED_FRONTMATTER = [
    "size_cut_pct",
    "uncertainty",
    "late_cycle",
    "data_date",
    "live_date",
    "breadth_universe",
    "cross_reference",
]

REQUIRED_CSV_COLS = [
    "date", "n_lc", "pct_above_sma_20", "pct_above_sma_50",
    "n_etf_above_sma_20", "n_etf_above_sma_50", "breadth_divergence_pp",
    "advancing", "declining", "unchanged", "ad_net", "adl_cum", "adl_slope_10d",
    "breadth_pctile_1y", "divergence_pctile_1y", "is_data_date",
]

REGIME_REQUIRED_KEYS = (
    "size_cut_pct", "uncertainty", "late_cycle", "breadth_pct_spx",
    "index_below_20sma", "vix", "vix3m", "atr_extensions",
)

NUM = r"[-+]?\d+(?:\.\d+)?"


# ----------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------
def norm(text: str) -> str:
    """Normalize a heading for prefix matching."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_frontmatter(md: str) -> dict:
    """Parse the YAML-ish front matter into a flat dict of scalars.

    A flat parser on purpose: this checker asserts the regime flags are SEPARATE
    fields, so it must not paper over a nested block.
    """
    out = {}
    if not md.startswith("---"):
        return out
    end = md.find("\n---", 3)
    if end == -1:
        return out
    block = md[3:end]
    for line in block.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            continue  # nested — the flat contract forbids it for the regime flags
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def split_sections(md: str) -> dict:
    """Map normalized section name -> the body text under it."""
    sections = {}
    current = None
    buf = []
    in_fm = md.startswith("---")
    if in_fm:
        end = md.find("\n---", 3)
        md_body = md[end + 4:] if end != -1 else md
    else:
        md_body = md
    for line in md_body.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf)
            current = norm(line[3:])
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def find_section(sections: dict, wanted: str):
    """Return (key, body) for the first section whose normalized name starts with `wanted`.

    Matching is done on the name with the spaces REMOVED, so `breadthpercentile` matches
    "## Breadth percentile — …" and `methodsourcehealthcaveats` matches
    "## Method, source health & caveats".
    """
    want = wanted.replace(" ", "")
    for key, body in sections.items():
        k = key.replace(" ", "")
        if k == want or k.startswith(want):
            return key, body
    return None, None


def numbers_in(text: str):
    return [float(x) for x in re.findall(NUM, text.replace(",", ""))]


def parse_bool(value: str):
    v = str(value).strip().strip("\"'").lower()
    if v in ("true", "yes"):
        return True
    if v in ("false", "no"):
        return False
    return None


# ----------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------
def check(md_path, csv_path, json_path, regime_path, reply_path):
    failures = []
    notes = []

    for p in (md_path, csv_path):
        if not p or not os.path.exists(p):
            failures.append(f"MISSING FILE: {p}")
    if failures:
        return failures, notes

    md = open(md_path, encoding="utf-8").read()
    sections = split_sections(md)
    fm = parse_frontmatter(md)

    # --- 1. the contract marker ------------------------------------------------------
    # The marker may sit in the front matter or on the marker line just under it.
    head = "\n".join(md.splitlines()[:40])
    if CONTRACT_VERSION not in head and CONTRACT_VERSION not in parse_frontmatter(md):
        failures.append(
            f"the contract marker `{CONTRACT_VERSION}` is not in the front matter or the "
            "first 40 lines"
        )

    # --- 1b. no stub markers survive --------------------------------------------------
    for marker in ("<!-- FILL", "<!-- TODO", "PLACEHOLDER", "TODO:"):
        if marker in md:
            failures.append(
                f"the artifact still carries a stub marker ({marker!r}) — the live layer was "
                "not filled in; a stub must not ship"
            )
            break

    # --- 2. front matter: the regime flags are SEPARATE structured fields -------------
    for key in REQUIRED_FRONTMATTER:
        if key not in fm:
            failures.append(f"front matter is missing the field `{key}`")
    if "regime" in fm:
        val = str(fm["regime"]).lower()
        if "uncertainty" in val or "late_cycle" in val or "size_cut" in val:
            failures.append(
                "front matter carries the regime flags as ONE concatenated string in `regime` — "
                "they must be separate fields (size_cut_pct / uncertainty / late_cycle)"
            )
    if "size_cut_pct" in fm:
        try:
            int(str(fm["size_cut_pct"]).strip())
        except ValueError:
            failures.append(f"front matter `size_cut_pct` is not an integer: {fm['size_cut_pct']!r}")
    for flag in ("uncertainty", "late_cycle"):
        if flag in fm and parse_bool(fm[flag]) is None:
            failures.append(f"front matter `{flag}` is not a boolean: {fm[flag]!r}")

    # --- 2b. the cross-reference must name a REAL counterpart --------------------------
    # The renderer used to hardcode the literal template `daily-screens/<date>/breadth.md`,
    # so the published artifact carried a placeholder that points at nothing, and the
    # checker did not look at the field at all. The end-of-day counterpart of an intraday
    # read is the directory of the FIRE date (cron #09 closes that same session at
    # 18:30 ET), so the path must carry the live_date, not the settled data_date.
    xr = fm.get("cross_reference", "")
    if xr:
        if "<date>" in xr or not re.search(r"\d{4}-\d{2}-\d{2}", xr):
            failures.append(
                "front matter `cross_reference` carries no concrete date — the literal "
                f"`<date>` placeholder must not ship: {xr!r}"
            )
        elif fm.get("live_date") and fm["live_date"] not in xr:
            failures.append(
                f"front matter `cross_reference` does not name the live_date's end-of-day "
                f"counterpart ({fm['live_date']}): {xr!r}"
            )

    # --- 3. the section skeleton, in order --------------------------------------------
    seen = []
    for wanted in REQUIRED_SECTIONS:
        key, _ = find_section(sections, wanted)
        if key is None:
            failures.append(f"missing section `## {wanted}`")
        else:
            seen.append(key)
    positions = []
    for wanted in REQUIRED_SECTIONS:
        key, _ = find_section(sections, wanted)
        if key is not None:
            positions.append(list(sections).index(key))
    if len(positions) == len(REQUIRED_SECTIONS) and positions != sorted(positions):
        failures.append(
            "the sections are out of order: "
            + " → ".join(s for s in sections if s in seen)
        )

    # --- 4. the TL;DR: exactly three bullets ------------------------------------------
    _, tldr = find_section(sections, "tldr")
    if tldr is not None:
        bullets = [ln for ln in tldr.splitlines()
                   if re.match(r"^\s*([-*•]|\d+\.)\s+\S", ln)]
        if len(bullets) != 3:
            failures.append(
                f"the TL;DR must carry exactly 3 bullets (what breadth did · the one important "
                f"divergence · the caveat that changes how to read it) — found {len(bullets)}"
            )

    # --- 5. the advance/decline tally, IN THE HEADLINE TABLE -------------------------
    _, breadth = find_section(sections, "breadth")
    if breadth is not None:
        low = breadth.lower()
        if "advancing" not in low or "declining" not in low:
            failures.append(
                "the breadth table carries no advance/decline tally — publish advancing / "
                "declining / unchanged counts in the FIRST table, not a caveat"
            )
        else:
            rows = [ln for ln in breadth.splitlines() if ln.strip().startswith("|")]
            ad_row = None
            for ln in rows:
                if "advancing" in ln.lower() and "declining" in ln.lower():
                    ad_row = ln
                    break
            if ad_row is None:
                failures.append("no table row carries the advancing/declining counts")
            else:
                nums = numbers_in(ad_row)
                if not nums:
                    failures.append(
                        "the advance/decline row carries no numbers — publish the counts"
                    )
                if "proxy" in ad_row.lower():
                    low_row = ad_row.lower()
                    has_limit = ("not an advance/decline" in low_row
                                 or "cap-weight" in low_row or "cap weight" in low_row
                                 or "proxy" in low_row and "not" in low_row)
                    if not has_limit:
                        failures.append(
                            "the advance/decline row is labelled a proxy but does not state the "
                            "proxy's limitation in the table itself"
                        )
    # a proxy used ANYWHERE must be limited where it is used
    for ln in md.splitlines():
        low = ln.lower()
        if "proxy" in low and "not an advance/decline" not in low and "cap-weight" not in low \
                and "cap weight" not in low:
            failures.append(
                f"a proxy is mentioned without its limitation on the same line: {ln.strip()[:120]!r}"
            )
            break

    # --- 6. the percentile --------------------------------------------------------------
    # The band must sit on the SAME LINE as the field. Scanning the whole section would
    # accept an artifact whose table dropped the band but whose prose still mentions it.
    _, pct = find_section(sections, "breadthpercentile")
    if pct is not None:
        # `\b` matters: `breadth_pctile_1y_50dma` CONTAINS `breadth_pctile_1y` as a
        # prefix, and without the boundary the check would read the 50-DMA percentile.
        target = None
        value = None
        for ln in pct.splitlines():
            mm = re.search(r"breadth_pctile_1y\b\D{0,20}(" + NUM + r")", ln)
            if mm:
                target, value = ln, float(mm.group(1))
                break
        if target is None:
            failures.append(
                "the percentile section does not publish the field `breadth_pctile_1y` "
                "with a number beside it"
            )
        else:
            if not (0.0 <= value <= 100.0):
                failures.append(
                    f"`breadth_pctile_1y` = {value} is outside 0..100"
                )
            if not any(b in target for b in PCTILE_BANDS):
                failures.append(
                    "the `breadth_pctile_1y` row publishes no band — use one of "
                    + ", ".join(sorted(PCTILE_BANDS))
                )

    # --- 7. the divergence ---------------------------------------------------------------
    # The value carries its unit ("pp") and the band must sit on the SAME LINE as the
    # field — a band mentioned only in the prose does not satisfy the contract.
    _, div = find_section(sections, "breadthdivergence")
    if div is not None:
        target = None
        value = None
        for ln in div.splitlines():
            mm = re.search(r"breadth_divergence\b\D{0,20}(" + NUM + r")\s*pp", ln)
            if mm:
                target, value = ln, float(mm.group(1))
                break
        if target is None:
            failures.append(
                "the divergence section does not publish the field `breadth_divergence` "
                "with a value in percentage points (e.g. `breadth_divergence` | +29.42 pp)"
            )
        else:
            if not (-100.0 <= value <= 100.0):
                failures.append(
                    f"`breadth_divergence` = {value} pp is not a plausible percentage-point spread"
                )
            if not any(b in target for b in DIVERGENCE_BANDS):
                failures.append(
                    "the `breadth_divergence` row publishes no band — use one of "
                    + ", ".join(sorted(DIVERGENCE_BANDS))
                )
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", div)
        if len(set(dates)) < 5:
            failures.append(
                f"the divergence section carries {len(set(dates))} dated sessions — publish the "
                "last 5 so the reader can see whether the spread is widening or closing"
            )

    # --- 8. the CSV, and its agreement with the markdown ----------------------------------
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        failures.append("the CSV is empty")
        return failures, notes
    missing_cols = [c for c in REQUIRED_CSV_COLS if c not in rows[0]]
    if missing_cols:
        failures.append("the CSV is missing column(s): " + ", ".join(missing_cols))

    data_rows = [r for r in rows if str(r.get("is_data_date", "")).lower() == "yes"]
    if len(data_rows) != 1:
        failures.append(
            f"the CSV must carry exactly one row with is_data_date=yes — found {len(data_rows)}"
        )
    else:
        row = data_rows[0]
        for col in ("advancing", "declining", "unchanged", "breadth_pctile_1y",
                    "breadth_divergence_pp", "n_lc", "pct_above_sma_20"):
            if not str(row.get(col, "")).strip():
                failures.append(f"the CSV's data-date row has an empty `{col}`")
        try:
            pctile = float(row.get("breadth_pctile_1y"))
            if not (0.0 <= pctile <= 100.0):
                failures.append(f"the CSV's `breadth_pctile_1y` = {pctile} is outside 0..100")
        except (TypeError, ValueError):
            failures.append("the CSV's `breadth_pctile_1y` is not a number")
        # the markdown and the CSV must agree on the published percentage
        if breadth is not None:
            csv_pct = None
            try:
                csv_pct = float(row.get("pct_above_sma_20"))
            except (TypeError, ValueError):
                pass
            if csv_pct is not None:
                md_pcts = [float(x) for x in re.findall("(" + NUM + r")\s*%", breadth)]
                if not md_pcts:
                    failures.append(
                        "the breadth section publishes no percentage — the reader cannot see the "
                        "level at all"
                    )
                elif not any(abs(p - csv_pct) <= 0.05 for p in md_pcts):
                    failures.append(
                        f"the markdown's breadth percentage does not match the CSV's "
                        f"({csv_pct}) for the data-date row — published: {md_pcts}"
                    )

    # --- 9. the regime sidecar ------------------------------------------------------------
    if regime_path:
        if not os.path.exists(regime_path):
            failures.append(f"MISSING FILE: {regime_path}")
        else:
            regime = json.load(open(regime_path, encoding="utf-8"))
            if isinstance(regime.get("regime"), dict):
                failures.append(
                    "the regime payload is NESTED under a `regime` key — the canonical shape is "
                    "FLAT (the 2026-11-04 schema break)"
                )
            for key in REGIME_REQUIRED_KEYS:
                if key not in regime:
                    failures.append(f"the regime payload is missing the key `{key}`")
            if "_schema" not in regime:
                failures.append("the regime payload is missing `_schema`")
            ext = regime.get("atr_extensions")
            if isinstance(ext, dict) and not ext:
                failures.append(
                    "the regime payload's `atr_extensions` is EMPTY — the index identifier key "
                    "does not match what the SQL emits (`ticker`, not `symbol`), so `late_cycle` "
                    "could never fire"
                )

    # --- 10. the metrics JSON ----------------------------------------------------------------
    if json_path:
        if not os.path.exists(json_path):
            failures.append(f"MISSING FILE: {json_path}")
        else:
            blob = json.load(open(json_path, encoding="utf-8"))
            for path in (("breadth", "pctile_1y"), ("divergence", "pp"), ("divergence", "band")):
                node = blob
                for key in path:
                    node = node.get(key) if isinstance(node, dict) else None
                    if node is None:
                        break
                if node is None:
                    failures.append(
                        f"the metrics JSON is missing {'.'.join(path)}"
                    )
            try:
                p = float(blob["breadth"]["pctile_1y"])
                if not (0.0 <= p <= 100.0):
                    failures.append(f"the metrics JSON's breadth pctile_1y = {p} is outside 0..100")
            except (KeyError, TypeError, ValueError):
                pass
            hist = blob.get("divergence", {}).get("history_5d") or []
            if len(hist) < 5:
                failures.append(
                    f"the metrics JSON's divergence history has {len(hist)} sessions — 5 are required"
                )

    # --- 11. the settled layer is never blended with the live tape ---------------------------
    if "data_date" in fm and "live_date" in fm:
        if fm["data_date"] == fm["live_date"]:
            notes.append(
                "data_date and live_date are the same session — legitimate when the breadth feed "
                "has already settled the fire date; make sure the artifact says which layer it is"
            )
    if breadth is not None and "settled" not in breadth.lower():
        failures.append(
            "the breadth section does not say it is the SETTLED session — the settled breadth "
            "and the live tape must never be blended into one number"
        )
    _, live = find_section(sections, "livetape")
    if live is None:
        failures.append("the live-tape section is missing")
    elif "live_date" in fm:
        # the live date belongs on the SECTION HEADING ("## Live tape — 2026-11-05")
        heading = ""
        for ln in md.splitlines():
            if ln.lower().startswith("## live tape"):
                heading = ln
                break
        if fm["live_date"] not in heading and fm["live_date"] not in live:
            failures.append(
                f"the live-tape section does not carry the front-matter live_date "
                f"({fm['live_date']}) — the settled session and the live session must be "
                "labelled separately"
            )

    # --- 12. the reply -------------------------------------------------------------------------
    if reply_path:
        if not os.path.exists(reply_path):
            failures.append(f"MISSING FILE: {reply_path}")
        else:
            reply = open(reply_path, encoding="utf-8").read()
            low = reply.lower()
            if "### signal" not in low:
                failures.append("the reply has no `### Signal` section")
            else:
                signal = reply[low.index("### signal"):]
                signal = signal.split("\n### ", 1)[0]
                if not re.search(r"divergence", signal, re.I):
                    failures.append(
                        "the reply's `### Signal` does not name the breadth divergence — it is the "
                        "metric that changes position sizing and it must have its own line"
                    )
                if not (re.search(r"advanc", signal, re.I) and re.search(r"declin", signal, re.I)):
                    failures.append(
                        "the reply's `### Signal` does not name the advance/decline tally"
                    )

    return failures, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="assert the cron #10 breadth artifact contract")
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--json")
    ap.add_argument("--regime")
    ap.add_argument("--reply")
    args = ap.parse_args(argv)

    failures, notes = check(args.md, args.csv, args.json, args.regime, args.reply)
    for n in notes:
        print(f"NOTE: {n}")
    if failures:
        print(f"FAIL: {len(failures)} contract violation(s) in {args.md}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: breadth artifact contract {CONTRACT_VERSION} satisfied — {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Acceptance checker for the cron #20 US EOD artifact (CSV + markdown).

EOD_DERIVE_V2

This checker is INDEPENDENT of the builder: it re-implements the issuer-grouping rule
rather than importing `eod_derive.py`, because a checker that shares code with the thing
it checks cannot catch a bug in that code. It asserts the published contract:

  CSV
   1. the header carries every required column, in order
   2. `data_quality` is never empty and every value is in the closed vocabulary
   3. every CAP_CARRIED row names a non-empty `cap_source_symbol` that resolves to a row of
      the SAME issuer
   4. no HIGH_LOW_UNAVAILABLE row has a populated high or low
   5. no row publishes a close outside its own published range
   6. a missing value is empty, never zero
   7. the implied share count (market_cap / close) is plausible on every capped row
   8. `market_cap_usd` equals `market_cap` (the US file is already USD)

  MARKDOWN
   9. the report opens with a TL;DR of exactly three bullets
  10. the Market read is a TABLE with at least six numeric rows
  11. the Coverage table reports populated counts AND per-flag counts
  12. the Method section states the market-cap currency and the conversion direction

Exit code 0 = every assertion passed. Exit code 1 = one or more failed; each failure is
printed on its own line.

  python3 tools/check_eod_artifact.py --csv us-eod/2026-11-05.csv --md us-eod/2026-11-05.md
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

MARKER = "EOD_DERIVE_V2"

REQUIRED_COLUMNS = [
    "date", "ticker", "name", "open", "high", "low", "close", "volume", "change_pct",
    "market_cap", "pe_ratio", "sector", "currency", "exchange",
    "rel_volume", "pct_from_52w_high", "pct_from_52w_low", "sma_20", "sma_50", "sma_200",
    "pct_vs_sma_50", "pct_vs_sma_200", "atr_14", "atr_pct", "gap_pct",
    "avg_daily_dollar_volume", "float_shares", "market_cap_usd", "cap_source_symbol",
    "data_quality",
]

VOCABULARY = {"OK", "RANGE_ADJUSTED", "HIGH_LOW_UNAVAILABLE", "CAP_CARRIED", "NO_SECTOR",
              "NO_PE", "NO_CAP", "NO_HISTORY", "NO_PRIOR_CLOSE", "EX_DISTRIBUTION"}

# independent implementation of the issuer grouping (do not import the builder)
CLASS_MARKERS = re.compile(r"\s*[-–—]?\s*\b(class|series|ser\.?)\s*\.?\s*[a-z0-9]{1,3}\b\s*$",
                           re.I)
PAREN_NOISE = re.compile(r"\([^)]*\)")


def issuer_key(name: str, ticker: str) -> str:
    n = (name or "").strip().lower()
    n = PAREN_NOISE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip(" ,-")
    prev = None
    while prev != n:
        prev = n
        n = CLASS_MARKERS.sub("", n).strip(" ,-")
    return n or (ticker or "").split("-")[0].lower()


def f(x):
    try:
        if x is None or x == "":
            return float("nan")
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--session", default="")
    ap.add_argument("--prior-csv", default="",
                    help="the PRIOR session's published CSV - the anchor change_pct must agree with")
    args = ap.parse_args()

    failures: list[str] = []
    checks: list[str] = []

    def ok(msg):
        checks.append(f"ok   {msg}")

    def bad(msg):
        failures.append(f"FAIL {msg}")

    # ---------------------------------------------------------------- CSV
    with open(args.csv, newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        bad(f"csv header is missing columns: {missing}")
    else:
        ok(f"csv header carries all {len(REQUIRED_COLUMNS)} required columns")
    if header[:14] != REQUIRED_COLUMNS[:14]:
        bad("the first 14 columns are not the original session columns in order")
    else:
        ok("the first 14 columns are unchanged in name and order")
    if len(header) != len(set(header)):
        bad("the header repeats a column name")

    if not rows:
        bad("the csv has no rows")
        rows = []

    by_ticker = {r.get("ticker", ""): r for r in rows}
    keys = {r.get("ticker", ""): issuer_key(r.get("name", ""), r.get("ticker", "")) for r in rows}

    empty_flags = 0
    bad_vocab = 0
    carried = 0
    carried_bad = 0
    hl_bad = 0
    range_bad = 0
    zero_bad = 0
    shares_bad = 0
    capusd_bad = 0
    for r in rows:
        dq = (r.get("data_quality") or "").strip()
        if dq == "":
            empty_flags += 1
        else:
            for tok in dq.split("|"):
                if tok not in VOCABULARY:
                    bad_vocab += 1
        flags = set(dq.split("|"))
        if "CAP_CARRIED" in flags:
            carried += 1
            src = (r.get("cap_source_symbol") or "").strip()
            if not src or src not in by_ticker:
                carried_bad += 1
            elif keys.get(src) != keys.get(r.get("ticker", "")):
                carried_bad += 1
        if "HIGH_LOW_UNAVAILABLE" in flags:
            if (r.get("high") or "").strip() or (r.get("low") or "").strip():
                hl_bad += 1
        # close must sit inside its own published range
        hi, lo, cl = f(r.get("high")), f(r.get("low")), f(r.get("close"))
        if cl == cl and hi == hi and lo == lo and not (lo <= cl <= hi):
            range_bad += 1
        # a missing value is empty, never zero
        for col in ("close", "volume", "market_cap", "pe_ratio"):
            v = (r.get(col) or "").strip()
            if v == "0" or v == "0.0":
                zero_bad += 1
        if (r.get("market_cap") or "").strip() and (r.get("market_cap_usd") or "").strip() \
                and r["market_cap"] != r["market_cap_usd"]:
            capusd_bad += 1
        cap, cl2 = f(r.get("market_cap")), f(r.get("close"))
        if cap == cap and cl2 == cl2 and cl2 != 0:
            implied = cap / cl2
            if not (1e3 <= implied <= 1e13):
                shares_bad += 1

    (bad if empty_flags else ok)(f"data_quality has no empty value ({empty_flags} empty)")
    (bad if bad_vocab else ok)(f"every data_quality token is in the closed vocabulary "
                               f"({bad_vocab} unknown)")
    (bad if carried_bad else ok)(f"every CAP_CARRIED row names a row of the same issuer "
                                 f"({carried} carried rows, {carried_bad} bad)")
    (bad if hl_bad else ok)(f"no HIGH_LOW_UNAVAILABLE row has a populated high/low ({hl_bad})")
    (bad if range_bad else ok)(f"no row publishes a close outside its own range ({range_bad})")
    (bad if zero_bad else ok)(f"no missing value is written as zero ({zero_bad})")
    (bad if capusd_bad else ok)(f"market_cap_usd == market_cap on every row ({capusd_bad})")
    (bad if shares_bad else ok)(f"the implied share count is plausible on every capped row "
                                f"({shares_bad})")

    # change_pct must be the PRICE change against the prior session's settled close.
    # A quote service's previous_close is dividend-adjusted for payers, and a bar whose
    # date was never asserted is stale - either one publishes a change that is not the
    # session's price change, with no error anywhere.
    if args.prior_csv:
        prior = {r.get("ticker", ""): r for r in csv.DictReader(open(args.prior_csv, newline=""))}
        bad_change = []
        for r in rows:
            pc = f(r.get("change_pct", ""))
            cl = f(r.get("close", ""))
            pr = prior.get(r.get("ticker", ""))
            if pr is None or pc != pc or cl != cl:
                continue
            pc0 = f(pr.get("close", ""))
            if pc0 != pc0 or pc0 == 0:
                continue
            implied = (cl / pc0 - 1.0) * 100.0
            if abs(implied - pc) > max(0.05, abs(pc) * 0.005):
                bad_change.append((r.get("ticker", ""), round(implied, 3), pc))
        if bad_change:
            bad(f"{len(bad_change)} row(s) publish a change_pct that is not the price change "
                f"against the prior session's close "
                f"(first: {bad_change[0][0]} implied {bad_change[0][1]} published {bad_change[0][2]})")
        else:
            ok("every change_pct is the price change against the prior session's close")
    else:
        checks.append("skip change_pct consistency (no --prior-csv given)")

    # derived columns present and numeric where populated
    for col in ("rel_volume", "sma_20", "sma_50", "sma_200", "atr_14", "atr_pct",
                "gap_pct", "pct_from_52w_high", "pct_from_52w_low",
                "avg_daily_dollar_volume", "float_shares"):
        vals = [r.get(col, "") for r in rows if (r.get(col) or "").strip()]
        bads = sum(1 for v in vals if f(v) != f(v))
        (bad if bads else ok)(f"{col}: {len(vals)} populated, {bads} non-numeric")

    # ---------------------------------------------------------------- MARKDOWN
    if args.md:
        md = open(args.md).read()
        heads = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("#")]
        if not heads or heads[0].startswith("##"):
            bad("the markdown does not open with a title")
        else:
            ok("the markdown opens with a title")

        m = re.search(r"^##\s+TL;DR\s*$", md, re.M)
        if not m:
            bad("the markdown has no TL;DR section")
        else:
            body = md[m.end():]
            nxt = re.search(r"^##\s+", body, re.M)
            section = body[:nxt.start()] if nxt else body
            bullets = [ln for ln in section.splitlines() if ln.strip().startswith("- ")]
            if len(bullets) == 3:
                ok("the TL;DR has exactly three bullets")
            else:
                bad(f"the TL;DR has {len(bullets)} bullets, expected 3")

        m = re.search(r"^##\s+Market read\s*$", md, re.M)
        if not m:
            bad("the markdown has no Market read section")
        else:
            body = md[m.end():]
            nxt = re.search(r"^##\s+", body, re.M)
            section = body[:nxt.start()] if nxt else body
            numeric_rows = 0
            for ln in section.splitlines():
                if not ln.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) < 3:
                    continue
                nums = sum(1 for c in cells if re.search(r"[-+]?\d", c))
                if nums >= 3 and not set("".join(cells)) <= set("-: "):
                    numeric_rows += 1
            if numeric_rows >= 6:
                ok(f"the Market read is a table with {numeric_rows} numeric rows (>= 6)")
            else:
                bad(f"the Market read has {numeric_rows} numeric rows, expected >= 6")

        cov_ok = ("Rows populated" in md) or ("Rows populated" in md)
        flags_ok = bool(re.search(r"`data_quality`|Data-quality flags", md))
        (bad if not (cov_ok and flags_ok) else ok)(
            "the Coverage section reports populated counts and per-flag counts")

        method = md.lower()
        cur_ok = ("usd" in method and "market-cap currency" in method) or \
                 "market_cap is **usd" in method or "market cap is **usd" in method
        dir_ok = "conversion direction" in method or "no fx conversion" in method
        (bad if not cur_ok else ok)("the Method section states the market-cap currency")
        (bad if not dir_ok else ok)("the Method section states the conversion direction")

    for c in checks:
        print(c)
    for c in failures:
        print(c)
    print(f"\n{len(checks)} checks passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

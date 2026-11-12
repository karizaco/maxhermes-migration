#!/usr/bin/env python3
"""
check_focus_rvol_artifact.py — assert the cron #07 focus-rvol artifact contract.

Do not eyeball it. The alert tier of this routine was STRUCTURALLY DEAD for five consecutive
sessions (2026-11-05 through 2026-11-11): every one of them published `alerts: none` while the
tape was hot — 2026-11-10 alone had SEVEN names above the 1.5x bar and not one could be shown to
be a crossing. The cause was mechanical, not editorial: the prior reading was read ONLY from the
previous session's published CSV, and the focus roster turns over by 0-4 of 12 names between
sweeps, so the baseline almost never covered today's names. A missing ticker was published as
`n/a`, and an absent prior reading silently disarms the alert tier.

The contract now requires the prior reading to be COMPUTED when the published CSV does not carry
the ticker, and to publish where each reading came from. These clauses turn that into machine
assertions so a run that regresses FAILS instead of shipping another silent "none".

USAGE
    python3 check_focus_rvol_artifact.py \
        --md daily-screens/<date>/focus-rvol-snapshot.md \
        --csv daily-screens/<date>/focus-rvol-snapshot.csv \
        [--reply reply.txt]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

CONTRACT_VERSION = "focus-rvol-alert-v1"

# The alert bar, per cron #07's prompt STEP 6.
RVOL_ALERT_THRESHOLD = 1.5
NEAR_MISS_FLOOR = 1.275

# The provenance values the contract allows.
SOURCES = {"published_csv", "recomputed_same_feed", "unavailable"}

FAILURES: list[str] = []
CHECKS = 16


def fail(clause: str, msg: str) -> None:
    FAILURES.append(f"[{clause}] {msg}")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(txt: str, header: str) -> str:
    if header not in txt:
        return ""
    rest = txt.split(header, 1)[1]
    nxt = re.search(r"^## ", rest, flags=re.M)
    return rest[: nxt.start()] if nxt else rest


def fnum(v: str):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--reply")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        fail("C0", f"the artifact markdown is missing: {args.md}")
        report()
    if not os.path.exists(args.csv):
        fail("C0", f"the artifact CSV is missing: {args.csv} — a run that ships only the .md "
                   f"starves the next fire's baseline")
        report()

    md = read(args.md)
    with open(args.csv, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    # ---------------------------------------------------------------- C1 the CSV exists and has rows
    if not rows:
        fail("C1", "the CSV has no rows — the baseline for the next fire would be empty")

    # ---------------------------------------------------------------- C2 the provenance column exists
    if rows:
        if "prev_session_rvol_source" not in rows[0]:
            fail("C2", "the CSV has no `prev_session_rvol_source` column — the reader cannot tell "
                       "a published prior reading from a recomputed one")
        if "prev_session_rvol" not in rows[0]:
            fail("C2", "the CSV has no `prev_session_rvol` column")
        if "rvol_now" not in rows[0]:
            fail("C2", "the CSV has no `rvol_now` column")

    # ---------------------------------------------------------------- C3 every row has a legal source
    bad_src = []
    for r in rows:
        s = (r.get("prev_session_rvol_source") or "").strip()
        if s not in SOURCES:
            bad_src.append(f"{r.get('symbol')}={s!r}")
    if bad_src:
        fail("C3", "rows with a missing or illegal `prev_session_rvol_source` "
                   f"(allowed: {sorted(SOURCES)}): {', '.join(bad_src)}")

    # ---------------------------------------------------------------- C4 n/a is only ever paired with unavailable
    bad_na = []
    for r in rows:
        src = (r.get("prev_session_rvol_source") or "").strip()
        pv = (r.get("prev_session_rvol") or "").strip()
        if pv in ("n/a", "", "-") and src != "unavailable":
            bad_na.append(f"{r.get('symbol')} (prev={pv!r}, src={src!r})")
    if bad_na:
        fail("C4", "a row has no prior reading but does not declare `unavailable`: "
                   + ", ".join(bad_na))

    # ---------------------------------------------------------------- C5 a value is never declared unavailable
    bad_val = []
    for r in rows:
        src = (r.get("prev_session_rvol_source") or "").strip()
        pv = fnum(r.get("prev_session_rvol") or "")
        if src == "unavailable" and pv is not None:
            bad_val.append(f"{r.get('symbol')} (prev={pv})")
    if bad_val:
        fail("C5", "a row declares `unavailable` yet carries a numeric prior reading: "
                   + ", ".join(bad_val))

    # ---------------------------------------------------------------- C6 THE REGRESSION CLAUSE
    # A name above the alert bar whose prior reading is missing is a LEVEL with no baseline.
    # That is allowed ONLY when the recompute was genuinely impossible (`unavailable`).
    # If the prior reading is simply absent (`n/a` under any other source), the alert tier is
    # being silenced by the roster turnover again — the exact 5-session defect.
    silenced = []
    for r in rows:
        now = fnum(r.get("rvol_now") or "")
        src = (r.get("prev_session_rvol_source") or "").strip()
        pv = fnum(r.get("prev_session_rvol") or "")
        if now is None:
            continue
        if now >= RVOL_ALERT_THRESHOLD and pv is None and src != "unavailable":
            silenced.append(f"{r.get('symbol')} ({now:.2f}x)")
    if silenced:
        fail("C6", "names above the alert bar with NO prior reading and no `unavailable` "
                   "explanation — the alert tier is being silenced again: " + ", ".join(silenced))

    # ---------------------------------------------------------------- C7 crossings are claimed consistently
    # A name may appear in the '## Alerts' section only as a PROVEN CROSSING (prior < 1.5 <= now)
    # or as an explicitly non-alert LEVEL (tier WATCH / NEAR MISS / UNADJUSTED). The section
    # legitimately lists levels alongside crossings, so membership alone is not a claim.
    alerts_sec = section(md, "## Alerts")
    named = set(re.findall(r"\*\*([A-Z]{1,5})\b", alerts_sec))
    named |= set(re.findall(r"^\s*-\s*\*\*([A-Z]{1,5})\*\*", alerts_sec, flags=re.M))
    by_sym = {r.get("symbol"): r for r in rows}
    real, alertted = set(), set()
    for r in rows:
        now = fnum(r.get("rvol_now") or "")
        pv = fnum(r.get("prev_session_rvol") or "")
        if now is not None and pv is not None and pv < RVOL_ALERT_THRESHOLD <= now:
            real.add(r.get("symbol"))
        if (r.get("tier") or "").strip().upper() == "ALERT":
            alertted.add(r.get("symbol"))
    missing = real - named
    if missing:
        fail("C7", "names that provably crossed the alert bar but are not named in the "
                   f"'## Alerts' section: {', '.join(sorted(missing))}")
    overclaimed = alertted - real
    if overclaimed:
        fail("C7", "names tiered ALERT without a provable crossing "
                   f"(prior < 1.5 <= now): {', '.join(sorted(overclaimed))}")
    # A name named in the section but neither a crossing nor an explicit level is a claim
    # the data does not support.
    levels = {"WATCH", "NEAR MISS", "UNADJUSTED", ""}
    unsupported = {s for s in named
                   if s in by_sym
                   and s not in real
                   and (by_sym[s].get("tier") or "").strip().upper() not in levels}
    if unsupported:
        fail("C7", "names named in '## Alerts' that are neither a provable crossing nor an "
                   f"explicit level: {', '.join(sorted(unsupported))}")

    # ---------------------------------------------------------------- C8 the artifact states the provenance split
    if not re.search(r"recomputed", md, flags=re.I):
        fail("C8", "the artifact never mentions the recomputed baseline — the reader cannot see "
                   "how many prior readings were recomputed rather than published")
    if not re.search(r"prev_session_rvol_source", md):
        fail("C8", "the artifact never names the `prev_session_rvol_source` column")

    # ---------------------------------------------------------------- C9 the counts are stated
    counts = section(md, "### Counts")
    if counts:
        for key in ("alert", "Required"):
            if key.lower() not in counts.lower():
                fail("C9", f"the '### Counts' block does not state the {key} count")
    else:
        fail("C9", "the artifact has no '### Counts' block")

    # ---------------------------------------------------------------- C10 a crossing needs a real prior reading
    for r in rows:
        tier = (r.get("tier") or "").strip().upper()
        pv = fnum(r.get("prev_session_rvol") or "")
        if tier == "ALERT" and pv is None:
            fail("C10", f"{r.get('symbol')} is tiered ALERT with no numeric prior reading")

    # ---------------------------------------------------------------- C11 near misses carry both values
    for r in rows:
        now = fnum(r.get("rvol_now") or "")
        if now is None:
            continue
        if NEAR_MISS_FLOOR <= now < RVOL_ALERT_THRESHOLD:
            if not (r.get("prev_session_rvol") or "").strip():
                fail("C11", f"near miss {r.get('symbol')} ({now:.3f}x) carries no prior value")

    # ---------------------------------------------------------------- C12 the CSV has one row per ticker
    syms = [r.get("symbol") for r in rows]
    if len(syms) != len(set(syms)):
        fail("C12", "the CSV has a duplicate symbol")

    # ---------------------------------------------------------------- C13 the tier vocabulary is closed
    allowed_tiers = {"ALERT", "NEAR MISS", "WATCH", "UNADJUSTED", "-", ""}
    for r in rows:
        if (r.get("tier") or "").strip().upper() not in allowed_tiers:
            fail("C13", f"{r.get('symbol')} has an unknown tier {r.get('tier')!r}")

    # ---------------------------------------------------------------- C14 the markdown carries the table
    if "## Table" not in md:
        fail("C14", "the artifact has no '## Table' section")
    if "## Alerts" not in md:
        fail("C14", "the artifact has no '## Alerts' section")

    # ---------------------------------------------------------------- C15 the reply names the crossings
    if args.reply and os.path.exists(args.reply):
        reply = read(args.reply)
        for s in sorted(real):
            if s not in reply:
                fail("C15", f"the reply does not name the crossing ticker {s}")
        if real and not re.search(r"^alerts:\s*\S", reply, flags=re.M):
            fail("C15", "the reply has no 'alerts:' line")

    report()


def report():
    print()
    if FAILURES:
        print(f"CONTRACT FAILED — {len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"CONTRACT OK — {CHECKS} checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

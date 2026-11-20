#!/usr/bin/env python3
"""
premarket_refresh_build.py — build cron #26b's pre-market-refresh artifact from a FROZEN pull.

WHY THIS FILE EXISTS
--------------------
The 2026-11-12 run took 17.9 minutes and 56% of it was spent writing and REPAIRING the
artifact generator: five rebuilds, three failed patch attempts, and three template bugs of its
own (an un-interpolated `{sum(...)}` because the f-prefix sat on the wrong continued string
literal, a doubled "ET ET", a missing f-prefix). Two defects reached the CSV because of it:
a row with a NULL 30-day volume was published with `avg_volume_30d = 0`, which produced a
fabricated `pct_of_adv` of 100000.00%, and a row with a NULL market cap was published as 0.
Both are the "never fill a missing value with zero" rule, broken by a one-line `or 0`.

This file owns everything NUMERIC so a number can never be typed by hand:

  * the gates (A = liquidity, B = the $100m quality floor) and the headline / thin-tape split;
  * the gap-quality table (PM range, Hold %, pm %ADV, the print descriptors, the Driver, the
    key level and the invalidation-with-its-side);
  * the top-of-book tables, the thin tape, "what changed since the morning brief";
  * the companion CSV, with `prior_close` DERIVED from the values the CSV itself publishes
    (4 dp price, 2 dp change) so every row reproduces its own prior close;
  * the front matter and the pinned section skeleton.

The run supplies only what is genuinely JUDGEMENT, in a slots file: the Driver map (read from
the catalyst the 08:30 brief already sourced), and the risk / watch picks. The setup slot is
computed by the ladder the procedure defines, and the builder REFUSES a setup that the ladder
would not produce unless the run says why.

USAGE
    python3 premarket_refresh_build.py \
        --merged merged.json \
        --morning-md daily-briefs/2026-11-12-pre-market.md \
        --morning-csv daily-briefs/2026-11-12-pre-market.csv \
        --slots slots.json \
        --date 2026-11-12 --fire-time-et "2026-11-12 09:20" --snapshot-et "09:24" \
        --session-state PRE-OPEN \
        --out-dir daily-briefs

SLOTS FILE (JSON)
    {
      "drivers": {"TTEK": {"class": "EARNINGS-RECONFIRM", "anchored": true,
                           "note": "adjusted EPS $0.49 against $0.47 expected, net revenue $1.15bn"}},
      "setup":  {"ticker": "TTEK"},
      "risk":   {"ticker": "NVDA", "clause": "the AI complex's de-rating is accelerating"},
      "watch":  {"ticker": "KYTX", "clause": "the morning brief's own setup has collapsed"},
      "verdict": {"direction": "more", "clause": "optional override"}
    }

OUTPUT
    <out-dir>/<date>-pre-market-refresh.md
    <out-dir>/<date>-pre-market-refresh.csv
    A machine summary on stderr: the computed band counts, the setup rung, the changed-since
    count, the fade/entry counts against the NAMED base, and any warning.

EXIT CODES
    0 = the artifact was written and passed its own internal checks
    1 = an input was missing or the artifact failed an internal check (nothing is written)
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys

# Capability marker. v4 (2026-11-19) fixes four defects measured on the 2026-11-19 fire:
# the front-matter parser rejected the morning brief's own v2 layout (title and intro BEFORE
# the `---` block) and published a literal "?"; the late-pull branch published the live
# session's `close` disagreement as "ISOLATED field defects, NOT a live session" while its own
# front matter said `market_open_at_pull: true`; a gap-DOWN name was published as having
# "extended its gap" when it had NARROWED; and the band-membership sentence claimed the band
# "grew" when it shrank. It SUPERSEDES premarket-refresh-build-v3, which is still named here
# so a procedure copy that asks for v3 still fetches a WORKING file rather than nothing.
# Capability marker. v5 (2026-11-19) adds the FIFTH defect measured on the same fire: the LIVE
# late-pull branch computed the stall sentence and then DROPPED it, so a replayed file never said
# WHY it was late - the procedure requires the intro to state the stall, the pull time and the
# open time. v4 fixed the front-matter parser, the late-pull Source health, the gap-direction verb
# and the "?" holes. It SUPERSEDES premarket-refresh-build-v3 and v4, which are still named here so
# a procedure copy that asks for either still fetches a WORKING file rather than nothing.
# Capability marker. v6 (2026-11-20) fixes the sixth defect, measured on the 2026-11-20 fire:
# the top-of-book section said "The two tables below carry the top 15 and top 10 of those
# qualifying sets" and published ELEVEN gainer rows, because only 11 of the 181 band gainers
# clear Gate A + Gate B on a down tape - a sentence that reads as a COMPLETE table while the
# table is short. The section now publishes what it actually carries, in the procedure's own
# idiom ("showing N of M"), for BOTH tables and on EVERY fire, so a short table can never read
# as a full one. It SUPERSEDES v3, v4 and v5, which are still named here so a procedure copy
# that asks for any of them still fetches a WORKING file rather than nothing.
# Capability marker. v7 (2026-11-20) fixes two more prose defects measured on the same fire:
# Source health published "17 of the 25 headline names have no sourced catalyst" while the
# gap-quality table carried 21 rows - the denominator was hardcoded - and the Rule 1 / Rule 2
# bullets told the reader to "apply it at 09:31" on a file published after the 09:30 open. The
# denominator is now the table's own size, and the rules say what is true of the file that
# carries them. It SUPERSEDES v3, v4, v5 and v6, which are still named here so a procedure
# copy that asks for any of them still fetches a WORKING file rather than nothing.
PREMARKET_REFRESH_BUILD_V7 = "premarket-refresh-build-v7"
PREMARKET_REFRESH_BUILD_V6 = "premarket-refresh-build-v6"
PREMARKET_REFRESH_BUILD_V5 = "premarket-refresh-build-v5"
PREMARKET_REFRESH_BUILD_V4 = "premarket-refresh-build-v4"
PREMARKET_REFRESH_BUILD_V3 = "premarket-refresh-build-v3"

CRON_VALUE = "26-agentic-pre-market-brief-refresh"
SOURCE_VALUE = "TradingView america scanner"

DRIVERS = {"CASH-OUT", "CASH-IN", "LIABILITY-RESOLVED", "ASSET-VALUE", "EARNINGS-RAISE",
           "EARNINGS-RECONFIRM", "EARNINGS-CUT", "CORPORATE-EVENT", "SECTOR-BETA", "NONE",
           "unclassified"}
# rung 1 of the setup ladder: the classes with measured evidence of a RUNNING gap
SETUP_CLASSES = {"CASH-OUT", "CASH-IN", "LIABILITY-RESOLVED", "ASSET-VALUE", "EARNINGS-RAISE"}

CSV_HEADER = ["ticker", "name", "premarket_close", "premarket_change_pct", "premarket_volume",
              "avg_volume_30d", "pct_of_adv", "prior_close", "prior_session_change_pct",
              "live_close", "live_change_pct", "live_volume", "market_cap", "sector", "exchange",
              "screen_complete"]

GATE_A_VOL = 100_000
GATE_A_CAP = 200_000_000
GATE_A_CAP_VOL = 10_000
GATE_B_CAP = 100_000_000
MOVE_EPS = 0.2               # a gap that moved by more than this counts as "changed"
HOLD_RUNG2 = 80.0           # rung 2 of the ladder: the gap is still holding
TAIL_GATE_FAIL = 16         # the tail tier's gate-fail slots (the brief's C7 mix)
TAIL_UNRANKED = 14          # the tail tier's unranked slots (C7's 7 flat-print + 7 unranked)
QUOTE_PCT, AUCTION_PCT = 2.0, 30.0

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("  ! %s" % msg, file=sys.stderr)


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def fmt(v, dp=2):
    return "" if v is None else ("%%.%df" % dp) % v


def cap_of(row):
    """The PUBLISHED cap: the corroborated one when the pull reconciled it, else the scanner's."""
    v = row.get("market_cap_published")
    if v is None or v == "":
        v = row.get("market_cap_basic")
    return num(v)


def hold_pct(row):
    lo, hi, pm = num(row.get("premarket_low")), num(row.get("premarket_high")), num(row.get("premarket_close"))
    if lo is None or hi is None or pm is None or hi == lo:
        return None
    return round((pm - lo) / (hi - lo) * 100.0)


def adv_pct(row):
    pv, adv = num(row.get("premarket_volume")), num(row.get("average_volume_30d_calc"))
    if pv is None or adv is None or adv <= 0:
        return None
    return pv / adv * 100.0


def print_flags(row):
    a, h = adv_pct(row), hold_pct(row)
    if a is None:
        q = "n/a"
    elif a < QUOTE_PCT:
        q = "QUOTE"
    elif a <= AUCTION_PCT:
        q = "AUCTION"
    else:
        q = "CHURN"
    if h is None:
        hf = "n/a"
    elif h >= HOLD_RUNG2:
        hf = "holding"
    elif h < 50:
        hf = "half-filled"
    else:
        hf = "mid"
    return q, hf


def gate_a(row):
    pv, cap = num(row.get("premarket_volume")) or 0, cap_of(row) or 0
    return pv >= GATE_A_VOL or (cap >= GATE_A_CAP and pv >= GATE_A_CAP_VOL)


def gate_b(row):
    return (cap_of(row) or 0) >= GATE_B_CAP


def cap_str(c):
    if c is None:
        return "n/a"
    if c >= 1e9:
        return "$%.2fB" % (c / 1e9)
    if c >= 1e6:
        return "$%,.1fM".replace(",", "") % (c / 1e6) if False else "$%.1fM" % (c / 1e6)
    return "$%,.0f".replace(",", "") % c if False else "$%.0f" % c


def cap_plain(c):
    if c is None:
        return "n/a"
    if c >= 1e6:
        return "%.1fM" % (c / 1e6)
    return "%.0f" % c


def invalidation(row, prior):
    """Always a DOWNSIDE trigger, always with its side."""
    if num(row.get("premarket_change")) >= 0:
        return "back to/below prior close %s" % fmt(prior, 2)
    return "below PM low %s" % fmt(num(row.get("premarket_low")), 4).rstrip("0").rstrip(".")


def key_level(row, prior):
    return "prior close %s" % fmt(prior, 2)


def driver_for(row, drivers, morning):
    """The Driver comes from the map the run built from the morning brief's OWN catalysts."""
    t = row["ticker"]
    m = morning.get(t)
    if m is None:
        return "NONE", "not in the morning brief's CSV — new to the screen"
    if (m.get("has_news") or "").strip().lower() != "yes":
        return "NONE", "the morning brief sourced no catalyst for this name"
    d = drivers.get(t)
    if not d:
        return "NONE", "the morning brief marked has_news=yes but no per-name catalyst was sourced"
    cls = (d.get("class") or "").strip()
    if cls not in DRIVERS:
        warn("%s carries an unknown Driver class %r — published as NONE" % (t, cls))
        return "NONE", "unknown driver class"
    if cls == "NONE":
        return "NONE", "no per-name catalyst sourced"
    return (cls + ("+ANCHORED" if d.get("anchored") else "")), d.get("note") or ""


def pick_setup(candidates, drivers, morning):
    """The procedure's ladder. Returns (ticker, rung, note) or (None, 0, reason)."""
    anchored = []
    for r in candidates:
        drv, note = driver_for(r, drivers, morning)
        if drv.endswith("+ANCHORED"):
            anchored.append((r, drv, note))
    if not anchored:
        return None, 0, "no name carries an anchored catalyst"
    rung1 = [x for x in anchored if x[1].replace("+ANCHORED", "") in SETUP_CLASSES]
    if rung1:
        best = max(rung1, key=lambda x: (num(x[0]["premarket_change"]), x[0]["ticker"]))
        return best[0]["ticker"], 1, best[2]
    rung2 = [x for x in anchored if (hold_pct(x[0]) or 0) >= HOLD_RUNG2]
    if rung2:
        best = max(rung2, key=lambda x: (num(x[0]["premarket_change"]), x[0]["ticker"]))
        return best[0]["ticker"], 2, best[2]
    return None, 0, "no name carries an anchored catalyst"


def pull_phase(pulled_at_et):
    """WHEN the pull landed, in ET, against the 09:30 open and the 16:00 close.

    The pull's own clock is already ET (the pull writes it with its ET offset), so this
    is a clock comparison, not a timezone conversion - a hardcoded UTC-4 offset would
    read an hour late.
    """
    try:
        hh = int(str(pulled_at_et).split(" ")[1][:2])
        mm = int(str(pulled_at_et).split(" ")[1][3:5])
    except Exception:
        return "unknown"
    t = hh + mm / 60.0
    if t >= 16.0:
        return "closed"
    if t >= 9.5:
        return "live"
    return "pre-open"


def closest_candidate(gap_up_candidates, drivers, morning):
    """The cash case still has to NAME a candidate.

    The setup slot is computed by the ladder, and the ladder can legitimately come back
    EMPTY - measured on 2026-11-16 and again on 2026-11-17.  The cash case then publishes
    the candidate that came CLOSEST to the slot: an ANCHORED name came closest, because it
    failed only on the class or on the Hold bar, while an unanchored name failed on the
    anchor itself.  Among equals the bigger gap is closer.

    Without this the builder's own cash-case output carried no digit and no invalidation
    level, and its watch table lost a row - and the contract checker rejects both.
    """
    anchored, plain = [], []
    for r in gap_up_candidates:
        drv, _note = driver_for(r, drivers, morning)
        (anchored if drv.endswith("+ANCHORED") else plain).append(r)
    pool = anchored or plain
    if not pool:
        return None
    return max(pool, key=lambda x: (num(x.get("premarket_change")) or 0)).get("ticker")


def ladder_gap_note(gap_up_candidates, drivers, morning):
    """WHY the ladder came back empty - computed from the data, never hand-typed."""
    five, other, unanchored, none_ct = [], [], [], 0
    for r in gap_up_candidates:
        drv, _note = driver_for(r, drivers, morning)
        if drv == "NONE":
            # no sourced catalyst at all - a FINDING, and NOT the same as a catalyst
            # without a hard number.  Counting it as the latter asserts a catalyst the
            # morning brief never sourced.
            none_ct += 1
            continue
        if not drv.endswith("+ANCHORED"):
            unanchored.append(r)
            continue
        (five if drv.replace("+ANCHORED", "") in SETUP_CLASSES else other).append(r)
    if five:
        return ""
    parts = []
    if not other:
        parts.append("no name in the headline set carries an anchored catalyst")
    else:
        holds = ", ".join(
            "%s %+.2f%% at Hold %s%%" % (r["ticker"], num(r["premarket_change"]),
                                         hold_pct(r)) for r in other)
        parts.append("rung 1 of the ladder is empty (no anchored name carries one of the five "
                     "classes) and the anchored gainers are all below the 80%% Hold that rung 2 "
                     "requires (%s)" % holds)
    if unanchored:
        parts.append("%s carr%s a catalyst but no hard number, so %s anchored"
                     % (", ".join(r["ticker"] for r in unanchored),
                        "ies" if len(unanchored) == 1 else "y",
                        "it is not" if len(unanchored) == 1 else "none of them is"))
    if none_ct:
        parts.append("%d of the headline gainers carr%s no sourced catalyst at all"
                     % (none_ct, "ies" if none_ct == 1 else "y"))
    return "; ".join(parts)


def parse_front_matter(path):
    """The machine-readable block, as a dict.

    It is a `---` fenced block and it is NOT always the FIRST thing in the file. The morning
    brief's own v2 contract puts its title and intro paragraph BEFORE the block (measured
    2026-11-19: the 08:30 brief opens with `# Agentic pre-market brief - 2026-11-19` and a
    summary paragraph, and the `---` block comes after them). The old `txt.startswith("---")`
    guard therefore returned {} for the real baseline, and this artifact published a literal
    "?" where the baseline's band counts belong and "a band the brief counted at 0 names" in
    Source health. Find the FIRST fence - exactly what the brief's own checker does in
    `tools/check_premarket_brief.py`'s `front_matter()`.
    """
    if not path or not os.path.exists(path):
        return {}
    txt = open(path, encoding="utf-8", errors="replace").read()
    lines = txt.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            start = i
            break
    if start is None:
        return {}
    fm = {}
    for line in lines[start + 1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def fm_band_text(fm):
    """The baseline band as one phrase. NEVER a literal "?" and NEVER a 0.

    A missing count is a missing count: the old template published `?` where the morning
    brief's own published band counts belong, and the checker had no placeholder rule that
    caught a single `?` (its list held `???`). "an unpublished band" says what is true.
    """
    g, d = num(fm.get("up_3pct")), num(fm.get("down_3pct"))
    if g is None or d is None:
        return "an unpublished band"
    return "%d gainers / %d decliners" % (int(g), int(d))


def read_morning_csv(path):
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(r.get("ticker") or "").strip()] = r
    return out


def build(args):
    merged = json.load(open(args.merged, encoding="utf-8"))
    rows = merged["rows"] if isinstance(merged, dict) and "rows" in merged else merged
    for r in rows:
        r["ticker"] = (r.get("ticker") or r.get("name") or "").strip()
    # A row with NO pre-market print is not a row with a blank price. The skill excludes such
    # rows from the CSV (the checker asserts a non-empty premarket_close on every row) and
    # publishes the name in prose without a price. Publishing 0.0000 would be a fabrication.
    before = len(rows)
    rows = [r for r in rows if num(r.get("premarket_close")) is not None]
    if len(rows) != before:
        warn("%d row(s) carried no pre-market print and were excluded from the screen"
             % (before - len(rows)))
    # The merged table may carry names the BAND cannot see (the watchlist's ETFs, the trending
    # names outside +/-3%). They are not band rows, so they must not enter the refresh's screen:
    # the CSV's row count has to equal up_3pct + down_3pct.
    band_names = set(merged.get("band_gainers") or []) | set(merged.get("band_decliners") or [])
    if band_names:
        dropped = [r["ticker"] for r in rows if r["ticker"] not in band_names]
        rows = [r for r in rows if r["ticker"] in band_names]
        if dropped:
            warn("%d name(s) outside the +/-3%% band were dropped from the screen (%s)"
                 % (len(dropped), ", ".join(dropped[:5])))

    morning = read_morning_csv(args.morning_csv)
    fm_morning = parse_front_matter(args.morning_md)
    slots = {}
    if args.slots and os.path.exists(args.slots):
        slots = json.load(open(args.slots, encoding="utf-8"))
    drivers = slots.get("drivers") or {}

    # ---- the GATE's own verdict, read from its output file ----
    # The gate is the decider, so the file that carries its verdict is the source of truth for
    # the branch, and the builder CROSS-CHECKS the branch it was told to publish against it.
    # Measured 2026-11-18: the gate returned OPEN on one isolated scanner `close` defect for a
    # pull that landed before the open; the run published PRE-OPEN and had to say so in prose.
    # Now the disagreement is mechanical: both verdicts are published, and the defects are named.
    gate = {}
    if args.state and os.path.exists(args.state):
        try:
            gate = json.load(open(args.state, encoding="utf-8"))
        except Exception as exc:                       # a broken gate file is not a reason to lie
            warn("the session-state verdict file %s could not be read (%s) — the file's session "
                 "state is published unverified" % (args.state, exc))
    gate_state = (gate.get("session_state") or "").upper()
    defects = gate.get("close_field_defects") or []
    if gate_state and gate_state != args.session_state.upper():
        warn("the session-state gate returned %s and this file is published as %s — both "
             "verdicts are published in Source health" % (gate_state, args.session_state))

    # The PUBLISHED cap, in order of trust: the morning brief's own reconciled figure (it ran
    # the three-source sweep and published the corroborated cap), then the pull's reconciled
    # figure, then the scanner's raw `market_cap_basic`. Re-using the morning's column is the
    # difference between one sweep per morning and one sweep per fire, and it is the only cap
    # that is corroborated rather than merely present.
    reused = 0
    for r in rows:
        t = r["ticker"]
        mc = num((morning.get(t) or {}).get("market_cap"))
        if mc is not None and mc <= 0:
            mc = None      # a cap of ZERO is not a cap — it is a missing value
        if mc is not None:
            r["market_cap_published"] = mc
            r["cap_source"] = "the morning brief's reconciled cap"
            reused += 1
        elif r.get("market_cap_published") not in (None, ""):
            r["cap_source"] = r.get("cap_source") or "the pull's reconciled cap"
        elif r.get("market_cap_basic") not in (None, ""):
            r["market_cap_published"] = r.get("market_cap_basic")
            r["cap_source"] = "the scanner's market_cap_basic (unreconciled)"
        else:
            r["market_cap_published"] = None
            r["cap_source"] = "no cap published"

    up = [r for r in rows if (num(r.get("premarket_change")) or 0) > 0]
    dn = [r for r in rows if (num(r.get("premarket_change")) or 0) < 0]
    up.sort(key=lambda r: -(num(r["premarket_change"]) or 0))
    dn.sort(key=lambda r: (num(r["premarket_change"]) or 0))

    head_up = [r for r in up if gate_a(r) and gate_b(r)][:15]
    head_dn = [r for r in dn if gate_a(r) and gate_b(r)][:10]
    thin_up = [r for r in up if gate_a(r) and not gate_b(r)]
    thin_dn = [r for r in dn if gate_a(r) and not gate_b(r)]

    # ---- the setup slot: the ladder, then the run's override ----
    candidates = [r for r in head_up + head_dn]
    gap_up_candidates = [r for r in candidates if (num(r["premarket_change"]) or 0) > 0]
    ladder_t, rung, ladder_note = pick_setup(gap_up_candidates, drivers, morning)
    slots_setup = (slots.get("setup") or {}).get("ticker")
    setup_t = slots_setup or ladder_t
    if slots_setup and ladder_t and slots_setup != ladder_t:
        warn("the slots file names %s as the setup but the ladder produces %s — the run's pick "
             "wins and the deviation is published in Source health" % (slots_setup, ladder_t))
    if not setup_t:
        warn("no anchored setup — the cash case is published")
    by_ticker = {r["ticker"]: r for r in rows}

    # ---- the cash case still names the candidate that came closest ----
    cash_cand, cash_note = None, ""
    if not setup_t:
        cash_cand = closest_candidate(gap_up_candidates, drivers, morning)
        cash_note = ladder_gap_note(gap_up_candidates, drivers, morning)

    # ---- changed since the morning brief ----
    live_gap = {r["ticker"]: num(r["premarket_change"]) for r in rows
                if num(r["premarket_change"]) is not None}
    moved = []
    for t, g in live_gap.items():
        m = morning.get(t)
        if not m:
            continue
        mg = num(m.get("gap_pct"))
        if mg is None:
            continue
        if abs(g - mg) > MOVE_EPS:
            moved.append((abs(g - mg), g - mg, t, mg, g))
    moved.sort(key=lambda x: (-x[0], x[2]))
    changes_since = len(moved)

    mband = {t for t, m in morning.items()
             if num(m.get("gap_pct")) is not None and abs(num(m["gap_pct"])) >= 3}
    faded = sorted(mband - set(live_gap))
    entered_all = set(live_gap) - mband
    entered = sorted(t for t in entered_all if t in morning)
    unclassified = len(entered_all) - len(entered)

    setup_moves = []
    for t, m in morning.items():
        if not (m.get("setup_theme") or "").strip():
            continue
        g = live_gap.get(t)
        mg = num(m.get("gap_pct"))
        if g is None:
            setup_moves.append((0.0, None, t, mg, None))
        elif mg is not None and abs(g - mg) > MOVE_EPS:
            setup_moves.append((abs(g - mg), g - mg, t, mg, g))
    # a name that LEFT the band is worth showing, but it is not "a move" — it sorts last.
    setup_moves.sort(key=lambda x: (0 if x[1] is not None else 1,
                                    -(x[0] if x[1] is not None else 0.0), x[2]))

    # ---- the verdict's numbers ----
    now_dec = len(dn)
    now_gain = len(up)
    # The gate-passing counts, and the rows the headline tables can actually carry. On a thin
    # tape fewer than 15 gainers clear the gates, and a table that shows 11 under a heading
    # that says "top 15" reads as a complete one. The section publishes both numbers.
    q_gain = sum(1 for r in up if gate_a(r) and gate_b(r))
    q_dec = sum(1 for r in dn if gate_a(r) and gate_b(r))
    head_gain_rows = min(15, q_gain)
    head_decl_rows = min(10, q_dec)
    then_dec = num(fm_morning.get("down_3pct"))
    then_gain = num(fm_morning.get("up_3pct"))
    widened = narrowed = 0
    for r in dn:
        m = morning.get(r["ticker"])
        if not m:
            continue
        mg = num(m.get("gap_pct"))
        if mg is None:
            continue
        d = num(r["premarket_change"]) - mg
        if abs(d) <= MOVE_EPS:
            continue
        if d < 0:
            widened += 1
        else:
            narrowed += 1
    ext = fad = 0
    for r in up:
        m = morning.get(r["ticker"])
        if not m:
            continue
        mg = num(m.get("gap_pct"))
        if mg is None:
            continue
        d = num(r["premarket_change"]) - mg
        if abs(d) <= MOVE_EPS:
            continue
        if d > 0:
            ext += 1
        else:
            fad += 1
    if widened > narrowed and (then_dec is None or now_dec > then_dec):
        direction = "more"
    elif narrowed > widened and (then_dec is not None and now_dec < then_dec):
        direction = "less"
    else:
        direction = "no clearer"
    side = "downside" if now_dec > now_gain else ("upside" if now_gain > now_dec else "two-way")

    # ---- the risk and the watch ----
    risk = slots.get("risk") or {}
    watch = slots.get("watch") or {}
    risk_t = risk.get("ticker")
    if not risk_t and head_dn:
        risk_t = head_dn[0]["ticker"]
        warn("no risk picked — the biggest headline decliner (%s) is used" % risk_t)
    watch_t = watch.get("ticker")
    if not watch_t and setup_moves:
        watch_t = setup_moves[0][2]
        warn("no watch picked — the biggest mover among the morning's setups (%s) is used" % watch_t)

    L = []
    A = L.append
    snap = args.snapshot_et
    snap_hm = snap[:5]
    weekday = datetime.date.fromisoformat(args.date).strftime("%A")
    state = args.session_state.upper()
    market_open = state == "OPEN"
    phase = pull_phase(merged.get("pulled_at_et"))
    stall_min = args.stall_min or 0

    A("---")
    A("date: %s" % args.date)
    A("cron: %s" % CRON_VALUE)
    A("fire_time_et: %s" % args.fire_time_et)
    A("snapshot_et: %s" % snap_hm)
    A("source: %s" % SOURCE_VALUE)
    A("status: ok")
    A("changes_since_morning: %d" % changes_since)
    A("up_3pct: %d" % now_gain)
    A("down_3pct: %d" % now_dec)
    A("screen_complete: %s" % ("true" if merged.get("band", {}).get("complete", True) else "false"))
    if market_open:
        A("market_open_at_pull: true")
        A("pull_late: true")
    A("---")
    A("")
    A("# Pre-market refresh - %s %s" % (weekday, args.date))
    A("")
    if market_open:
        stall_txt = ""
        if stall_min and stall_min > 0:
            stall_txt = ("**The platform held this fire for %d minute%s before its first tool "
                         "call**, so the pull landed late" % (stall_min,
                                                             "" if stall_min == 1 else "s"))
            if phase == "closed":
                stall_txt += (" — after the 09:30 ET open and the 16:00 ET close, which is why "
                              "this file is a reconstruction of the 09:20 checkpoint rather than "
                              "a live pre-open read")
            else:
                stall_txt += " — after the 09:30 ET open"
            stall_txt += "."
        if phase == "closed":
            A("One pull of the TradingView `america` scanner at **%s**, and the regular session "
              "had already opened AND closed — so the `premarket_*` columns below are the "
              "completed pre-market session (the final prints before the bell) and the "
              "`live_*` columns in the companion CSV carry the **settled** close of the "
              "**%s** session, not an intraday live price. The front matter carries "
              "`pull_late: true` and `market_open_at_pull: true`. %s" % (snap, args.date,
                                                                        stall_txt))
        else:
            A("One pull of the TradingView `america` scanner at **%s**, and the regular session is "
              "**already open** (the 09:30 ET open has happened) — so the `premarket_*` columns "
              "below are the completed pre-market session and the live regular-session values are "
              "published in their own block. The front matter carries `pull_late: true` and "
              "`market_open_at_pull: true`.%s"
              % (snap, (" " + stall_txt) if stall_txt else ""))
    else:
        A("One pull of the TradingView `america` scanner at **%s**, before the 09:30 ET open. "
          "Both screens were pulled with the row cap at 1000 and the scanner's own "
          "`totalCount` matched the rows returned on each (%d gainers, %d decliners), so the "
          "counts above are exact, not floors. The regular session has **not** opened, so every "
          "`live_*` column in the companion CSV is blank - the pre-market prints below are the "
          "last trades before the bell." % (snap, now_gain, now_dec))
    A("")
    A("## Bottom line")
    A("")

    # ---- line 1: the one setup ----
    if not setup_t and not cash_cand:
        A("1. **The one setup** - no name carries an anchored catalyst this morning - the setup "
          "is cash, and the levels below are the watch list, not a position.")
    elif not setup_t:
        r = by_ticker[cash_cand]
        pm, hi, lo = num(r["premarket_close"]), num(r["premarket_high"]), num(r["premarket_low"])
        pc = pm / (1 + num(r["premarket_change"]) / 100.0)
        h = hold_pct(r)
        drv, _note = driver_for(r, drivers, morning)
        A("1. **The one setup** - no name carries an anchored catalyst that clears the setup slot "
          "this morning - %s - so the setup is cash, and the levels below are the watch list, not "
          "a position: the closest candidate is **%s** at **%+.2f%%** (Hold **%s**, a print of "
          "**%s** inside a %s-%s pre-market range, `%s`), and a trade back to/below prior close "
          "**%s** invalidates it."
          % (cash_note, cash_cand, num(r["premarket_change"]),
             ("%d%%" % h) if h is not None else "an unknown share",
             fmt(pm, 4).rstrip("0").rstrip("."),
             fmt(lo, 4).rstrip("0").rstrip("."), fmt(hi, 4).rstrip("0").rstrip("."),
             drv, fmt(pc, 2)))
    else:
        r = by_ticker[setup_t]
        pm, hi, lo = num(r["premarket_close"]), num(r["premarket_high"]), num(r["premarket_low"])
        pc = (num(r["premarket_close"]) / (1 + num(r["premarket_change"]) / 100.0))
        h = hold_pct(r)
        drv, note = driver_for(r, drivers, morning)
        base = drv.replace("+ANCHORED", "")
        rung_txt = ("rung 1 - the class is one of the five" if rung == 1 else
                    "rung 2 - a class outside the five-class list, taken because the gap is "
                    "still holding")
        note_txt = (" - its catalyst is anchored: %s" % note) if note else ""
        A("1. **The one setup** - **%s** (%s) - a break of its pre-market high **%s** is the "
          "trigger, invalidated by a trade back to/below prior close **%s**; the gap is "
          "**%+.2f%%** at a print of **%s**, which is %s of its %s-%s pre-market range%s - so "
          "this is a %s slot: `%s`."
          % (setup_t, r.get("description") or setup_t, fmt(hi, 4).rstrip("0").rstrip("."),
             fmt(pc, 2), num(r["premarket_change"]), fmt(pm, 4).rstrip("0").rstrip("."),
             ("%d%%" % h) if h is not None else "an unknown share",
             fmt(lo, 4).rstrip("0").rstrip("."), fmt(hi, 4).rstrip("0").rstrip("."),
             note_txt, rung_txt, drv))

    # ---- line 2: the one risk ----
    if risk_t and risk_t in by_ticker:
        r = by_ticker[risk_t]
        pc = num(r["premarket_close"]) / (1 + num(r["premarket_change"]) / 100.0)
        lo = num(r["premarket_low"])
        gap = num(r["premarket_change"])
        # The level that ends the move follows the gap's DIRECTION: on a gap-up a trade back
        # to/below the prior close ENDS the gap, and on a gap-down a break of the pre-market
        # low says the move is still running.  One template cannot say both.
        if gap >= 0:
            level_txt = ("a trade back to/below the prior close **%s** says the gap is gone"
                         % fmt(pc, 2))
        else:
            level_txt = ("a break of the pre-market low **%s** says the move is still running"
                         % fmt(lo, 4).rstrip("0").rstrip("."))
        A("2. **The one risk** - **%s** - %s: %s is **%+.2f%%** at **%s** against a prior close "
          "of **%s**, and %s."
          % (risk_t, risk.get("clause") or "the risk to this tape",
             risk_t, gap, fmt(num(r["premarket_close"]), 4).rstrip("0").rstrip("."),
             fmt(pc, 2), level_txt))
    else:
        A("2. **The one risk** - no name in the screen cleared the gates on the downside, so "
          "there is no single name to name - watch the index futures and the 10-year at the open.")

    # ---- line 3: the one thing to watch at the open ----
    if watch_t and watch_t in by_ticker:
        r = by_ticker[watch_t]
        pc = num(r["premarket_close"]) / (1 + num(r["premarket_change"]) / 100.0)
        gap = num(r["premarket_change"])
        # Same rule as the risk line: on a gap-up an open ABOVE the last print keeps it bid,
        # and on a gap-down an open BELOW it says the seller is still there.
        if gap >= 0:
            open_txt = ("an open above **%s** keeps it bid, below **%s** confirms the gap is gone"
                        % (fmt(num(r["premarket_close"]), 4).rstrip("0").rstrip("."),
                           fmt(num(r["premarket_low"]), 4).rstrip("0").rstrip(".")))
        else:
            open_txt = ("an open below **%s** says the seller is still there, a reclaim of **%s** "
                        "says the gap is being bought back"
                        % (fmt(num(r["premarket_close"]), 4).rstrip("0").rstrip("."),
                           fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip(".")))
        A("3. **The one thing to watch at the open** - **%s** - %s: %s is **%+.2f%%** at a print "
          "of **%s** against a prior close of **%s**, inside a %s-%s pre-market range; %s."
          % (watch_t, watch.get("clause") or "the name to watch", watch_t,
             gap, fmt(num(r["premarket_close"]), 4).rstrip("0").rstrip("."),
             fmt(pc, 2), fmt(num(r["premarket_low"]), 4).rstrip("0").rstrip("."),
             fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip("."), open_txt))
    else:
        A("3. **The one thing to watch at the open** - the index futures and the 10-year - a "
          "move against the tape before the bell is the level that decides the session.")

    A("")
    A("## What to watch at the open")
    A("")
    A("| Name | Prior close | PM last | PM low | PM high | Trigger | Invalidation |")
    A("|---|---|---|---|---|---|---|")
    for t, trig, inv in ((setup_t or cash_cand, None, None), (risk_t, None, None),
                         (watch_t, None, None)):
        if not t or t not in by_ticker:
            continue
        r = by_ticker[t]
        pc = num(r["premarket_close"]) / (1 + num(r["premarket_change"]) / 100.0)
        gap = num(r["premarket_change"])
        if gap >= 0:
            trig = "break of PM high %s" % fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip(".")
            inv = "back to/below prior close %s" % fmt(pc, 2)
        else:
            trig = "break below PM low %s" % fmt(num(r["premarket_low"]), 4).rstrip("0").rstrip(".")
            inv = "reclaim of PM high %s" % fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip(".")
        A("| %s | %s | %s | %s | %s | %s | %s |"
          % (t, fmt(pc, 2), fmt(num(r["premarket_close"]), 4),
             fmt(num(r["premarket_low"]), 4).rstrip("0").rstrip("."),
             fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip("."),
             trig, inv))
    A("")
    if market_open:
        A("- **Rule 1 - the open is the verdict on the gap.** An open BELOW the last pre-market "
          "print means the gap is being sold, not bought. **This file's pull landed at %s, after "
          "the 09:30 ET open, so the open has already happened** - the live regular-session price "
          "is published in the companion CSV's `live_close` column, and a live price below the "
          "last pre-market print is Rule 1's verdict already rendered." % snap)
        A("- **Rule 2 - the 30-minute candle is the breakout test.** If, thirty minutes after the "
          "open, the session high is STILL the opening-range high, the gap is a fade, not a "
          "breakout. **That 30-minute check has already printed** on this file - the levels in "
          "it are exit levels, not entry levels.")
    else:
        A("- **Rule 1 - the open is the verdict on the gap.** An open BELOW the last pre-market print "
          "means the gap is being sold, not bought. This refresh fires at 09:20, so it cannot apply "
          "Rule 1 - it publishes the last pre-market print and the PM low so the reader can apply it "
          "at 09:31.")
        A("- **Rule 2 - the 30-minute candle is the breakout test.** If, thirty minutes after the "
          "open, the session high is STILL the opening-range high, the gap is a fade, not a "
          "breakout; the levels in this file are then exit levels, not entry levels. This is a 10:00 "
          "check, not a 09:45 one.")
    A("")
    A("## 1. Refreshed top-of-book")
    A("")
    A("The +/-3%% pre-market band held **%d gainers and %d decliners** at %s. Gate A is "
      "pre-market volume of 100,000 shares, or a $200m cap with 10,000 pre-market shares; Gate B "
      "is a $100m market cap decided on the reconciled cap. **%d of the %d band gainers and %d of "
      "the %d band decliners clear both gates.** The two tables below carry the top 15 gainers "
      "and the top 10 decliners of those qualifying sets - **gainers: showing %d of 15, "
      "decliners: showing %d of 10**."
      % (now_gain, now_dec, snap,
         q_gain, now_gain, q_dec, now_dec,
         head_gain_rows, head_decl_rows))
    A("")
    A("### Top 15 gainers")
    A("")
    A("| Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector | Snapshot |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in head_up:
        A("| %s | %s | %s | %+.2f%% | %s | %s | %s | %s | %s |"
          % (r["ticker"], r.get("description") or "", fmt(num(r["premarket_close"]), 4),
             num(r["premarket_change"]), "{:,.0f}".format(num(r["premarket_volume"]) or 0),
             ("%.2f%%" % adv_pct(r)) if adv_pct(r) is not None else "n/a",
             cap_plain(cap_of(r)), r.get("sector") or "", snap_hm))
    A("")
    A("### Top 10 decliners")
    A("")
    A("| Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector | Snapshot |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in head_dn:
        A("| %s | %s | %s | %+.2f%% | %s | %s | %s | %s | %s |"
          % (r["ticker"], r.get("description") or "", fmt(num(r["premarket_close"]), 4),
             num(r["premarket_change"]), "{:,.0f}".format(num(r["premarket_volume"]) or 0),
             ("%.2f%%" % adv_pct(r)) if adv_pct(r) is not None else "n/a",
             cap_plain(cap_of(r)), r.get("sector") or "", snap_hm))
    A("")
    A("### Thin tape")
    A("")
    A("Real prints on thin books: the Gate-A-passing, Gate-B-failing names, published in full - "
      "**%d gainers and %d decliners qualify and all %d are shown below**. These never top a "
      "headline table." % (len(thin_up), len(thin_dn), len(thin_up) + len(thin_dn)))
    A("")
    A("| Ticker | Name | Pre-market | % | Pm vol | Mkt cap | Side |")
    A("|---|---|---|---|---|---|---|")
    for r in thin_up + thin_dn:
        A("| %s | %s | %s | %+.2f%% | %s | %s | %s |"
          % (r["ticker"], r.get("description") or "", fmt(num(r["premarket_close"]), 4),
             num(r["premarket_change"]), "{:,.0f}".format(num(r["premarket_volume"]) or 0),
             cap_plain(cap_of(r)), "gainer" if num(r["premarket_change"]) > 0 else "decliner"))
    A("")
    shells = sorted([r for r in thin_up + thin_dn if (cap_of(r) or 0) < 10_000_000],
                     key=lambda r: -abs(num(r["premarket_change"])))
    if shells:
        top = shells[0]
        A("**The largest prints in this block are not market moves.** %s is **%+.2f%%** on %s "
          "pre-market shares against a %s market cap - a market cap of that size is a shell by "
          "arithmetic, not a market. %s on this block are the same profile: recap, reverse-split, "
          "shell and micro-float events, **not themes**, and no catalyst is claimed for any of "
          "them here."
          % (top["ticker"], num(top["premarket_change"]),
             "{:,.0f}".format(num(top["premarket_volume"]) or 0), cap_str(cap_of(top)),
             ", ".join(r["ticker"] for r in shells[1:6])))
    excluded = [r for r in rows if not gate_a(r) and abs(num(r["premarket_change"]) or 0) >= 3]
    excluded.sort(key=lambda r: -abs(num(r["premarket_change"])))
    if excluded:
        e = excluded[0]
        A("")
        A("**%d band name%s excluded from every table for liquidity %s named here so nothing is "
          "hidden.** %s printed **%+.2f%%** at **%s** on **%s** pre-market shares - below the "
          "10,000-share floor Gate A sets - so it is an unverifiable print, not a market."
          % (len(excluded), "" if len(excluded) == 1 else "s",
             "is" if len(excluded) == 1 else "are", e["ticker"], num(e["premarket_change"]),
             fmt(num(e["premarket_close"]), 4).rstrip("0").rstrip("."),
             "{:,.0f}".format(num(e["premarket_volume"]) or 0)))
    A("")
    # ---- the tail tier: the names the gates and the table cap left out ----
    headline = set(r["ticker"] for r in head_up + head_dn)
    tail_pool = [r for r in rows if r["ticker"] not in headline]
    gate_fail = [r for r in tail_pool if not (gate_a(r) and gate_b(r))]
    unranked = [r for r in tail_pool if gate_a(r) and gate_b(r)]
    gf = sorted(gate_fail, key=lambda r: -abs(num(r["premarket_change"]) or 0))[:TAIL_GATE_FAIL]
    ur = sorted(unranked, key=lambda r: -abs(num(r["premarket_change"]) or 0))[:TAIL_UNRANKED]
    tail_rows = sorted(gf + ur, key=lambda r: -abs(num(r["premarket_change"]) or 0))
    A("### Tail - refreshed")
    A("")
    A("The names the gates and the table cap left out, on this pull's print (**%s**) instead of "
      "the 08:30 one, ranked by `|gap|` and direction-agnostic. `gate-fail` failed the liquidity "
      "or the quality gate, `unranked` cleared both gates but did not make the headline tables. "
      "This is a watchlist, not a second set of setups - no name here is promoted into the "
      "top-of-book. The `flat-print` cohort (a gap inside 3%%) is absent by construction: those "
      "names are outside the band and therefore not in this file's CSV. **%d of %d** candidates "
      "are shown, and the cohorts are mixed on purpose - the gate-failing cohort alone is %d "
      "names deep and would read as noise."
      % (snap, len(tail_rows), len(tail_pool), len(gate_fail)))
    A("")
    A("| Ticker | Cohort | Prior close | Pre-market last | Gap % | PM range | Key level | "
      "Invalidation |")
    A("|---|---|---|---|---|---|---|---|")
    for r in tail_rows:
        pm = num(r["premarket_close"])
        pc = pm / (1 + num(r["premarket_change"]) / 100.0)
        lo, hi = num(r["premarket_low"]), num(r["premarket_high"])
        A("| %s | %s | %s | %s | %+.2f%% | %s-%s | %s | %s |"
          % (r["ticker"], "gate-fail" if r in gf else "unranked", fmt(pc, 2),
             fmt(pm, 4).rstrip("0").rstrip("."), num(r["premarket_change"]),
             fmt(lo, 4).rstrip("0").rstrip("."), fmt(hi, 4).rstrip("0").rstrip("."),
             key_level(r, pc), invalidation(r, pc)))
    A("")
    A("## 2. Gap quality - can this gap hold?")
    A("")
    A("One row per headline name, all from the SAME single pull. **Print** is a descriptor of how "
      "the gap was made and whether it is still holding, not a filter - the **Driver** column is "
      "what ranks.")
    A("")
    A("| Ticker | Name | Gap % | PM range | Hold % | pm %ADV | Print | Driver | Key level | "
      "Invalidation |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in head_up + head_dn:
        pc = num(r["premarket_close"]) / (1 + num(r["premarket_change"]) / 100.0)
        h = hold_pct(r)
        q, hf = print_flags(r)
        drv, _ = driver_for(r, drivers, morning)
        A("| %s | %s | %+.2f%% | %s-%s | %s | %s | %s+%s | %s | %s | %s |"
          % (r["ticker"], r.get("description") or "", num(r["premarket_change"]),
             fmt(num(r["premarket_low"]), 4).rstrip("0").rstrip("."),
             fmt(num(r["premarket_high"]), 4).rstrip("0").rstrip("."),
             h if h is not None else "n/a",
             ("%.2f%%" % adv_pct(r)) if adv_pct(r) is not None else "n/a",
             q, hf, drv, key_level(r, pc), invalidation(r, pc)))
    A("")
    A("- **PM range** = `premarket_low` - `premarket_high`. **Hold %** = (premarket_close - low) / "
      "(high - low) x 100: 100 = the last print is at the top of its pre-market range (the gap is "
      "holding), 0 = it is at the bottom (the gap is gone). **pm %ADV** = premarket_volume / "
      "average_volume_30d x 100.")
    A("- **Driver** is read from the catalyst the 08:30 brief already sourced - this file searches "
      "for no news. `has_news = no` in the morning CSV is `NONE`, and so is a name whose cluster "
      "carried the news but whose own catalyst was not sourced.")
    A("")
    A("## 3. What changed since the morning brief")
    A("")
    both = [t for t in live_gap if t in morning]
    A("**%d of the %d names present in both this pull and the morning brief's CSV moved by more "
      "than 0.2 percentage points** - the gap is live and most of the tape repriced between the "
      "two pulls. Sorted by the size of the change, not by the size of the gap."
      % (changes_since, len(both)))
    A("")
    A("| Ticker | Morning gap | Refresh gap | Change | Hold % |")
    A("|---|---|---|---|---|")
    for _, d, t, mg, lg in moved[:20]:
        h = hold_pct(by_ticker[t])
        A("| %s | %+.2f%% | %+.2f%% | %+.2fpp | %s |" % (t, mg, lg, d, h if h is not None else "n/a"))
    A("")
    A("**Of the morning brief's published setups, the ones that moved most:**")
    A("")
    A("| Ticker | Morning gap | Refresh gap | Change | Driver |")
    A("|---|---|---|---|---|")
    for _, d, t, mg, g in setup_moves[:12]:
        if g is None:
            A("| %s | %+.2f%% | out of the band | out of band | %s |"
              % (t, mg, driver_for({"ticker": t}, drivers, morning)[0]))
        else:
            A("| %s | %+.2f%% | %+.2f%% | %+.2fpp | %s |"
              % (t, mg, g, d, driver_for(by_ticker[t], drivers, morning)[0]))
    A("")
    real_moves = [x for x in setup_moves if x[1] is not None]
    big_setup = real_moves[0] if real_moves else None
    flips = [x for x in real_moves if (x[3] > 0) != (x[4] > 0)]
    if big_setup:
        t, mg, g = big_setup[2], big_setup[3], big_setup[4]
        # The verb follows the SIGN of the change. The old template said "gave back" whatever
        # the sign was, so a setup whose gap EXTENDED was published as "gave back 7.48pp, from
        # +13.08% to +20.56%" — a sentence that contradicts the two numbers in it.
        # Measured 2026-11-18 (BRBR, +7.48pp).
        delta = big_setup[1]
        # The verb follows the DIRECTION of the gap, not just the sign of the change. Measured
        # 2026-11-19: SLS moved from -20.61% to -14.15% and the artifact published "extended its
        # gap 6.46pp" - on a gap-DOWN name a POSITIVE change is the decline NARROWING, so the
        # sentence contradicted the two numbers in it.
        if (num(mg) or 0) < 0:
            verb = ("widened its decline **%.2fpp**" % abs(delta)) if delta < 0 else \
                   ("narrowed its decline **%.2fpp**" % abs(delta))
        else:
            verb = ("gave back **%.2fpp**" % abs(delta)) if delta < 0 else \
                   ("extended its gap **%.2fpp**" % abs(delta))
        A("**Two facts behind those numbers.** %s - one of the morning brief's setups - %s, "
          "from %+.2f%% to %+.2f%%.%s"
          % (t, verb, mg, g,
             (" A second setup flipped sign, from %+.2f%% to %+.2f%%."
              % (flips[0][3], flips[0][4])) if flips else ""))
    wid = sorted([x for x in moved if x[4] < 0 and x[1] < 0], key=lambda x: x[1])[:4]
    if wid:
        A("On the other side the decliners widened: %s."
          % ", ".join("%s %+.2f%% to %+.2f%%" % (x[2], x[3], x[4]) for x in wid))
    A("")
    A("**Band membership.** The band went from the brief's %s to %d / %d. "
      "Of the %d band names the morning brief published in its CSV, **%d no longer clear the "
      "+/-3%% band**%s and **%d published name%s entered it**.%s"
      % (fm_band_text(fm_morning), now_gain, now_dec,
         len(mband), len(faded),
         (" (%s)" % ", ".join(faded)) if faded else "", len(entered),
         "" if len(entered) == 1 else "s",
         (" The other %d names in the live band were never published in the morning CSV, so the "
          "baseline cannot say whether they entered or faded - see Source health."
          % unclassified) if unclassified else ""))
    A("")
    A("## 4. Verdict")
    A("")
    v = slots.get("verdict") or {}
    A("**%s directional, and to the %s.** %s"
      % (direction.capitalize(), side,
         v.get("clause") or
         ("The decliner side moved from %s to %d, of the %d names in common that are on the "
          "downside **%d widened their gap and %d narrowed it**, and on the long side %d gaps "
          "extended while %d gave their gaps back. %d of the %d names in common repriced by more "
          "than 0.2pp."
          % (("%d names" % int(then_dec)) if then_dec is not None else "an unpublished count",
             now_dec, widened + narrowed, widened, narrowed,
             ext, fad, changes_since, len(both)))))
    A("")
    A("## 5. Source health")
    A("")
    A("- **One pull.** Every number in this file and in the companion CSV comes from a single pull "
      "of the TradingView `america` scanner at %s. Both screens were pulled with `range:[0,1000]` "
      "and `len(rows) == totalCount` held on each (%d/%d gainers, %d/%d decliners), so "
      "`screen_complete: %s` and the band counts are exact."
      % (snap, now_gain, now_gain, now_dec, now_dec,
         "true" if merged.get("band", {}).get("complete", True) else "false"))
    if not market_open:
        A("- **The regular session had not opened at the pull.** The scanner's `close` column is "
          "the last completed regular session's close, and the companion CSV's `live_close`, "
          "`live_change_pct` and `live_volume` columns are **blank, never 0**.")
    # The gate's OWN totals. `close_field_defects` is the SAMPLE the gate prints (it names the
    # first 20 rows); `failed` and `checked` are the totals. Measured 2026-11-19: the gate
    # returned OPEN with 581 of 747 common names off their prior close, and the artifact
    # published "disagreed ... on 20 name(s) ... These are ISOLATED field defects, NOT a live
    # session" - which contradicted its own front matter (`market_open_at_pull: true`) and the
    # gate's verdict. The GATE WINS: when the gate says the session is live, the wholesale
    # `close` movement IS the live session, and the artifact says so.
    pt = (gate.get("tests") or {}).get("prior_close_matches_morning") or {}
    gate_failed = num(pt.get("failed"))
    gate_checked = num(pt.get("checked"))
    defect_ct = int(gate_failed) if gate_failed is not None else len(defects)
    if market_open:
        A("- **The scanner's `close` column is the LIVE regular-session price, not the prior "
          "close.** It disagreed with the morning brief on %d of the %d common names — that "
          "wholesale move IS the live session the gate reads, and it is why the front matter "
          "carries `market_open_at_pull: true`. The published prior close for every name is the "
          "DERIVED one (from the pre-market print), never the scanner's `close`."
          % (defect_ct, int(gate_checked) if gate_checked is not None else defect_ct))
    elif defects:
        A("- **The scanner's `close` column disagreed with the morning brief on %d name(s): %s.** "
          "These are ISOLATED field defects, not a live session — the gate reads a live session "
          "as the `close` column moving off the prior close for essentially every common name. "
          "The morning brief's own Source health usually names the same rows it corrected, and "
          "the published prior close for each of these names is the derived one, not the "
          "scanner's `close`." % (defect_ct, ", ".join(defects)))
    if gate_state and gate_state != args.session_state.upper():
        A("- **The session-state gate returned `%s` and this file is published as `%s`.**%s The "
          "gate's own reason: %s"
          % (gate_state, args.session_state.upper(),
             (" " + args.state_note) if args.state_note else "",
             gate.get("verdict_reason") or "not recorded"))
    A("- **`prior_close` is DERIVED**, never taken from the screener's `close` column: "
      "`round(premarket_close / (1 + premarket_change_pct / 100), 4)`, computed from the values "
      "this CSV publishes (4 dp price, 2 dp change) so every row reproduces its own prior close.")
    capsrc = {}
    for r in rows:
        s = r.get("cap_source")
        if s:
            capsrc[s] = capsrc.get(s, 0) + 1
    if capsrc:
        A("- **Market cap**: %s. The cap published for a name is the RECONCILED one where the pull "
          "could corroborate it, and the scanner's own `market_cap_basic` otherwise."
          % "; ".join("%s (%d names)" % (k, v) for k, v in sorted(capsrc.items(), key=lambda x: -x[1])[:3]))
    if setup_t:
        A("- **The setup slot is a %s slot.** The ladder takes the first rung that is satisfiable: "
          "anchored plus one of the five classes (rung 1), then anchored plus any class whose gap "
          "is still holding at Hold 80 or better (rung 2). The slot is a LONG on a gap-up - the "
          "trigger is the pre-market high, the level that must break for the gap to extend - so "
          "a rung-1 class sitting on a gap-down name whose gap has already given back its range "
          "is not a setup."
          % ("rung-1" if rung == 1 else "rung-2"))
    none_ct = sum(1 for r in head_up + head_dn
                  if driver_for(r, drivers, morning)[0] == "NONE")
    head_ct = len(head_up) + len(head_dn)
    A("- **The Driver is read from the morning brief's OWN sourced catalysts**, per name - "
      "`has_news = no` is `NONE`, and so is a name whose cluster carried the news but whose own "
      "catalyst was not sourced. `NONE` is a finding: %d of the %d headline names have no "
      "sourced catalyst." % (none_ct, head_ct))
    A("- **The morning brief's CSV is a published-name subset, not the whole band.** It holds %d "
      "rows (%d of them in the +/-3%% band) against a band the brief counted at %s names, so "
      "band-level fade and entrant counts cannot be derived from it: a name absent from the CSV "
      "was never published, which is not the same as having faded out of the band. **The "
      "comparison base used here is the %d published band names**, and the fade count (%d) and "
      "the entrant count (%d) are stated against that base. The %d live-band names the morning "
      "CSV never carried are reported as unclassified rather than counted as entrants."
      % (len(morning), len(mband),
         (num(fm_morning.get("up_3pct")) or 0) + (num(fm_morning.get("down_3pct")) or 0),
         len(mband), len(faded), len(entered), unclassified))
    A("- **No catalyst was searched for in this run.** The Driver column carries the catalyst the "
      "08:30 brief already sourced and labels it with the fixed vocabulary. A name with no "
      "sourced catalyst is `NONE`.")
    nulls = [r["ticker"] for r in rows if num(r.get("average_volume_30d_calc")) is None
             or cap_of(r) is None]
    if nulls:
        A("- **%d row%s carr%s a null value from the scanner** (%s) and %s published **empty, "
          "never 0**: a missing average volume is not a zero volume, and a zero would make "
          "`pct_of_adv` a fabricated number."
          % (len(nulls), "" if len(nulls) == 1 else "s", "ies" if len(nulls) == 1 else "y",
             ", ".join(nulls[:6]), "their cells are" ))
    A("")
    A("---")
    A("")
    A("_Companion CSV: `daily-briefs/%s-pre-market-refresh.csv` - %d rows, one per name in the "
      "screened band, same pull as this file._" % (args.date, len(rows)))
    A("")

    md = "\n".join(L)

    # ---------------- the companion CSV ----------------
    csv_rows = []
    for r in sorted(rows, key=lambda x: (0 if (num(x["premarket_change"]) or 0) > 0 else 1,
                                         -(num(x["premarket_change"]) or 0))):
        pm = round(num(r["premarket_close"]), 4)
        chg = round(num(r["premarket_change"]), 2)
        prior = round(pm / (1 + chg / 100.0), 4)
        adv = num(r.get("average_volume_30d_calc"))
        pv = num(r.get("premarket_volume"))
        cap = cap_of(r)
        advp = (pv / adv * 100.0) if (adv and pv is not None) else None
        # `prior_session_change_pct` is the PRIOR session's move.  In a pre-open pull the
        # scanner's `change` IS that move; in a LATE pull the scanner's `change` is TODAY's
        # move, so the number comes from the morning CSV (pulled pre-open) and is EMPTY for
        # a name the morning CSV never carried - never today's move under the wrong header,
        # and never 0.  The three `live_*` columns carry the regular session once the pull
        # has landed after the open; before it they are EMPTY, never 0.
        if market_open:
            psc_raw = (morning.get(r["ticker"]) or {}).get("prior_session_change_pct")
            psc_val = ("%.2f" % num(psc_raw)) if num(psc_raw) is not None else ""
            live_close = ("%.4f" % num(r["close"])) if num(r.get("close")) is not None else ""
            live_chg = ("%.2f" % num(r["change"])) if num(r.get("change")) is not None else ""
            live_vol = ("%d" % num(r["volume"])) if num(r.get("volume")) is not None else ""
        else:
            psc_val = ("%.2f" % num(r["change"])) if num(r.get("change")) is not None else ""
            live_close, live_chg, live_vol = "", "", ""
        csv_rows.append([
            r["ticker"], r.get("description") or "", "%.4f" % pm, "%.2f" % chg,
            "{:,.0f}".format(pv or 0).replace(",", ""),
            ("%d" % int(adv)) if adv is not None else "",
            ("%.2f" % advp) if advp is not None else "",
            "%.4f" % prior,
            psc_val,
            live_close, live_chg, live_vol,
            ("%.0f" % cap) if cap is not None else "",
            r.get("sector") or "", r.get("exchange") or "",
            "true" if merged.get("band", {}).get("complete", True) else "false"])

    # ---------------- internal checks (a broken artifact must not be written) ----------------
    problems = []
    if len(csv_rows) != len(rows):
        problems.append("the CSV has %d rows for %d names" % (len(csv_rows), len(rows)))
    if market_open and all(not r[9] for r in csv_rows):
        problems.append("market_open_at_pull is true but live_* are blank")
    if not market_open and not all((not r[9]) and (not r[10]) and (not r[11]) for r in csv_rows):
        problems.append("the pull was pre-open but live_* are not blank on every row")
    for r in csv_rows:
        try:
            pmf, chf, pcf = float(r[2]), float(r[3]), float(r[7])
        except ValueError:
            problems.append("%s has an unparseable price/change/prior_close" % r[0])
            break
        if abs(pmf / (1 + chf / 100.0) - pcf) > 0.0005 + abs(pcf) * 1e-6:
            problems.append("%s does not reproduce its own prior close" % r[0])
            break
        # A missing average volume is not a zero volume: the cell is published EMPTY and so is
        # its %ADV. This is the invariant the 2026-11-12 run broke (it published avg=0 and a
        # fabricated pct_of_adv of 100000.00%). A %ADV of 74229.73% is NOT a fabrication — it is
        # honest arithmetic on a name whose 30-day average is a few thousand shares — so the
        # magnitude is not policed, only the presence/absence correspondence.
        if bool(r[5].strip()) != bool(r[6].strip()):
            problems.append("%s has avg_volume_30d %s but pct_of_adv %s"
                            % (r[0], r[5] or "EMPTY", r[6] or "EMPTY"))
            break
        if r[5].strip() and float(r[5]) <= 0:
            problems.append("%s has a non-positive avg_volume_30d" % r[0])
            break
        if r[6].strip() and float(r[6]) > 1e8:
            problems.append("%s has an impossible pct_of_adv (%s)" % (r[0], r[6]))
            break
    for ph in ("TODO", "TBD", "FIXME", "PLACEHOLDER", "{", "}"):
        if ph in md:
            problems.append("the markdown contains the placeholder %r" % ph)
            break
    if problems:
        for p in problems:
            print("  BUILD FAILED: %s" % p, file=sys.stderr)
        print("nothing was written", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    md_path = os.path.join(args.out_dir, "%s-pre-market-refresh.md" % args.date)
    csv_path = os.path.join(args.out_dir, "%s-pre-market-refresh.csv" % args.date)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        w.writerows(csv_rows)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)

    print("built %s" % md_path, file=sys.stderr)
    print("built %s (%d rows)" % (csv_path, len(csv_rows)), file=sys.stderr)
    print("  band: %d gainers / %d decliners (complete=%s)" % (now_gain, now_dec,
          merged.get("band", {}).get("complete", True)), file=sys.stderr)
    print("  setup: %s (rung %s)  risk: %s  watch: %s"
          % (setup_t or "(cash)", rung or "-", risk_t or "-", watch_t or "-"), file=sys.stderr)
    print("  changed since the morning brief: %d of %d common names" % (changes_since, len(both)),
          file=sys.stderr)
    print("  base: %d published band names -> %d faded, %d entered, %d unclassified"
          % (len(mband), len(faded), len(entered), unclassified), file=sys.stderr)
    return 0


def merged_pulled_at(path):
    """The pull's own ET clock. NEVER hand-type it: the environment's America/New_York has no
    DST (November is EST, UTC-5), so a hand-typed or UTC-4 clock reads an hour late."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, dict):
            return obj.get("pulled_at_et") or obj.get("pulled_at") or ""
    except (OSError, ValueError):
        pass
    return ""


def main():
    ap = argparse.ArgumentParser(description="build the cron #26b pre-market-refresh artifact")
    ap.add_argument("--merged", required=True, help="brief26_pull.py's merged.json")
    ap.add_argument("--morning-md", default=None)
    ap.add_argument("--morning-csv", default=None)
    ap.add_argument("--slots", default=None, help="the run's judgement: drivers, setup, risk, watch")
    ap.add_argument("--date", required=True)
    ap.add_argument("--fire-time-et", default=None,
                    help="the fire's ET clock (default: <date> 09:20 — this routine's slot)")
    ap.add_argument("--snapshot-et", default=None,
                    help="the pull's ET clock (default: taken from the merged file's pulled_at_et)")
    ap.add_argument("--session-state", default="PRE-OPEN", choices=["PRE-OPEN", "OPEN"])
    ap.add_argument("--state", default=None,
                    help="session_state.py's verdict file (state.json). The builder reads the "
                         "gate's OWN verdict and the names of any isolated scanner `close` "
                         "defects from it, and publishes both in Source health")
    ap.add_argument("--state-note", default=None,
                    help="the run's reason when it publishes a session state other than the "
                         "gate's verdict")
    ap.add_argument("--stall-min", type=int, default=0,
                    help="the platform's delay before this fire's first tool call, in minutes "
                         "(from the window check's stall_min) - published in the intro")
    ap.add_argument("--out-dir", default="daily-briefs")
    args = ap.parse_args()
    if not args.fire_time_et:
        args.fire_time_et = "%s 09:20" % args.date
    if not args.snapshot_et:
        pulled = str(merged_pulled_at(args.merged))
        m = re.search(r"(\d{2}:\d{2}(?::\d{2})?)", pulled)
        args.snapshot_et = m.group(1) if m else "00:00"
    return build(args)


if __name__ == "__main__":
    sys.exit(main())

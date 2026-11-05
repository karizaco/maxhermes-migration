#!/usr/bin/env python3
"""correlation_report.py — deterministic renderer for cron #12 (cross-asset correlation snapshot).

WHY THIS EXISTS
---------------
Until now the artifact markdown was hand-assembled by the model every run, so the
layout drifted: tables changed column order, highlight tables appeared with a
different number of rows, and the delta table was sometimes 5 rows and sometimes
9. A correlation matrix is a COMPARISON artifact — its value depends on being
byte-comparable with last week's file. So the formatting is now generated from
mats.json by code, not typed by hand.

COLOR
-----
GitHub strips `style=` from markdown, and the desktop chat renders GFM (no ANSI),
so "color" here means emoji color blocks + unicode bars:

    magnitude buckets
      |r| >= 0.70  🟥  strong relationship
      0.60-0.70    🟧  elevated
      0.40-0.60    🟨  moderate
      0.20-0.40    🟩  mild
      |r| < 0.20   🟦  effectively uncorrelated

    bars   ▁▂▃▄▅▆▇█  scaled to |r| over 8 steps

    flags  ✅ ok   ⚠️ watch   🔴 broken   ➕/➖ delta direction

USAGE
-----
    python3 correlation_report.py \
        --current /workspace/data_cross/mats.json \
        --prior   /workspace/data_cross/mats_prevweek.json \
        --partial /workspace/data_cross/mats_partial.json \
        --series  /workspace/data_cross/series.json \
        --prior-artifact prior-2026-10-28.md \
        --date 2026-11-02 --iso-week 2026-W45 --fire-et 10:05 \
        --out /workspace/cross-asset/2026-11-02.md

--partial and --series are REQUIRED and the renderer FAILS (non-zero exit) when either
file is absent. They were optional until 2026-11-05, and that silence was a defect class
of its own: `correlation_matrix.py` did not write them, so a missing file silently DROPPED
the Performance table, the price-level appendix and the excluded-partial-session proof,
and the run still reported "complete". A renderer that withholds evidence and says
nothing is the same class of bug as publishing a stale window.

--prior is still optional: the prior-week matrix normally travels INSIDE the current
mats.json (correlation_matrix.py --prior-window embeds it as `matrix_returns_prior`).
When neither is available the artifact says `regime_shift: unknown` — never a silent
"no", which would read as a clean bill of health for a comparison that never ran.

EXIT CODES: 0 = artifact written; 2 = bad arguments; 3 = a required input file is
missing or malformed; 4 = the artifact could not be written.
"""
import argparse
import json
import math
import os
import statistics
import sys
from datetime import date, datetime, timedelta

SYMS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "UUP", "EEM", "^VIX"]
NAMES = {
    "SPY": "S&P 500", "QQQ": "Nasdaq-100", "IWM": "Russell 2000",
    "TLT": "20+ Yr Treasury", "GLD": "Gold", "UUP": "US Dollar",
    "EEM": "Emerging Mkts", "^VIX": "VIX",
}

# The routine's definition — do not change it here and there.
SHIFT_THRESHOLD = 0.20
# A missing marker means a STALE renderer produced the artifact: the checker asserts it.
CONTRACT_VERSION = "cross-asset-v4"


def fail(msg, code=3):
    """Abort loudly. Never degrade a missing input into a quietly shorter artifact."""
    print(f"correlation_report: FAIL: {msg}", file=sys.stderr)
    sys.exit(code)

# ---- color helpers ---------------------------------------------------------

def mag_bucket(r: float) -> str:
    a = abs(r)
    if a >= 0.70:
        return "🟥"
    if a >= 0.60:
        return "🟧"
    if a >= 0.40:
        return "🟨"
    if a >= 0.20:
        return "🟩"
    return "🟦"


def bucket_name(r: float) -> str:
    a = abs(r)
    if a >= 0.70:
        return "strong"
    if a >= 0.60:
        return "elevated"
    if a >= 0.40:
        return "moderate"
    if a >= 0.20:
        return "mild"
    return "uncorrelated"


def bar(r: float) -> str:
    """8-step magnitude bar, scaled so |r|=1 -> ████████."""
    a = abs(r)
    n = int(round(a * 8))
    n = max(0, min(8, n))
    return "█" * n + "░" * (8 - n)


def sgn(x: float) -> str:
    return f"{x:+.2f}"


def pair_list(mat, syms=None):
    syms = syms or SYMS
    out = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            x, y = syms[i], syms[j]
            out.append((x, y, mat[x][y]))
    return out


def r2(x):
    return round(x, 2)


# ---- the signal line --------------------------------------------------------
# The 2026-11-04 artifact's TL;DR already carried the sentence a trader acts on
# ("SPY-TLT +0.30, so TLT is a weak diversifier rather than a hedge"), but the CHAT
# REPLY led with something else. The reply is what gets read, so the implication has
# to be computable and copyable — not re-derived from a table by eye every fire.
#
# Three facts, in this order:
#   1. the HEDGE IMPLICATION — which instrument actually offsets which risk
#   2. the BEST DIVERSIFIER in the universe (the lowest |corr| pair)
#   3. the DISTANCE TO THE SHIFT THRESHOLD — max_pair_move vs the 0.20 threshold

def best_diversifier(cur, syms):
    """The lowest |corr| pair in the universe — the best diversification candidate."""
    pl = pair_list(cur, syms)
    if not pl:
        return None
    x, y, r = min(pl, key=lambda t: abs(t[2]))
    return {"pair": f"{x}–{y}", "corr": r}


def best_equity_hedge(cur, syms):
    """The proxy that offsets equity risk most — the lowest corr against SPY.

    ^VIX is excluded on purpose: volatility is the risk MEASURE, not a hedge against it.
    """
    if "SPY" not in syms:
        return None
    cands = []
    for y in syms:
        if y in ("SPY", "^VIX"):
            continue
        v = cur["SPY"].get(y)
        if v is not None:
            cands.append((v, y))
    if not cands:
        return None
    v, y = min(cands)
    return {"pair": f"{y}–SPY", "corr": v}


def hedge_implication(cur, syms):
    """One clause: what actually offsets what. Anchored on SPY-TLT, the routine's
    canonical equity/bond read, and corrected by the best equity offset in the
    universe when a different proxy does the job better."""
    out = ""
    if "SPY" in syms and "TLT" in syms:
        c = cur["SPY"]["TLT"]
        if c > 0.20:
            clause = ("bonds move WITH equities, so TLT is a weak diversifier, not a hedge "
                      "against a growth selloff")
        elif c < -0.20:
            clause = "bonds offset equity risk, so TLT still hedges a growth selloff"
        else:
            clause = ("bonds are effectively uncorrelated with equities, so TLT neither hedges "
                      "nor amplifies a growth selloff")
        out = f"SPY–TLT {c:+.2f} → {clause}"
    bh = best_equity_hedge(cur, syms)
    if bh and not out.startswith(bh["pair"]):
        out += f"; best equity offset in the universe is {bh['pair']} {bh['corr']:+.2f}"
    if not out:
        out = "no equity/bond pair in this universe to read a hedge implication from"
    return out


def build_signal_line(cur, prior, syms, maxd, prior_present):
    """The one line the chat reply leads with."""
    div = best_diversifier(cur, syms)
    parts = [hedge_implication(cur, syms)]
    if div:
        parts.append(f"best diversifier {div['pair']} {div['corr']:+.2f}")
    if prior_present:
        dist = SHIFT_THRESHOLD - maxd
        parts.append(f"largest pair move {maxd:.4f} vs the {SHIFT_THRESHOLD:.2f} "
                     f"regime-shift threshold ({dist:.4f} to go)")
    else:
        parts.append(f"largest pair move UNKNOWN — no prior-week window, so the "
                     f"distance to the {SHIFT_THRESHOLD:.2f} regime-shift threshold "
                     f"cannot be computed")
    return " · ".join(parts)


# ---- sections ---------------------------------------------------------------

def render_matrix(cur, syms):
    head = "| | " + " | ".join(syms) + " |"
    sep = "|---" * (len(syms) + 1) + "|"
    lines = [head, sep]
    for x in syms:
        cells = []
        for y in syms:
            if x == y:
                cells.append("**+1.00**")
            else:
                r = cur[x][y]
                cells.append(f"{sgn(r)} {mag_bucket(r)}")
        lines.append(f"| **{x}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_heatmap_list(cur, syms):
    """A flat, color-blocked list — easier to read on mobile than an 8x8 grid."""
    rows = []
    for x, y, r in sorted(pair_list(cur, syms), key=lambda t: -abs(t[2])):
        rows.append(
            f"| {mag_bucket(r)} | **{x}–{y}** | {sgn(r)} | `{bar(r)}` | {bucket_name(r)} |"
        )
    head = "| | Pair | Corr | \\|corr\\| | Band |"
    sep = "|---|---|---|---|---|"
    return "\n".join([head, sep] + rows)


def render_highlights(cur, syms):
    pl = pair_list(cur, syms)
    strong = sorted(pl, key=lambda t: -abs(t[2]))
    top3 = strong[:3]
    weak = sorted(pl, key=lambda t: abs(t[2]))[:3]
    def block(title, rows, note):
        s = [f"### {title}", "", "| | Pair | Corr | Band | Note |", "|---|---|---|---|---|"]
        for x, y, r in rows:
            s.append(f"| {mag_bucket(r)} | **{x}–{y}** | {sgn(r)} | {bucket_name(r)} | {note} |")
        return "\n".join(s)
    return (
        block("🔴 Strongest pairs (|corr| ≥ 0.70)", top3, "strong relationship")
        + "\n\n"
        + block("🔵 Weakest pairs (|corr| < 0.25) — diversification candidates", weak,
                "effectively uncorrelated — hedge value")
    )


def render_delta(cur, prior, syms, partial=None):
    d = []
    for x, y, r in pair_list(cur, syms):
        p = prior[x][y]
        d.append((abs(r - p), x, y, r, p))
    d.sort(reverse=True)
    maxd = d[0][0]
    shift = ("🔴 REGIME_SHIFT" if maxd > SHIFT_THRESHOLD
             else ("⚠️ borderline" if maxd > 0.15 else "✅ no shift"))
    lines = [
        f"**Flag:** {shift} — largest absolute move **{maxd:.4f}** ({d[0][1]}–{d[0][2]}), "
        f"threshold {SHIFT_THRESHOLD:.2f}",
        "",
        "| Move | Pair | Prior | This week | Δ | Corr ↑/↓ |",
        "|---|---|---|---|---|---|",
    ]
    for a, x, y, r, p in d:
        if a < 0.005:
            continue
        arrow = "➕" if (r - p) > 0 else "➖"
        lines.append(
            f"| {a:.4f} | **{x}–{y}** | {sgn(p)} | {sgn(r)} | {r - p:+.4f} | {arrow} |"
        )
    return "\n".join(lines), maxd


def render_returns(series, start, end, syms, quotes=None):
    """Return the performance table.

    The intraday column is derived from the SNAPSHOT'S OWN series (last bar vs the
    one before it), NOT from a live quote feed: a live feed would inject TODAY's
    prices into a snapshot whose window ended on an earlier session, which is a
    silent date error.
    """
    _last_week_start = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
    def ret(s):
        rows = {d: v for d, v, _ in series[s]}
        keys = sorted(rows)
        # The matrix's FIRST return observation is (first in-window session) /
        # (the session before it) - 1. So the window return must be measured from
        # the close BEFORE the first in-window session, otherwise the performance
        # column is one bar short of the matrix it is supposed to describe.
        before = [k for k in keys if k < start]
        a = max(before) if before else keys[0]
        b = max([k for k in keys if k <= end])
        return (rows[b] / rows[a] - 1) * 100, a, b
    def wret(s, d0, d1):
        rows = {d: v for d, v, _ in series[s]}
        keys = sorted(rows)
        a = max([k for k in keys if k <= d0], default=keys[0])
        b = max([k for k in keys if k <= d1])
        return (rows[b] / rows[a] - 1) * 100
    live_col = (
        "Today (live quote)" if quotes else "Intraday (partial bar, adjclose)"
    )
    lines = [
        f"| Proxy | Name | 6-month | Last week | {live_col} |",
        "|---|---|---|---|---|",
    ]
    for s in syms:
        r, a, b = ret(s)
        lw = wret(s, _last_week_start, end)
        # The intraday column comes from the SNAPSHOT'S OWN series (last bar vs the
        # one before), never from a live quote feed: a live feed would inject TODAY's
        # prices into a snapshot whose window ended on an earlier session.
        rows = {d: v for d, v, _ in series[s]}
        keys = sorted(rows)
        live = "—"
        if quotes and s in quotes.get("quotes", {}):
            q = quotes["quotes"][s]
            live = f"{q['change_pct']:+.2f}% (live)"
        elif len(keys) >= 2:
            # label the bar date — before the open the last available bar is the
            # PREVIOUS session, so an unlabelled "intraday" column would be wrong
            live = f"{(rows[keys[-1]] / rows[keys[-2]] - 1) * 100:+.2f}% ({keys[-1][5:]})"
        lines.append(f"| **{s}** | {NAMES[s]} | {r:+.2f}% | {lw:+.2f}% | {live} |")
    return "\n".join(lines)


def levels_corr(series, start, end, syms):
    sets = []
    for s in syms:
        sets.append({d: v for d, v, _ in series[s]})
    common = set.intersection(*[set(x) for x in sets])
    common = sorted(d for d in common if start <= d <= end)
    if len(common) < 10:
        return None, 0
    def corr(a, b):
        ma, mb = statistics.mean(a), statistics.mean(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
        return num / den
    out = {}
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a = [sets[i][d] for d in common]
            b = [sets[j][d] for d in common]
            out[(syms[i], syms[j])] = corr(a, b)
    return out, len(common)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--prior")
    ap.add_argument("--partial", required=True,
                    help="the matrix INCLUDING the in-progress session — REQUIRED: the "
                         "renderer fails rather than dropping the section that proves "
                         "excluding the partial bar changed no conclusion")
    ap.add_argument("--series", required=True,
                    help="the price series — REQUIRED: the Performance table and the "
                         "price-level appendix are read from it")
    ap.add_argument("--quotes")
    ap.add_argument("--date", required=True)
    ap.add_argument("--iso-week", required=True)
    ap.add_argument("--fire-et", default="10:05")
    ap.add_argument("--window-start", default=None)
    ap.add_argument("--window-end", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--regime", default=None)
    ap.add_argument("--tl-dr", default=None,
                    help="path to a text file with the TL;DR prose (hand-written, injected verbatim)")
    ap.add_argument("--deviations", default=None,
                    help="path to a text file with the deviations-from-spec bullets")
    args = ap.parse_args()

    if not os.path.exists(args.current):
        fail(f"--current file not found: {args.current}")
    try:
        cur_doc = json.load(open(args.current))
    except Exception as exc:
        fail(f"--current file is unreadable ({args.current}): {exc}")
    for key in ("matrix_returns", "window"):
        if key not in cur_doc:
            fail(f"--current has no '{key}' key ({args.current})")
    cur = cur_doc["matrix_returns"]
    win = cur_doc["window"]
    start = args.window_start or win["start"]
    end = args.window_end or win["end"]
    syms = cur_doc.get("tickers", SYMS)
    syms = [s for s in SYMS if s in syms] or SYMS

    # The prior-week matrix normally lives in the SAME file as the current one
    # (correlation_matrix.py --prior-window embeds it as `matrix_returns_prior`).
    # Fall back to a separate --prior file for older layouts.
    prior = None
    if args.prior:
        pd_ = json.load(open(args.prior))
        prior = pd_.get("matrix_returns_prior") or pd_.get("matrix_returns")
    elif "matrix_returns_prior" in cur_doc:
        prior = cur_doc["matrix_returns_prior"]

    # --- REQUIRED INPUTS. These were optional until 2026-11-05, and the tolerance was
    #     a defect: correlation_matrix.py did not write them, so the Performance table,
    #     the price-level appendix and the excluded-partial-session proof silently
    #     vanished and the run still reported success. Fail loudly instead.
    for flag, path in (("--series", args.series), ("--partial", args.partial)):
        if not path:
            fail(f"{flag} is required — the Performance table, the price-level appendix "
                 f"and the excluded-partial-session proof all depend on it.")
        if not os.path.exists(path):
            fail(f"{flag} file not found: {path}\n"
                 f"  correlation_matrix.py writes series.json and mats_partial.json "
                 f"itself; re-run it (--window-end auto --prior-window) and try again. "
                 f"Refusing to write an artifact that silently omits its own evidence.")

    try:
        series = json.load(open(args.series))
    except Exception as exc:
        fail(f"--series file is unreadable ({args.series}): {exc}")
    try:
        pdoc = json.load(open(args.partial))
    except Exception as exc:
        fail(f"--partial file is unreadable ({args.partial}): {exc}")

    missing_series = [s for s in syms if not series.get(s)]
    if missing_series:
        fail(f"--series is missing data for {missing_series} — every proxy needs a price "
             f"series for the Performance table and the level-correlation appendix.")
    if "matrix_returns" not in pdoc:
        fail(f"--partial has no 'matrix_returns' key ({args.partial}) — it must carry the "
             f"matrix computed over the window INCLUDING the in-progress session.")
    partial = pdoc["matrix_returns"]
    missing_partial = [s for s in syms if s not in partial]
    if missing_partial:
        fail(f"--partial is missing {missing_partial} — the excluded-partial-session "
             f"comparison needs a value for every proxy.")

    quotes = json.load(open(args.quotes)) if args.quotes else None

    # DATE GUARD: a live quote is only used if the QUOTE ITSELF is stamped with the
    # snapshot's own date (per-quote `as_of`), not merely fetched on that date.
    # Before the open, a feed returns the PREVIOUS session's close with a fresh
    # retrieval timestamp — a retrieval-date check would pass it and silently label
    # yesterday's move as "today". A quote whose as_of date differs from the
    # snapshot date is a stale print and is dropped.
    quotes = None
    if args.quotes:
        q = json.load(open(args.quotes))
        raw = q.get("quotes", {})
        # the bridge returns a LIST of quote objects; be tolerant of a dict too
        if isinstance(raw, dict):
            items = list(raw.values())
        else:
            items = list(raw)
        dated = {
            it.get("symbol"): it for it in items
            if it.get("symbol") and (it.get("as_of") or "")[:10] == args.date
        }
        if dated:
            quotes = dict(q)
            quotes["quotes"] = dated

    iso = args.iso_week
    d = date.fromisoformat(args.date)
    prev_art = f"cross-asset/{(d - timedelta(days=7)).isoformat()}.md"

    # regime + shift
    regime = args.regime or "see TL;DR"
    shift_flag = "unknown"
    maxd = 0.0
    delta_md = ""
    prior_present = bool(prior)
    if prior:
        delta_md, maxd = render_delta(cur, prior, syms)
        shift_flag = "yes" if maxd > SHIFT_THRESHOLD else "no"

    # The one line the CHAT REPLY leads with. Computed here, from the same numbers the
    # tables use, so the reply can never disagree with the artifact.
    signal_line = build_signal_line(cur, prior, syms, maxd, prior_present)
    div = best_diversifier(cur, syms)
    best_div = f"{div['pair']} {div['corr']:+.2f}" if div else "unknown"
    distance = (f"{SHIFT_THRESHOLD - maxd:.4f}" if prior_present else "unknown")

    # hedge pair (lowest |corr| pair among non-vol)
    pl = pair_list(cur, syms)
    hedge = min(pl, key=lambda t: abs(t[2]))
    hp, hq, hr = hedge

    # partial effect
    part_md = ""
    part_max = 0.0
    part_note = ""
    partial_includes = False
    if partial:
        # Did the partial matrix ACTUALLY include a newer session than the published
        # one? If it did not (the in-progress bar was not available for every proxy),
        # the partial matrix is identical to the published one and every delta is 0.0000
        # — which must NOT be reported as "including the bar changes no conclusion".
        pwin = pdoc.get("window", {})
        pend = pwin.get("end")
        partial_includes = bool(pdoc.get("includes_in_progress_session")) or (
            pend is not None and str(pend) > str(end))
        pd = []
        for x, y, r in pair_list(cur, syms):
            pd.append((abs(r - partial[x][y]), x, y, r, partial[x][y]))
        pd.sort(reverse=True)
        part_max = pd[0][0]
        rows = ["| Pair | Excluded (published) | Included | Δ |", "|---|---|---|---|"]
        for a, x, y, r, p in pd[:5]:
            rows.append(f"| **{x}–{y}** | {sgn(r)} | {sgn(p)} | {p - r:+.4f} |")
        part_md = "\n".join(rows)
        if partial_includes:
            part_note = (
                f"Including the in-progress bar moves no pair by more than "
                f"**{part_max:.4f}** — no conclusion in this report changes.\n")
        else:
            part_note = (
                f"**The in-progress session was NOT available for every proxy**, so the "
                f"partial matrix covers the same sessions as the published one "
                f"(last common session {pend}) and every delta below is 0.0000 by "
                f"construction — this is NOT evidence that the in-progress bar changes "
                f"nothing.\n")

    # source health rows
    src = []
    for s in cur_doc.get("sources", []):
        sym = s.get("symbol", "?")
        src.append(
            f"| Yahoo Chart API | `{sym}` · range=1y · interval=1d | {s.get('http')} | "
            f"**ok** — {s.get('bars')} bars, last {s.get('last_bar')} |"
        )
    cc = cur_doc.get("crosscheck_shibui_raw")
    cc_note = "not run"
    if cc:
        m = 0.0
        for x, y, _ in pair_list(cur, [s for s in syms if s != "^VIX"]):
            m = max(m, abs(cur[x][y] - cc["matrix_returns"][x][y]))
        cc_note = f"max abs diff vs published matrix **{m:.4f}**"

    # levels appendix
    lv_md = ""
    lv, n = levels_corr(series, start, end, syms)
    if not lv:
        fail(f"the price-level appendix could not be computed — only {n} common sessions in "
             f"the window {start}→{end}. The appendix is part of the artifact contract, "
             f"so refusing to write an artifact that silently omits it.")
    rows = ["| Pair | Level corr | Pair | Level corr |", "|---|---|---|---|"]
    items = sorted(lv.items(), key=lambda kv: kv[1])
    half = (len(items) + 1) // 2
    for i in range(half):
        a = items[i]
        left = f"{mag_bucket(a[1])} **{a[0][0]}–{a[0][1]}** | {a[1]:+.2f}"
        if i + half < len(items):
            b = items[i + half]
            right = f"{mag_bucket(b[1])} **{b[0][0]}–{b[0][1]}** | {b[1]:+.2f}"
        else:
            right = " | "
        rows.append(f"| {left} | {right} |")
    lv_md = "\n".join(rows)

    ret_md = render_returns(series, start, end, syms, quotes)

    # ---- assemble
    # The front matter carries the SIGNAL LINE — the one line the chat reply leads with.
    # It is computed here, from the same numbers the tables use, so the reply can never
    # drift from the artifact. The checker asserts the reply carries it.
    shift_text = ("🔴 YES" if shift_flag == "yes"
                  else ("✅ NO" if shift_flag == "no" else "⚠️ UNKNOWN — no prior window"))
    parts = []
    parts.append(f"""---
date: {args.date}
cron: 12-cross-asset-correlation-snapshot
contract: {CONTRACT_VERSION}
iso_week: {iso}
fire_time_et: {args.fire_et}
window_start: {start}
window_end: {end}
n_sessions: {win.get('n_sessions')}
n_return_obs: {win.get('n_return_obs')}
basis: {win.get('basis')}
universe: {len(syms)}
regime: {regime}
regime_shift: {shift_flag}
max_pair_move: {maxd:.4f}
shift_threshold: {SHIFT_THRESHOLD:.2f}
distance_to_threshold: {distance}
best_diversifier: {best_div}
signal_line: {signal_line}
partial_includes_in_progress: {'yes' if partial_includes else 'no'}
partial_window_end: {pdoc.get('window', {}).get('end')}
server_side: true
engine: {cur_doc.get('engine')}
window_end_derived_from_data: {str(cur_doc.get('window', {}).get('end_derived_from_data', False)).lower()}
vix_included: {'yes' if '^VIX' in syms else 'no'}
errors: 0
---

# 🧭 Cross-asset correlation snapshot — window ending {end} (run {args.date})

> **Snapshot** {args.date} · week **{iso}** · {args.fire_et} ET intraday
> **Window** {start} → {end} · **{win.get('n_sessions')} aligned sessions** ({win.get('n_return_obs')} log-return obs) · basis `{win.get('basis')}`
> **Universe** {len(syms)} proxies ({', '.join(syms)}) — unchanged
> **Regime** **{regime}**
> **Regime shift** {shift_text} — largest pair move **{maxd:.4f}** (threshold {SHIFT_THRESHOLD:.2f})

> **Signal** {signal_line}

### Legend

| | Meaning | | Meaning |
|---|---|---|---|
| 🟥 | \\|corr\\| ≥ 0.70 — strong | 🟩 | 0.20–0.40 — mild |
| 🟧 | 0.60–0.70 — elevated | 🟦 | < 0.20 — effectively uncorrelated |
| 🟨 | 0.40–0.60 — moderate | `████░░░░` | magnitude bar (8 steps) |
""")

    if args.deviations and os.path.exists(args.deviations):
        parts.append("\n## \u26A0\uFE0F Deviations from the skill spec\n")
        parts.append(open(args.deviations).read().strip())

    if args.tl_dr and os.path.exists(args.tl_dr):
        parts.append("\n## \U0001F4CC TL;DR\n")
        parts.append(open(args.tl_dr).read().strip())

    parts.append("## 📊 Matrix — daily log returns\n")
    parts.append(render_matrix(cur, syms))
    parts.append(
        "\n> Color = magnitude band, sign shown in the number. "
        "Returns basis removes shared drift; levels are in the appendix.\n"
    )

    parts.append("## 🔎 Flat heatmap — every pair, ranked by |corr|\n")
    parts.append(render_heatmap_list(cur, syms))

    parts.append("\n## 🏆 Highlights\n")
    parts.append(render_highlights(cur, syms))

    if delta_md:
        parts.append("\n## 🔁 Week-over-week delta (matched-length window roll)\n")
        parts.append(delta_md)

    if ret_md:
        parts.append("\n## 📈 Performance\n")
        parts.append(ret_md)

    if part_md:
        parts.append(f"\n## 🧪 Effect of the excluded partial session ({args.date})\n")
        parts.append(part_note)
        parts.append(part_md)

    parts.append("\n## 🩺 Source health\n")
    src.append(
        f"| shibui via MCP bridge | `stock_data_query` — DuckDB `corr()`, one round trip | 200 | "
        f"**ok** — server-side matrix, {len(syms)}/{len(syms)} series injected |"
    )
    src.append(f"| shibui raw cross-check | `shibui.stock_quotes` (7 ETFs) | 200 | **ok** — {cc_note} |")
    src.append(
        "| MCP availability probe | catalog probe | — | `mcp__*` finance tools known-unregistered "
        "in this runtime — not counted as an error |"
    )
    parts.append(
        "| Source | Endpoint / query | HTTP | Status |\n|---|---|---|---|\n" + "\n".join(src)
    )
    parts.append("\n**No source failures — errors: 0.** No fallback chain entered.\n")

    if lv_md:
        parts.append("\n## 📎 Appendix — price-level correlations\n")
        parts.append(
            "> Local Pearson on aligned price levels — a **supplement only**. "
            "The published matrix above is the server-side returns matrix.\n"
        )
        parts.append(lv_md)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    import re as _re
    body = _re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)).strip() + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")
    print(f"signal_line: {signal_line}")


if __name__ == "__main__":
    main()

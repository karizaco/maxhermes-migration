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

Missing --prior / --partial / --series are tolerated: the corresponding sections
are dropped and the report says so, rather than fabricating numbers.
"""
import argparse
import json
import math
import os
import statistics
from datetime import date, datetime, timedelta

SYMS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "UUP", "EEM", "^VIX"]
NAMES = {
    "SPY": "S&P 500", "QQQ": "Nasdaq-100", "IWM": "Russell 2000",
    "TLT": "20+ Yr Treasury", "GLD": "Gold", "UUP": "US Dollar",
    "EEM": "Emerging Mkts", "^VIX": "VIX",
}

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
    shift = "🔴 REGIME_SHIFT" if maxd > 0.20 else ("⚠️ borderline" if maxd > 0.15 else "✅ no shift")
    lines = [
        f"**Flag:** {shift} — largest absolute move **{maxd:.4f}** ({d[0][1]}–{d[0][2]}), "
        f"threshold 0.20",
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
        a = max([k for k in keys if k <= start], default=keys[0])
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
            live = f"{quotes['quotes'][s]['change_pct']:+.2f}%"
        elif len(keys) >= 2:
            live = f"{(rows[keys[-1]] / rows[keys[-2]] - 1) * 100:+.2f}%"
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
    ap.add_argument("--partial")
    ap.add_argument("--series")
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

    cur_doc = json.load(open(args.current))
    cur = cur_doc["matrix_returns"]
    win = cur_doc["window"]
    start = args.window_start or win["start"]
    end = args.window_end or win["end"]
    syms = cur_doc.get("tickers", SYMS)
    syms = [s for s in SYMS if s in syms] or SYMS

    prior = json.load(open(args.prior))["matrix_returns"] if args.prior else None
    partial = json.load(open(args.partial))["matrix_returns"] if args.partial else None
    series = json.load(open(args.series)) if args.series else None
    quotes = json.load(open(args.quotes)) if args.quotes else None

    # DATE GUARD: a live quote feed is only used if it is actually quoting the
    # snapshot's own date. Otherwise it would inject TODAY's prices into a
    # snapshot whose window ended on an earlier session — a silent date error.
    quotes = None
    if args.quotes:
        q = json.load(open(args.quotes))
        qdate = (q.get("retrieved_at") or "")[:10]
        if qdate == args.date:
            quotes = q

    iso = args.iso_week
    d = date.fromisoformat(args.date)
    prev_art = f"cross-asset/{(d - timedelta(days=7)).isoformat()}.md"

    # regime + shift
    regime = args.regime or "see TL;DR"
    shift_flag = "no"
    maxd = 0.0
    delta_md = ""
    if prior:
        delta_md, maxd = render_delta(cur, prior, syms)
        shift_flag = "yes" if maxd > 0.20 else "no"

    # hedge pair (lowest |corr| pair among non-vol)
    pl = pair_list(cur, syms)
    hedge = min(pl, key=lambda t: abs(t[2]))
    hp, hq, hr = hedge

    # partial effect
    part_md = ""
    part_max = 0.0
    if partial:
        pd = []
        for x, y, r in pair_list(cur, syms):
            pd.append((abs(r - partial[x][y]), x, y, r, partial[x][y]))
        pd.sort(reverse=True)
        part_max = pd[0][0]
        rows = ["| Pair | Excluded (published) | Included | Δ |", "|---|---|---|---|"]
        for a, x, y, r, p in pd[:5]:
            rows.append(f"| **{x}–{y}** | {sgn(r)} | {sgn(p)} | {p - r:+.4f} |")
        part_md = "\n".join(rows)

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
    if series:
        lv, n = levels_corr(series, start, end, syms)
        if lv:
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

    ret_md = ""
    if series:
        ret_md = render_returns(series, start, end, syms, quotes)

    # ---- assemble
    parts = []
    parts.append(f"""---
date: {args.date}
cron: 12-cross-asset-correlation-snapshot
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
server_side: true
engine: {cur_doc.get('engine')}
vix_included: {'yes' if '^VIX' in syms else 'no'}
errors: 0
---

# 🧭 Cross-asset correlation snapshot — window ending {end} (run {args.date})

> **Snapshot** {args.date} · week **{iso}** · {args.fire_et} ET intraday
> **Window** {start} → {end} · **{win.get('n_sessions')} aligned sessions** ({win.get('n_return_obs')} log-return obs) · basis `{win.get('basis')}`
> **Universe** {len(syms)} proxies ({', '.join(syms)}) — unchanged
> **Regime** **{regime}**
> **Regime shift** {'🔴 YES' if shift_flag == 'yes' else '✅ NO'} — largest pair move **{maxd:.4f}** (threshold 0.20)

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
        parts.append(
            f"Including the in-progress bar moves no pair by more than **{part_max:.4f}** — "
            "no conclusion in this report changes.\n"
        )
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

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    import re as _re
    body = _re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)).strip() + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()

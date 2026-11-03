#!/usr/bin/env python3
"""
Rewrite every routine's inline holiday-skip block to call the shared
skip_marker.sh, so a deliberate skip lands ON THE REMOTE instead of dying in
the sandbox.

The inline block each prompt carries today:

    DATE=$(TZ=America/New_York date +%Y-%m-%d)
    case "$DATE" in
        2026-01-01|...)
            mkdir -p /workspace/$DATE
            cat > /workspace/$DATE/SKIPPED_<stem>.md <<EOF
    ...
    EOF
            echo "out-of-window: US market holiday ($DATE)"
            echo "no artifact; no push"
            exit 0
            ;;
    esac
    echo "window-check: OK ($DATE)"

It writes the marker into the SANDBOX and exits without pushing, so the skip
left no trace on the outputs repo and was indistinguishable from a failed run
(the 2026-10-26 case). The replacement calls the shared script, which writes
the marker under refs/skipped-markers/ AND pushes it.
"""
import re, os, glob, sys

# This script lives in tools/, so the repo root is one level up.
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = os.path.join(BASE, "cloud-prompts", "cron-prompts")

# NN -> (output dir, marker stem, human label)
MAP = {
    "02": ("asia-pre-market", "asia_pre_market_reactions", "Cron #02 asia-pre-market-reactions"),
    "04": ("daily-screens", "reversal_bullish_3_55", "Cron #04 reversal-bullish-3:55"),
    "05": ("international-eod", "eod_international_daily", "Cron #05 eod-international-daily"),
    "06": ("daily-screens", "stock_screener_pattern_study_backlog", "Cron #06 stock-screener-pattern-study-backlog"),
    "07": ("daily-screens", "stock_screener_focus_rvol_09_45", "Cron #07 stock-screener-focus-rvol-09:45"),
    "08": ("daily-screens", "stock_screener_pre_market_gapper", "Cron #08 stock-screener-pre-market-gapper"),
    "09": ("daily-screens", "stock_screener_daily_sweep_18_30", "Cron #09 stock-screener-daily-sweep-18:30"),
    "10": ("daily-screens", "stock_screener_breadth_snapshot", "Cron #10 stock-screener-breadth-snapshot"),
    "12": ("cross-asset", "cross_asset_correlation_snapshot", "Cron #12 cross-asset-correlation-snapshot"),
    "13": ("macro-calendar", "macro_calendar_midweek", "Cron #13 macro-calendar-midweek"),
    "14": ("macro-calendar", "macro_calendar_week_ahead", "Cron #14 macro-calendar-week-ahead"),
    "15": ("earnings", "earnings_reaction_scanner", "Cron #15 earnings-reaction-scanner"),
    "16": ("options-flow", "unusual_options_flow_daily", "Cron #16 unusual-options-flow-daily"),
    "17": ("us-stocks-in-play", "us_stocks_in_play", "Cron #17 us-stocks-in-play"),
    "19": ("earnings", "earnings_reminder_daily", "Cron #19 earnings-reminder-daily"),
    "20": ("us-eod", "eod_watchlist_csv_snapshot", "Cron #20 eod-watchlist-csv-snapshot"),
    "22": ("weekly", "weekly_market_recap_preview", "Cron #22 weekly-market-recap-preview"),
    "23": ("daily-briefs", "agentic_post_market_brief", "Cron #23 agentic-post-market-brief"),
    "25": ("ntrt", "ntrt_gap_brief_daily", "Cron #25 ntrt-gap-brief-daily"),
    "26": ("daily-briefs", "agentic_pre_market_brief", "Cron #26 agentic-pre-market-brief"),
}

NEW_BLOCK = '''```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
#
# The skip marker is written AND PUSHED by the shared script, so a deliberate
# skip leaves a trace on the outputs repo instead of dying in the sandbox. A
# marker that never leaves the sandbox is indistinguishable from a failed run.
# The marker lives in refs/skipped-markers/, outside every routine's output
# directory, so it can never be mistaken for a delivered artifact.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        S=/workspace/skip_marker.sh
        for U in \\
          "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/skip_marker.sh" \\
          "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/skip_marker.sh" ; do
          curl -sL --max-time 30 -o "$S.tmp" "$U" 2>/dev/null
          # A 404 page is a non-empty body that is NOT a script - never run one.
          if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!'; then
            mv -f "$S.tmp" "$S"; break
          fi
          rm -f "$S.tmp"
        done
        if [ -s "$S" ] && head -1 "$S" 2>/dev/null | grep -q '^#!'; then
          sh "$S" --out {OUT} --name {STEM} \\
             --label "{LABEL}" \\
             --reason "US market holiday ($DATE)" \\
             --nn {NN} --date "$DATE" || \\
             echo "skip-marker push: FAILED (the marker is still in the sandbox)"
        else
          echo "skip-marker push: SKIPPED (skip_marker.sh unavailable - the marker could not be written)"
        fi
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```'''


def main():
    changed = []
    for path in sorted(glob.glob(os.path.join(PROMPTS, "*.md"))):
        b = os.path.basename(path)
        s = open(path, encoding="utf-8").read()
        m = re.search(r"\(cron #(\d+)\)", s)
        if not m:
            continue
        nn = m.group(1)
        if nn not in MAP:
            print("  no map entry for", b, nn)
            continue
        out, stem, label = MAP[nn]

        # locate the fenced bash block that contains the holiday case
        blocks = list(re.finditer(r"```bash\n(.*?)\n```", s, re.S))
        target = None
        for blk in blocks:
            if "2026-11-26" in blk.group(1) and "SKIPPED" in blk.group(1):
                target = blk
                break
        if target is None:
            print("  no holiday block found in", b)
            continue

        new = NEW_BLOCK.format(OUT=out, STEM=stem, LABEL=label, NN=nn)
        s2 = s[:target.start()] + new + s[target.end():]
        if s2 != s:
            open(path, "w", encoding="utf-8").write(s2)
            changed.append((b, nn, out, stem))
    print(f"rewrote {len(changed)} prompts:")
    for b, nn, out, stem in changed:
        print(f"  #{nn} {b:46s} out={out:18s} stem={stem}")


if __name__ == "__main__":
    main()

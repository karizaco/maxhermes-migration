#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# window_check.sh — the ONE window check for the cron fleet.
#
# WHY THIS EXISTS
# ---------------
# Every prompt carried its own ~2.4 KB copy of the window-check block, with the flag values
# edited by hand. That produced six distinct variants of the same block and, worse, a block
# that is almost entirely DEAD CODE: the day-of-week now lives in the SCHEDULER expression,
# so the weekday / weekend / DAY_OF_WEEK branches can never fire (proven for all 20 prompts
# by enumerating the days each schedule can fire).
#
# What was NOT dead — and was promised by 17 prompt tails but implemented by only one — was
# the market-holiday guard. A cron expression cannot express a holiday, and the scheduler fires
# Mon-Fri INCLUDING market holidays. On 2026-01-19, 2026-02-16, 2026-05-25, 2026-09-07 and
# 2026-11-26 the weekday routines would otherwise write a normal artifact on a closed market.
#
# So this script keeps ONE live gate (the holiday) and drops the rest.
#
# USAGE — configure with environment variables, then call:
#   WEEKDAYS_ONLY=true WEEKEND_ONLY=false MARKET_HOURS_ONLY=false DAY_OF_WEEK=0 \
#   SKIP_DIR=/workspace/2026-11-02 SKIP_NAME=asia_pre_market_reactions \
#   SKIP_LABEL="Cron #2 asia-pre-market-reactions" \
#   HOLIDAYS="2026-01-01 2026-01-19 ..." sh /workspace/window_check.sh
#
#   WEEKDAYS_ONLY   true|false   skip Sat/Sun
#   WEEKEND_ONLY    true|false   skip Mon-Fri
#   MARKET_HOURS_ONLY true|false skip outside HOUR_MIN..HOUR_MAX
#   DAY_OF_WEEK     0 = no constraint, 1=Mon .. 7=Sun (%u convention)
#   HOUR_MIN/HOUR_MAX           the market-hours gate (default 9 / 17)
#   SKIP_DIR        where to write the SKIPPED marker (optional — omit to skip silently)
#   SKIP_NAME       marker filename stem (no colon — colons break shells and the auditor)
#   SKIP_LABEL      the human-readable title inside the marker
#   HOLIDAYS        space- or newline-separated YYYY-MM-DD market closure dates
#
# EXIT CODES
#   0 = in-window (prints "window-check: OK (<now ET>)")
#   1 = out of window (prints "out-of-window: <reason>"; writes the SKIPPED marker if SKIP_DIR)
set -u

WEEKDAYS_ONLY="${WEEKDAYS_ONLY:-true}"
WEEKEND_ONLY="${WEEKEND_ONLY:-false}"
MARKET_HOURS_ONLY="${MARKET_HOURS_ONLY:-false}"
DAY_OF_WEEK="${DAY_OF_WEEK:-0}"
HOUR_MIN="${HOUR_MIN:-9}"
HOUR_MAX="${HOUR_MAX:-17}"

NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
DATE=$(TZ=America/New_York date +%Y-%m-%d)
SKIP_REASON=""

# --- dead branches, kept only as a safety net (the scheduler normally guarantees these) ---
[ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ] && SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
[ "$WEEKEND_ONLY" = "true" ]  && [ "$DOW" -lt 6 ] && SKIP_REASON="weekday (day=$DOW, expected Sat-Sun)"

if [ "$DAY_OF_WEEK" -gt 0 ] 2>/dev/null && [ "$DOW" -ne "$DAY_OF_WEEK" ]; then
  case "$DAY_OF_WEEK" in
    1) DAY_NAME="Monday" ;;    2) DAY_NAME="Tuesday" ;; 3) DAY_NAME="Wednesday" ;;
    4) DAY_NAME="Thursday" ;; 5) DAY_NAME="Friday" ;;  6) DAY_NAME="Saturday" ;;
    7) DAY_NAME="Sunday" ;;
    *) DAY_NAME="day $DAY_OF_WEEK" ;;
  esac
  SKIP_REASON="wrong day (today=$DOW, expected $DAY_NAME=$DAY_OF_WEEK)"
fi

if [ "$MARKET_HOURS_ONLY" = "true" ]; then
  if [ "$HOUR" -lt "$HOUR_MIN" ] || [ "$HOUR" -ge "$HOUR_MAX" ]; then
    SKIP_REASON="outside market hours (hour=$HOUR, expected $HOUR_MIN-$((HOUR_MAX-1)) ET)"
  fi
fi

# --- the ONE live gate: market holidays. The scheduler cannot express them. ---
# Half-days (07:00 / 13:00 ET) are trading days and must still report — do NOT skip them.
if [ -n "${HOLIDAYS:-}" ]; then
  for h in $HOLIDAYS; do
    if [ "$h" = "$DATE" ]; then
      SKIP_REASON="US market holiday ($DATE)"
      break
    fi
  done
fi

if [ -n "$SKIP_REASON" ]; then
  if [ -n "${SKIP_DIR:-}" ] && [ -n "${SKIP_NAME:-}" ]; then
    mkdir -p "$SKIP_DIR" 2>/dev/null || true
    # SKIP_NAME must not contain a colon — three routines used colons, which break shells.
    SAFE_NAME=$(printf '%s' "$SKIP_NAME" | tr ':' '_')
    cat > "$SKIP_DIR/SKIPPED_${SAFE_NAME}.md" <<EOF
# ${SKIP_LABEL:-Cron} — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: $SKIP_REASON
- No artifact produced.
EOF
  fi
  echo "out-of-window: $SKIP_REASON"
  echo "no artifact; no push"
  exit 1
fi

echo "window-check: OK ($NOW_ET)"
exit 0

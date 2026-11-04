#!/bin/sh
# WINDOW_CHECK_V2 - the ONE window check for the cron fleet.
#
# WHY IT EXISTS
# ---------------
# 20 prompts each carried their own copy of the window-check block: a holiday `case`
# statement with the same ten dates, re-typed by hand, plus a copy-pasted
# skip_marker.sh fetch. The copies had already drifted (quoting, `case` vs `case "..."`,
# marker paths) and the fleet's own audit (docs/remediation/CRON-PROMPT-AUDIT.md, item D3)
# flagged the duplication. One file, fetched at RUN TIME, ends the drift: this is the
# only copy, and a fix to it lands on the next fire of every routine with no prompt
# redeploy.
#
# WHY IT IS EVALUATED AGAINST THE FIRE, NOT THE WALL CLOCK
# --------------------------------------------------------
# The platform resumes a crashed cron conversation IN PLACE, hours or days later, with
# the original prompt. So "now" is the RESUME time, not the FIRE time, and a gate
# driven by the wall clock misfires in both directions:
#
#   * a fire scheduled on a market HOLIDAY, replayed on a trading day -> the wall-clock
#     gate sees a trading day and PUBLISHES a brief for a closed market;
#   * a fire scheduled on a trading day, replayed on a weekend or holiday -> the
#     wall-clock gate SKIPS a real brief that is still owed.
#
# So every gate here - the market-holiday list AND the optional market-hours window -
# is evaluated against the fire's own scheduled clock, passed in as --scheduled-at-ms
# (epoch ms of the run's scheduled_at_ms). The agent resolves that value ONCE per run
# and reuses it for the artifact path, so the gate and the artifact can never disagree
# about which day they belong to.
#
# USAGE
#   sh window_check.sh --scheduled-at-ms <epoch_ms> \
#       --out <output-dir> --name <marker-stem> --label "<human title>" --nn <NN> \
#       [--market-hours HHMM-HHMM] [--holidays "YYYY-MM-DD ..."] [--holidays-file <path>]
#       [--now-at-ms <epoch_ms>]
#
#   --scheduled-at-ms  the fire's scheduled instant, epoch ms. This is the whole point
#                      of the script: without it the gates fall back to the wall clock
#                      and a replay is judged by the wrong day. If it is absent the
#                      script says so loudly and uses the wall clock as a last resort.
#   --out              the routine's output directory, for the skip marker.
#   --name             marker filename stem (no colon).
#   --label            human-readable title inside the marker.
#   --nn               routine number, recorded in the marker's commit subject.
#   --market-hours     optional HHMM-HHMM window evaluated against the FIRE's ET clock
#                      (e.g. 0930-1100). Omit for no hour gate.
#   --holidays         optional override of the market-holiday list.
#   --holidays-file    a file of closure dates, one per line (# comments ignored). The
#                      canonical file is cloud-prompts/_shared/nyse-holidays.txt.
#   --now-at-ms        testing only: pretend "now" is this epoch ms.
#
# EXIT CODES
#   0 = in window: publish the artifact
#   1 = out of window: do not publish; the skip marker was written and pushed
#   3 = bad usage
#
# The script prints the lines the prompt's reply format expects, and writes the skip
# marker through skip_marker.sh so a deliberate skip leaves a trace on the outputs repo
# instead of dying in the sandbox.
set -u

OUT=""; NAME=""; LABEL=""; NN=""; SCHED_MS=""; MKT_HRS=""; NOW_MS=""; HOLIDAY_FILE=""
HOLIDAYS_DEFAULT="2025-01-01 2025-01-20 2025-02-17 2025-05-26 2025-06-19 2025-07-04 2025-09-01 2025-11-27 2025-12-25 2026-01-01 2026-01-19 2026-02-16 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25 2027-01-01 2027-01-18 2027-02-15 2027-05-31 2027-06-18 2027-07-05 2027-09-06 2027-11-25 2027-12-24 2028-01-17 2028-02-21 2028-05-29 2028-06-19 2028-07-04 2028-09-04 2028-11-23 2028-12-25"
# The NYSE closures for 2025-2028 (2025 is historical; it is here so the three
# copies of this list match exactly and the parity lint stays meaningful). Half-days (07:00 / 13:00 ET) are TRADING days and must
# still report - they are deliberately absent.
#
# TWO DEFECTS THIS LIST USED TO CARRY, both fixed 2026-11-04:
#   * GOOD FRIDAY (2026-04-03) was listed. The NYSE is OPEN on Good Friday - it closes
#     most European and Asian exchanges, which is where the bad copy came from - so the
#     fleet skipped a live session.
#   * The list stopped at 2026, so on 2027-01-01 (a Friday) every weekday routine would
#     have fired and published for a closed market.
#
# Keep this in step with the auditor's copy in cron-prompts/90-delivery-auditor.md and with
# cloud-prompts/_shared/nyse-holidays.txt; window_check_test.sh asserts the two prompt
# lists agree, and tools/schedule-drift.py's lint asserts all three do.
HOLIDAYS="${HOLIDAYS:-$HOLIDAYS_DEFAULT}"
# The canonical calendar is cloud-prompts/_shared/nyse-holidays.txt: 2025-2028, Good Friday
# excluded, half-days recorded separately as trading days. It is fetched here so EVERY routine
# gets the full list without any prompt change - the inline default above is only the fallback
# for an offline run, and it is deliberately kept identical to the auditor's copy so the parity
# check in window_check_test.sh keeps holding.
if [ -z "${HOLIDAYS:-}" ] && [ -z "${HOLIDAY_FILE:-}" ]; then
  _cal=/workspace/nyse-holidays.txt
  if [ ! -s "$_cal" ]; then
    curl -sL --max-time 20 -o "$_cal" \
      "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/nyse-holidays.txt" 2>/dev/null
  fi
  if [ -s "$_cal" ] && grep -qE '^20[0-9]{2}-[0-9]{2}-[0-9]{2}' "$_cal" 2>/dev/null; then
    HOLIDAY_FILE="$_cal"
  fi
fi
# --holidays-file reads the canonical calendar (cloud-prompts/_shared/nyse-holidays.txt): one
# file to extend each year, instead of a date list hand-typed into several places. Comment
# lines and blanks are ignored. An explicit --holidays still wins.
if [ -n "$HOLIDAY_FILE" ] && [ -f "$HOLIDAY_FILE" ]; then
  HOLIDAYS=$(grep -vE '^[[:space:]]*(#|$)' "$HOLIDAY_FILE" | tr '\n' ' ')
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --out)            OUT="${2:-}";   shift 2 ;;
    --name)           NAME="${2:-}";  shift 2 ;;
    --label)          LABEL="${2:-}"; shift 2 ;;
    --nn)             NN="${2:-}";    shift 2 ;;
    --scheduled-at-ms) SCHED_MS="${2:-}"; shift 2 ;;
    --market-hours)   MKT_HRS="${2:-}"; shift 2 ;;
    --holidays)       HOLIDAYS="${2:-}"; shift 2 ;;
    --holidays-file)  HOLIDAY_FILE="${2:-}"; shift 2 ;;
    --now-at-ms)      NOW_MS="${2:-}"; shift 2 ;;
    --help|-h)        sed -n '2,60p' "$0"; exit 0 ;;
    *) echo "window_check.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$OUT" ]; then
  echo "window_check.sh: --out is required" >&2; exit 3
fi

# --- the clock ---------------------------------------------------------------
# Every timestamp is derived with TZ=America/New_York so the artifact, the gate and
# the marker all agree, in DST or not. Never hardcode a -4/-5 offset.
et_of_ms() {
  # $1 = epoch ms. Prints "YYYY-MM-DD HHMM" in US/Eastern.
  TZ=America/New_York date -d "@$(( ${1:-0} / 1000 ))" +"%Y-%m-%d %H%M"
}

NOW_MS_EFF="${NOW_MS:-}"
if [ -z "$NOW_MS_EFF" ]; then
  NOW_MS_EFF=$(( $(date +%s) * 1000 ))
fi
NOW_ET=$(et_of_ms "$NOW_MS_EFF")
NOW_DATE="${NOW_ET%% *}"
NOW_HM="${NOW_ET##* }"

REPLAY="no"
if [ -n "$SCHED_MS" ]; then
  FIRE_ET=$(et_of_ms "$SCHED_MS")
  FIRE_DATE="${FIRE_ET%% *}"
  FIRE_HM="${FIRE_ET##* }"
  if [ "$FIRE_DATE" != "$NOW_DATE" ]; then
    REPLAY="yes (fire $FIRE_DATE, now $NOW_DATE)"
  fi
else
  # Degraded: no scheduled instant was supplied, so we cannot tell a replay from an
  # on-time fire. Say so loudly - a silent fallback is how a replay gets judged by
  # the wrong day.
  echo "window-check: WARNING - no --scheduled-at-ms supplied; judging by the wall clock ($NOW_DATE)." >&2
  echo "window-check: WARNING - if this is a replay, the gates below use the WRONG day." >&2
  FIRE_DATE="$NOW_DATE"
  FIRE_HM="$NOW_HM"
fi

# --- write the skip marker ---------------------------------------------------
# Delegated to skip_marker.sh so the marker is PUSHED: a deliberate skip must leave
# a trace on the outputs repo, otherwise it is indistinguishable from a failed run.
write_marker() {
  _reason="$1"
  _script="${WINDOW_CHECK_SKIP_MARKER:-}"
  if [ -z "$_script" ]; then
    _script=/workspace/skip_marker.sh
    for _u in \
      "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/skip_marker.sh" \
      "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/skip_marker.sh" ; do
      curl -sL --max-time 30 -o "$_script.tmp" "$_u" 2>/dev/null
      # A 404 page is a non-empty body that is NOT a script - never run one.
      if head -1 "$_script.tmp" 2>/dev/null | grep -q '^#!'; then
        mv -f "$_script.tmp" "$_script"; break
      fi
      rm -f "$_script.tmp"
    done
  fi
  if [ ! -s "$_script" ] || ! head -1 "$_script" 2>/dev/null | grep -q '^#!'; then
    echo "skip-marker push: SKIPPED (skip_marker.sh unavailable - the marker could not be written)"
    return 1
  fi
  sh "$_script" --out "$OUT" --name "$NAME" --label "$LABEL" \
     --reason "$_reason" --nn "$NN" --date "$FIRE_DATE" || {
    echo "skip-marker push: FAILED (the marker is still in the sandbox)"
    return 1
  }
  return 0
}

# --- gate 1: the market holiday (the ONE gate a cron expression cannot express) --
for _h in $HOLIDAYS; do
  if [ "$_h" = "$FIRE_DATE" ]; then
    REASON="US market holiday ($FIRE_DATE)"
    echo "out-of-window: $REASON"
    if write_marker "$REASON"; then
      echo "push: marker pushed (refs/skipped-markers/${FIRE_DATE}_SKIPPED_${NAME}.md)"
    else
      echo "push: marker push FAILED (the marker is still in the sandbox)"
    fi
    echo "no artifact; no push"
    exit 1
  fi
done

# --- gate 2: the fire's own clock window (optional, per-routine) --------------
# Evaluated against the FIRE's ET clock, not the wall clock: this gate exists to
# catch a routine that is firing at the wrong hour (a timezone mistake), and it must
# not fire merely because a REPLAY executed outside the window.
if [ -n "$MKT_HRS" ]; then
  _lo="${MKT_HRS%%-*}"
  _hi="${MKT_HRS##*-}"
  # Strip leading zeros before arithmetic: 0930 is not a valid octal literal.
  _hm=$(printf '%s' "$FIRE_HM" | sed 's/^0*//'); [ -n "$_hm" ] || _hm=0
  _lo_n=$(printf '%s' "$_lo" | sed 's/^0*//'); [ -n "$_lo_n" ] || _lo_n=0
  _hi_n=$(printf '%s' "$_hi" | sed 's/^0*//'); [ -n "$_hi_n" ] || _hi_n=0
  if [ "$_hm" -lt "$_lo_n" ] || [ "$_hm" -gt "$_hi_n" ]; then
    REASON="off-clock fire (ET $FIRE_HM, expected $(printf '%s-%s' "$_lo" "$_hi"))"
    echo "out-of-window: $REASON"
    if write_marker "$REASON"; then
      echo "push: marker pushed (refs/skipped-markers/${FIRE_DATE}_SKIPPED_${NAME}.md)"
    else
      echo "push: marker push FAILED (the marker is still in the sandbox)"
    fi
    echo "no artifact; no push"
    exit 1
  fi
fi

echo "window-check: OK ($FIRE_DATE)"
echo "fire-date: $FIRE_DATE"
echo "replay: $REPLAY"
exit 0

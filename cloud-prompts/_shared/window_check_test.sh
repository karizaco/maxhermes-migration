#!/bin/sh
# window_check_test.sh - OFFLINE tests for window_check.sh.
#
# WHY THIS EXISTS
# ---------------
# A docstring is not a test. This script proves the four behaviours the fleet depends on:
#
#   1. an on-time fire on a trading day passes;
#   2. a fire whose SCHEDULED date is a market holiday is skipped, and the marker is
#      dated with the FIRE date (not the wall clock);
#   3. a REPLAY is judged by its own scheduled date, not by the day it happens to
#      execute on - this is the case that silently dropped the Oct-30 brief on 2026-11-01
#      and is the whole reason --scheduled-at-ms exists;
#   4. the market-hours gate is evaluated against the FIRE's clock, so a replay outside
#      the window still publishes.
#
# It is OFFLINE and dependency-free: no network, no PyPI, no cron scheduler. The
# marker writer is stubbed via WINDOW_CHECK_SKIP_MARKER, so nothing is pushed.
#
# USAGE:  sh window_check_test.sh
# EXIT:   0 = all tests passed, 1 = a test failed.
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WC="$HERE/window_check.sh"
TMP=$(mktemp -d 2>/dev/null || echo /tmp/wc_test.$$)
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }

# --- stub marker writer: records its arguments, never pushes -------------------
cat > "$TMP/skip_marker_stub.sh" <<'STUB'
#!/bin/sh
# Records the marker arguments so a test can assert on the FIRE date.
out=""; name=""; reason=""; nn=""; date=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:-}"; shift 2 ;;
    --name) name="${2:-}"; shift 2 ;;
    --label) label="${2:-}"; shift 2 ;;
    --reason) reason="${2:-}"; shift 2 ;;
    --nn) nn="${2:-}"; shift 2 ;;
    --date) date="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s|%s|%s|%s\n' "$date" "$reason" "$nn" "$name" > "$MARKER_OUT"
echo "skip-marker written: refs/skipped-markers/${date}_SKIPPED_${name}.md"
exit 0
STUB
chmod +x "$TMP/skip_marker_stub.sh"

export WINDOW_CHECK_SKIP_MARKER="$TMP/skip_marker_stub.sh"

# --- fixed instants -----------------------------------------------------------
# 2026-11-02 09:00 ET  = a Monday, a trading day.
MS_FIRE_MON=$(TZ=America/New_York date -d "2026-11-02 09:00:00" +%s)000
# 2026-11-26 09:00 ET  = Thanksgiving, a market holiday (Thursday).
MS_FIRE_HOL=$(TZ=America/New_York date -d "2026-11-26 09:00:00" +%s)000
# 2026-11-03 09:00 ET  = the day after the Monday fire (a Tuesday).
MS_NOW_TUE=$(TZ=America/New_York date -d "2026-11-03 09:00:00" +%s)000
# 2026-10-30 09:00 ET  = a Friday fire that the platform replayed on a Sunday.
MS_FIRE_FRI=$(TZ=America/New_York date -d "2026-10-30 09:00:00" +%s)000
MS_NOW_SUN=$(TZ=America/New_York date -d "2026-11-01 12:00:00" +%s)000
# 2026-11-04 09:00 ET  = a Wednesday.
MS_NOW_WED=$(TZ=America/New_York date -d "2026-11-04 09:00:00" +%s)000
# 2026-11-02 09:45 ET  = the hour cron #07 actually fires at (schedule `45 9 * * 1-5`).
MS_FIRE_0945=$(TZ=America/New_York date -d "2026-11-02 09:45:00" +%s)000
# 2026-11-04 22:45 ET  = a fire genuinely scheduled off-hours.
MS_FIRE_OFF=$(TZ=America/New_York date -d "2026-11-04 22:45:00" +%s)000

run() { # run <label> <expected_rc> <expect_substring_or_-> <args...>
  _label="$1"; _exp_rc="$2"; _exp="$3"; shift 3
  export MARKER_OUT="$TMP/marker.out"
  rm -f "$MARKER_OUT"
  OUT=$(sh "$WC" "$@" 2>&1); RC=$?
  if [ "$RC" -ne "$_exp_rc" ]; then
    bad "$_label" "expected rc=$_exp_rc got rc=$RC; output: $(printf '%s' "$OUT" | tr '\n' '/')"
    return
  fi
  if [ "$_exp" != "-" ] && ! printf '%s' "$OUT" | grep -q -- "$_exp"; then
    bad "$_label" "output lacks '$_exp': $(printf '%s' "$OUT" | tr '\n' '/')"
    return
  fi
  ok "$_label"
}

echo "window_check.sh offline tests"
echo

echo "[gate 1] market holiday"
run "on-time trading day passes" 0 "window-check: OK" \
  --scheduled-at-ms "$MS_FIRE_MON" --now-at-ms "$MS_NOW_TUE" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

run "holiday fire is skipped" 1 "out-of-window: US market holiday" \
  --scheduled-at-ms "$MS_FIRE_HOL" --now-at-ms "$MS_FIRE_HOL" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

if [ -f "$TMP/marker.out" ]; then
  MDATE=$(cut -d'|' -f1 "$TMP/marker.out")
  MREASON=$(cut -d'|' -f2 "$TMP/marker.out")
  MNN=$(cut -d'|' -f3 "$TMP/marker.out")
  [ "$MDATE" = "2026-11-26" ] && ok "marker is dated with the FIRE date (2026-11-26)" \
    || bad "marker dated with the fire date" "got '$MDATE'"
  printf '%s' "$MREASON" | grep -q "2026-11-26" && ok "marker reason carries the fire date" \
    || bad "marker reason carries the fire date" "got '$MREASON'"
  [ "$MNN" = "25" ] && ok "marker carries the routine number (25)" \
    || bad "marker carries the routine number" "got '$MNN'"
else
  bad "holiday skip wrote a marker" "no marker file was written"
fi

echo
echo "[gate 2] replay is judged by its own scheduled date"
# A Monday fire replayed on a Tuesday: the scheduled date is a trading day, so it
# must publish even though the wall clock moved.
run "Monday fire replayed on a Tuesday publishes" 0 "fire-date: 2026-11-02" \
  --scheduled-at-ms "$MS_FIRE_MON" --now-at-ms "$MS_NOW_TUE" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

# THE regression this script exists for: a FRIDAY fire replayed on a SUNDAY. The
# wall clock says weekend -> would skip a real brief. The scheduled date says Friday
# -> must publish.
run "Friday fire replayed on a Sunday publishes" 0 "fire-date: 2026-10-30" \
  --scheduled-at-ms "$MS_FIRE_FRI" --now-at-ms "$MS_NOW_SUN" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

# The mirror image: a HOLIDAY fire replayed on a trading day must still be skipped.
run "holiday fire replayed on a trading day is still skipped" 1 "out-of-window: US market holiday" \
  --scheduled-at-ms "$MS_FIRE_HOL" --now-at-ms "$MS_NOW_WED" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

run "replay is reported" 0 "replay: yes" \
  --scheduled-at-ms "$MS_FIRE_MON" --now-at-ms "$MS_NOW_TUE" \
  --out ntrt --name ntrt_gap_brief_daily --label "Cron #25 ntrt-gap-brief-daily" --nn 25

echo
echo "[gate 3] market hours against the FIRE's clock"
run "on-time fire inside the window passes" 0 "window-check: OK" \
  --scheduled-at-ms "$MS_FIRE_0945" --now-at-ms "$MS_NOW_TUE" --market-hours 0930-1100 \
  --out daily-screens --name stock_screener_focus_rvol_09_45 \
  --label "Cron #07 stock-screener-focus-rvol-09:45" --nn 07

# A replay that executes OUTSIDE the window must still publish: the fire was in
# window, and this is the fire's data.
run "replay outside the window still publishes" 0 "window-check: OK" \
  --scheduled-at-ms "$MS_FIRE_0945" --now-at-ms "$MS_NOW_WED" --market-hours 0930-1100 \
  --out daily-screens --name stock_screener_focus_rvol_09_45 \
  --label "Cron #07 stock-screener-focus-rvol-09:45" --nn 07

# A fire genuinely scheduled off-hours is still declined.
run "fire scheduled off-hours is declined" 1 "out-of-window: off-clock fire" \
  --scheduled-at-ms "$MS_FIRE_OFF" --now-at-ms "$MS_FIRE_OFF" --market-hours 0930-1100 \
  --out daily-screens --name stock_screener_focus_rvol_09_45 \
  --label "Cron #07 stock-screener-focus-rvol-09:45" --nn 07

echo
echo "[gate 4] degraded mode and argument handling"
run "missing --scheduled-at-ms warns and still runs" 0 "window-check: OK" \
  --now-at-ms "$MS_NOW_TUE" --out ntrt --name ntrt_gap_brief_daily \
  --label "Cron #25 ntrt-gap-brief-daily" --nn 25

if sh "$WC" --out ntrt --name x --label y --nn 25 --now-at-ms "$MS_NOW_TUE" 2>&1 | grep -q "WARNING - no --scheduled-at-ms"; then
  ok "degraded mode warns on stderr"
else
  bad "degraded mode warns on stderr"
fi

sh "$WC" --name x --label y --nn 25 >/dev/null 2>&1
[ $? -eq 3 ] && ok "missing --out is a usage error (rc=3)" || bad "missing --out is a usage error"

sh "$WC" --out ntrt --name x --label y --nn 25 --bogus-flag >/dev/null 2>&1
[ $? -eq 3 ] && ok "unknown argument is a usage error (rc=3)" || bad "unknown argument is a usage error"

echo
echo "[parity] the holiday list matches the auditor's copy"
AUDITOR="$HERE/../cron-prompts/90-delivery-auditor.md"
if [ -f "$AUDITOR" ]; then
  # The auditor's list is the same ten dates in a ``` block.
  # The auditor's list is the SECOND fenced block after the sentence that introduces it
  # (the first fence is the opening ```). Take the block whose lines are all dates.
  AUD=$(awk '/closures are in the/{f=1; next} f&&/^```/{c++; next} f&&c==1{print} f&&c==2{exit}' \
        "$AUDITOR" | grep -oE '20[0-9]{2}-[0-9]{2}-[0-9]{2}' | sort -u | tr '\n' ' ')
  # The script's list lives in window_check.sh, not in this test - read it from there.
  SCRIPT_LIST=$(grep '^HOLIDAYS_DEFAULT=' "$WC" | sed 's/^HOLIDAYS_DEFAULT="//; s/"$//' \
                | tr ' ' '\n' | grep -E '^20' | sort -u | tr '\n' ' ')
  if [ "$(printf '%s' "$AUD" | tr -s ' ')" = "$(printf '%s' "$SCRIPT_LIST" | tr -s ' ')" ]; then
    ok "window_check.sh and the auditor list the same 10 holidays"
  else
    bad "window_check.sh and the auditor list the same 10 holidays" "script: $SCRIPT_LIST | auditor: $AUD"
  fi
else
  echo "  skip (auditor prompt not found next to this script)"
fi

echo
printf '%s\n' "----------------------------------------"
printf 'passed: %s   failed: %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0

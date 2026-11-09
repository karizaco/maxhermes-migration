#!/bin/sh
# quota_check.sh — the ADVISORY Token Plan quota probe for the cloud cron fleet.
#
# WHY
# ---
# The MiniMax Token Plan 5-hour window (error 2056) can block a whole morning: on
# 2026-11-05 every fire between 08:30 and 09:50 ET was rejected at its first model
# call and could only be resumed once the window freed. This answers the question a
# RUNNING routine actually has at 08:30 — "how much of the window is left, and when
# does it free?" — and, through the routine's reply, tells the operator the same.
#
# IT CANNOT PREVENT THE STALL
# -----------------------------
# A routine cannot probe its way out of a block: the model call that runs this script
# is the very call that gets rejected. So the probe is ADVISORY. It tells a running
# routine to TRIM its work (fetch the skill once, pull the screen once, skip the
# optional sections) and it tells the operator that the window is nearly gone.
#
# FAIL-OPEN
# ----------
# With no key it says so and exits 0. A missing key is NOT an error, must never be
# counted in `errors:`, and must never stop a routine. The same is true of a probe
# failure: report it, proceed.
#
# USAGE
#     sh quota_check.sh
#
# ENV
#     MINIMAX_API_KEY   the Token Plan / M Plan API secret. OPTIONAL.
#                       Documented endpoint:
#                       curl --location 'https://www.minimax.io/v1/token_plan/remains' \
#                            --header 'Authorization: Bearer <key>'

set -u
URL="https://www.minimax.io/v1/token_plan/remains"

if [ -z "${MINIMAX_API_KEY:-}" ]; then
  echo "quota: probe unavailable (MINIMAX_API_KEY is not set) - proceeding; the 5-hour window cannot be checked"
  exit 0
fi

TMP="${TMPDIR:-/tmp}/quota_check.$$"
CODE=$(curl -sL --max-time 15 -o "$TMP" -w '%{http_code}' \
  "$URL" -H "Authorization: Bearer ${MINIMAX_API_KEY}" 2>/dev/null) || CODE="000"

if [ ! -s "$TMP" ]; then
  echo "quota: probe failed (empty body, http ${CODE}) - proceeding"
  rm -f "$TMP"; exit 0
fi

# The endpoint's response shape is not documented. Parse tolerantly: look for the
# fields we know how to name, and if none is found print the body so a human can
# read it rather than inventing a number.
python3 - "$TMP" "$CODE" <<'PYEOF' 2>/dev/null || echo "quota: probe failed (unreadable body) - proceeding"
import json, sys, datetime
path, code = sys.argv[1], sys.argv[2]
raw = open(path, encoding="utf-8", errors="replace").read()
try:
    d = json.loads(raw)
except Exception:
    print("quota: probe returned an unparseable body (http %s) - proceeding" % code)
    print("quota-body: " + " ".join(raw.split())[:400])
    raise SystemExit(0)

base = d.get("base_resp") or {}
if base.get("status_code") not in (None, 0) and base.get("status_msg"):
    print("quota: probe failed (http %s: %s) - proceeding" % (code, base.get("status_msg")))
    raise SystemExit(0)


def pick(obj, *names):
    """First non-empty value for any of `names`, searched one level deep."""
    if not isinstance(obj, dict):
        return None
    for n in names:
        for k, v in obj.items():
            if k.lower() == n.lower() and v not in (None, "", [], {}):
                return v
    for v in obj.values():
        if isinstance(v, dict):
            got = pick(v, *names)
            if got is not None:
                return got
    return None


def as_pct(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if 0 < f <= 1.0:
        return round(f * 100)
    return round(f)


def as_et(v):
    if v in (None, ""):
        return None
    try:
        ts = float(v)
    except (TypeError, ValueError):
        return str(v)
    if ts > 1e11:
        ts /= 1000.0
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        return None


five = pick(d, "remaining_5h", "remaining5h", "five_hour_remaining", "reset_5h", "reset5h")
weekly = pick(d, "remaining_weekly", "remainingweekly", "weekly_remaining", "reset_weekly", "resetweekly")
p5 = as_pct(pick(d, "remaining_5h_ratio", "five_hour_ratio", "ratio_5h", "usage_5h"))
pw = as_pct(pick(d, "remaining_weekly_ratio", "weekly_ratio", "ratio_weekly", "usage_weekly"))
r5 = as_et(pick(d, "reset_5h_at", "reset_time_5h", "five_hour_reset_at", "reset_5h_time"))
rw = as_et(pick(d, "reset_weekly_at", "reset_time_weekly", "weekly_reset_at", "reset_weekly_time"))

parts = []
if p5 is not None:
    parts.append("5h window %d%% remaining" % p5)
elif five is not None:
    parts.append("5h window %s" % five)
if r5:
    parts.append("5h resets %s" % r5)
if pw is not None:
    parts.append("weekly %d%% remaining" % pw)
elif weekly is not None:
    parts.append("weekly %s" % weekly)
if rw:
    parts.append("weekly resets %s" % rw)

if parts:
    print("quota: " + ", ".join(parts))
else:
    print("quota: probe OK but no recognised field (http %s) - proceeding" % code)
    print("quota-body: " + " ".join(json.dumps(d).split())[:400])
PYEOF

rm -f "$TMP"
exit 0

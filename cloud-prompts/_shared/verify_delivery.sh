#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# verify_delivery.sh — confirm the artifact is ON the remote.
#
# WHY THIS EXISTS
# ---------------
# A `git push` that exits 0 is not proof of delivery. The fleet's old push block piped the
# push through `head -3`, so the exit status was head's (always 0) and a REJECTED push
# reported success. The consequence on 2026-10-28 was a lost options-flow artifact.
#
# This script answers the only question that matters: is the path present on the remote branch?
#
# USAGE
#   verify_delivery.sh --path <repo-relative-path> [--branch <branch>] [--nn <NN>] [--repo <owner/name>]
#
#   --nn <NN>   ALSO check that the commit that last touched the path carries the routine
#               number in its subject. Cron #90's near-miss triage attributes a push to a
#               routine by grepping commit subjects for "cron (#)?NN ", so a delivered
#               artifact whose subject lacks the number is reported as MISSING even though
#               the file is on the branch. This check makes that visible at push time
#               instead of at audit time. Omit --nn for the original presence-only behaviour.
#
#   --repo      owner/name of the artifact repo (default karizaco/minimax-cloud-outputs).
#               Only used by the --nn check.
#
# EXIT CODES
#   0 = present on origin/<branch> (and, with --nn, the subject carries the routine number)
#   1 = ABSENT — the artifact did not land. Report this plainly; do not claim success.
#   3 = bad arguments
#   4 = present, but the commit subject does NOT carry the routine number — the artifact
#       landed but is not attributable to a routine. Fix forward with a correctly-subjected
#       commit; do NOT force-push (master mirrors main as a fast-forward, so rewriting a
#       main commit permanently breaks the mirror's ancestry gate).
set -u

PATH_=""; BRANCH="main"; NN=""; REPO="karizaco/minimax-cloud-outputs"
while [ $# -gt 0 ]; do
  case "$1" in
    --path)   PATH_="${2:-}";   shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --nn)     NN="${2:-}";     shift 2 ;;
    --repo)   REPO="${2:-}";   shift 2 ;;
    *) echo "verify_delivery.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$PATH_" ]; then
  echo "verify_delivery.sh: --path is required" >&2
  exit 3
fi

cd "${REPO_DIR:-/workspace}" 2>/dev/null || { echo "DELIVERY: FAILED (no repo dir)"; exit 1; }
git fetch -q origin "$BRANCH" 2>/dev/null || true

if ! git cat-file -e "origin/$BRANCH:$PATH_" 2>/dev/null; then
  echo "DELIVERY: FAILED (origin/$BRANCH:$PATH_ NOT found)"
  exit 1
fi
echo "DELIVERY: ok (origin/$BRANCH:$PATH_ present)"

# ---------------------------------------------------------------------------------------------
# Optional: is the artifact ATTRIBUTABLE to a routine?
#
# The commit that last touched the path must have a subject of the form "cron (#)?NN <name> <date>".
# The subject is resolved from the GitHub API first, because the routine's clone is SHALLOW and
# `git log -- <path>` has no history to walk there. If neither source can answer, the subject is
# reported as UNVERIFIED and the check does not fail — an infrastructure hiccup must not turn a
# successful delivery into a reported failure.
# ---------------------------------------------------------------------------------------------
[ -z "$NN" ] && exit 0

SUBJECT=""
SUBJ_SRC=""
if command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  SUBJECT=$(curl -sG --max-time 25 \
      --data-urlencode "path=$PATH_" \
      --data-urlencode "sha=$BRANCH" \
      --data-urlencode "per_page=1" \
      "https://api.github.com/repos/$REPO/commits" 2>/dev/null \
    | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(d,list) and d:
    print((d[0].get("commit",{}).get("message") or "").splitlines()[0])
' 2>/dev/null)
  [ -n "$SUBJECT" ] && SUBJ_SRC="api"
fi

if [ -z "$SUBJECT" ]; then
  SUBJECT=$(git log -1 --format=%s "origin/$BRANCH" -- "$PATH_" 2>/dev/null | head -1)
  [ -n "$SUBJECT" ] && SUBJ_SRC="git"
fi

if [ -z "$SUBJECT" ]; then
  echo "SUBJECT: unverified (could not resolve the commit subject for $PATH_ — delivery is proven, attribution is not)"
  exit 0
fi

if printf '%s' "$SUBJECT" | grep -qE "^cron (#)?${NN}[[:space:]]"; then
  echo "SUBJECT: ok ($SUBJECT)"
  exit 0
fi

echo "SUBJECT: FAILED (expected a subject matching 'cron (#)?${NN} ', got '$SUBJECT')"
echo "  the artifact IS on origin/$BRANCH, but cron #90's triage greps commit subjects for"
echo "  'cron (#)?${NN} ' and will report it as MISSING. Fix forward with a commit whose subject"
echo "  carries the routine number. Do NOT force-push main — master mirrors it fast-forward."
exit 4

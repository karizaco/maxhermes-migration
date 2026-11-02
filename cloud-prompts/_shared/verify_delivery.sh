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
#   verify_delivery.sh --path <repo-relative-path> [--branch <branch>]
#
# EXIT CODES
#   0 = present on origin/<branch>
#   1 = ABSENT — the artifact did not land. Report this plainly; do not claim success.
set -u

PATH_=""; BRANCH="main"
while [ $# -gt 0 ]; do
  case "$1" in
    --path)   PATH_="${2:-}";   shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    *) echo "verify_delivery.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$PATH_" ]; then
  echo "verify_delivery.sh: --path is required" >&2
  exit 3
fi

cd "${REPO_DIR:-/workspace}" 2>/dev/null || { echo "DELIVERY: FAILED (no repo dir)"; exit 1; }
git fetch -q origin "$BRANCH" 2>/dev/null || true

if git cat-file -e "origin/$BRANCH:$PATH_" 2>/dev/null; then
  echo "DELIVERY: ok (origin/$BRANCH:$PATH_ present)"
  exit 0
fi

echo "DELIVERY: FAILED (origin/$BRANCH:$PATH_ NOT found)"
exit 1

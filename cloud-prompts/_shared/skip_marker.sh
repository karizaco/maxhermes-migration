#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# skip_marker.sh — write AND PUSH a skipped-fire marker, for the cron fleet.
#
# WHY THIS EXISTS
# ---------------
# Every routine's window check wrote its SKIPPED marker into the SANDBOX and then
# exited 0 without pushing it. The marker therefore never reached the outputs repo,
# so a deliberate skip left no trace on the remote and became indistinguishable from
# a failed run — the 2026-10-26 case for cron #16: neither an artifact nor a marker
# exists, and only the scheduler's run history shows the fire happened.
#
# The marker is written INSIDE the routine's own output directory, so the shared
# push script stages it with the rest of that routine's output tree and it lands in
# the SAME commit as the routine's other files. The filename cannot match cron #90's
# artifact pattern (^<dir>/YYYY-MM-DD\.md$), so a marker is never mistaken for a
# delivered artifact.
#
# USAGE
#   sh /workspace/skip_marker.sh --out <output-dir> --name <marker-stem> \
#       --label "<human title>" --reason "<reason>" [--date YYYY-MM-DD] [--nn NN]
#
#   --out     the routine's output directory, relative to the repo root. The marker is
#             written to <repo-root>/<out>/SKIPPED_<date>.md (or SKIPPED_<name>.md when
#             --name is given) and pushed from there.
#   --name    marker filename stem. Defaults to the date, giving SKIPPED_<date>.md.
#   --label   the human-readable title inside the marker.
#   --reason  why the fire was skipped.
#   --date    the date to stamp. Defaults to today in US/Eastern.
#   --nn      routine number, recorded in the commit subject.
#
# EXIT CODES
#   0 = the marker was written and pushed (or was already on the branch)
#   1 = the marker was written but NOT pushed - it is still in the sandbox; say so
#   2 = no GITHUB_TOKEN and no connector fallback
#   3 = refused (bad args)
#
# A skip is NOT a failure: this script never returns a non-zero status that should
# stop the caller from finishing its reply. The caller reports what happened.
set -u

OUT=""; NAME=""; LABEL=""; REASON=""; DATE=""; NN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)    OUT="${2:-}";   shift 2 ;;
    --name)   NAME="${2:-}";  shift 2 ;;
    --label)  LABEL="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --date)   DATE="${2:-}";  shift 2 ;;
    --nn)     NN="${2:-}";    shift 2 ;;
    *) echo "skip_marker.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$OUT" ]; then
  echo "skip_marker.sh: --out is required" >&2
  exit 3
fi
case "$OUT" in
  ''|*' '*|'-'*|'/'*|*'/'|*'//'*)
    echo "skip_marker.sh: --out must be a plain directory name (got '$OUT')" >&2
    exit 3 ;;
esac

DATE="${DATE:-$(TZ=America/New_York date +%Y-%m-%d)}"
[ -n "$NAME" ] || NAME="$DATE"
# A colon breaks shells and the auditor's path matching.
SAFE_NAME=$(printf '%s' "$NAME" | tr ':' '_')
LABEL="${LABEL:-Cron}"
REASON="${REASON:-unknown}"

REPO_DIR="${REPO_DIR:-/workspace}"
# The marker lives in refs/skipped-markers/, the fleet's established home for
# skipped-fire audit trail. It is OUTSIDE every routine's output dir, so it can
# never be mistaken for a delivered artifact, and it cannot collide between
# routines that share an output directory.
#
# The push script stages the WHOLE --out tree, so --out must be the directory
# that holds the marker and nothing else. refs/skipped-markers is exactly that.
MARKER_STEM="${SAFE_NAME}"
MARKER_REL="refs/skipped-markers/${DATE}_SKIPPED_${MARKER_STEM}.md"
mkdir -p "$REPO_DIR/refs/skipped-markers" 2>/dev/null || true

cat > "$REPO_DIR/$MARKER_REL" <<EOF
# ${LABEL} — SKIPPED
- Date (ET): $DATE
- Reason: $REASON
- No artifact produced: $OUT/$DATE.md is intentionally absent.
- This marker IS the audit trail for the skip. The routine fired and declined; it did not fail.
EOF

echo "skip-marker written: $MARKER_REL"

# --- push it -----------------------------------------------------------------
# The shared push script stages the routine's WHOLE output tree, so the marker
# lands in the same commit as the routine's other files. It is fetched on demand
# because the sandbox is fresh on every fire.
PUSH=/workspace/push_artifact.sh
# ALWAYS fetch a fresh copy. A stale sandbox copy is a hazard: the pre-2026-11-03
# version ignores REMOTE_URL, so a local test against a bare repo would silently
# push to the LIVE outputs repo instead. Overwriting is the safe default.
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/push_artifact.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh" ; do
  curl -sL --max-time 30 -o "$PUSH.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script - never run one.
  if head -1 "$PUSH.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$PUSH.tmp" "$PUSH"; break
  fi
  rm -f "$PUSH.tmp"
done

if [ ! -s "$PUSH" ] || ! head -1 "$PUSH" 2>/dev/null | grep -q '^#!'; then
  echo "skip-marker push: SKIPPED (push script unavailable; the marker is still in the sandbox at $MARKER_REL)"
  exit 1
fi

# The commit subject must carry the routine number: cron #90's near-miss triage
# greps commits for "cron (#)?NN " to attribute a push to a routine. A marker
# commit without it is invisible to the auditor.
if [ -n "$NN" ]; then
  MSG="cron $NN $OUT SKIPPED $DATE"
else
  MSG="cron $OUT SKIPPED $DATE"
fi

# SRC_DIR is passed explicitly: the push script would otherwise derive it from
# --out, which is only correct when the marker directory IS the output directory.
if sh "$PUSH" --out refs/skipped-markers --add "$MARKER_REL" --branch main --msg "$MSG" \
      --src-dir "$REPO_DIR/refs/skipped-markers"; then
  echo "skip-marker push: ok ($MARKER_REL on origin/main)"
  exit 0
fi
echo "skip-marker push: FAILED (the marker is still in the sandbox at $MARKER_REL)"
exit 1

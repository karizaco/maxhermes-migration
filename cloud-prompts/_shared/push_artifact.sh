#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# push_artifact.sh — the ONE push implementation for the cron fleet.
#
# WHY THIS EXISTS
# ---------------
# The fleet used to carry a ~3.2 KB bash push block in each of 21 prompts. The bodies were
# byte-identical except for three lines (mkdir / cp / git add), so every fix had to be made 21
# times — and the bug class below lived in all 21 copies.
#
#   git push -q origin HEAD:refs/heads/X 2>&1 | head -3
#
# `| head -3` makes the pipeline's exit status HEAD'S (always 0), so a REJECTED push reported
# success. Measured 2026-10-28: a concurrent push lost options-flow/<date>.md and reported
# exit 0. Cron #90 was still carrying this trap on 2026-11-02.
#
# This script captures the exit status DIRECTLY, never uses `git add -A` (which staged 283
# deletions on 2026-10-25 and wiped seven routines' artifacts), and retries a rejected push by
# re-fetching and rebuilding the worktree from the NEW tip — which is what makes the loser of
# a shared-fire-minute race land on a later attempt.
#
# USAGE
#   push_artifact.sh --out <output-dir> --add <repo-relative-path> [--branch <branch>] [--msg <text>]
#
#   --out     the routine's output directory, relative to the repo root (e.g. daily-screens)
#   --add     the exact repo-relative path to stage. NEVER '.', NEVER a wildcard.
#   --branch  target branch (default: main). Cron #90 pushes to audit/status.
#   --msg     commit message (default: "cron <out> <date>")
#
# EXIT CODES
#   0 = pushed, and the path verified present on origin/<branch>
#   1 = push failed after 3 attempts — the artifact is STILL in the sandbox; say so
#   2 = no GITHUB_TOKEN — push skipped; the caller writes the artifact and replies
#   3 = refused (bad args, or staged deletions detected)
set -u

OUT=""; ADD=""; BRANCH="main"; MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)    OUT="${2:-}";   shift 2 ;;
    --add)    ADD="${2:-}";   shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --msg)    MSG="${2:-}";   shift 2 ;;
    *) echo "push_artifact.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$OUT" ] || [ -z "$ADD" ]; then
  echo "push_artifact.sh: --out and --add are both required" >&2
  exit 3
fi
case "$ADD" in
  *'*'*|.|/*)
    echo "push_artifact.sh: --add must be a plain repo-relative path (got '$ADD')" >&2
    exit 3 ;;
esac
case "$BRANCH" in
  ''|*' '*|'-'*|'/'*|*'/'|*'//'*)
    echo "push_artifact.sh: --branch must be a plain branch name (got '$BRANCH')" >&2
    exit 3 ;;
esac

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "push: skipped (token unset)"
  exit 2
fi

export GIT_SSL_CAINFO="${GIT_SSL_CAINFO:-/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt}"
export SSL_CERT_FILE="$GIT_SSL_CAINFO"
export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME="${HOME:-/workspace/.home}"
mkdir -p "$HOME"

git config --global http.sslCAInfo "$GIT_SSL_CAINFO" 2>/dev/null || true
git config --global user.email  "maxhermes-cloud@local" 2>/dev/null || true
git config --global user.name   "MaxHermes Cloud Cron"      2>/dev/null || true

REPO_DIR="${REPO_DIR:-/workspace}"
cd "$REPO_DIR" || { echo "push: FAILED (no repo dir at $REPO_DIR)"; exit 1; }

git init -q 2>/dev/null || true
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"
else
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"
fi

LAST_ERR=""
for attempt in 1 2 3; do
  git fetch -q origin "$BRANCH" 2>/dev/null || true
  git worktree prune 2>/dev/null || true
  # NOTE: no $RANDOM - it is a bashism and `set -u` makes it fatal under dash.
  WT="${REPO_DIR}/.wt.$$.$attempt"
  rm -rf "$WT"
  # Base the worktree on origin/<BRANCH> when that branch exists remotely (the normal case:
  # main, and audit/status for cron #90). If the target branch does not exist yet, base on
  # origin/main instead and let the push create it - otherwise the very first push to a new
  # branch fails with "could not create a worktree".
  if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null 2>&1; then
    BASE_REF="origin/$BRANCH"
  else
    BASE_REF="origin/main"
  fi
  if ! git worktree add -f "$WT" "$BASE_REF" >/dev/null 2>&1; then
    LAST_ERR="could not create a worktree from $BASE_REF"
    continue
  fi

  # copy the routine's output tree into the worktree.
  # SRC_DIR is where the artifact lives in the sandbox (default /workspace/$OUT); OUT is the
  # same path relative to the repo root.
  SRC_DIR="${SRC_DIR:-/workspace/$OUT}"
  ADD_DIR=$(dirname "$ADD")
  mkdir -p "$WT/$ADD_DIR" 2>/dev/null || true
  if [ -d "$SRC_DIR" ]; then
    mkdir -p "$WT/$OUT"
    cp -r "$SRC_DIR/." "$WT/$OUT/" 2>/dev/null || true
  fi

  cd "$WT" || { rm -rf "$WT"; continue; }
  # Stage ONLY the named path. Never `git add -A`: in a fresh worktree that stages every
  # other file on the branch as DELETED (2026-10-25: 283 files wiped).
  git add -- "$ADD" 2>/dev/null || true
  STAGED="$(git status --short)"
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    cd "$REPO_DIR"; rm -rf "$WT"; exit 1
  fi
  if echo "$STAGED" | grep -q '^ *D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    cd "$REPO_DIR"; rm -rf "$WT"; exit 3
  fi

  git commit -q -m "${MSG:-cron $OUT $(TZ=America/New_York date +%Y-%m-%d)}" 2>/dev/null || true

  # Capture the exit status DIRECTLY. Never `git push ... | head -3` — that returns head's
  # status (always 0) and reports a rejected push as a success.
  if git push -q origin "HEAD:refs/heads/$BRANCH" 2>/tmp/push_artifact.err; then
    echo "push: ok (attempt $attempt)"
    cd "$REPO_DIR"; rm -rf "$WT"
    # Verify what actually landed, not merely that the push exited 0.
    if git fetch -q origin "$BRANCH" 2>/dev/null && \
       git cat-file -e "origin/$BRANCH:$ADD" 2>/dev/null; then
      echo "DELIVERY: ok (origin/$BRANCH:$ADD present)"
      exit 0
    fi
    echo "DELIVERY: FAILED (push exited 0 but origin/$BRANCH:$ADD is absent)"
    exit 1
  fi

  LAST_ERR="$(head -1 /tmp/push_artifact.err 2>/dev/null | tr -d '\r')"
  echo "push: attempt $attempt rejected: $LAST_ERR"
  cd "$REPO_DIR"; rm -rf "$WT"
  sleep 5
done

echo "push: FAILED (3 attempts rejected - the artifact is STILL in the sandbox at /workspace/$OUT/)"
[ -n "$LAST_ERR" ] && echo "push: last error: $LAST_ERR"
exit 1

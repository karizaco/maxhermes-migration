#!/bin/sh
# PUSH_ARTIFACT_VERSION: 2026-11-08.1
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
#   push_artifact.sh --out <output-dir> --add <repo-relative-path> [--branch <branch>] [--msg <text>] [--nn <NN>]
#
#   --out     the routine's output directory, relative to the repo root (e.g. daily-screens)
#   --add     the routine's PRIMARY artifact path. Used for the delivery check and to derive
#             the routine identity. The routine's WHOLE output tree is staged, not just this
#             file — see "WHAT GETS STAGED" below.
#   --branch  target branch (default: main). Cron #90 pushes to audit/status.
#   --msg     commit message. Overrides the derived default.
#   --nn      routine number. Overrides the derived default.
#   --src-dir where the files live in the sandbox. Defaults to /workspace/<out>.
#
# WHAT GETS STAGED — the whole output tree, NOT just --add
# ----------------------------------------------------------
# The pre-2026-11-02 per-prompt blocks did `git add <own-dir>`: one commit per routine,
# carrying every file the routine produced. The first version of this script staged only the
# single `--add` path, which broke every MULTI-FILE routine: cron #09 produces 27 files, so
# only one landed per push and the agent had to push 27 times — 61 commits on 2026-11-02, each
# regenerating the artifact's `generated_et` timestamp so the previous push was stale by the
# next check. It ended in a push loop.
#
# The worktree is built from origin/<branch>, so staging the routine's output directory stages
# exactly the files that DIFFER from the branch — the routine's own artifacts, and nothing else.
# A sibling routine's file in the same directory is already on the branch and unchanged, so it
# is not staged. Files are never deleted: `cp -r` only adds to the worktree.
#
# DEFAULT-BRANCH MIRROR
#   After a successful push to `main`, this script also fast-forwards `master` (the repo's
#   GitHub default branch, which cannot be changed without Administration scope) to the
#   pushed tip. Pointer-only, fast-forward-only, ancestry-gated, and strictly best-effort:
#   it never touches an artifact and it can never fail the push above. See
#   mirror_default_branch() below.
#
# EXIT CODES
#   0 = pushed, and the path verified present on origin/<branch>
#   1 = push failed after 3 attempts — the artifact is STILL in the sandbox; say so
#   2 = no GITHUB_TOKEN — push skipped; the caller writes the artifact and replies
#   3 = refused (bad args, or staged deletions detected)
set -u

# --- SELF-HEAL (2026-11-04) -----------------------------------------------------
# WHY: the fleet's prompt fetch blocks use `[ -s file ] || curl`, which can NEVER reach
# its own fallback — the FIRST successful download satisfies the guard, so the second URL
# is dead code. Measured 2026-11-04: raw.githubusercontent served a STALE blob for >17
# minutes after a push (jsDelivr was fresh), so a routine firing in that window ran a
# STALE push script. This re-fetches ITSELF from the authoritative, non-CDN-cached
# contents API and re-execs the fresh copy if the remote is newer.
# Guarded by an env var so it can NEVER loop, and it is a no-op when the remote is
# identical or older. One extra API call per push (~1s).
if [ -z "${_PUSH_ARTIFACT_HEALED:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
  _PA_TMP=/tmp/_push_artifact_selfheal.sh
  curl -sL --max-time 20 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$_PA_TMP" \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/push_artifact.sh?ref=main" 2>/dev/null
  if [ -s "$_PA_TMP" ] && head -1 "$_PA_TMP" 2>/dev/null | grep -q '^#!'; then
    _PA_LOC_V=$(sed -n 's/^# PUSH_ARTIFACT_VERSION: //p' "$0" 2>/dev/null | head -1)
    _PA_REM_V=$(sed -n 's/^# PUSH_ARTIFACT_VERSION: //p' "$_PA_TMP" 2>/dev/null | head -1)
    _PA_LOC_V=${_PA_LOC_V:-0.0.0}; _PA_REM_V=${_PA_REM_V:-0.0.0}
    _PA_NEW=$(printf '%s\n%s\n' "$_PA_LOC_V" "$_PA_REM_V" | sort -V | tail -1)
    if [ "$_PA_REM_V" != "$_PA_LOC_V" ] && [ "$_PA_NEW" = "$_PA_REM_V" ]; then
      _PA_HEALED="$(dirname "$0" 2>/dev/null)/.push_artifact.healed.sh"
      cp "$_PA_TMP" "$_PA_HEALED" 2>/dev/null && {
        _PUSH_ARTIFACT_HEALED=1; export _PUSH_ARTIFACT_HEALED
        echo "push_artifact: self-healed $_PA_LOC_V -> $_PA_REM_V (from the contents API)"
        exec sh "$_PA_HEALED" "$@"
      }
    fi
  fi
  rm -f "$_PA_TMP"
fi

OUT=""; ADD=""; ADD_ALL=""; BRANCH="main"; MSG=""; NN=""; NM=""; SRC_DIR_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)    OUT="${2:-}";   shift 2 ;;
    --add)    ADD="${2:-}";   ADD_ALL="$ADD_ALL ${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --msg)    MSG="${2:-}";   shift 2 ;;
    --nn)     NN="${2:-}";    shift 2 ;;
    --src-dir) SRC_DIR_ARG="${2:-}"; shift 2 ;;
    *) echo "push_artifact.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$OUT" ] || [ -z "$ADD" ]; then
  echo "push_artifact.sh: --out and --add are both required" >&2
  exit 3
fi

# --- THE SLOT: the common parent directory of the --add paths -------------------------
# SRC_DIR is where the artifact lives in the sandbox and the script copies that whole tree
# into the worktree before staging it. With --out daily-screens that tree is the ENTIRE
# output folder (2026-11-12: 773 files, 22 MB) for a two-file push - every byte is copied
# and every file is re-hashed to discover that nothing changed.
#
# The SLOT is the deepest directory that holds EVERY --add path. The script then copies and
# stages only that directory. When the --add paths span different roots there is no common
# slot, and the script falls back to the whole output tree (the old behaviour).
SLOT=""
for _a in $ADD_ALL; do
  _d=$(dirname "$_a")
  if [ -z "$SLOT" ]; then
    SLOT="$_d"
  elif [ "$_d" = "$SLOT" ]; then
    :
  elif [ "$_d" = "." ] || [ "$SLOT" = "." ]; then
    SLOT=""
    break
  elif [ "${_d#"$SLOT"/}" != "$_d" ]; then
    :                                   # _d is inside SLOT - keep SLOT
  else
    SLOT=""                             # no common ancestor
    break
  fi
done
[ "$SLOT" = "." ] && SLOT=""
if [ -n "$SLOT" ]; then
  echo "push: slot '$SLOT' (staging only that directory)"
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
# --out is a repo-RELATIVE directory, which may be nested (e.g. refs/skipped-markers).
# It was previously restricted to a single plain name. That restriction was
# rejected as unusable for the skipped-fire marker path, which lives in a
# subdirectory; no routine passed a nested --out before, so relaxing it is
# additive. What is still refused: absolute paths, "..", wildcards, whitespace
# and anything starting with "-" (which git would read as an option).
case "$OUT" in
  ''|*' '*|'-'*)
    echo "push_artifact.sh: --out must be a relative path with no spaces and not start with '-' (got '$OUT')" >&2
    exit 3 ;;
  .)
    : ;;  # documented usage: --out . means the repo root
  /*|*/../*|*/..|..|../*|*'*'*|*'?'*)
    echo "push_artifact.sh: --out must be a safe relative path (got '$OUT')" >&2
    exit 3 ;;
esac

# --- Windows-safe path sanitization (2026-11-08) ----------------------------
# WHY: the outputs repo is checked out on Windows. A basename containing
# Windows-illegal characters (notably ':') cannot be checked out there — 76
# historical files already break a plain clone. Generators must not write those
# names, but the LLM has also *improvised* colon filenames
# (reversal-bullish-3:55-near-misses.csv, …-CORRECTION.md). This block is the
# chokepoint: every routine delivers through this script, so illegal names are
# normalized here even when a prompt, skill, or agent still uses the old form.
#
# Convention matches skip_marker.sh: replace ':' (and other illegal basename
# chars) with '_'. Prose times ("15:55 ET") and scheduler cron_names are
# unaffected — only filesystem paths that pass through --add / the staged tree.
win_safe_component() {
  # Replace Windows-illegal filename characters; strip trailing dots/spaces.
  _c=$(printf '%s' "$1" | sed 's/[<>:"\\|?*]/_/g' | sed 's/[. ]*$//')
  [ -n "$_c" ] || _c="_"
  printf '%s' "$_c"
}

win_safe_path() {
  # Keep '/' as the separator; sanitize every other component.
  _in=$1
  _out=""
  _first=1
  # IFS=/ walk without requiring bash arrays
  old_ifs=$IFS
  IFS=/
  # leading ./ or empty components from // are skipped
  for _part in $_in; do
    IFS=$old_ifs
    if [ -z "$_part" ]; then
      continue
    fi
    _safe=$(win_safe_component "$_part")
    if [ "$_first" -eq 1 ]; then
      _out="$_safe"
      _first=0
    else
      _out="$_out/$_safe"
    fi
    IFS=/
  done
  IFS=$old_ifs
  # preserve a leading "./" only if input was exactly that — not needed here
  printf '%s' "$_out"
}

sanitize_tree() {
  # Rename any file/dir basename under $1 that is Windows-illegal.
  # Depth-first so children move before parents.
  _root=$1
  [ -d "$_root" ] || return 0
  # Prefer find -depth; fall back to a simple pass if find is missing.
  if command -v find >/dev/null 2>&1; then
    _list=$(find "$_root" -depth 2>/dev/null)
  else
    _list=$(ls -1 "$_root" 2>/dev/null)
  fi
  printf '%s\n' "$_list" | while IFS= read -r _p; do
    [ -n "$_p" ] || continue
    [ "$_p" = "$_root" ] && continue
    _base=$(basename "$_p")
    _dir=$(dirname "$_p")
    _safe=$(win_safe_component "$_base")
    if [ "$_base" = "$_safe" ]; then
      continue
    fi
    _dest="$_dir/$_safe"
    if [ -e "$_dest" ]; then
      echo "push: windows-sanitize: drop '$_base' (safe name '$_safe' already exists)"
      rm -rf "$_p"
    else
      mv -f "$_p" "$_dest"
      echo "push: windows-sanitize: '$_base' -> '$_safe'"
    fi
  done
}

# Normalize --add paths BEFORE identity derivation and delivery checks, so a
# caller that still passes …/reversal-bullish-3:55.md is rewritten to …3_55.md
# and matches the files the generators now write.
_ADD_NEW=""
_ADD_LAST=""
for _addp in $ADD_ALL; do
  _s=$(win_safe_path "$_addp")
  if [ "$_addp" != "$_s" ]; then
    echo "push: windows-sanitize: --add '$_addp' -> '$_s'"
  fi
  _ADD_NEW="$_ADD_NEW $_s"
  _ADD_LAST="$_s"
done
ADD_ALL=$(printf '%s' "$_ADD_NEW" | sed 's/^ *//')
# ADD is the last --add (historical behaviour); keep that after sanitizing.
if [ -n "$_ADD_LAST" ]; then
  ADD="$_ADD_LAST"
fi
case "$ADD" in
  *':'*|*'<'*|*'>'*|*'|'*|*'?'*|'*'*|*"'"*|*'\\'*)
    echo "push: ABORTED ( --add still unsafe after sanitize: '$ADD')" >&2
    exit 3 ;;
esac

# Sanitize the sandbox source tree so the copy into the worktree (and the
# connector fallback's LOCAL_FILE lookup) already uses safe basenames.
SRC_DIR="${SRC_DIR_ARG:-/workspace/${SLOT:-$OUT}}"
sanitize_tree "$SRC_DIR"

# --- routine identity -------------------------------------------------------
# The commit subject must carry the routine NUMBER: cron #90's near-miss triage greps commits
# for "cron (#)?NN " to attribute a push to a routine. Without the number a routine's push is
# invisible to the auditor and a delivered artifact is reported as MISSING.
#
# The number is derived from the artifact path, so it is deterministic instead of depending on
# the agent remembering to pass --msg. This table is the same mapping the roster uses.
# A routine whose artifact path matches NO pattern gets NN="" and a subject with no number at
# all ("cron daily-briefs <date>"), which cron #90's triage reports as MISSING. That is why
# every path a routine can produce needs a row here -- and why a caller should still pass
# --nn explicitly: the table can only be fixed by a push, the flag travels with the call.
# NOTE: --add OVERWRITES, so $ADD holds only the LAST path given. With several --add paths the
# routine number used to be derived from that last path alone, so a second path (a companion
# CSV, say) silently wiped the number out of the commit subject — and cron #90's triage greps
# subjects for "cron (#)?NN ", which then reports a DELIVERED artifact as MISSING. Deriving from
# the FIRST path that matches the table fixes that. A single --add caller is unaffected: one
# path, same answer as before.
# The NAME is derived on EVERY run, whether or not --nn was passed.
#
# Before 2026-11-12 the whole table sat inside `if [ -z "$NN" ]`, so a caller that passed
# --nn explicitly skipped it entirely: NN was set, NM stayed empty, and the subject fell
# back to the generic output directory ("cron 04 daily-screens 2026-11-12" instead of
# "cron 04 reversal-bullish-3_55 2026-11-12"). The NUMBER survived, so cron #90's triage
# still attributed the push - but the routine NAME was silently lost for every routine that
# passes --nn, and the name is what makes a commit scannable.
#
# NN is taken from the table only when the caller did NOT supply it; NM is taken from the
# table whenever the table recognises the path.
for _addp in $ADD_ALL; do
  case "$_addp" in
    asia-pre-market/*) _NN=02; _NM=asia-pre-market-reactions ;;
    earnings/*-reminders.md) _NN=19; _NM=earnings-reminder-daily ;;
    earnings/*-reactions.md) _NN=15; _NM=earnings-reaction-scanner ;;
    daily-briefs/*-pre-market.md) _NN=26; _NM=agentic-pre-market-brief ;;
    daily-briefs/*-pre-market.csv) _NN=26; _NM=agentic-pre-market-brief ;;
    daily-briefs/*-pre-market-refresh.md) _NN=26b; _NM=agentic-pre-market-brief-refresh ;;
    daily-briefs/*-post-market.md) _NN=23; _NM=agentic-post-market-brief ;;
    daily-screens/*/pre-market-gapper.md) _NN=08; _NM=stock-screener-pre-market-gapper ;;
    daily-screens/*/focus-rvol-snapshot.md) _NN=07; _NM=stock-screener-focus-rvol-09:45 ;;
    daily-screens/*/breadth-snapshot.md) _NN=10; _NM=stock-screener-breadth-snapshot ;;
    daily-screens/*/reversal-bullish-3_55.md) _NN=04; _NM=reversal-bullish-3_55 ;;
    daily-screens/*/reversal-bullish-3_55.csv) _NN=04; _NM=reversal-bullish-3_55 ;;
    daily-screens/*/weekly-ipo.md) _NN=06; _NM=stock-screener-pattern-study-backlog ;;
    daily-screens/*/daily-sweep.md) _NN=09; _NM=stock-screener-daily-sweep-18:30 ;;
    cross-asset/*) _NN=12; _NM=cross-asset-correlation-snapshot ;;
    macro-calendar/*-midweek.md) _NN=13; _NM=macro-calendar-midweek ;;
    macro-calendar/*-week-ahead.md) _NN=14; _NM=macro-calendar-week-ahead ;;
    ntrt/*) _NN=25; _NM=ntrt-gap-brief-daily ;;
    options-flow/*) _NN=16; _NM=unusual-options-flow-daily ;;
    us-stocks-in-play/*) _NN=17; _NM=us-stocks-in-play ;;
    us-eod/*) _NN=20; _NM=eod-watchlist-csv-snapshot ;;
    international-eod/*) _NN=05; _NM=eod-international-daily ;;
    weekly/*-preview.md) _NN=22; _NM=weekly-market-recap-preview ;;
    preopen-feed/*) _NN=92; _NM=preopen-catalyst-capture ;;
    _audit/status.json) _NN=90; _NM=delivery-auditor ;;
    *) _NN=""; _NM="" ;;
  esac
  [ -n "$_NM" ] || continue
  [ -z "$NN" ] && NN="$_NN"
  [ -z "$NM" ] && NM="$_NM"
  break
done

# The subject's date is the ARTIFACT's date, taken from the artifact path — not the execution
# date. On a delayed replay those differ, and cron #90 greps commits by the audited date.
ART_DATE=""
for _addp in $ADD_ALL; do
  ART_DATE=$(printf '%s' "$_addp" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
  [ -n "$ART_DATE" ] && break
done
[ -n "$ART_DATE" ] || ART_DATE=$(TZ=America/New_York date +%Y-%m-%d)

if [ -z "$MSG" ]; then
  if [ -n "$NN" ]; then
    # ${NM:-$OUT} — NM is only set when the routine is derived from the artifact path.
    # A caller that passes --nn without --msg must not trip `set -u` on an unset NM.
    MSG="cron $NN ${NM:-$OUT} $ART_DATE"
  else
    MSG="cron $OUT $ART_DATE"
  fi
fi

# A literal {date} in the --msg is replaced with the ARTIFACT's date, so the prompt does not
# depend on the agent substituting the placeholder correctly. The date comes from the artifact
# path, so on a delayed replay it is the scheduled date, not the execution date.
case "$MSG" in
  *"{date}"*) MSG=$(printf '%s' "$MSG" | sed "s|{date}|$ART_DATE|g") ;;
esac

# --- GitHub connector fallback -------------------------------------------------
# When the sandbox has no GITHUB_TOKEN, or every git attempt was rejected, deliver the file
# through the GitHub connector instead: it needs no token in the sandbox, and a file-level
# write cannot stage deletions the way `git add -A` did on 2026-10-25 (283 files wiped).
#
# It has NO equivalent of the 3-attempt race-retry, so it stays a FALLBACK. The git path is
# still PRIMARY for routines that share a fire minute with a partner.
connector_fallback() {
  # SAFETY (2026-11-12): the connector writes to the PRODUCTION outputs repo and it has
  # NO notion of REMOTE_URL - it talks to the GitHub API. So a caller that pointed
  # REMOTE_URL at a local/test remote (a push-script rehearsal) would have its FILE
  # written to production anyway, because the connector fallback ignores the override.
  # Measured: a rehearsal against a local bare repo overwrote the live
  # daily-screens/2026-11-12/reversal-bullish-3_55.md on main with the rehearsal's
  # placeholder, and the real artifact had to be re-pushed. So: if REMOTE_URL is NOT
  # the production outputs repo, the connector must NOT run.
  case "${REMOTE_URL:-}" in
    *github.com/karizaco/minimax-cloud-outputs.git) : ;;
    *)
      echo "push: connector fallback SKIPPED (REMOTE_URL is not the production outputs repo -"
      echo "       the connector would write to production regardless of the override)"
      return 1 ;;
  esac
  command -v mcode-tools >/dev/null 2>&1 || {
    echo "push: connector fallback unavailable (mcode-tools not on PATH)"; return 1; }
  LOCAL_FILE="${SRC_DIR:-/workspace/$OUT}/$(basename "$ADD")"
  [ -e "$LOCAL_FILE" ] || LOCAL_FILE="${REPO_DIR:-/workspace}/$ADD"
  HELP=/workspace/push_via_connector.sh
  # A sibling copy, if the caller fetched both files into one directory.
  SIB="$(dirname "$0" 2>/dev/null)/push_via_connector.sh"
  if [ ! -s "$HELP" ] && [ -s "$SIB" ]; then HELP="$SIB"; fi
  if [ ! -s "$HELP" ]; then
    for U in \
      "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/push_via_connector.sh" \
      "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_via_connector.sh" ; do
      curl -sL --max-time 30 -o "$HELP.tmp" "$U" 2>/dev/null
      # A 404 page is a non-empty body that is NOT a script - never run one.
      if head -1 "$HELP.tmp" 2>/dev/null | grep -q '^#!'; then
        mv -f "$HELP.tmp" "$HELP"; break
      fi
      rm -f "$HELP.tmp"
    done
  fi
  if [ ! -s "$HELP" ] || ! head -1 "$HELP" 2>/dev/null | grep -q '^#!'; then
    rm -f "$HELP"
    echo "push: connector fallback skipped (could not fetch push_via_connector.sh)"; return 1
  fi
  # A routine whose deliverable is a FOLDER (cron #05 writes
  # international-eod/<DATE>/: 16 region CSVs + summary.md + the machine-readable
  # companions) has no single file for the connector. Push every file in it, one
  # call each, so the folder is delivered as completely as the git path delivers it.
  if [ -d "$LOCAL_FILE" ]; then
    _n=0
    for _f in "$LOCAL_FILE"/*; do
      [ -f "$_f" ] || continue
      if ! sh "$HELP" --path "$ADD/$(basename "$_f")" --file "$_f" --branch "$BRANCH" \
           --msg "${MSG:-cron $OUT $(TZ=America/New_York date +%Y-%m-%d)}"; then
        echo "push: connector fallback failed on $ADD/$(basename "$_f")"
        return 1
      fi
      _n=$((_n + 1))
    done
    [ "$_n" -gt 0 ] || {
      echo "push: connector fallback skipped (no files in $LOCAL_FILE)"; return 1; }
    echo "push: connector fallback delivered $_n file(s) from $ADD"
    return 0
  fi
  [ -f "$LOCAL_FILE" ] || {
    echo "push: connector fallback skipped (the artifact is not at $LOCAL_FILE)"; return 1; }
  sh "$HELP" --path "$ADD" --file "$LOCAL_FILE" --branch "$BRANCH" \
     --msg "${MSG:-cron $OUT $(TZ=America/New_York date +%Y-%m-%d)}"
}

# --- keep the repo's DEFAULT branch (master) in step with main --------------------
# GitHub's `default_branch` for the outputs repo is `master`, and it CANNOT be changed
# without repository Administration scope - the cron token does not have it, so it is a
# standing constraint, not an oversight. Every routine pushes to `main`, so without this
# anyone who opens the repo URL or runs a bare `git clone` lands on a tree that is a day
# behind the artifacts.
#
# `master` is therefore kept as a fast-forward MIRROR of `main`:
#   * pointer-only  - it moves a branch pointer; it never writes, deletes or rewrites an artifact
#   * fast-forward  - it can only move master FORWARD, so it can never lose a commit
#   * ancestry-gated - if `master` holds a commit the target does not, the mirror is SKIPPED,
#                      never force-pushed
#
# This runs AFTER the routine's own push, on every push to `main`, so the default branch
# trails `main` by minutes rather than by a day. It is strictly best-effort: every step is
# guarded and the function always returns 0, because a mirror failure must NEVER fail an
# artifact push.
mirror_default_branch() {
  TARGET="${1:-}"
  [ -n "$TARGET" ] || return 0
  git fetch -q origin "+refs/heads/master:refs/remotes/origin/master" 2>/dev/null || \
    git fetch -q origin master 2>/dev/null || true
  if ! git rev-parse --verify --quiet origin/master >/dev/null 2>&1; then
    echo "  master mirror: skipped (no master branch on the remote)"
    return 0
  fi
  if ! git merge-base --is-ancestor origin/master "$TARGET" 2>/dev/null; then
    echo "  master mirror: skipped (origin/master has commits the pushed tip does not - not a fast-forward)"
    return 0
  fi
  if git push -q origin "$TARGET:refs/heads/master" 2>/tmp/master_mirror.err; then
    echo "  master mirror: fast-forwarded to $(git rev-parse --short "$TARGET" 2>/dev/null)"
  else
    echo "  master mirror: skipped (push rejected: $(head -1 /tmp/master_mirror.err 2>/dev/null | tr -d '\r'))"
  fi
  return 0
}

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "push: no GITHUB_TOKEN in the sandbox - trying the GitHub connector"
  if connector_fallback; then
    echo "push: ok (connector)"
    exit 0
  fi
  echo "push: skipped (no token and the connector fallback did not land the file - the artifact is STILL in the sandbox)"
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
SRC_DIR="${SRC_DIR_ARG:-${SRC_DIR:-/workspace/${SLOT:-$OUT}}}"
cd "$REPO_DIR" || { echo "push: FAILED (no repo dir at $REPO_DIR)"; exit 1; }

git init -q 2>/dev/null || true
# REMOTE_URL exists so the script can be tested against a local bare repo. The cron prompts
# never set it, so the production target is always the GitHub outputs repo.
REMOTE_URL="${REMOTE_URL:-https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git}"
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
else
  git remote set-url origin "$REMOTE_URL"
fi

LAST_ERR=""
for attempt in 1 2 3; do
  # NOTE: fetch the branch into its remote-tracking ref EXPLICITLY. A bare `git fetch origin
  # main` updates FETCH_HEAD but does NOT advance refs/remotes/origin/main in a shallow clone,
  # so a later `git cat-file origin/main:<path>` would read a STALE ref and report a delivery
  # failure for an artifact that is actually on the branch.
  git fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null || \
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
  ADD_DIR=$(dirname "$ADD")
  mkdir -p "$WT/$ADD_DIR" 2>/dev/null || true
  # The copy target and the staged path are the SLOT when there is one, else $OUT.
  STAGE_PATH="${SLOT:-$OUT}"
  if [ -d "$SRC_DIR" ]; then
    mkdir -p "$WT/$STAGE_PATH"
    cp -r "$SRC_DIR/." "$WT/$STAGE_PATH/" 2>/dev/null || true
    # Second pass: rewrite any illegal basename before git add.
    sanitize_tree "$WT/$STAGE_PATH"
  fi

  cd "$WT" || { rm -rf "$WT"; continue; }
  # Stage the routine's WHOLE output tree, so every file it produced lands in ONE commit.
  # The worktree was built from origin/<branch>, so this stages exactly what DIFFERS from the
  # branch — the routine's own artifacts. A sibling routine's file in the same directory is
  # already on the branch and unchanged, so it is not staged. Never `git add -A`: in a fresh
  # worktree that stages every other file on the branch as DELETED (2026-10-25: 283 files
  # wiped).
  git add -- "$STAGE_PATH" 2>/dev/null || true
  STAGED="$(git diff --cached --name-only 2>/dev/null)"
  if [ -z "$STAGED" ]; then
    # Nothing differs from the branch. Either the artifact is already there byte-identical
    # (a re-run that produced the same output) or the routine wrote nothing.
    if git cat-file -e "origin/$BRANCH:$ADD" 2>/dev/null; then
      echo "push: ok (no change - $ADD is already on origin/$BRANCH)"
      cd "$REPO_DIR"; rm -rf "$WT"; exit 0
    fi
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    cd "$REPO_DIR"; rm -rf "$WT"; exit 1
  fi
  if git diff --cached --name-status 2>/dev/null | grep -q '^D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    cd "$REPO_DIR"; rm -rf "$WT"; exit 3
  fi

  git commit -q -m "$MSG" 2>/dev/null || true

  # Capture the exit status DIRECTLY. Never `git push ... | head -3` — that returns head's
  # status (always 0) and reports a rejected push as a success.
  # The sha we are about to push is the mirror's target: it is `main`'s new tip, and
  # `master` can only be fast-forwarded to it.
  PUSHED_SHA="$(git rev-parse HEAD 2>/dev/null)"
  if git push -q origin "HEAD:refs/heads/$BRANCH" 2>/tmp/push_artifact.err; then
    echo "push: ok (attempt $attempt)"
    cd "$REPO_DIR"; rm -rf "$WT"
    # Keep the repo's default branch in step. Only for pushes to `main` - cron #90 pushes
    # to `audit/status` and must never touch `master` from there.
    if [ "$BRANCH" = "main" ] && [ -n "${PUSHED_SHA:-}" ]; then
      mirror_default_branch "$PUSHED_SHA"
    fi
    # Verify what actually landed, not merely that the push exited 0.
    git fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null || \
      git fetch -q origin "$BRANCH" 2>/dev/null || true
    if git cat-file -e "origin/$BRANCH:$ADD" 2>/dev/null; then
      N=$(git ls-tree -r --name-only "origin/$BRANCH" -- "$OUT" 2>/dev/null | wc -l)
      echo "DELIVERY: ok (origin/$BRANCH:$ADD present; $OUT now holds $N file(s))"
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

echo "push: 3 git attempts rejected - the artifact is STILL in the sandbox at /workspace/$OUT/"
[ -n "$LAST_ERR" ] && echo "push: last error: $LAST_ERR"
echo "push: trying the GitHub connector as a fallback"
if connector_fallback; then
  echo "push: ok (connector fallback)"
  exit 0
fi
echo "push: FAILED (git refused AND the connector fallback did not land the file)"
exit 1

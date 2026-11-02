#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# push_via_connector.sh — deliver ONE file through the GitHub connector.
#
# WHY THIS EXISTS
# ---------------
# push_artifact.sh needs a GITHUB_TOKEN in the sandbox. When the token is absent the script
# exits 2 and the routine writes its artifact and REPLIES — but the artifact never lands on
# the remote. That is a silent delivery loss: the run looks healthy and the file is gone.
#
# The GitHub connector needs NO token in the sandbox, and a file-level write cannot stage
# deletions the way `git add -A` did on 2026-10-25 (283 files wiped).
#
# WHAT IT IS NOT
# --------------
# It is a FALLBACK, not a replacement. The connector has no equivalent of push_artifact.sh's
# 3-attempt race-retry, so routines that share a fire minute with a partner must keep the
# git path as PRIMARY. This script exists for the case where the git path cannot run at all.
#
# USAGE
#   push_via_connector.sh --path <repo-relative-path> --file <local-file> \
#                          [--branch <branch>] [--msg <commit-message>]
#
# EXIT CODES
#   0 = delivered AND verified (the remote blob matches the local file byte for byte)
#   1 = connector unavailable, or the write failed, or the remote does not match
#   3 = bad arguments
set -u

PATH_=""; FILE=""; BRANCH="main"; MSG=""
OWNER="${GITHUB_OWNER:-karizaco}"
REPO="${GITHUB_REPO:-minimax-cloud-outputs}"

while [ $# -gt 0 ]; do
  case "$1" in
    --path)   PATH_="${2:-}";   shift 2 ;;
    --file)   FILE="${2:-}";    shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --msg)    MSG="${2:-}";     shift 2 ;;
    *) echo "push_via_connector.sh: unknown argument '$1'" >&2; exit 3 ;;
  esac
done

if [ -z "$PATH_" ] || [ -z "$FILE" ]; then
  echo "push_via_connector.sh: --path and --file are both required" >&2
  exit 3
fi
case "$PATH_" in
  ''|*' '*|'-'*|'/'*|*'/'|*'//'*)
    echo "push_via_connector.sh: --path must be a plain repo-relative path (got '$PATH_')" >&2
    exit 3 ;;
esac
case "$BRANCH" in
  ''|*' '*|'-'*|'/'*|*'/'|*'//'*)
    echo "push_via_connector.sh: --branch must be a plain branch name (got '$BRANCH')" >&2
    exit 3 ;;
esac
if [ ! -f "$FILE" ]; then
  echo "push_via_connector.sh: local file '$FILE' does not exist" >&2
  exit 1
fi
if ! command -v mcode-tools >/dev/null 2>&1; then
  echo "push_via_connector.sh: mcode-tools not on PATH - connector path unavailable" >&2
  exit 1
fi

TMPD="$(mktemp -d 2>/dev/null || echo /tmp/pvc.$$)"
mkdir -p "$TMPD" 2>/dev/null || true

# --- 1. the blob SHA of the file being replaced, if it already exists on the branch.
#     create_or_update_file REQUIRES the sha when the path exists.
SHA=""
GET="$TMPD/get.json"
mcode-tools connector call connector__github__get_file_contents \
  --args "{\"owner\":\"$OWNER\",\"repo\":\"$REPO\",\"path\":\"$PATH_\",\"ref\":\"refs/heads/$BRANCH\"}" \
  >"$GET" 2>/dev/null
if [ -s "$GET" ]; then
  SHA=$(tr '\n' ' ' <"$GET" | sed -n 's/.*SHA: \([0-9a-f]\{40\}\).*/\1/p' | head -1)
fi

# --- 2. build the call arguments (content is the file's exact text, not base64).
ARGS="$TMPD/args.json"
python3 - "$FILE" "$OWNER" "$REPO" "$PATH_" "${MSG:-cron $PATH_}" "$BRANCH" "$SHA" >"$ARGS" <<'PY'
import json, sys
content_file, owner, repo, path, message, branch, sha = sys.argv[1:8]
with open(content_file, "r", encoding="utf-8", errors="replace") as fh:
    content = fh.read()
args = {"owner": owner, "repo": repo, "path": path, "content": content,
        "message": message, "branch": branch}
if sha:
    args["sha"] = sha
print(json.dumps(args))
PY
if [ ! -s "$ARGS" ]; then
  echo "push_via_connector.sh: could not build the connector arguments" >&2
  rm -rf "$TMPD"; exit 1
fi

# --- 3. write the file.
OUT="$TMPD/out.txt"
if ! mcode-tools connector call connector__github__create_or_update_file \
     --args-file "$ARGS" >"$OUT" 2>&1; then
  echo "push_via_connector.sh: connector call failed: $(head -1 "$OUT" 2>/dev/null)" >&2
  rm -rf "$TMPD"; exit 1
fi
if grep -qiE '"success"[[:space:]]*:[[:space:]]*false|error' "$OUT" 2>/dev/null; then
  echo "push_via_connector.sh: connector reported an error: $(head -c 200 "$OUT")" >&2
  rm -rf "$TMPD"; exit 1
fi

# --- 4. VERIFY. A write that reported success is not proof: read the file back from the
#     remote and compare it byte for byte with the local file.
VER="$TMPD/ver.json"
mcode-tools connector call connector__github__get_file_contents \
  --args "{\"owner\":\"$OWNER\",\"repo\":\"$REPO\",\"path\":\"$PATH_\",\"ref\":\"refs/heads/$BRANCH\"}" \
  >"$VER" 2>/dev/null
python3 - "$VER" "$FILE" <<'PY'
import json, sys
ver_path, local_path = sys.argv[1], sys.argv[2]
try:
    blocks = json.load(open(ver_path, encoding="utf-8", errors="replace"))
except Exception as exc:
    print("DELIVERY: FAILED (could not read the verification response: %s)" % exc)
    raise SystemExit(1)
remote = None
if isinstance(blocks, list):
    for b in blocks:
        res = b.get("resource") if isinstance(b, dict) else None
        if isinstance(res, dict) and "text" in res:
            remote = res["text"]
            break
if remote is None and isinstance(blocks, dict):
    c = blocks.get("content")
    if isinstance(c, list) and c:
        c = c[0]
    if isinstance(c, dict):
        remote = c.get("text")
if remote is None:
    print("DELIVERY: FAILED (the path is not readable on the remote branch)")
    raise SystemExit(1)
with open(local_path, "r", encoding="utf-8", errors="replace") as fh:
    local = fh.read()
if remote != local:
    print("DELIVERY: FAILED (the remote blob differs from the local file)")
    raise SystemExit(1)
print("DELIVERY: ok (connector write verified byte for byte)")
PY
RC=$?
rm -rf "$TMPD"
exit $RC

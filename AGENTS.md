# AGENTS.md — working in `maxhermes-migration`

This repo is the **source of truth for the Cloud cron fleet**. Everything a routine needs at run
time is fetched from here, so a change here changes the next fire of that routine.

```
cloud-prompts/cron-prompts/    one file per routine = the DEPLOYED prompt, byte for byte
cloud-prompts/skills/          one skill spec per routine = the PROCEDURE, fetched at run time
cloud-prompts/_shared/         the fleet-wide blocks every routine downloads
cloud-prompts/_shared/PROMPT-BLOCKS.md      the rules that are identical across the fleet
cloud-prompts/_shared/RUNTIME-CONTRACT.md   the measured state of every data source
docs/                          one file per review: IMPROVEMENTS- / CROSSCHECK- / BUGREPORT-
tools/                         the deterministic helpers (see below)
```

## 1. Where a finding goes

**The repo, not agent memory.** Agent memory is the hot layer — a short list of rules that apply
to *every* future session. A routine-scoped finding does not belong there: it buries the
cross-session rules and it goes stale the moment the routine changes. A dated
`### Untitled (YYYY-MM-DD)` memory section is the classic symptom.

| What you found | Where it goes |
|---|---|
| A data quirk, a trap, a corrected procedure | `docs/IMPROVEMENTS-cronNN-<routine>.md` |
| A change to how a routine works | that routine's `cloud-prompts/skills/<name>/SKILL.md` |
| A fleet-wide rule | `cloud-prompts/_shared/PROMPT-BLOCKS.md` or `RUNTIME-CONTRACT.md` |
| A defect in a prompt or shared script | the file itself, plus a line in the matching doc |

The full rule, as the routines themselves see it, is in
`cloud-prompts/_shared/PROMPT-BLOCKS.md` → **WHERE A FINDING GOES**. It is fetched at run time, so
a routine that finds something knows where to put it without being told.

## 2. A change to a SKILL needs no deploy; a change to a PROMPT does

- **Skill spec or `_shared/` file** → push and stop. The routine downloads it at run time, so the
  next fire uses it. No `cron_update`, no byte-drift risk. This is the cheapest and safest edit
  path, and it is where procedure changes belong.
- **Prompt file** → the file IS the deployed prompt. Push it, then redeploy it
  (`tools/deploy_prompts.py`), then **verify by SHA-256**. A repo prompt that is not redeployed
  makes cron #91's drift guard report PROMPT-DRIFT every day.

**The repo file is canonical.** When the platform and the repo disagree, find out which one is
right before you "fix" anything — see `docs/IMPROVEMENTS-cronNN-*.md` for the cases where the
platform was the one that was wrong.

## 3. Fetch a repo file with the ladder, never with `[ -s file ] ||`

The old idiom

```bash
for U in "$B/file.md" "https://cdn.jsdelivr.net/.../file.md"; do
  [ -s /workspace/file.md ] || curl -sL -o /workspace/file.md "$U"
done
```

is **dead**: the first successful download satisfies the guard, so the second URL is never
reached, and a file already on disk is never refreshed. Measured 2026-11-04: `raw.githubusercontent`
served a stale blob for >17 minutes after a push while the GitHub **contents API** was fresh.

Use the canonical ladder (already in every rewritten block, and enforced by
`tools/adopt_fetch_ladder.py`):

1. **contents API first** — it is the only source that is not CDN-cached;
2. fetch to `"$D.tmp"`, never straight onto the target;
3. reject on the **BODY** (`"message"` = a GitHub error JSON), not on the byte count;
4. `mv` into place and `break`, so the next URL is only tried when this one really failed;
5. **say so loudly** when the file is still missing.

```bash
D=/workspace/file.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/file.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/file.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/file.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "file.sh fetch FAILED - <what to do instead>"
```

A run-time-fetched **helper is only live if some fetch block downloads it** — a reference is not a
delivery mechanism. Adding a file under `_shared/` that a procedure invokes by path means the
fetch block that puts it on disk is part of the change.

## 4. The tools

| Tool | What it does |
|---|---|
| `tools/deploy_prompts.py` | emits the EXACT bytes for a `cron_update`, then verifies the read-back by SHA-256 and re-checks every other field |
| `tools/adopt_fetch_ladder.py` | rewrites every dead `[ -s file ] || curl` fetch into the canonical ladder (`--check` / `--apply`, idempotent) |
| `tools/adopt_window_check.py` | rewrites every prompt's inlined window check to call the one shared `window_check.sh` |
| `tools/prompt_bytes.py` | dump/diff a prompt's exact bytes (wrap-safe) |
| `tools/rewrite_prompts.py`, `tools/apply_skip_marker.py` | other deterministic fleet-wide rewrites |
| `tools/gen_roster.py`, `tools/gen_index.py`, `tools/gen_docs_index.py` | regenerate the roster, the README index and the docs index |
| `tools/schedule-drift.py` | compares every live schedule against `tools/schedule-ground-truth.json` (the ground truth is rebuilt from `migration-state.json`, never from the live scheduler) |
| `tools/check_bonde_artifact.py`, `tools/check_premarket_artifact.py`, `tools/check_breadth_artifact.py` | assert the artifact CONTRACT of cron #04 / #08 / #10 — the section skeleton, the required fields, the published verdict vocabulary and the CSV's agreement with the markdown. Each has a regression test next to it (`tools/test_premarket_contract.py`, `tools/test_breadth_contract.py`) that proves the contract is satisfiable AND that every breach is caught |

Run the generators after you change what they generate, and **never hand-edit their output**.

## 5. Deploying a prompt, without drift

```bash
python3 tools/deploy_prompts.py --emit <NN>     # exact bytes + the task_id/schedule
# cron_update with task_id + schedule + timezone + prompt
python3 tools/deploy_prompts.py --verify        # hash deployed vs repo
```

Always resend `schedule` **and** `timezone` — a `cron_update` that omits `timezone` resets it to
`Etc/GMT-7` (UTC+7), and this has happened on a prompt-only update. Never send `enabled` (it is
coerced to the string `"true"`), and never send `model` (`cron_update` has no such field).

**A length check is not a byte check.** Only SHA-256 over the raw bytes is proof, and a line-level
diff hides a same-length substitution.

## 6. Conventions

- `docs/IMPROVEMENTS-cronNN-<routine>.md` — a review of one routine and what changed.
- `docs/CROSSCHECK-<topic>.md` — two routines checked against each other.
- `docs/BUGREPORT-<topic>.md` — a defect found outside the routine-review flow.
- `docs/README.md` holds the index; regenerate it with `python3 tools/gen_docs_index.py`.
- Every doc records the **EVIDENCE** for the change, so the next person can check the finding
  rather than take it on trust.

## 7. Safety

- Work on a branch. The fleet commits to `main` concurrently — re-check `origin/main` before and
  after, and merge, never force-push.
- **Never `git reset --hard origin/main`** in a checkout that holds your own edit: the reset
  wipes it. Hold the edited file outside the repo and copy it into a fresh worktree.
- Never `git add -A` — it has staged 283 deletions. Scope the add to your own path.
- Verify a push against the **GitHub contents API with `?ref=main`**, never against `raw` (it is
  CDN-cached and serves stale bytes) and never against a fresh clone (it checks out `master`).

# Improvements — 2026-11-04: the dead fetch fallback, and where a finding goes

**Date:** 2026-11-04 · **Scope:** the fleet's fetch idiom and the routing of routine findings
**Repo:** `karizaco/maxhermes-migration` · **Branch:** `chore/fetch-ladder-and-memory-routing-2026-11-04`

---

## 1. The defect: a fallback that could never be reached

The fleet-wide fetch idiom was:

```bash
for U in "$B/file.md" "https://cdn.jsdelivr.net/gh/.../file.md"; do
  [ -s /workspace/file.md ] || curl -sL -o /workspace/file.md "$U"
done
```

`[ -s file ] ||` is satisfied by the **first** successful download, so the second URL was dead
code. The loop looked like it had a fallback; it did not. Two consequences:

1. **the fallback was never reached** — a routine could only ever use the first URL; and
2. **the file was never refreshed** — if it was already on disk, no URL was fetched at all, so a
   stale helper survived for the rest of the sandbox's life.

### The evidence (2026-11-04)

After a push, `raw.githubusercontent.com` served the **stale** blob for **>17 minutes** while
`cdn.jsdelivr.net` served the fresh one, and the GitHub **contents API** — which is not
CDN-cached — was fresh immediately. The prompt's own fetch loop was run against that state and
pulled the old file: the failure was reproduced, not inferred.

Measured on the same day, across the three mirrors: **API/connector 1 s · raw 284 s · jsDelivr
15 h+**. The mirrors cache `main` independently, so "the CDN I used was fresh" says nothing about
the next one.

### Scope

| Where | Count | Consequence |
|---|---|---|
| `cloud-prompts/cron-prompts/*.md` — the `push_artifact.sh` fetch in the GIT PUSH block | 22 prompts | the push helper could be stale or missing |
| `cloud-prompts/_shared/PROMPT-BLOCKS.md` — its own self-fetch | 1 | the fleet-wide rules could be stale |
| `cloud-prompts/_shared/PROMPT-BLOCKS.md` — `probe_mcp.py`, `mcp_bridge.py`, `rvol_fetch.py` | 3 | the bridge and the volume helper could be stale |
| `cloud-prompts/_shared/preopen-capture.md` — `push_artifact.sh` | 1 | cron #92a/#92b could push with a stale helper |
| `cloud-prompts/skills/us-stocks-in-play/SKILL.md` — `rvol_fetch.py` | 1 | cron #17 could fall back to 245 per-symbol calls |

**20 of the 22 prompts download `PROMPT-BLOCKS.md` in step 1, before their own GIT PUSH block.**
So a canonical fetch inside the shared block installs a fresh helper first, and each prompt's own
copy of the old idiom is then never reached. Only **#26b** and **#90** have no such path — they
do not download `PROMPT-BLOCKS.md` — so they were fixed in their own prompt files and redeployed.

> The README claims the shared block is "downloaded at run time by **every** routine". That is
> false for five: `#01`, `#26b`, `#90`, `#92a`, `#92b`. Corrected in `cron-prompts/README.md`.

## 2. The fix

One canonical ladder, now used by every fetch block:

1. the **GitHub contents API first** — the only source that is not CDN-cached;
2. fetch to `"$D.tmp"`, never straight onto the target;
3. reject on the **BODY** (`"message"` = a GitHub error JSON), not on the byte count — a 403 body
   is non-empty JSON;
4. `mv` into place and `break`, so the next URL is tried only when this one really failed;
5. **say so loudly** when the file is still missing.

`mv` is safe here because the temp file lives in the target's own directory (`mv` across
`/tmp` → `/workspace` fails with EXDEV — the workspace is a NAS mount).

### The tool

`tools/adopt_fetch_ladder.py` applies it fleet-wide. It is deterministic, idempotent
(`--check` after `--apply` reports 0 changes), and it matches any `for U in … done` loop whose
body guards on `[ -s <file> ] || curl`, whatever shape that loop has.

```bash
python3 tools/adopt_fetch_ladder.py --check            # report only
python3 tools/adopt_fetch_ladder.py --apply            # the default target set
python3 tools/adopt_fetch_ladder.py --check --targets all
```

**Blast radius is split on purpose.** Shared files are downloaded by the routines at run time, so
a fix lands on the next fire of every routine that uses them — no prompt redeploy, no byte-drift
risk. Prompt files *are* the deployed prompt: editing one without redeploying it makes cron #91's
drift guard report PROMPT-DRIFT every day. So the default target set is only the two routines
that have no other fetch path (`#26b`, `#90`), and **a fleet-wide rollout must deploy every
prompt it touches in the same session** (`--targets all`).

### Verification

- `bash -n` on every rewritten block, compared against the same block at `HEAD`: **0 regressions**.
- Live fetch: the ladder pulled `push_artifact.sh` from the contents API and the SHA-256 matched
  the repo blob exactly (`22a364823e586d11b…`).
- **Refresh:** a deliberately corrupted copy was replaced by the fresh one on the next run — the
  old idiom would have kept the stale file.
- **Failure:** with every URL 404, the ladder printed `file.sh fetch FAILED …`, wrote no file and
  left no `.tmp` behind.

## 3. Where a finding goes (the routing rule)

A routine's findings were being written into **agent memory**, which is the hot layer — a short
list of rules that apply to every future session. A routine-scoped finding does not belong there:
it buries the cross-session rules and it goes stale the moment the routine changes. The visible
symptom was a run of `### Untitled (YYYY-MM-DD)` headings — each one a new heading that nothing
ever merged or retired.

The rule is now written where the routines will actually see it:

- `cloud-prompts/_shared/PROMPT-BLOCKS.md` → **WHERE A FINDING GOES** (fetched at run time by 20
  of the routines);
- `AGENTS.md` at the repo root → the same rule for anyone working in the repo.

| What you found | Where it goes |
|---|---|
| A data quirk, a trap, a corrected procedure | `docs/IMPROVEMENTS-cronNN-<routine>.md` |
| A change to how a routine works | that routine's `cloud-prompts/skills/<name>/SKILL.md` (no redeploy) |
| A fleet-wide rule | `cloud-prompts/_shared/PROMPT-BLOCKS.md` or `RUNTIME-CONTRACT.md` |
| A defect in a prompt or shared script | the file itself, plus a line in the matching doc |

## 4. Also in this change

- **`skills/memory-cleanup/SKILL.md`** — the cleanup procedure itself, which until now existed
  only in one session's head: the size targets, the classification rules, the heading-anchor
  deletion trick, the byte-exact edit traps, the 10-topic and 30 KB caps, the concurrent-writer
  hazard, and the two-call summary write.
- **`cron-prompts/README.md`** — the false "every routine downloads the shared block" claim.

## 5. Not done, and why

- The other **20 prompts** still carry the old idiom in their own GIT PUSH block. It is
  **unreachable** for them (the shared block installs a fresh helper first) and
  `tools/adopt_fetch_ladder.py --targets all` will rewrite them — but that rewrite must be
  **deployed in the same session**, or cron #91 reports drift on 20 routines every day. It is a
  deliberate, separately deployable step, not an oversight.

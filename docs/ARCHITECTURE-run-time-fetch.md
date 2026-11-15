# ARCHITECTURE — the run-time fetch, and why the fleet is built this way

**Date:** 2026-11-15 · **Scope:** the whole fleet — how a routine's code reaches it at fire
time, where that code lives, how it is versioned, and who consumes it.

This is the one thing about the fleet that is not obvious from any single routine, so it is
written down once here rather than re-explained in every prompt.

---

## 1. The shape, in one paragraph

The scheduler stores a **prompt** and nothing else. The prompt does not contain the procedure —
it contains *instructions to download the procedure*. At fire time the routine fetches its skill
spec and the fleet's shared blocks from `karizaco/maxhermes-migration`, runs the shared helpers,
and writes its artifact to `karizaco/minimax-cloud-outputs`. **A change to the procedure is a
push to that repo and nothing else** — no redeploy, no re-paste, no scheduler call. A change to
the *prompt text* does need a deploy, because the prompt is the only thing the scheduler holds.

That asymmetry is the whole design, and everything below is the detail.

---

## 2. The two repos

| Repo | Holds | Written by | Read by |
|---|---|---|---|
| **`karizaco/maxhermes-migration`** | the *procedure*: 30 shared blocks (`cloud-prompts/_shared/`), 14 skill specs (`cloud-prompts/skills/`), 28 prompt files (`cloud-prompts/cron-prompts/`), 80 deterministic tools (`tools/`), the review record (`docs/`) | you, me, any agent fixing something | every fire of every routine |
| **`karizaco/minimax-cloud-outputs`** | the *artifacts*: `daily-screens/`, `us-stocks-in-play/`, `earnings/`, `daily-briefs/`, `options-flow/`, … | the fleet's pushes | the fleet reads its own artifacts back; you read them |

The first repo is the source of truth for *how*; the second is the record of *what happened*.

---

## 3. The three layers of one routine

```
the scheduler ──stores──► cloud-prompts/cron-prompts/<routine>.md      (the DEPLOYED prompt)
                                 │  fetches at run time
                                 ▼
        cloud-prompts/skills/<routine>/SKILL.md   (the PROCEDURE for that routine)
        cloud-prompts/_shared/*                   (the fleet-wide blocks every routine uses)
                                 │  fetches + runs at run time
                                 ▼
        tools/*  (engines, checkers, deploy harness)   (the deterministic parts)
                                 │
                                 ▼
        karizaco/minimax-cloud-outputs/…             (the artifact)
```

- **The prompt** is the small, stable thing the scheduler holds (28 files for 27 live routines). It carries the title rule, the
  window check, the fetch ladders, the output path, the push block and the reply format — and
  then delegates everything else.
- **The skill spec** is where the procedure lives. It is fetched in full at fire time, which is
  why a procedure change needs no deploy.
- **`_shared/`** holds the fleet-wide blocks every routine downloads: `window_check.sh`,
  `push_artifact.sh`, `verify_delivery.sh`, `mcp_bridge.py`, `tv_scan.py`, `quota_check.sh`,
  `nyse-holidays.txt`, and the two fleet-wide rulebooks (`PROMPT-BLOCKS.md`,
  `RUNTIME-CONTRACT.md`).
- **`tools/`** holds the deterministic parts — the scoring engines, the artifact checkers (each
  with a regression test beside it), the deploy harness and the drift guard.

---

## 4. What a run-time fetch actually is

Every prompt that needs a helper carries the same ladder:

```bash
D=/workspace/helper.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/helper.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/helper.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/helper.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && grep -q 'HELPER_V2' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "helper.sh fetch FAILED - <what to do instead>"
```

Four things in that block are load-bearing, and each of them exists because its absence caused a
real failure:

1. **The contents API is tried first.** It is the only source that is not CDN-cached. Measured
   2026-11-04: `raw.githubusercontent` served a stale blob for **>17 minutes** after a push while the
   contents API was already fresh.
2. **The body is rejected, not the byte count.** A GitHub 404 is a non-empty JSON error page; the
   guard is `grep -q '"message"'`, not `[ -s file ]`.
3. **A capability marker gates the copy.** `WINDOW_CHECK_V2`, `TV_SCAN_V2`, `FOCUS_RVOL_RUN_V1`,
   `FOCUS_RVOL_UNIVERSE_V1`, `RVOL_FETCH_V2`, `BRIEF26_PULL_V1`… The marker says *"this copy has
   the behaviour the prompt needs"*, so a stale CDN copy cannot win over a newer one. It is a
   minimum-version gate, not a version.
4. **`mv` into place and `break`.** The next URL is tried only when this one really failed.

**A run-time-fetched helper is only live if some fetch block downloads it.** A reference is not a
delivery mechanism: adding a file under `_shared/` that a procedure invokes by path means the
fetch block that puts it on disk is part of the change. (This is the rule in `AGENTS.md` §3, and
it is why the shared fetch ladders are enforced by `tools/adopt_fetch_ladder.py`.)

---

## 5. Versioning — three senses, and they are not the same thing

| Sense | How it is versioned | Consequence |
|---|---|---|
| **Source** | git, `main`, one commit per change | reviewable, `git log` is the history. The fleet commits to `main` **concurrently** — re-check `origin/main` before and after, merge, never force-push. |
| **Contract** | a capability marker string in the file | coarse ("has the behaviour"), no semver, no changelog requirement. A helper whose behaviour changes MUST bump its marker, or a stale copy can be mistaken for a current one. |
| **Resolution** | **deliberately unpinned** — the ladder fetches `?ref=main` | a fix lands and the *next* fire uses it. Nothing is pinned to a SHA. |

**Unpinned is the feature and the risk.** The benefit: a procedure fix reaches every fire of
that routine without anyone pasting anything. The costs, stated plainly:

- **A bad push reaches every routine that fetches that file**, immediately, with no gate between
  the commit and the next fire. This is why the shared helpers carry markers and regression tests
  (`tools/test_*_contract.py`).
- **Two fires a day apart can legitimately disagree** — yesterday's artifact was produced by the
  previous copy of the helper. That is not a bug; it is the price of not redeploying. When a
  change alters published numbers, say so in the artifact.
- **Nothing detects a helper that changed but should not have.** The guard is the *spec* drift
  check (cron #91: the spec the deployed prompt fetches vs the repo's file), not a content check.

---

## 6. The two change paths

| You changed | What you do | Blast radius |
|---|---|---|
| a **skill spec**, a **`_shared/`** block, a **`tools/`** script | push, and **stop** | the next fire of that routine (or every routine, for `_shared/`) picks it up. No `cron_update`, no byte-drift risk. **This is where procedure changes belong.** |
| a **prompt file** | push → `tools/deploy_prompts.py --emit <NN>` → `cron_update` → **verify by SHA-256** | the scheduler's stored copy changes; every later fire reads the new bytes |

The prompt path is the expensive one, and it is expensive because it is hand-carried text:

- `tools/deploy_prompts.py --emit` prints the **exact bytes** for the `cron_update` argument;
  `--verify` hashes what the scheduler holds against the repo.
- **Always resend `schedule` AND `timezone`** — a `cron_update` that omits `timezone` resets it
  to `Etc/GMT-7` (UTC+7). That has happened on a prompt-only update.
- **Never send `enabled`** (it is coerced to the string `"true"`) and **never send `model`**
  (`cron_update` has no such field).
- **A length check is not a byte check.** Measured 2026-11-13: a 51,745-byte prompt was deployed
  and came back **the exact right length with six dropped words and one line-wrap** — a diff
  that a length check passes and SHA-256 does not.

---

## 7. Who consumes this?

**Only this fleet — your own MiniMax Cloud crons.** **27 live routines** (25 producers plus the
#90 delivery auditor and the #91 drift guard), all owned by `Mavis`, all `America/New_York`, all
`MiniMax-M3.1-Flash`, all `session.mode=new`, firing between 06:30 and 22:30 ET plus the 04:05
drift guard.

The repo holds **28 prompt files** for those 27 routines: `92-preopen-catalyst-capture.md` is a
parent prompt with **no schedule of its own** — its live slots are #92a (08:30 ET) and #92b
(09:50 ET). The authoritative list of live routines is `tools/schedule-ground-truth.json`, which
is what the generated index and cron #91's drift guard both read.

- **The fleet consumes its own helpers and its own artifacts.** #26 prepends yesterday's
  `tier-a.md`; #07 reads #09's `focus.md` and #17's boards; #90 audits what landed; #91 guards
  the schedules. The helpers exist to serve these routines and nothing else.
- **There is no other consumer.** No CI, no `.github/`, no `package.json`, no `pyproject.toml` —
  the repo is documents and scripts, read over HTTPS by a scheduler. Nothing else in your setup
  imports them.
- **The local Windows Mavis tree is archived and explicitly dead.** `archive/README.md`: *"Frozen
  migration / archaeology. Not loaded by Cloud crons."* The same routines ran locally before the
  2026-09-25 migration; `cloud-prompts/` is the migrated live tree. The prompts still carry the
  note that the local Windows helpers do not exist in Cloud.

---

## 8. The failure modes, each with its measurement

| Failure | What actually happens | Where it is handled |
|---|---|---|
| **Stale CDN** | `raw` served a blob **>17 min** old after a push | contents API first in every ladder |
| **Dead fallback code** | the old `[ -s file ] || curl` idiom: the first success satisfies the guard, so the second URL is never tried, and a file already on disk is never refreshed | `tools/adopt_fetch_ladder.py` rewrites every occurrence |
| **Silent truncation** | a fetch returns a 404 JSON body with HTTP 200 | reject on the BODY (`"message"`), not the byte count |
| **Old copy wins** | a cached copy lacks the behaviour the prompt needs | capability marker in the guard |
| **A helper nobody downloads** | the procedure names a path that no fetch block populates | `AGENTS.md` §3: "a reference is not a delivery mechanism" |
| **A bad push hits everyone** | `_shared/` changes reach every routine at the next fire | markers + `tools/test_*_contract.py` beside each checker |
| **A paste that is right-length and wrong** | six dropped words in a 51,745-byte prompt | SHA-256 the read-back; `tools/verify_prompts.py` |
| **A prompt-only update resets the timezone** | `Etc/GMT-7` (UTC+7) — 11 h off, after the close | always resend `schedule` + `timezone` |
| **The repo and the platform disagree** | find out which is wrong before "fixing" either | the repo file is canonical |

---

## 9. The verification tooling map

| Tool | What it proves |
|---|---|
| `tools/deploy_prompts.py --emit <NN>` | the exact bytes for a `cron_update`, with the task_id and schedule |
| `tools/verify_prompts.py --list <cron-list.json>` | every deployed prompt is **byte-identical** to the repo (hashes the scheduler's own bytes) |
| `tools/schedule-drift.py` | every live schedule matches `tools/schedule-ground-truth.json`, and every routine's **fetched spec** matches the repo's file (the SPEC-DRIFT check a prompt hash can never do) |
| `tools/check_<routine>_artifact.py` | the artifact CONTRACT — skeleton, required fields, published vocabulary, md↔csv agreement |
| `tools/test_<routine>_contract.py` | the checker is satisfiable **and** that every breach is caught (a checker never observed failing is a claim) |
| `tools/adopt_fetch_ladder.py`, `tools/adopt_window_check.py` | deterministic fleet-wide rewrites; idempotent (`--check` / `--apply`) |
| `tools/prompt_bytes.py` | dump/diff a prompt's exact bytes, wrap-safe |

After changing what a generator produces, **run the generator** — `gen_index.py`,
`gen_roster.py`, `gen_docs_index.py` — and never hand-edit their output.

---

## 10. A worked example (2026-11-12 → 2026-11-13, cron #07)

One change, both paths, and the difference between them made concrete:

1. A review found the scoring engine publishing three **wrong columns** (`rvol_intraday_live`
   mis-scaled, `rvol_prev` hardcoded `n/a`, `rvol_trend` measured against the wrong window).
   The fix went into `tools/focus_rvol_score.py` and `tools/check_focus_rvol_artifact.py`
   (three new clauses, with a fault-injection shape in the repo's own test). **Push and stop** —
   the next fire picked it up with no scheduler call.
2. The same review changed the prompt's *descriptive* text (the front-matter key list, the
   pre-market vocabulary, the near-miss ordering rule). That file **is** the deployed prompt, so
   it needed a deploy: emit → `cron_update` → SHA-256 the read-back.
3. The first deploy came back **51,745 bytes — the exact right length, with six dropped words
   and one line-wrap**. The read-back verifier caught it, the line diff named the six lines, and
   the second deploy verified byte-identical (`sha256 61dc2ccc…`, 18/18 routines MATCH).
4. While doing that, the harness's `--verify` turned out to point at a `tools/verify_prompts.py`
   that **did not exist** — nothing could prove what had actually landed. It exists now.

The lesson worth keeping: **the cheap path is the one that keeps the procedure in files.** Every
hour spent hand-pasting a prompt is an hour that could have been spent changing a file.

---

## 11. Adding a new helper, safely

1. Put the file in `cloud-prompts/_shared/` (fleet-wide) or `cloud-prompts/skills/<routine>/`
   (one routine).
2. Give it a **capability marker** and bump it when the behaviour changes.
3. Add the **fetch block** to the prompt that needs it — a file nothing downloads is not shipped.
4. Use the canonical ladder (contents API → raw → jsDelivr), fetch to `.tmp`, reject on the body,
   `mv` + `break`, and say loudly when the file is still missing.
5. If it changes what is published, update the routine's **skill spec** (§7 of that routine) so
   the next fire describes it correctly — and the artifact's contract checker if there is one.
6. Push. **No deploy** — unless the prompt's own text has to change.
7. Record the finding in `docs/IMPROVEMENTS-cronNN-<routine>.md`, and regenerate the docs index.

---

## 12. Where this doc sits in the routing rules

`PROMPT-BLOCKS.md` → **WHERE A FINDING GOES** is the rule the routines themselves read (it is
fetched at run time). It sends a *finding* to `docs/`, a *procedure change* to the routine's
skill spec, a *fleet-wide rule* to `_shared/`, and a *defect* to the file itself. This document
is the **architecture reference** the humans read; it is not a substitute for any of those.

Related: `AGENTS.md` (the working rules for this repo), `cloud-prompts/cron-prompts/README.md`
(the live routine index), `docs/README.md` (the review record).

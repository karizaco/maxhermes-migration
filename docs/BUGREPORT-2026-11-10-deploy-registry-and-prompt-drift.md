# Bug report — the deploy registry carried a stale schedule, and #08's deployed prompt was 5 bytes off the repo

**Found by:** cron #91 (schedule-drift-guard), daily 04:05 ET check of 2026-11-10.
**Severity:** Medium for the registry row (silent, and one `--emit` away from a bad deploy);
**Low** for the prompt delta (cosmetic — one word inside a `#` comment — but it makes the
guard report PROMPT-DRIFT every single day).

Both defects were found by the guard's own checks, and neither was visible from the live
scheduler: every routine's schedule was correct, the roster balanced at 26/26, and no spec
had drifted. Both defects lived in the REPO — in the tools the fleet uses to deploy and to
prove the deployment — and the repo is not what the schedule check reads.

---

## Defect 1 — `tools/deploy_prompts.py` still carried #08's OLD schedule

### What

`tools/deploy_prompts.py`'s `TASKS` map is the registry the deploy harness emits from: each
row is `(task_id, schedule)`, and `--emit NN` hands the deployer both. The row for
`08-stock-screener-pre-market-gapper.md` still read:

```python
"08-stock-screener-pre-market-gapper.md":   ("457578163015913", "30 8 * * 1-5"),
```

### Why that is a landmine, not a cosmetic typo

On 2026-11-09 (#08's `e881634`, "move the 08:30 slot to 08:34") #08 was moved OFF the
08:30 slot to `34 8 * * 1-5`, because at 08:30 three routines fire in the same minute
(#26, #08, #92a), each carrying a ~300–520k-token context — and that collision exhausted
the Token Plan 5-hour window and cost the fleet its whole morning. That commit updated the
ground truth, the #08 prompt and the auditor's roster table. **`deploy_prompts.py` was not
updated.**

So the deploy harness would have handed the next deployer of #08 a schedule that puts it
back on the 08:30 slot with #26 and #92a. A stale row is worse than a missing row: a
missing row makes `--emit` refuse the routine (a visible failure), while a stale row
produces a *successful-looking* deploy that silently re-creates the collision.

### Measured

Live scheduler vs the map, all 26 rows, checked by hand on 2026-11-10 (only #08 differed):

```
08-stock-screener-pre-market-gapper.md   map=30 8 * * 1-5   live=34 8 * * 1-5   <-- STALE
```

Every other row agreed with the live scheduler byte-for-byte.

### Fix

The row now carries the ground truth's schedule, `34 8 * * 1-5`, with the reason recorded
in a comment beside it so the next reader knows the row is not a duplicate of #26's.

**Plus a gate, because a fix with no gate is a wish.** `tools/test_schedule_drift_contract.py`
gained a check asserting that every `deploy_prompts.py` schedule agrees with
`tools/schedule-ground-truth.json`. The test was observed RED with the stale row restored
(fault injection) before the fix was accepted — a checker never observed failing is a
claim, not a guard.

---

## Defect 2 — #08's deployed prompt was 5 bytes off the repo

### What

The repo file `cloud-prompts/cron-prompts/08-stock-screener-pre-market-gapper.md` and the
prompt actually deployed on the scheduler differed by exactly one word, inside a comment:

```
repo:      # market. The CDNs also cache independently, so one of them can serve stale bytes for
deployed:  # market. The CDNs cache independently, so one of them can serve stale bytes for
```

13401 B (repo) vs 13396 B (deployed); SHA-256 `e6b586ac…` vs `fb7d8394…`.

### Which side is wrong — and why the REPO is right (this took a fault injection to settle)

The naive reading is "the platform dropped 5 bytes, so sync the repo down to it". **That is
wrong**, and syncing down would have made the fleet permanently unstable. Four pieces of
evidence, in increasing order of strength:

1. **The deployed copy matches NO blob in the repo's entire history.** All 35 distinct
   historical blobs of that file were enumerated across every ref; none is `fb7d8394…`. It
   is not a state anyone committed — it is a paste artifact.

2. **The repo's copy is what the platform itself carried a day earlier.** Commit `6cd8d74`
   ("cron #08: sync the deployed prompt's three tokens, and write down what a 13 KB paste
   costs") reconciled the repo to the platform's bytes and recorded their hash explicitly:
   *"The repo now carries the platform's bytes (sha256 e6b586ac…), so cron #91's drift guard
   sees nothing."* `e6b586ac…` is the repo's current hash. So on 2026-11-09 the platform
   carried exactly the repo's bytes — with "also" — and the platform copy changed
   afterwards.

3. **The generator that owns that comment block emits "also".** `tools/adopt_window_check.py`
   is the tool that owns the inlined window-check block, and its template (line 80) reads
   `# market. The CDNs also cache independently, …`. 19 of the 21 fleet prompts say "also";
   only #15 says otherwise.

4. **Fault injection proved the direction is one-way.** Syncing the repo DOWN to the
   platform's bytes (deleting "also " from the repo file) and then running the generator
   (`adopt_window_check.py --apply`) puts "also " straight back — the word reappears
   immediately. Syncing down therefore does not converge: the generator and the platform
   would fight over one word forever, re-creating the drift the next time anyone ran the
   generator.

So the platform's copy is the damaged one — a paste that dropped a word from a comment —
and the repo is canonical. The fleet's own rule for this case is already written down:
*"When the repo is correct, re-paste the platform — do not 'fix' the repo to match a
corrupted platform."*

### Fix

Deploy the repo file to the scheduler byte-exactly and verify by SHA-256 against the repo
blob (AGENTS.md §5). The behavioral impact is nil either way — "also" is prose in a `#`
comment inside the fetch ladder — but until the two agree, cron #91 reports PROMPT-DRIFT
for #08 every day, and a guard that cries wolf daily is a guard that gets ignored.

---

## What was NOT changed, and why

- **No schedule was repaired.** Every one of the 26 live schedules was already correct
  (`drift: 0`, roster 26/26). Nothing about a schedule needed repairing, so no `cron_update`
  wrote a schedule.
- **#07's conversation reuse was NOT "repaired".** Session `446509091221813` appears on 9 of
  #07's runs from 2026-10-15 to 2026-10-25, i.e. ~2 weeks of a fixed-conversation binding
  from before the fleet-wide sessionId→new migration. Its recent fires each got a fresh
  session and its live binding is `new` today, so the detector labels it
  `CONV-REUSE HISTORICAL` — history, not a live fault. A fixed-conversation binding can
  also be deliberate, so it is reported, never repaired.
- **The two one-off audit tasks** (`audit-cron17-…`, `audit-cron26-…`) have an empty
  schedule and no repo file. They are one-shot reminders, not recurring routines; the
  ground truth correctly does not carry them, so the roster check is not affected.
- **`cloud-prompts/cron-prompts/roster.json` / `ROSTER.md` were left alone.** They are dated
  snapshots (`as_of_et: 2026-11-06`) of live state and carry the artifact-presence columns;
  they are regenerated wholesale by `tools/gen_roster.py` and are not a registry the
  detector reads. The registry of record for a schedule is `tools/schedule-ground-truth.json`.

# IMPROVEMENTS — 2026-11-12 — the push helper lost the routine NAME, and the connector fallback writes to PRODUCTION

Two defects in `cloud-prompts/_shared/push_artifact.sh`, both found by the cron #04 fire on
2026-11-12. **The helper is fetched at RUN time, so both fixes land fleet-wide with NO
`cron_update` and NO prompt drift.**

---

## 1. Passing `--nn` silently dropped the routine NAME from the commit subject

`push_artifact.sh` derives the commit subject from a table of artifact-path patterns:

```
daily-screens/*/reversal-bullish-3_55.md) NN=04; NM=reversal-bullish-3_55 ;;
```

Before 2026-11-12 the whole table sat inside `if [ -z "$NN" ]; then`, so a caller that passed
`--nn` explicitly skipped the table **entirely**: `NN` was set from the flag, `NM` stayed empty,
and the subject fell back to the generic output directory:

```
cron 04 daily-screens 2026-11-12        <- what --nn 04 produced
cron 04 reversal-bullish-3_55 2026-11-12 <- what the table produces (yesterday's push)
```

The **number** survived, so cron #90's triage (`grep 'cron (#)?NN '`) still attributed the push —
nothing was reported MISSING. But the routine NAME was lost for every routine that passes
`--nn`, and the name is what makes a commit scannable by a human.

**Landed:** the table now runs on EVERY push. `NN` is taken from the table only when the caller
did not supply it; `NM` is taken from the table whenever the table recognises the path. The
table rows write to `_NN`/`_NM` and the assignment happens once, after the match.

**Verified** by rehearsal against a local bare repo (both with and without `--nn 04`):

```
cron 04 reversal-bullish-3_55 2026-11-12
```

### A second gap in the same table (NOT changed here)

Several table patterns are basename-shaped (`daily-briefs/*-pre-market-refresh.md`) while the
live layout is dated (`daily-briefs/<DATE>/<file>.md`), so those rows never match and the
routine name still falls back to the output directory. Cron #26b's push today reads
`cron 26b daily-briefs 2026-11-12` for exactly this reason. The NUMBER is correct and cron #90's
attribution is intact, so this is cosmetic — but it is a table-wide gap, not a one-routine one.
**Left for the fleet rather than fixed inside cron #04's scope:** every routine's path shape has
to be enumerated before the table can be trusted, and a wrong row here mislabels a commit.

---

## 2. The connector fallback IGNORES `REMOTE_URL` — a rehearsal wrote to PRODUCTION

`push_artifact.sh`'s git path honours `REMOTE_URL` (and `REPO_DIR`), so a push can be rehearsed
against a local bare repo. The **connector fallback does not**: it talks to the GitHub API and
always writes to the production outputs repo.

Rehearsing the helper against a local remote on 2026-11-12 therefore wrote the rehearsal's
placeholder file over the live artifact:

```
34f9113 cron 04 reversal-bullish-3_55 2026-11-12
 daily-screens/2026-11-12/reversal-bullish-3_55.md | 75 +----------------------
 1 file changed, 1 insertion(+), 74 deletions(-)
```

The artifact was restored on the next push (the tip now carries the correct bytes, verified with
the **git blob API**, not the CDN-cached contents API), but the production branch briefly carried
a placeholder. The real lesson is not the mistake — it is that the helper had **no guard** against
it.

**Landed:** `connector_fallback()` now refuses to run unless `REMOTE_URL` is the production
outputs repo:

```
case "${REMOTE_URL:-}" in
  *github.com/karizaco/minimax-cloud-outputs.git) : ;;
  *) echo "push: connector fallback SKIPPED (REMOTE_URL is not the production outputs repo ..."
     return 1 ;;
esac
```

**Verified** by rehearsal: the git path succeeded against the local bare repo and the connector
was skipped; the production artifact blob was byte-identical before and after.

---

## THE RULE FOR EVERY FUTURE SESSION

> **Never rehearse `push_artifact.sh` against a non-production remote without understanding the
> connector fallback.** The git path is redirectable; the connector is not. As of 2026-11-12 the
> helper refuses the connector when `REMOTE_URL` is not the production repo — but a rehearsal that
> DOES reach production is a production write, and a push-script test is not a read-only action.

Corollary: **verify a delivery with the GIT BLOB API** (`GET /git/blobs/<sha>`), never the
contents API alone — the contents API is CDN-cached, so a stale blob looks exactly like a commit
that never happened.

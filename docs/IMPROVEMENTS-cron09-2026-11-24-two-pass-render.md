# IMPROVEMENTS-cron09-2026-11-24 — the second pass re-spent the fleet's metered bridge allowance

**Date:** 2026-11-24
**Routine:** cron #09 `stock-screener-daily-sweep-18:30` (the end-of-day sweep)
**Fire:** 2026-11-24 18:30 ET (dispatched 18:30:03 ET, `stall_min: 0` — not stalled, window check OK, `fire-date: 2026-11-24`)
**Artifacts:** `daily-screens/2026-11-24/daily-sweep.md` + `breadth.md` + `_regime.json` in `karizaco/minimax-cloud-outputs@main`
**Found by:** the 2026-11-24 fire itself, while working out how to render the narrative without a second fetch.

---

## Finding 1 — `run --live-json` re-runs every fetch, and the bridge is metered

**The skill's own run order (§4.5.5) is two `cmd_run` invocations:**

```bash
python3 "$P" run --date <CRON_DATE> --out ... --scratch ... --bridge ...   # 1. fetch
# the Agent writes scratch/live.json
python3 "$P" run --date <CRON_DATE> --live-json ...                         # 2. render the narrative
```

Step 2 is a **full `cmd_run`**: it re-resolves the T+1 session, re-pulls the
fresh book, re-runs the eight shibui branches, re-pulls the CANSLIM growth
half, re-runs the enrichment pass, re-runs the valuation overlay and re-pulls
the breadth read. The narrative is the only thing that changed between the two
calls.

**Why that is expensive.** The bridge is metered: **50 tool calls/day per
egress IP, shared across the whole fleet** (`PROMPT-BLOCKS.md`, "THE BRIDGE IS
METERED"). One call costs one unit regardless of how many symbols it returns,
so the cost is in the CALLS: 8 branch queries + 1 CANSLIM + ~10 enrichment
chunks (200 symbols each) + ~6 overlay chunks (1,188 symbols) + the breadth
pass ≈ **~27 metered calls** for one sweep. A literal two-step run spends
that twice: ~54 units for a single routine, from an allowance the WHOLE fleet
shares.

**Why it is dangerous rather than merely wasteful.** The second run usually
**succeeds**, and the artifact looks perfect — every number is right, the
checker passes, the delivery verification passes. Nothing in the run record
shows the double spend. It is a silent tax on every future fire, and it gets
worse as the fleet grows: the first routine to hit the cap takes the
`429`/quota stall and dies, and the failure is attributed to the wrong fire.

**The pipeline already has the right flags.** `cmd_run` accepts
`--fresh-json`, `--breadth-json`, `--enrichment-json`, `--branches-json`,
`--canslim-json` and `--overlay-json` precisely so a second pass can replay
the first pass's data. **But nothing on the first pass saves those stage
outputs to disk**, so the flags have nothing to point at and the two-step
order can only be run the expensive way.

### The fix — `tools/sweep_two_pass.py` (marker `SWEEP_TWO_PASS_V1`)

A driver that imports `tools/sweep_pipeline.py` and patches the four collector
functions **in memory** (the pipeline file on disk is never modified):

| phase | what it does | metered bridge calls |
|---|---|---|
| `--phase 1` | fetches everything and PERSISTS each collector's result under `<scratch>/pass1/` | ~27 (the fetch happens **here, once**) |
| `--phase 2` | replays those persisted results and renders the Agent's narrative on top | **1** — only the `market-recap get_quotes` batch for the book names |

The fresh book and the overlay are the pipeline's own persisted files
(`scratch/tv_sweep.json`, `scratch/overlay.json`), replayed through the
pipeline's own `--fresh-json` / `--overlay-json` flags. The four stages the
pipeline does NOT persist are replayed from `<scratch>/pass1/`.

**One trap in the naive replay path.** `cmd_run`'s own replay branch rebuilds
`screen_coverage` from the saved rows — and it hardcodes `"pages": 1`, which
loses the real page count and the real `consistent` flag. The driver replays
the REAL `coverage` dict captured in pass 1, so the published coverage table
is byte-identical to the one-pass run.

**Measured on the 2026-11-24 fire.** Pass 1 logged the full fetch (fresh book
3,725 names; 8 shibui branches, `rows_kept == rows_passing` on all nine
branches; enrichment; overlay 1,188 symbols; breadth) and ended with the
expected four stub failures (`daily-sweep.md` / `breadth.md` still carried
`<!-- FILL: … -->` markers — the narrative did not exist yet). Pass 2 replayed
the same data with the narrative in place: the log showed **no** fetch stage
at all, only the book-quote batch, and the pipeline's own check returned
**OK**. The published numbers are identical to what a single run produces —
1,378 candidates, 12 Focus, 8 Tier-A, the same coverage table.

Phase 1 exits **1** by design (the checker rejects the stub). Phase 2 must
exit **0**, and the artifact must be free of stub markers — that is the
assertion, and the pipeline's own `check` stage is the gate.

### What changed in the repo

- **NEW** `tools/sweep_two_pass.py` (marker `SWEEP_TWO_PASS_V1`) — the two-pass driver.
- **SKILL** `cloud-prompts/skills/stock-screener-suite/SKILL.md` — new §4.5.5b
  "The second pass MUST NOT re-fetch", with the fetch ladder for the driver
  and the phase-1-exits-1 explanation. The skill is fetched at RUN time, so
  this lands on the next fire with no `cron_update` and no prompt drift.

---

## Note (not a defect) — the Cboe delayed-quote CDN is still blocked from this egress

The 2026-11-19 fix gave the volatility pair a Yahoo chart-API fallback
(`^VIX` / `^VIX3M`, both symbols from the same session bar). It fired again on
2026-11-24: the Cboe CDN answered **HTTP 403** and the pair was published
from the Yahoo fallback, quoted at **16:15:01 ET**. One pair, used everywhere
in the document; `degraded_sources: 1`; the reply's `errors: 1`.

The fallback is now a **routine path, not an incident** — it is disclosed in
`breadth.md`'s `vix_quote_time` front-matter, in the volatility section and in
the source-health table. The Cboe primary has been unavailable from this
egress since 2026-11-19; if it is expected to work, the egress (not the code)
is the thing to fix.

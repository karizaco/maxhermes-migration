# IMPROVEMENTS — cron #04 (Bonde reversal-bullish) — 2026-11-20

## The finding

On 2026-11-20 the 15:55 ET fire produced **zero mechanical passers** (817 names scanned,
1 candle survivor, 0 through the history gates). On a zero-passer day the screen wrote a
Candidates section that was **not a table at all** — a single italic line:

```
## Candidates

_No name passed every gate today._
```

The contract's own gate, `tools/check_bonde_artifact.py`, asserts that the Candidates table
carries its columns (`bar_low`, `bar_high`, `stop_class`, `vol_vs_30d_avg_pct`, `capitulation`,
`body_low`, `stop_basis`) on **every** artifact. With no table there were no headers, so the
run failed 7 checks that had nothing to do with the screen:

```
FAIL the Candidates table is missing the 'bar_low' column
FAIL the Candidates table is missing the 'bar_high' column
FAIL the Candidates table is missing the 'stop_class' column
FAIL the Candidates table is missing the 'vol_vs_30d_avg_pct' column
FAIL the Candidates table is missing the 'capitulation' column
FAIL the Candidates table is missing the 'body_low' column
FAIL the Candidates table is missing the 'stop_basis' column
```

**This is the GATE-vs-SCREEN class of defect, and the gate was right.** The contract says the
Candidates section is a table with one row per name; the CSV — which the script always wrote
correctly — published its 56-column header with zero rows. The two files disagreed about the
shape of an empty result, and the markdown side could not satisfy the contract the CSV side
already satisfied. The fix is in the screen, not in a hand-edited artifact.

Note the shape of the trap: **the run that produces nothing is the run that cannot publish.**
Every prior fire of this routine had at least one passer, so the zero-candidate path had never
been exercised — and the defect was invisible until a quiet tape hit it.

## The fix (in `tools/reversal_bullish.py`)

`write_md()` now always renders the Candidates table and only THEN adds the explanatory note:

```python
    A("## Candidates")
    A("")
    for line in _md_candidates_table(results):
        A(line)
    if not results:
        A("")
        A("_No name passed every gate today._")
```

The header row is data-independent, so an empty run's Candidates section is byte-identical
whatever the tape did — and it mirrors the CSV, which already published its header with zero
rows. The gate passes on the empty artifact: 16/16 on the 2026-11-20 fire.

## Second fix in the same file: a source-health row with no status

The source-health table published

```
| market-recap (bridge) | market state / index backdrop | see caveats |
```

but `market_state()` is **never called** by the screen (`grep -n "market_state("
tools/reversal_bullish.py` → one hit, the definition). So the row named a source the run did
not use, and pointed at a caveat that was not there. `_shared/PROMPT-BLOCKS.md` rule 5 requires
a status per source: `ok` / `failed:<reason>` / — when a source was not used — say that. The row
now reads:

```
| market-recap (bridge) | market state / index backdrop | not used by this screen — the day-alignment proof is the TradingView + shibui pair |
```

The day-alignment proof (the scanner's implied previous close vs shibui's latest settled close)
never needed market-recap, so nothing that the artifact relies on changes.

## Verification

- 2026-11-20 artifact: `check_bonde_artifact.py` → **16/16 ok, exit 0** (it failed 8 before the fix).
- The published artifact and its CSV were byte-verified on `origin/main` through the **git blob
  API** (not the contents API, which is CDN-cached): md sha `49dbff8255`, csv sha `b690cffdf9`,
  both identical to the local bytes.
- The fix is in the SCREEN, so it lands with the next fire — no `cron_update`, no prompt edit.

## The general rule

**A gate that asserts a document's SHAPE must be satisfiable by the document's EMPTY case.**
The failure mode is asymmetric and hides in quiet runs: the artifact shape that only appears on a
day with nothing to say is the one that is never exercised, and the day it finally appears is
the day the routine cannot publish. When a section is allowed to be empty, the section's
**frame** must still be published — a table with its header and no rows, a list with its
"nothing here" line — exactly as the CSV twin already did.

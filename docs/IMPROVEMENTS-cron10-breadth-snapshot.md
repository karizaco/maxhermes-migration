# IMPROVEMENTS — cron #10 `stock-screener-breadth-snapshot`

## 2026-11-10 — the front-matter `cross_reference` shipped a literal `<date>` placeholder, and the checker never looked at the field

### Context — the 2026-11-10 14:00 ET fire

The run itself was clean: window check OK (`fire-date: 2026-11-10`, `replay: no`, `stall_min: 3`),
the reference helper `scripts/breadth_metrics.py` computed the settled layer in 6 bridge calls with
every paged series asserting `rows_kept == rows_passing`, and the settled numbers were

- data_date **2026-11-09** (shibui is T+1), universe **911 names** (NYSE/NASDAQ/AMEX, cap > $10B)
- breadth **67.84%** above the 20-DMA, 1-year percentile **90.8**, band `ABOVE_NORMAL`
- divergence **+27.84 pp**, band `BROAD` (2 of 5 index ETFs above their own 20-DMA)
- advance/decline **765 / 143 / 3**, ratio **5.35**, 10-session net **+739**, ADL slope **+40.35/session**
- live tape (2026-11-10, open): SPY -0.60%, QQQ -1.13%; VIX **20.42 / VIX3M 21.33** (ratio 0.958)

### The defect

`render_markdown()` in `cloud-prompts/skills/stock-screener-suite/scripts/breadth_metrics.py`
hardcoded the front-matter line:

```python
'cross_reference: "end-of-day counterpart: daily-screens/<date>/breadth.md (cron #09, 18:30 ET)"',
```

So every artifact published the **literal template string** `<date>` — a path that points at
nothing. Two things made it survive:

1. The **checker did not assert the field at all**. `REQUIRED_FRONTMATTER` covered the regime
   flags and `data_date` / `live_date` / `breadth_universe`, and `cross_reference` was not in the
   list, so no check could fail on it.
2. The prompt's own SELF-DESCRIPTION block spells the field with the same `<date>` placeholder, so
   the placeholder reads like the intended literal rather than an unfilled template.

The 2026-11-10 artifact was repaired by hand after rendering (the line was rewritten to
`daily-screens/2026-11-10/breadth.md`) and the pushed file was verified byte-identical to the
remote.

### Which date is the right one?

The end-of-day counterpart of an **intraday** read is the directory of the **fire** date: cron #09
fires at 18:30 ET on the SAME session and writes `daily-screens/<fire_date>/breadth.md`. The
settled `data_date` is one session back (shibui is T+1), so pointing the cross-reference at
`daily-screens/<data_date>/breadth.md` — as the 2026-11-10 TL;DR caveat first did — names the
wrong artifact: that file is the *previous* session's end-of-day read, and this fire's own
counterpart does not exist yet at 14:00 ET.

### The fix (in the repo, so it lands on the next fire with no `cron_update`)

1. `scripts/breadth_metrics.py` — the front matter now renders the live/fire date:

   ```python
   f"cross_reference: \"end-of-day counterpart: daily-screens/{live.get('live_date') or data_date}"
   f"/breadth.md (cron #09, 18:30 ET)\"",
   ```

2. `tools/check_breadth_artifact.py` — `cross_reference` is now a required front-matter field and
   it is asserted, not merely present:
   - the value must contain a concrete `YYYY-MM-DD` (the literal `<date>` is a FAIL),
   - and it must contain the `live_date` (the fire date's counterpart), so a cross-reference that
     names the settled session's directory is a FAIL too.

3. Fault injection, both directions, on the 2026-11-10 artifact:
   - the shipped artifact → `OK: breadth artifact contract breadth-artifact-v1 satisfied`;
   - the same artifact with `<date>` substituted back in → `FAIL … the literal `<date>` placeholder
     must not ship`.

### Carry into the next run

- The **TL;DR caveat bullet is agent-supplied** (it lives in the `live` layer, not in the
  renderer), so the next run must point it at `daily-screens/<fire_date>/breadth.md` and not at
  the `data_date`'s directory.
- The prompt's SELF-DESCRIPTION block still writes `daily-screens/<date>/breadth.md`. It is
  harmless once the renderer supplies a concrete date, but a future edit to the prompt should
  make the placeholder explicit (`<fire date>`) so nobody reads it as a literal again.

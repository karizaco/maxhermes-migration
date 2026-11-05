# Cron #12 — cross-asset-correlation-snapshot: improvements

## 2026-11-04 — `correlation_matrix.py` does not emit `series.json` / `mats_partial.json`

The skill spec's render command references three data files:

```
--current  /workspace/data_cross/mats.json
--partial  /workspace/data_cross/mats_partial.json
--series   /workspace/data_cross/series.json
```

`correlation_matrix.py` writes **only `mats.json`**. It fetches the full Yahoo series
(`yahoo_series`), aligns them (`common_dates`) and clips them to the window, but it never
persists them — and it computes the partial-session matrix nowhere. Both extra files are
therefore missing on every run, and `correlation_report.py` silently omits the
**Performance** table, the **price-level appendix** and the **Effect of the excluded partial
session** section (it tolerates the missing args).

**Why this matters:** the partial-session section is the artifact's proof that excluding the
in-progress bar changed no conclusion, and the performance table is the only place the reader
sees the window's returns. Both are load-bearing, and both were absent by default.

**Fix used on 2026-11-04 (this run):** a thin wrapper (`build_series.py`) that **imports**
`correlation_matrix` and reuses its own `yahoo_series` / `common_dates` / `build_sql` /
`shibui_sql` functions to produce both files — so the series alignment and the partial matrix
stay on the helper's code path, and the partial matrix is still computed **server-side**
(DuckDB `corr()` via the MCP bridge), never by hand.

**Recommendation:** make the helper emit these two files itself, so the spec's render command
works verbatim and no wrapper is needed:

- `series.json` — `{symbol: [[date, adjclose, rawclose], ...]}`, spanning from ~2 weeks
  **before** the window start (the matrix's first return observation needs the prior close as
  its base) through **today** (the intraday column needs the partial bar). The renderer reads
  `series[s]` as a list of 3-tuples and ignores the third element.
- `mats_partial.json` — `{"matrix_returns": {...}}` for the same window **including** the
  in-progress session, computed with `build_sql` + `shibui_sql` over the extended date set.

Watch-outs found on this run:

- `series.json` must include the session **before** the window start, otherwise the
  performance table's 6-month return is one bar short of the matrix it describes.
- The intraday column must come from the snapshot's **own** series, not a live quote feed —
  the renderer's `as_of` guard drops stale quotes, and the snapshot's own partial bar is
  already dated correctly.
- The sandbox clock reports `America/New_York` as **EST (UTC-5)** on 2026-11-04, i.e. one hour
  behind the true Eastern wall clock (DST ended 2026-11-01). The platform's scheduler fires on
  the same clock, so the fire instant and `derived_at_et` are mutually consistent — but do not
  use the sandbox ET stamp to infer real market-clock time.

## 2026-11-05 — the three fixes landed

### 1. The helper emits `series.json` and `mats_partial.json` itself

`correlation_matrix.py` now writes **all three** files the renderer reads, so the spec's
render command works verbatim with no wrapper:

| File | Written by | Contents |
|---|---|---|
| `mats.json` | the helper | the published server-side returns matrix, the matched-length prior-week matrix, source health |
| `series.json` | the helper | `{symbol: [[date, adjclose, rawclose], …]}`, from `SERIES_LEAD_DAYS = 14` days before the window start through today |
| `mats_partial.json` | the helper | `{"matrix_returns": {…}}` for the same window **including** the in-progress session, via the helper's own `build_sql` + `shibui_sql` — server-side DuckDB `corr()`, never by hand |

`yahoo_series()` now returns **two** series (`basis_close`, `raw_close`) so the third slot
of each `series.json` row carries the raw close while the second carries the basis close
the matrix was computed from.

### 2. The renderer FAILS when a required input is missing

`--series` and `--partial` are now **required**, and a missing/unreadable/shapeless file
aborts with exit 3 and a message naming the file. Until this they were optional, and
because the helper did not write them, a missing file silently dropped `📈 Performance`,
`🧪 Effect of the excluded partial session` and `📎 Appendix — price-level correlations`
while the run reported success.

Two honesty guards came with it:

- `partial_includes_in_progress` is published in the front matter. When the in-progress
  session was **not** available for every proxy, the partial matrix equals the published
  one and every delta is 0.0000 — the section now says that outright instead of claiming
  "no conclusion changes".
- When there is no prior-week matrix, the front matter reads `regime_shift: unknown`, not
  a silent `no`.

### 3. The duplicate-window assertion, and the reply that leads with the implication

New `tools/check_cross_asset_artifact.py` is the routine's **permanent pre-push
assertion** — it absorbs the one-off task `verify-cron12-window-roll-2026-11-05`
(`window_end_derived_from_data`, `n_sessions`, colour bands) and adds the
**duplicate-window** refusal: if `cross-asset/` already holds a file whose window end
equals the derived one, the run does not publish a second artifact for that window.

The reply's first `### Signal` line is now the artifact's `signal_line`, computed by the
renderer from the same numbers the tables use:

```
SPY–TLT +0.31 → bonds move WITH equities, so TLT is a weak diversifier, not a hedge against a growth selloff; best equity offset in the universe is UUP–SPY -0.34 · best diversifier QQQ–TLT +0.16 · largest pair move 0.0346 vs the 0.20 regime-shift threshold (0.1654 to go)
```

Three facts, in order: the **hedge implication**, the **best diversifier**, and the
**distance to the shift threshold**.

`tools/test_cross_asset_contract.py` proves the contract is satisfiable AND that the
checker bites: it renders a conforming artifact from synthetic data, requires the checker
to accept it, then mutates it nine ways (stale derived flag, stale contract marker,
dropped section, missing colour band, ragged table, missing signal line, a partial
section overstating its proof, a reply without the implication, a reply without the
threshold) plus a duplicate window, and requires the checker to fail each one. It also
proves the renderer refuses a missing `--series` / `--partial` and an omitted `--series`.

**Nothing was deployed with `cron_update`.** The contract lives in the SKILL spec and in
the two scripts, all fetched at RUN time, so the next fire picks it up with no prompt
edit and therefore no drift risk. The deployed #12 prompt is untouched.

### Fetch hardening (a stale copy must never win)

The SKILL's script fetch now demands a **capability marker** in each file:
`correlation-matrix-v2` in the helper, `cross-asset-v4` in the renderer. The contents API
is tried first (authoritative, not CDN-cached), then jsDelivr, then raw — and the old
single-URL `curl` with no marker check is gone. An older helper does not write the two
files at all, and an older renderer drops three sections instead of failing; either one
must be recognised and rejected rather than used.

# Cron #15 — earnings-reaction-scanner: the four fixes of 2026-11-05

Routine review of cron #15 (`earnings-reaction-scanner`), prompted by the 2026-11-03 run and
the 2026-11-04 run that followed it. Every finding below was measured against live Yahoo and
TradingView data on 2026-11-05, not inferred.

The contract now lives in `cloud-prompts/skills/earnings-reaction-scanner/SKILL.md`
(**ARTIFACT FORMAT CONTRACT v2**, marker `REACTION_ARTIFACT_V2`), which the cron prompt
fetches at RUN time — so it lands on the next fire with no `cron_update` and no prompt drift.
The executable is `scripts/earnings_reaction_scanner.py` in `karizaco/minimax-cloud-outputs`
(`SCRIPT_VERSION 2026-11-05.1`).

---

## 1. The pre-market checker's Eastern-time handling — the DST trap

### The finding

The pipeline selected Yahoo's daily bars by **modal time-of-day** and kept only the bars that
matched. Yahoo stamps a daily bar at the session open *in the venue's local time*, so the
Eastern stamp of the **same** session moves by an hour across a DST boundary:

```
AAPL, Yahoo daily bars, fetched 2026-11-05:
  2026-10-22 09:30 ET   (13:30 UTC)  348.22
  ...
  2026-10-30 09:30 ET   (13:30 UTC)  344.63
  2026-11-02 09:30 ET   (14:30 UTC)  338.32      <- DST ended 2026-11-01
  2026-11-03 09:30 ET   (14:30 UTC)  331.90
```

Under the **fixed UTC-4 offset** the pipeline actually used on 2026-11-03, the same bars read
`09:30` (seven bars) and `10:30` (one bar). The modal was `09:30`, so the filter **kept the
older bars and discarded the newest one** — the base rolled back to the *prior-prior* session.

That is exactly what the 2026-11-03 artifact recorded, on every one of its US rows:

```
{"region": "US", "symbol": "AAPL", "yahoo_date": "2026-10-30", "yahoo_ref": 348.91,
 "tv_implied_ref": 344.63, "verdict": "stale_reference"}
```

`yahoo_ref` = Oct 29's close. `tv_implied_ref` = Oct 30's close. The base was **two sessions
old**. 88 of 130 checked rows failed this way — 66 US + 21 ASX + 1 EU — and were dropped as
"stale reference" when they were perfectly good rows.

### The second instance, still live after the offset was fixed

The `zoneinfo` fix (already in the repo, `SCRIPT_VERSION 2026-11-04.1`) repaired the **US** rows
but left the **ASX** rows broken, because an ASX bar is stamped at the session open too
(19:00 ET before the DST change, 18:00 ET after):

```
QAN.AX, Yahoo daily bars, fetched 2026-11-05:
  2026-10-29 19:00 ET (23:00 UTC)  8.79
  2026-11-01 18:00 ET (23:00 UTC)  8.80
  2026-11-02 18:00 ET (23:00 UTC)  9.36
  2026-11-03 18:00 ET (23:00 UTC)  8.90
```

The modal is `19:00` (six bars) → the three newest sessions were discarded. The 2026-11-04
artifact shows the damage: **24 of 25 ASX rows dropped**, and the AU table that shipped held
**one** row on a healthy tape.

### The fix

Session selection is now **by date and order, never by a modal time-of-day**:

* `resolve_session_bars()` takes the feed's bars as they come and derives `last` (the price the
  screener's `close` carries), `ref` (the bar immediately before it — the base the screener's
  `change` is measured against) and `prior_close` (the most recent **completed** session's
  close — the base an extended-hours percentage is measured against).
* The pre-market window is a **function**, `premarket_window_utc(day)`, resolved with
  `zoneinfo("America/New_York")`: 04:00-09:30 ET is **09:00-14:30 UTC in winter** and
  **08:00-13:30 UTC in summer**. The old filter was `3 < dt.hour < 9`, which is 04:00-08:59 ET
  — it dropped the **last 30 minutes** of the pre-market, including the 09:00-09:29 prints.
* The fetch ladder demands the **capability marker** `REACTION_ARTIFACT_V2`, in the cron
  prompt's `valid()` and in the pipeline's own `_valid_script()`. `SCRIPT_VERSION` alone cannot
  tell a stale blob from the current copy — an older copy carries it and compiles perfectly.

### The regression test

`tools/test_reaction_contract.py` part A runs the shipped code (the side-effect-free region
between the scanner's `PURE-HELPERS` markers, so the test can never trigger the self-heal and
never tests a copy):

* **A1/A2** — the window is 04:00-09:30 ET on a **winter** date (EST) and on a **summer** date
  (EDT), with the UTC bounds checked too.
* **A3** — with the exact bar fixtures above, the base is the **immediately prior** session
  (Nov 2 for the US, Nov 3 for the ASX), not the prior-prior one.
* **A4** — a 09:15 ET print is **inside** the window; 03:50 and 09:30 ET are outside.

---

## 2. The reference close is resolved first, and it is a hard gate

The cross-check used to run *after* the tables were built and its drops were invisible. It is
now a gate that runs **before** any table is built:

1. The screener's implied reference close (`close / (1 + change/100)`) is compared with Yahoo's
   reference close. A disagreement above **0.5%** means the row sat on a stale close → dropped.
2. A row whose reference close is **older than the previous session** → dropped.
3. Every surviving row publishes **`Ref close`**, **`Ref source`** (`yahoo_chart_daily`) and
   **`Ref asof`** (the date of that close), so a reader can see whether the row was checked
   against today's close or an older one.
4. The drops are **counted and published** as `rows_dropped_stale_ref` — never silently
   filtered.

### The trap in the gate itself

The first version of the date gate compared every row's base against the venue's previous
session date. That is right for the US (whose NYSE calendar is known) and **wrong for the
ASX**: an ASX bar is dated by its session *open* (19:00 ET the previous day), so the session
that closed at 02:00 ET on D has a base dated **D-2**. The first run of the change dropped
**25 of 25 ASX rows** and emptied the AU table. The gate is now venue-aware: the calendar test
runs for the US only, and every venue keeps the feed-gap test (a base more than 4 days before
the session means the feed skipped a session).

---

## 3. The actionable layer

The 2026-11-03 artifact was a catalogue with no actionable layer. Added:

* **`Move vs avg daily`** — the reaction ÷ the name's own mean absolute daily move over its last
  20 completed sessions. A −27% move in a name that averages ±3% is a different event from a
  −8% move in a name that averages ±7%. The average comes from the same daily-bar fetch that
  resolves the reference close, so it costs no extra call.
* **`US tradeable`** — `US-listed` / `US-listed (ADR)` / `ADR (VENUE:TICKER)` / `none`. The US-line
  index is **two** america-scanner calls (`type=stock` and `type=dr`) filtered to the 18 home
  countries the foreign tables draw from. Both types are needed: TradingView types most ADRs as
  `dr` but files others as `stock` — TotalEnergies (NYSE: TTE) is `stock`, and a `dr`-only index
  reports "no US line" for a name a US reader can buy.
* **`## Actionable read`** — a new section above the tables with (1) how to read the multiple,
  (2) the US-listed vs foreign-only split, and (3) **one not-yet-fully-priced hypothesis per
  region**, stated with its evidence and never as a recommendation.

The hypothesis is computable, not editorial: the move is still **extending** beyond the move it
follows (for a US row, the extended-hours print exceeds the regular session's move; for a live
EU session or a closed ASX session, the move exceeds the previous session's move) **and** it is
large relative to the name's own average daily move. The artifact states no direction and no
trade.

---

## 4. One table per name, and a count that matches

* **The one-table rule** (from `ntrt-gap-brief/SKILL.md` §2) now governs this artifact: each
  name appears **exactly once**, in exactly one table, with its catalyst in that row's last
  column. The separate `## Catalysts` section is **gone**. The pipeline reads
  `catalog/catalysts/<date>.md` and **merges each row into its ticker's row** — so the agent's
  research is preserved on a re-run and a name can never appear twice.
* **A symbol on a US venue and a foreign venue keeps the US row** (it carries the extended-hours
  columns and it is the line a US reader can trade); the dropped foreign row is listed in source
  health as `cross_region_rows_dropped`.
* **`degraded_sources`** counts each degraded source **separately**, with one numbered entry
  naming which source and what happened, and the chat reply's `errors:` **must equal that
  number**. On 2026-11-03 the reply said `errors: 1` for two unverified rows plus a stale
  TradingEconomics table — three degraded sources counted as one. The rule is now in
  `cloud-prompts/_shared/PROMPT-BLOCKS.md` (`## DELIVERY`), which every routine fetches at run
  time.

---

## The verification

`tools/check_reaction_artifact.py` is an **independent** checker (it does not import the
pipeline). It verifies the section skeleton and order, the absence of a `## Catalysts` section,
the required columns on every published row, the reference-close floor per venue, the
one-table rule, the `errors:` ↔ `degraded_sources:` agreement and the published
`rows_dropped_stale_ref`.

`tools/test_reaction_contract.py` proves the checker bites: it renders a conforming artifact
from synthetic data (the checker must accept it) and then **mutates it twelve ways** — the
checker must fail each. Two of those mutations were **no-ops** on the first run (the reply's
`errors:` line was mutated in the artifact text, and the `errors:` regex did not allow a
leading `-`), which is exactly the false "NOT CAUGHT" the mutation test has to catch: a
mutation that does not change the text must fail the test itself.

**Every check passes: 18 of 18.**

---

## 5. The 2026-11-06 fire: the US headline pass did not apply the hard gate

**Date:** 2026-11-06 · **Fire:** 08:00 ET, `earnings/2026-11-06-reactions.md`

### The finding

The reference close is a HARD GATE, and §2 above says so: a row whose base cannot be
established from Yahoo must be **dropped and counted**, never published. The EU/UK and AU
passes filtered their rows on the gate (`eu_keep` / `au_keep`). The **US headline pass did
not** — it built `us_ref` from the successful gates and then rendered `tagged` **as it came
out of the screener**, so a row whose Yahoo lookup failed was still rendered, with `—` in
`Ref close`, `Ref source`, `Ref asof` and `US tradeable`.

On the 2026-11-06 fire, **BRK.A** hit that path: Yahoo did not return a usable daily bar
(429 or a bad body), the pipeline recorded the degradation honestly
(`yahoo_chart_api.reference_close_unresolved`) — and then published the row anyway.

The independent checker caught it, exactly as designed:

```
FAIL: 1 contract violation(s) in earnings/2026-11-06-reactions.md
  - REFCLOSE: US — Headline table row 181 — ref_close_asof is not a date ('—')
```

The artifact was **not pushed** in that state. The same failure had already run on
2026-11-05 (that fire's degraded row was `PNR.AX`, an AU row, so the AU filter caught it
and the artifact passed) — a defect that only shows up when the *US* pass is the one that
loses the race with Yahoo.

### The fix

`scripts/earnings_reaction_scanner.py` (`karizaco/minimax-cloud-outputs`), `SCRIPT_VERSION`
2026-11-05.2 → **2026-11-06.1**: the US headline pass now filters on the same gate as EU
and AU, and counts what it drops in a **new published counter**,
`rows_dropped_unresolved_ref` (source health + the audit line). The row is dropped, not
published with a `—` base.

**Why the fix belongs in the repo, not in the artifact.** Hand-deleting the BRK.A line
would have made the checker pass while leaving the next fire to publish the same broken row
and fail again. The pipeline **self-heals**: at startup it compares itself byte-for-byte
with the shared-repo copy and re-execs a newer one. So the repair was pushed to `main`
first, then the pipeline was re-run — it self-healed
(`self-healed at start of run from 2026-11-05.2 to 2026-11-06.1`) and regenerated the
artifact **from the fixed code**. The artifact was never hand-edited.

**Verification:** `tools/check_reaction_artifact.py` → `OK: … conforms to
REACTION_ARTIFACT_V2`, `rows_dropped_unresolved_ref: 1` published, `degraded_sources: 1`,
reply `errors: 1`, delivery verified on `origin/main`.

### The generalisable lesson

**A gate that is applied on one path and not on its siblings is not a gate.** The EU and
AU filters were written first; the US headline pass was added later and inherited the
*lookup* but not the *filter*. Any new pass that consumes `cross_check()` must filter on
it (`if r:` … else drop-and-count), and the contract checker is what proves it — a checker
that has never been observed failing is a claim, not a check.

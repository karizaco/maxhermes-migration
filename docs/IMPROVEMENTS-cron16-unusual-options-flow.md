# Cron #16 `unusual-options-flow-daily` — General Improvement Audit

**Audited:** 2026-10-31 (Sat). Scope: the routine as a *system* — cron instructions, skill spec,
timing, data path, output contract, and the artifact series — not any single date.

**Verdict:** the routine now works and its delivery chain is sound, but the *method* is not yet
pinned down anywhere durable. Four of the nine artifacts in the series disagree with each other
on the headline metric because the source, the universe and the selection rule changed between
runs. The single highest-value improvement is to fix the method in the **skill spec**, not the
prompt, so every future run inherits it.

---

## 1. Current state (verified 2026-10-31)

| Item | Value | Verified how |
|---|---|---|
| Live task | `457305357095000`, agent Mavis, enabled | `cron_read view:list` |
| Schedule | `35 16 * * 1-5` America/New_York (16:35 ET, Mon–Fri) | `cron_read view:detail` |
| Next fire | 2026-11-02 16:35 ET (Mon) | decoded `next_run` |
| Prompt ↔ source | **byte-identical**, SHA-256 `4734e1aa…` both sides | diffed deployed prompt vs `maxhermes-migration` source |
| Prompt size | 18,280 bytes (was ~7.2 KB on 2026-10-27) | byte count |
| Series coverage | 9 artifacts: 10-16, 10-20…10-23, 10-27…10-30 | git trees API |
| Weekday gaps | **10-12, 10-13, 10-14, 10-15, 10-19, 10-26** | day-by-day sweep |
| Auditor coverage | `90-delivery-auditor` tracks `options-flow/{date}.md`, Mon–Fri | `#90` prompt roster |

**The 2026-10-27 outage is closed.** The schedule had been left at `30 22 * * *` while the
prompt's own `MARKET_HOURS_ONLY` gate demanded 09–16 ET — a fire time the gate could never
accept, so the routine skipped itself every day. It was re-anchored on 2026-10-27 and has
produced artifacts on every weekday since (10-28, 10-29, 10-30).

---

## 2. What is genuinely good now

Credit where due — the 2026-10-28 → 10-29 hardening pass fixed most of what was wrong:

- **The prompt is now a contract, not a wish.** It states the deployed schedule explicitly,
  names the tools that *actually exist* (`web_search`, `web_fetch`, `bash`), and carries an
  explicit "the `mcp__*` tools named above DO NOT EXIST" clause. That removes the old
  guaranteed tool-not-found abort.
- **The push block is safe.** Scoped `git add options-flow` inside a disposable worktree, with a
  staged-deletion abort, a 3-attempt re-fetch/rebuild race retry, and a mandatory
  `git cat-file -e origin/main:<path>` delivery check. No `git add -A`, no force-push, no
  `|| echo` masking.
- **The reply format matches the house style** (prose opener → `### Signal` → `### Method &
  caveats` → `### Files` → `### Push / errors`).
- **The 16:30 → 16:35 stagger** was the right fix for the `#05`/`#16` push race — it separates
  the two routines' fire minutes rather than relying on the retry loop to recover.
- **Later runs discovered and used better sources than my 10-27 run did** — Cboe as primary with
  Nasdaq as an independent second tape, plus a Treasury yield curve for the IV inversion.

---

## 3. The core problem: the method is not pinned down, so the series is not a series

This is the finding that matters most, and it is invisible from any single artifact.

The headline number is the put/call volume ratio. Across the nine artifacts it reads:

| Date | Primary chain source | P/C | Tag | Method note |
|---|---|---|---|---|
| 2026-10-16 | Yahoo | 0.60 | CALL | V/OI pre-cut |
| 2026-10-20 | Yahoo | 0.86 | MIXED | V/OI pre-cut |
| 2026-10-21 | Yahoo | 1.02 | MIXED | V/OI pre-cut |
| 2026-10-22 | Yahoo | 0.65 | CALL | **switched to volume pre-cut** |
| 2026-10-23 | Yahoo | 0.63 | CALL | volume pre-cut |
| 2026-10-27 | Yahoo (Cboe fills 0DTE) | 0.61 | CALL | volume pre-cut |
| 2026-10-28 | Yahoo (Cboe + Nasdaq cross-check) | 0.65 | CALL | volume pre-cut |
| 2026-10-29 | **Cboe** (Yahoo 429) | 0.75 | CALL | volume pre-cut |
| 2026-10-30 | **Cboe** (Yahoo unusable) | 1.05 | **MIXED** | volume pre-cut |

The first three rows are explicitly labelled "per-underlying top-10 **by V/OI**" in their own source
health sections, and 10-22 is where the switch to the volume cut happened. The source boundary is
exact: Yahoo was primary through 10-28; Cboe became primary on 10-29.

Three separate things moved at once, and none of them is visible in the final tag:

1. **The chain source changed.** 10-16 → 10-28 read Yahoo; 10-29 → 10-30 read Cboe. Cboe
   carries *yesterday's settled* open interest against *today's* volume — a materially different
   denominator from Yahoo's same-day basis. The 10-30 file (P/C 1.05, MIXED) was built on a
   different tape from the 10-29 file (0.75, CALL) one day earlier. The tag "flipped" on a
   source change as much as on flow.
2. **The pre-cut rule changed** on 10-22 (V/OI → volume). The first three artifacts are
   therefore not comparable with the rest, and each says so.
3. **The 4-expiry window drifted** because Yahoo drops the just-expired session-date 0DTE after
   the close. The window's *calendar dates* differ per run and per ticker.
**The 10-30 artifact is the clearest evidence:** it also discovered that ~50% of kept volume sits
in contracts whose theoretical value is below $0.05, that Cboe reports OI of exactly zero on three
contracts (making V/OI undefined), and that its `iv` field is a decimal fraction, not a
percentage. Each of those is a *method* question, and each was solved inside one run rather than
written down for the next.

**Recommendation:** freeze the method in the skill spec — same source-of-record every day, same
pre-cut rule, same expiry window rule, same unit conventions — and add a **methodology-change
log** at the top of the artifact so a reader can see when the numbers stopped being comparable.

---

## 4. Timing: 16:35 ET is right, and it should be defended

The skill's original spec was `55 9 * * 1-5` (09:55 ET, ~25 min after the open, "so vol settles").
The deployed schedule is 16:35 ET. **The deployed time is the better choice** for this metric:

- V/OI compares volume to open interest. At 09:55 the day's volume is a ~25-minute fragment
  against a full prior-day OI, so the ratio is mechanically depressed and unstable.
- After the close, volume is the day's settled total and OI is the settled figure the exchange
  will publish. The ratio is reproducible and comparable day to day.
- The 10-29 artifact shows what a partial-day sample would have cost: Cboe's snapshot pairs
  *yesterday's* OI with *today's* volume, which is exactly why its top row was 24,376 contracts
  against an OI of 1.

**But the skill spec still says `55 9 * * 1-5`** in its `## When` block, and the cron prompt's
`## SCHEDULE` block says only "Original local schedule: intraday". Both are now misleading. Any
future migration that trusts them will re-break the routine — this is exactly the drift class
that killed it.

**Recommendation:** state 16:35 ET as the schedule of record in *both* the skill's `## When` block
and the prompt's `## SCHEDULE` block, with a one-line note on *why* it is post-close rather than
the skill's original 09:55.

---

## 5. Concrete gaps, ordered by value

### P1 — Write the method into the skill spec (`SKILL.md`)

The skill spec is still the original local-Windows document. It still says:

- Output path `C:\Users\admin\...\research\options-flow\YYYY-MM-DD.md` (never exists in cloud)
- Pass A reads `research/watchlist.yaml` from a Windows path — **absent from every cloud run to
  date**, so Pass A has never once executed. Every artifact since 10-16 has been Pass-B-only.
- Step 3 calls `mcp__tradingview-advanced__stock_options_unusual_activity` — a tool that does not
  exist in this runtime
- The `## When` block says 09:55 ET, contradicting the deployed 16:35 ET

The spec also does **not** contain any of the hard-won conventions, each of which was rediscovered
at cost by a separate run:

| Convention | Discovered | Cost |
|---|---|---|
| Expiry date comes from the OCC **contract symbol**, not from the `expirationDate` epoch (which is 00:00 **UTC**; ET-rendering shifts it back one day) | 2026-10-27 | one wrong day across every row |
| ITM/OTM is **side-aware**: call ITM when strike < spot, put ITM when strike > spot. A sign-only rule inverts every call row. | 2026-10-27 | wrong label on 579 call rows in one file |
| Yahoo **drops the session-date 0DTE** after the close → use Cboe to fill it | 2026-10-27 | 0DTE slice missing entirely |
| Cboe `iv` is a **decimal fraction** (0.3 = 30%), not a percentage | 2026-10-29 | IV column off by 100× if read literally |
| Cboe reports **OI = 0** on some contracts → V/OI undefined, not "huge" | 2026-10-30 | three contracts ranked top-of-book on a divide-by-zero |
| Cboe IV is unreliable on **deep-ITM near-worthless** contracts | 2026-10-28 | 94.9% vs Yahoo's 14.8% on the same contract |
| ~50% of kept volume can sit in contracts worth **<$0.05** | 2026-10-30 | headline volume vastly overstates economic size |

**Recommendation:** add a `## Cloud data conventions` section to the skill spec carrying these
seven rules, each with the evidence date. Also add the `research/watchlist.yaml` question — either
ship a watchlist into the repo so Pass A can run, or delete Pass A from the spec. Right now the
spec promises a watchlist scan that has never happened once.

### P2 — Pin the source-of-record; keep one cross-check

Source drift is the biggest comparability risk (section 3). Pick **Cboe as the primary chain**
(it was the only source that never 429'd across 10-29/10-30, and it carries the 0DTE that Yahoo
drops), and keep **Nasdaq's public option-chain endpoint as the independent cross-check**. State
in the spec that a source swap is a methodology change that must be logged in the artifact.

Also: Yahoo's chain should stay in the ladder for the underlying prices and for its more
reliable IV on deep-ITM contracts, but it should not be the primary chain.

### P3 — Add a holiday / no-session guard

The prompt mentions holidays twice in prose and implements **no** holiday check. The window gate
only tests the hour. On **2026-11-26 (Thanksgiving)** and **2026-12-25 (Christmas)** — both
weekdays, both inside `1-5`, both at 16:35 — the routine will fire, find no session, and either
emit a hollow artifact or a misleading "no data" one.

**Recommendation:** add a small 2026-2027 US market-holiday list to the prompt's window check and
exit cleanly with a `SKIPPED_*.md` on those dates. The auditor's `possible_holiday` classification
already exists, so the two will agree.

### P4 — Fix the skip-audit-trail path

The window check writes `SKIPPED_unusual_options_flow_daily.md` to `/workspace/<date>/`, but the
push block stages **only** `options-flow/`. A skip therefore leaves a file in the sandbox that is
never pushed — the audit trail for a skipped fire is silently dropped. This is visible in the repo:
the `2026-10-11` and `2026-10-18` options skip files existed at my 2026-10-27 commit and are gone
now, while 10-26 has no skip file at all despite being a skipped fire.

**Recommendation:** stage the date directory too, or write the skip notice inside
`options-flow/` so it lands on `main`.

### P5 — Add a `methodology` block to the artifact header

Every artifact should carry, in machine-readable form: primary chain source, cross-check source,
pre-cut rule, expiry-window rule, and the count of rows whose OI is 0 / undefined. Then
day-over-day comparison becomes safe, and a reader can tell a real flow change from a method
change. The 10-29 and 10-30 files already do much of this in prose — it just needs to be uniform.

### P6 — Close the 2026-10-19 / 2026-10-26 gaps (or explain them)

Six weekdays in October have no artifact and no skip file. 10-19 and 10-26 are unexplained by
the current schedule. The auditor's roster will keep flagging them as `MISSING` forever unless
either the artifacts are backfilled (impossible — the chains are not retained) or the gaps are
recorded as known. **Recommendation:** have the auditor's status carry an `unrecoverable_gap`
class so historical gaps stop reading as live failures.

### P7 — Retain the raw chain snapshots

Raw chains are not retained between runs, so no past day can be recomputed. That is why the
10-16/10-20/10-21 artifacts are permanently provisional. Retaining a compact per-contract
`(ticker, expiry, side, strike, volume, oi)` CSV under `options-flow/_data/` would make any future
method change back-computable — and the repo already ignores `data/`, so it would need a
narrower path.

### P8 — Minor

- The `## DELIVERY` block still says "≤ 6 lines" in the skill's `## Output` section ("Compact
  ≤ 15-line summary in chat reply (top 5 only)") while the prompt says "no line cap". Remove the
  contradiction — the skill is the older document.
- The prompt's `## SCHEDULE` says "Original local schedule: intraday" with no stated
  post-close rationale. Add it (see section 4).
- The exclusion list should note that SPY/QQQ exclusion is *not* applied to IWM, which now
  carries 20–36% of kept volume and dominates the aggregate tag. The skill keeps IWM for
  interpretability, but the artifact should say plainly that the headline ratio is set by IWM.

---

## 6. What I did NOT recommend, and why

- **Moving the fire time back to 09:55 ET.** The skill's original hour is wrong for a volume/OI
  ratio (section 4). Post-close is correct.
- **Re-adding Pass A by inventing a watchlist.** A fabricated watchlist would manufacture
  coverage that does not exist. Ship a real one or drop the pass.
- **Backfilling the six missing October weekdays.** The chains were never retained. Retrospective
  artifacts would be fiction.
- **Changing the push path or the delivery format.** Both are now correct and recently hardened.
- **Touching the other 19 routines.** The audit found the same `MARKET_HOURS_ONLY`-style
  schedule/gate mismatch class elsewhere in the fleet (several crons now carry `* * 1` weekday
  fields against prompts that say Mon–Fri, and the auditor's roster still says Mon–Fri for six of
  them), but that is a separate, fleet-wide piece of work.

---

## 7. Suggested order of work

1. **P1** — write the seven cloud data conventions + fix `## When` + resolve Pass A in the skill
   spec. Highest value per edit; prevents every future run from rediscovering them.
2. **P2 + P5** — pin Cboe-primary/Nasdaq-crosscheck and add the methodology block.
3. **P3 + P4** — holiday guard and the skip-trail push path. Both are small, mechanical edits to
   the prompt, and both prevent wrong output rather than merely improving it.
4. **P6/P7** — auditor gap class and chain retention; both are repo-side.

Each of P1–P3 is a single-file edit in `karizaco/maxhermes-migration` followed by a
`cron_update` of the live prompt, verified by SHA-256 against the source — the triple-match
procedure already in use for this fleet.

---

## 10. Addendum — 2026-11-03: two sessions rebuilt, and the archival-recovery path

Two sessions of this series had no artifact: **2026-10-19** and **2026-10-26**. Both were due
(Mon–Fri regular trading days) and both lost their run. Their causes are now known exactly, from
the platform's own run history for the retired task `449955350683738`:

| Date | What happened |
|---|---|
| 2026-10-19 | The 16:30 ET fire **failed at the platform level** — status 2, `CRON_EXECUTION_FAILED`, `[1406010011]:explicit model is not registered. cause: <nil>`. No session started, so no skill fetch, no chain pull, no file. |
| 2026-10-26 | The fire **ran and the routine declined it**. The task's schedule was 22:30 ET while its own `MARKET_HOURS_ONLY=true` window check demanded 09:00–16:00 ET, so the prompt's first step exited `out-of-window: outside market hours (hour=22, expected 09-16 ET)` at 22:33 ET. It wrote only a `SKIPPED_*.md` marker into the sandbox and pushed nothing. |

The 2026-10-26 cause is the **same schedule-versus-gate contradiction** that was repaired on
2026-10-27 by moving the task to 16:35 ET. Note the shape of that failure: the run was healthy,
the artifact was built-worthy, and the routine declined itself — the exact class of failure this
audit's §1 calls "a cron that cannot verify itself."

### What could be recovered, and what could not

**The strike-level layer is unrecoverable.** Yahoo's options endpoint returns HTTP 200 with an
*empty* contract list for every expired expiry (verified for the 2026-10-19 and 2026-10-23
expiries); Cboe's delayed-quote service serves only the live session. Per-strike volume, open
interest, IV and moneyness cannot be retrieved for a past date by any reachable source. **No V/OI
figure can be computed for either date, and none appears in the rebuilt files.**

**The aggregate layer is recoverable and exact.** Cboe's historical options-data service serves
per-underlying daily volume for any past date:

```
https://www.cboe.com/us/options/market_statistics/historical_data/download/class/
  ?reportType=volume&volumeType=sum&volumeAggType=daily
  &symbolType=underlying&symbol=<SYM>
  &startDate=<YYYY-MM-DD>&endDate=<YYYY-MM-DD>
  &exchanges=CBOE&exchanges=BATS&exchanges=C2&exchanges=EDGX
```

It needs a browser `User-Agent` and a `Referer` of
`https://www.cboe.com/us/options/market_statistics/historical_data/`, or the request is refused.
The `all_symbols` variant of the same endpoint returns every underlying for a month at once and
is the fast way to confirm a total. Market-wide call/put volume and open interest come from
Cboe's daily market statistics page, `.../market_statistics/daily/?mkt=cone&dt=<DATE>`, which is
client-rendered and needs a headless browser to read.

Two caveats that keep the number honest: the archival total is **unfiltered** (every strike, every
expiry) and covers **only the four Cboe-operated venues**, whereas this series reads Yahoo's
chain, which spans every US venue. The ratio between the two is therefore not a conversion
factor — measured across the nine dates where both exist it ranges **0.38 to 1.50**. The total
also includes corporate-action-adjusted series (class names prefixed with a digit, e.g. `2IWM`):
2.37% of the universe on 2026-10-19 and 1.76% on 2026-10-26.

### What was published

`options-flow/2026-10-19.md` and `options-flow/2026-10-26.md` on `origin/main` of
`karizaco/minimax-cloud-outputs`. Each is labelled **RECONSTRUCTION** in its title and leads with
a section 0 that states what was lost, what is present, and that no V/OI figure can be computed.
Each carries the real per-underlying volume for the 8-name Pass B universe across the four Cboe
venues, the real market-wide call/put and open-interest picture, the real underlying closes, the
run's actual cause, and a cross-check table against the nine dates where an original artifact
exists. The series is now 12 consecutive sessions.

Convention 8 in the skill spec and the `reconstructed` label in cron #90's prompt were added so
this is repeatable: a future run that loses a session knows which archival source to reach for,
and the auditor knows not to report a rebuilt file as a clean delivery.


---

## 9. 2026-11-05 — the method change: rank by RELATIVE volume

**Migration commit:** `1ecfd94` (`feat(cron16): rank the options book by RELATIVE volume`).
Deployed prompt SHA-256 **`d6435ae7f6294b4d2067e03ff9bd8f197081d9028b44f50c04a38ce500f29601`**
— byte-identical to `cloud-prompts/cron-prompts/16-unusual-options-flow-daily.md` (16,021 bytes,
**no trailing newline**).

### Why

The routine ranked by absolute contract volume / V/OI across a fixed **8-name mega-cap universe**,
so the top of the book was structurally the largest names no matter what was actually unusual.
Measured on the 2026-11-04 session: the absolute top 10 and the relative top 10 shared **1 name
of 10**, and the loudest names were **below their own 10-session options-volume baseline**
(TSLA 0.44×, AMZN 0.52×, NVDA 0.75×) while quiet mid-caps were **2-8× theirs**
(ARRY 8.16×, FIS 7.38×, GRAB 3.79×, CLSK 2.62×). An absolute-volume screen cannot surface a
mid-cap when the universe contains none.

### What changed

| | Before | After |
|---|---|---|
| Headline | V/OI rank, absolute | **relative-volume composite** |
| Universe | 8 mega-caps | **top 60 US names by cash volume** (TV scanner) + the routine's 8 |
| Scoring | per-underlying top-10 by volume, then V/OI | **the whole 4-expiry window**, no absolute pre-cut |
| Measures | one (V/OI) | **five**: peer ratio, share of expiry, share of chain, options contracts ÷ cash shares, own-history |
| Engine | the model parsed 8 chains by hand | **`_shared/relvol_screen.py`** (`RELVOL_SCREEN_V1`) — ~60 chains 8-way parallel + 2 monthly baseline files, **~25 s** |
| Runtime | ~90 s | ~25 s measured (the universe got 8× bigger and it got faster) |

**The five measures**, each normalising a different size bias:

1. **Peer ratio** — contract volume ÷ the median volume of the other *meaningfully-traded* strikes
   (vol ≥ 50) in the same underlier + expiry + side. The vol≥50 floor matters: over all active
   strikes the median collapses into the near-dead tail and the ratio inflates 5-15× (RIOT 24C
   read 13.1× vs 207×).
2. **Share of expiry** — the contract's share of its expiry+side's volume in the chain.
3. **Share of chain** — its share of the underlier's whole options tape.
4. **Opt % of cash vol** — options contracts ÷ the underlier's share volume (cross-name).
5. **Own-history** — the name's own 10-session average options volume. **The only measure
   independent of the contract's chain size, and the most important column.**

Composite: `z(peer) + z(expiry_share) + z(opt%cash) + z(V/OI) + 1.5 × z(own_history)` — every
component published per row so the ranking can be re-weighted.

### The own-history baseline — the cheap way

Cboe's historical options-volume service, `all_symbols` monthly variant, returns **every
underlying's daily volume for a whole month in ONE call** (6.5 MB for Oct 2026, 219,701 rows,
~3,815 symbols/day). Two calls (previous + current month) cover a 10-session average that spans
the month boundary — it replaces 60 per-symbol calls and **reproduces the per-symbol endpoint
exactly** (verified 7/7 names on base volume, average and ratio). Needs a browser UA **and** the
`Referer: .../historical_data/` header. Caveats: **4 venues only** (CBOE, BATS, C2, EDGX — the
chain spans every US venue, so the ratio is internally consistent but the absolute volumes are a
different universe) and it **lags the live session by ~a day**, so the baseline is measured on the
last session the service has published and that date is labelled on every row.

### The series book is preserved

The legacy absolute method (the 8 routine names, per-underlying top-10 by volume, the legacy
filters, the bias tag) is still computed and published as a **secondary** section, so the put/call
series published since 2026-10-16 stays comparable. The engine reproduces the published 2026-11-04
figures **exactly**: put/call **0.74 (CALL)**, 57.1% of kept volume in sub-$0.05 contracts,
3.47 premium ratio, 82.2% of premium in ITM contracts. **The artifact's headline and the chat
reply's headline are now the relative screen** — the legacy tag is never the lead.

### Degradation

If the engine cannot be fetched or fails, the routine falls back to the **legacy method** and
labels the artifact `method: legacy_fallback (relvol engine unavailable: <reason>)` — a degraded
legacy artifact beats a failed run. The prompt fetches the engine with a **capability-marker**
check (`RELVOL_SCREEN_V1`); the skill spec carries the same ladder.

### Also fixed in the same pass

- The prompt's GIT PUSH block still carried the **dead `[ -s file ] || curl` ladder** (the first
  successful download satisfied the guard, so the fallback URL was never reachable) and fetched
  **only** `push_artifact.sh` — `verify_delivery.sh` is a separate helper the push script does not
  ship, so the mandatory verification was a silent no-op. Both helpers are now fetched with the
  contents-API ladder.
- `_shared/PROMPT-BLOCKS.md` now states that **`_shared/` helpers are executable** while a skill's
  own `scripts/` helpers are reference-only — the ambiguity that could have made an agent skip
  the engine.
- `_shared/RUNTIME-CONTRACT.md` §2f: the **Cboe endpoints were undocumented** (options-chain CDN,
  `all_symbols`, `class`, quote CDN) even though the CDN is this routine's primary tape. Added
  with the measured **HTTP 403 + XML `AccessDenied`** behaviour for a symbol with no listed
  options series — which is **not** a source failure (CHSN, CRIS, DKI, OMH on 2026-11-04).

### How to verify the deployment

```bash
# the deployed prompt == the repo blob, byte for byte
sha256sum cloud-prompts/cron-prompts/16-unusual-options-flow-daily.md   # d6435ae7f6294b4d…
# the engine is live on the contents API and runs clean
curl -sL -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/relvol_screen.py?ref=main" \
  -o /tmp/rv.py && grep -c RELVOL_SCREEN_V1 /tmp/rv.py && python3 /tmp/rv.py --date <D> --out /tmp/o.md --universe 60 --jobs 8
```

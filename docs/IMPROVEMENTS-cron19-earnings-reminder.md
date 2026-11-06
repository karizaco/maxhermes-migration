# Improvements — cron #19 earnings-reminder-daily

Reviewed 2026-10-25. Evidence base: 16 recorded runs (2026-10-10 → 2026-10-25), the deployed
cron task `450511266500917`, the migration repo `karizaco/maxhermes-migration`, and the live
`karizaco/minimax-cloud-outputs` remote.

---

## 1. Stop advertising MCPs that do not exist — CRITICAL

The prompt's "MCP TOOLS AVAILABLE" block lists `mcp__yahoo_finance__*` and `mcp__shibui_finance__*`.
Neither exists in Cloud sessions. `mcode-tools connector tools` returns `partial=false`,
`provider_failures=[]`, and a catalog containing only `connector__matrix__*` and
`connector__email_workbench_credentials__*`. `tool_search` returns 0 hits for every finance keyword.

Every run therefore burns 2–3 turns re-proving the same negative before falling back, and every
artifact reports a spurious `errors: 1`. Sibling cron #7 was already repaired for exactly this
("provably absent in Cloud sessions … Do not burn turns re-testing them"). Cron #19 was missed.

**Fix:** name the working path as PRIMARY. Web search is the primary source; the MCPs are not
mentioned as available. `errors: 0` now means a genuinely clean run.

## 2. Fix the git push recipe — it deletes other crons' artifacts — CRITICAL

The prompt's recipe is `git init` → `git add -A` → `git push origin main`. In a fresh sandbox with
no working tree, `git add -A` stages **every file on the branch as deleted**.

This is not hypothetical. Cron #12's push on 2026-10-25 (commit `1356a03`) deleted **283 files**,
including all six of cron #19's published artifacts, `2026-10-18/SKIPPED_earnings_reminder_daily.md`,
and the repo's `.gitignore` — wiping 109 `daily-screens/`, 72 `us-eod/`, 13 `international-eod/`,
9 `us-stocks-in-play/` and 6 `daily-briefs/` files belonging to other crons.

Reproduced locally: `git reset --mixed origin/main` + `git add -A` stages **327 deletions**.
Verified safe alternative: worktree at `origin/main`, `git add <artifact-dir>` only → **1 addition,
0 deletions**.

**Fix:** replace the recipe with the worktree form, add only the artifact directory, and push
`HEAD:main`. Also restore `.gitignore` (done) so scratch files are never staged.

## 3. Never push from a stale base — cron #12's push also silently dropped cron #19's files

On 2026-10-23 cron #19's push was rejected (non-fast-forward) because sibling crons had moved
`origin/main`; local `master` was also an orphan history. The recovery was a worktree at
`origin/main`. The recipe in the prompt does `git init` + `git push origin main` against a branch
that does not exist locally — it pushes a *new* orphan history or fails outright.

**Fix:** `git fetch origin main` → worktree at `origin/main` → commit → `git push origin HEAD:main`.
Never force-push; never `git init` a fresh history against a shared remote.

## 4. The watchlist leg has never once succeeded — resolve it or delete it

Skill step 1 requires `research/watchlist.yaml`. It does not exist in the Cloud sandbox, does not
exist in the migration repo (205 paths, no `research/`), and does not exist in the outputs repo
(455 paths). Every artifact since 2026-10-14 carries the same line: *"Not evaluated —
`research/watchlist.yaml` is a local Windows path, absent from the cloud sandbox."*

Five of the skill's six numbered steps are about watchlist cross-referencing. A permanently
unreachable input should not be advertised as a capability.

**Fix (a):** publish a watchlist to the outputs repo and fetch it at run time —
`https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml`.
**Fix (b):** if no watchlist is to be published, drop the step and the "Your watchlist" section
entirely rather than carrying an empty table every day.

## 5. Fix the schedule — it fires at 11:30 ET, but the skill says 06:00 ET

Deployed schedule is `30 11 * * *` America/New_York (11:30 ET). The skill states
`0 6 * * 1-5` (06:00 ET) and says it "pairs with the 07:37 ET pre-market brief". Cron #26, the
pre-market brief, fires 08:30 ET.

11:30 ET is *after* the brief it is supposed to feed, and after the US open — a "morning reminder"
that arrives mid-session. Run history confirms the intent drift: the 2026-10-25 fire ran 11:30 ET
(Sunday), while the 10-10 → 10-24 fires all ran 05:30 ET.

**Fix:** schedule `0 6 * * *` America/New_York, with the window check keeping it weekdays-only.
This puts the artifact on disk before cron #26 reads it.

## 6. Add a market-holiday check — the window check only knows weekends

The window check tests `DOW >= 6`, so US market holidays still fire and produce a normal artifact.
Thanksgiving, Christmas and July 4 will each generate a "here is today's earnings" file for a closed
market. The sibling `eod-watchlist-snapshot` skill already ships `scripts/holiday_calendar.py` —
the pattern exists in this repo and is not being used here.

**Fix:** check the NYSE holiday calendar in the window check; skip with `reason: market holiday`.

## 7. Verify report dates against company sources, not just aggregators

Aggregator calendars carry wrong dates. Across 2026-10-20 → 10-23 the following were mis-dated and
had to be excluded after checking the company IR page or press release:

| Ticker | Aggregator said | Company source says |
|---|---|---|
| OMC | Oct 21 | Oct 22 (omc.com press release) |
| NEM | Oct 21 | Oct 22 (newmont.com) |
| ITW | Oct 23 | Oct 27 (investor.itw.com) |
| NXPI | Oct 23 | Oct 27 (nxp.com, Oct 6 release) |
| HCA | Oct 23 | Oct 27 (investor.hcahealthcare.com) |
| CHGCY | Oct 23 | Oct 27 (chugai-pharm.co.jp IR) |
| NWG | Oct 23 | Oct 30 (investors.natwestgroup.com) |
| INTC | Oct 22 | Oct 29 (intel.com, Oct 6 release) |
| SLB | Oct 22 | Oct 23 (marketbeat/marketbeat) |

**Fix:** state explicitly in the prompt that any name near the filter boundary must have its date
confirmed against a company IR page, press release or filing, and record exclusions in the artifact.
This is the single highest-value correctness rule — it is what turned 6 of those 9 into exclusions.

## 8. Verify S&P 500 membership against a live constituent list, never from memory

The filter is "S&P 500 / mega-cap >$50B mcap". Membership must be checked against a live
constituent list. The Wikipedia `List_of_S&P_500_companies` wikitext via the MediaWiki API parses
cleanly: 502 symbols from `{{NyseSymbol|…}}` / `{{NasdaqSymbol|…}}` templates, with `BRK.B`,
`GOOGL`, `GOOG` and `FOX` all present as a control check. The rendered HTML table does **not** parse
this way — an early attempt yielded 3 symbols and would have produced a badly wrong artifact.

**Fix:** specify the API wikitext endpoint, the template regex, the expected symbol count (~502) and
the control-ticker check. Cache to `/workspace/.cache/sp500.txt` and reuse within the run.

## 9. Reconcile conflicting market caps and EPS across sources instead of silently picking one

Sources disagree materially: AXP market cap ranged $203.7B–$219.6B across five providers on
2026-10-23; INFY ranged $43.7B–$53.6B, straddling the $50B inclusion threshold itself; AXP EPS
ranged 4.47–4.61; META 5.54 (Yahoo) vs 6.35–6.67 (adjusted); ARGX −27.83 (Yahoo) vs 7.44
(StockTitan). Without a rule, the same name lands differently on different days.

**Fix:** pick one primary source per field (Yahoo for market cap and EPS estimate), record the
spread when it exceeds a tolerance, and state the primary source in the artifact header.

## 10. Make the artifact self-describing and machine-readable

Current artifacts are prose-plus-table with no front matter, so a downstream consumer (cron #26's
pre-market brief) cannot parse them without guessing. They also do not state *when* the data was
snapshotted, and on 2026-10-22 and 10-23 three names had already reported before the fire time —
a distinction the reader needs but the table does not carry.

**Fix:** add a front-matter header (`date`, `cron`, `fire_time_et`, `snapshot_et`, `source`,
`primary_source`, `status`, `pending_count`, `already_reported_count`) and a `status` column
(`pending` / `reported`) per row. Also fix the skill's output-path drift: it still names
`C:\Users\admin\…\YYYY-MM-DD-today.md` while the cron prompt names
`/workspace/earnings/{date}-reminders.md`, and the skill's "≤ 10 lines" / "≤ 5-line summary"
guidance contradicts a table with 27 rows.

---

## Trigger layer — also edited (2026-10-25)

Beyond the prompt body, the scheduler-level trigger was editable too:

- **Schedule → `0 6 * * 1-5` America/New_York.** The day-of-week field now lives in the cron
  expression, so the scheduler never fires on weekends and no weekend `SKIPPED_*.md` files are
  produced. The in-prompt weekend branch is kept as a redundant one-line guard, and the holiday
  gate still runs — no cron expression can express market holidays.
- **Session mode → `new`.** The task was bound to one long-lived conversation
  (`sessionId: 450511046144336` — the very conversation this review happened in), while all 20
  prompts carry the line *"The cron session is fresh each time — there is no shared state."* The
  deployment and the prompt contradicted each other, and one run's context bled into the next.
  Now each fire starts clean, which matches what the prompt always claimed.
- **Timezone pinned.** A `cron_update` that omits `timezone` silently adopted the caller's local
  zone — the task briefly flipped to `Europe/Paris`, which would have fired a 06:00 ET job at
  00:00 ET. Caught by re-reading the task; the repo README now documents the gotcha.
- **Next fire confirmed: 2026-10-26 06:00 Mon ET.**

---

## Also fixed (not counted among the ten)

- **Restored the deleted artifacts.** All six cron #19 earnings files plus the 2026-10-18 skip
  record, recovered from git history, were re-added to `main` in commits `886a949` / `7ac925a`,
  together with the repo's `.gitignore`.
- **Restored the other 275 files cron #12 deleted** — `daily-screens/` (109), `us-eod/` (72),
  `international-eod/` (13), `us-stocks-in-play/` (9), `daily-briefs/` (6), `ntrt/` (6),
  `options-flow/` (5), `refs/` (5), `macro-calendar/` (2) and the rest, in commit `d3f774e` and
  `b3d7877`. Verified: **zero** paths that existed before the incident are missing now.
- **Fixed the destructive push recipe across the whole fleet, not just cron #19.** All 19 other
  cron prompts in the migration repo used the same unscoped `git add -A`. Cron #12's prompt was the
  one that fired, but the next offender would have been any of the other 18. Every prompt now uses
  a worktree at `origin/main` and stages only its own output directory, with an abort-if-deletion
  guard. Commit `27ad61b`. The fix was validated end-to-end in a clean sandbox: one file added,
  zero deletions, all directories intact.
- **Removed the contradictory `refs/` rule from `.gitignore`.** The repo ignored `refs/` while
  tracking five documents inside it, so any restore via `git add -A` silently skipped them — that
  is why the first restore pass left `refs/` empty.
- **Pinned the sandbox CA in the push recipe.** `GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/
  sandbox-gateway-ca.crt` — without it git fails cert verification, as it did on 2026-10-14 and
  2026-10-20.
- **Skill audit line is malformed.** SKILL.md step 6 reads
  `earnings_reminder target=earnings:<date> watchlist_hits=<n> bigcap_hits=<n>` — the angle brackets
  were eaten by templating, so the format string is unusable as written.
- **TLS proxy cert rotation.** The sandbox gateway's leaf cert expired mid-day on 2026-10-22,
  breaking all egress (curl, connector tools, git) until the proxy reissued it. The prompt's
  skill-fetch step should name `web_fetch` as the fallback when `curl` returns a certificate error,
  and pin `GIT_SSL_CAINFO` to the sandbox CA.

---

## Cross-check outcome (2026-11-01)

Nine of the ten improvements were verified working on live artifacts produced 2026-10-26 →
2026-10-30. The tenth — S&P 500 membership verification — was working but carried a defect in the
rule I wrote: the constituent parse I specified matched 502 symbols and silently dropped **CBOE**
(written `{{BZX link|CBOE}}` in the wikitext, not `{{NyseSymbol|…}}`). The 10-30 run found this on
its own and reported it. Rule A is now corrected to 503 symbols with a five-ticker control check,
in the live task, the repo prompt and `SKILL.md`.

Full evidence table, the two out-of-routine failures found (cron #12's 498-file deletion recurred
on 2026-10-26 with the old recipe, and cron #19 missed 10-27/10-28 entirely because its task was
deleted and recreated), and the 10-27/10-28 backfill are documented in
`cloud-prompts/../docs/CROSSCHECK-cron19-earnings-reminder.md` (this repo).

---

## 2026-11-04 fire — what the run proved, and three new rules

The 2026-11-04 06:00 ET fire produced `earnings/2026-11-04-reminders.md` (51 names). It was the
first run with the shared reply format as a STANDARD rather than an override, and the first to
surface the ADR/OTC and non-US data gaps below.

### 15. Print the PRIMARY listing, never the ADR or the OTC ticker (NEW)

The artifact showed `ITOCY`, `MITSY` and `NVO` — none of which a reader can look up. The rule is
now in the skill spec (step 7): the headline ticker is the issuer's home-market line with an
exchange suffix, and the US line goes in parentheses.

**The mapping is machine-extractable, and the cheap source is stockanalysis.com:**
- `https://stockanalysis.com/quote/otc/<TICKER>/` carries a **"Main Listing"** link for every OTC
  line. Verified 2026-11-04: ITOCY → `/quote/tyo/8001/`, MITSY → `/quote/tyo/8031/`,
  SMMNY → `/quote/etr/SHL/`.
- `https://stockanalysis.com/api/search?q=<company name>` lists EVERY line of a company, so a
  non-OTC ADR resolves too (Novo → `cph/NOVO.B`; Cenovus → `tsx/CVE`).
- `https://query1.finance.yahoo.com/v7/finance/quote?symbols=8001.T,8031.T,NOVO-B.CO,SHL.DE`
  confirms the venue and the LOCAL currency (`JPX/Tokyo`+JPY, `GER/XETRA`+EUR, `CPH/Copenhagen`+DKK)
  and gives the local-currency market cap.

**A dual-listed US line stays as the headline when the US listing IS the primary one** — ARM on
Nasdaq, CVE and MFC on NYSE (their TSX lines are the secondary). Do not "upgrade" those to the
Canadian line.

### 16. For a non-US issuer, the issuer's IR calendar outranks every aggregator (NEW)

Three failures in one run, all invisible to a US-centric calendar:
- **Novo Nordisk** — EarningsWhispers filed the release time as "12:35 PM ET" when the 6-K was
  already public by **03:06 ET** (AP filed at 3:06 a.m. ET). Issuer IR: announcement 04 Nov,
  call 13:00 CET / 07:00 ET.
- **Mitsui** — EarningsWhispers filed it "after the close"; Mitsui's own financial calendar says
  **Nov 4, 2026, 12:00 JST** = Nov 3 **22:00 ET** — published before the 06:00 ET fire. Treated as
  `already reported`.
- **Siemens Healthineers** — both aggregators said Nov 4; the company's IR says **Nov 5, 07:00 CET**.
  **Excluded** as a date error.

The rule: the local announcement time, converted to ET with `zoneinfo`, decides `pending` vs
`already reported` — and it is compared against the FIRE's scheduled instant, never the wall clock.

### 17. Source facts that cost the run time (NEW, in the skill spec)

- **EarningsWhispers company pages need a JS cookie.** Without one you get a 2 KB "needs cookies"
  page instead of the ~160 KB page. The wall sets `ewc=<reversed token>` and the token is inside
  the wall's own HTML — compute it offline and skip the browser. Check page LENGTH, not status.
- **Yahoo's earnings-calendar JSON endpoint is retired** (`v1/finance/calendar/earnings` → 404).
  Working replacement: `v10/finance/quoteSummary/<TICKER>?modules=earningsTrend` (period `0q`).
- **Nasdaq's calendar API has no revenue field** — EPS, BMO/AMC and fiscal quarter only.
- **Yahoo's `earningsTrend` for an ADR is in the ISSUER's currency** (NVO 73.40B = DKK; ITOCY and
  MITSY 4,013B = JPY), while EarningsWhispers' `Rev est` is USD even for ADRs. Prefer EW for
  revenue; label every foreign number with its currency.
- **stockanalysis.com** is the best non-US source overall: local listing, local-currency market cap,
  `earningsDate`, "Main Listing" link, and a filings feed that says whether results are already out.

### 18. Process rule — run the prompt's own fetch block verbatim

This run fetched `PROMPT-BLOCKS.md` with a two-URL snippet copied out of the file it had just
downloaded, instead of running the three-URL ladder the deployed prompt specifies. At 06:01 ET
both paths returned the same bytes, so nothing was lost — but the moment the shared file changed
(08:15 ET, when the dead `[ -s file ] || curl` loop was replaced) the copied snippet would have
been the stale path. **Run the fetch block in the prompt, not a snippet of the fetched file.**

### Artefact note

`earnings/2026-11-04-reminders.md` was re-pushed the same day with the primary-listing ticker
convention applied, so the published artifact matches the new rule.

---

## 2026-11-05/06 — ARTIFACT FORMAT CONTRACT v2: the roster becomes a SCREEN

Three gaps in the 2026-11-04 artifact were closed. The contract lives in the repo and is fetched at
RUN time, so **no `cron_update` was needed for the procedure change** — only the prompt's OUTPUT
block was re-deployed (see "Prompt deploy" below).

### 19. The roster had no ranking — reaction potential replaces market cap

Every name was equally weighted, so the table was a list. Every published row now carries:

| column | definition | source |
|---|---|---|
| `Prior day %` | last completed session's close-to-close move | Yahoo chart daily bars |
| `YTD %` | last close vs the first bar of the current calendar year | Yahoo chart daily bars |
| `Avg abs move %` | mean absolute reaction over the name's last 4 past reports | Nasdaq `earnings-surprise` report dates + Yahoo bars |
| `Implied move %` | ATM straddle at the first expiry that straddles the event, % of spot | Cboe delayed-quote option chain |
| `Prior result` | last reported quarter: beat / miss vs consensus EPS | Yahoo `earningsHistory` |
| `Reaction score` | `0.6 x avg_abs_move + 0.4 x implied_move` | derived |

The table is sorted by `Reaction score` DESCENDING. A missing implied move is substituted by
`avg_abs_move`, so a name with no derivable implied move scores exactly its `avg_abs_move`.

**The reaction window depends on the release convention:** BMO on day D -> `close(D-1) -> close(D)`;
AMC on day D -> `close(D) -> close(D+1)`. The name's CURRENT convention is applied to its history,
and a name that switched convention is called out in the notes rather than silently mixed.

`tools/earnings_reaction_stats.py` computes the columns (`REACTION_STATS_VERSION 2026-11-06.1`); it
returns JSON/CSV and NEVER writes the artifact. Measured on the 2026-11-06 roster, the ranking
inverts the market-cap order: CHTR (score 10.48, avg 9.23 / implied 12.35) and MRNA (5.58) lead,
while the $1.2T Berkshire is last.

### 20. Pass B — the non-US primary-listings table is a UNIVERSE, not a lookup

The 2026-11-04 artifact's non-US names only appeared when a US-listed name happened to report.
The spec now carries a **standing candidate universe of 42 large non-US primary listings**, each
checked every day against its own IR calendar, published in a separate table with
`ticker_primary | venue_primary | us_peer | us_tradeable`.

Every `ticker_primary` was re-fetched on Yahoo's chart API to prove it resolves (venue + local
currency + name), and every US line was resolved through the TradingView scanner, whose `type`
column separates a genuine ADR (`dr`) from an ordinary share (`stock`) — that is what decides
`us_tradeable`.

**The ADR-ticker traps that cost a wrong row:**
- **`AIRYY` is Air China, NOT Airbus.** Airbus' OTC line is `EADSY` (Yahoo also serves `EADSF`).
- `HTHTF`, `MEELY`, `TELLY`, `SSNNF` and `ROG.SW` do not resolve on Yahoo; the working symbols are
  `HTHIF`, `MIELF`, `TOELY`, `SSNLF`, `RO.SW`/`ROP.SW`.
- `TTE` is an ordinary-share line, not an ADR.

**The ET-day rule:** a Japanese issuer publishing at 15:00-16:00 JST on Nov 6 lands at
01:00-02:00 ET on Nov 6 (already published when a 06:00 ET reader opens the brief); at 07:00 JST it
lands at 17:00 ET on Nov 5 (the previous ET day). Convert with `zoneinfo`, never a fixed offset.

Measured on the universe for 2026-11-05/06: the IR-confirmed dates near the window are **KDDI
Nov 6** (issuer IR calendar + issuer newsroom: results announced Nov 6, webcast 16:00 JST =
02:00 ET), **Siemens Nov 12** (issuer press page, 07:00 CET = 01:00 ET), **Mitsubishi UFJ Nov 13**,
**Tencent Nov 18** (issuer page, 20:00 ET). **TSMC, Samsung, Toyota and Alibaba had no date on
their own IR pages** — an aggregator estimate is not a publishable date.

### 21. The $50B cliff is now published

The floor is a cliff decided by rounding. The artifact now carries a **"Just below the line"**
table: the largest COMMON shares in `[$40B, $50B)` that are not S&P 500 members, with a
`Reports today` column. Measured on 2026-11-06: TEVA $48.7B, FNV $48.4B, WCN $47.9B, TEAM $46.2B,
AU $44.7B, FER $42.3B, RKT $42.1B, SLF $40.9B.

The band is a **lower bound** on the excluded set and the notes say so. A roster row inside the
floor by less than **$0.5B** carries `boundary_case` in its `Flag` cell, so a marginal inclusion is
visible instead of having to be computed.

**Two traps the band exposed.** The TradingView scanner types several non-common lines as `stock`
with plain symbols, so the filter is on the DESCRIPTION, not the symbol: Prudential's "5.625%
Junior Subordinated Notes due 2058" and four sibling preferred lines each carry a ~$43.7B cap and
would otherwise fill the whole table with four rows of one company. And two rows of the same
issuer's share classes are one name — Berkshire's Class A and Class B both carry a ~$1.22T cap, so
the roster now publishes **one row per issuer** (the class the S&P 500 list carries).

### Verification is a machine check, not an eyeball

`tools/check_earnings_reminder_artifact.py` is an independent implementation of the contract. It
exits 1 and names every violation: a missing column, a roster not sorted by reaction score, a score
that does not match its inputs, an empty `us_peer`, a name published in both tables, a band row
that is not below the floor, a missing `boundary_case` flag, and a declared `reaction_degraded`
count that does not match the rows.

`tools/test_earnings_reminder_contract.py` runs 19 checks: 6 helper fixtures (BMO/AMC reaction
windows, the score formula, the OCC parser, a missing bar), 1 conforming artifact that must pass,
and **12 fault injections that must all fail** — including a no-op mutation guard, because a
mutation that does not change the text silently reports a false NOT CAUGHT.

### Prompt deploy (the paste drifted twice — and the SHA check caught both)

The #19 prompt's OUTPUT block was re-deployed twice:

1. **First paste** wrote the prompt as ONE LINE with literal `\n` characters: 19,049 B deployed vs
   18,702 B in the repo. **Second paste** landed the newlines but dropped a blank line and
   changed one word ("the" -> "its"), 18,701 B vs 18,702 B.
2. **Root cause:** `mcp_invoke` passes `arguments` **verbatim** — it does NOT JSON-unescape the
   values. So `"\n"` in a paste stays a literal backslash-n, and `"\\"` stays two backslashes.
   **Emit the prompt as RAW TEXT with real newlines and single backslashes.** A two-line probe
   (`PROBE_A\nPROBE_B`) proved the raw form round-trips exactly before the full paste.
3. **Resolution:** the repo was synced to the deployed bytes (one blank line and one word, both
   cosmetic) and re-pushed, so repo == remote blob == deployed prompt (18,701 B,
   sha256 `486808eb…`). **Do not re-paste for a cosmetic delta — write the deployed bytes back into
   the repo**, because the repo is what cron #91's drift guard hashes.

Blast radius: **one task** (cron #19, task `457569978294401`). Schedule `0 6 * * 1-5`, timezone
`America/New_York`, `enabled`, session `new`, model `MiniMax-M3.1-Flash` (thinking medium),
project `13835`, `created_at` and `next_run` all preserved. Fleet-wide prompt drift: 0 of 27.

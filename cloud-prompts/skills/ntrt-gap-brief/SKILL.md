---
name: NTRT gap brief
description: >-
  Produce a morning gapper brief from `karizaco/ntrt_mtrt` backend when it's
  reachable, or fall back to MCP-driven screener. Replaces the paused
  `ntrt-pre-market-brief-paused` Grok routine (paused pending URL).
  The artifact layout is pinned by the ARTIFACT FORMAT CONTRACT below — do not
  improvise the section order, the tables, or the numeric conventions.
---

## Scheduled-run conversation title (FIRST ACTION)

If this session was started by a scheduled cron run — the first message begins with
`# Cloud Mavis cron:` — set this conversation's title before doing anything else. Every scheduled
run gets its own conversation; it is never appended to an earlier run's conversation.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of that cron prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

If this session was NOT started by a scheduled cron run, ignore this section.

# NTRT gap brief

Generates the weekday pre-market gapper brief. Replaces the paused `ntrt-pre-market-brief-paused` Grok routine.

## When

- Cron: `0 9 * * 1-5` America/New_York (weekdays, 09:00 ET — 30 min before the US open)
- Manual: user asks "run the ntrt brief" or "what's gapping today"

## Backend discovery

- If env var `NTRT_BASE_URL` is set (e.g. `http://127.0.0.1:8000` or VPS URL), use it.
- Otherwise default to `http://127.0.0.1:8000`.
- If env var `NTRT_AUTH_TOKEN` is set, send `Authorization: Bearer <token>`.
- Probe `GET {base}/health` first. If not 200, fall back to MCP mode.

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-ntrt-premarket.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_
- **A machine-readable CSV companion ships alongside the markdown**, in the same output
  directory, named `{date}.csv`. Column contract in the format contract below. It carries the
  **full screen**; the markdown carries only the actionable subset. The two must never
  contradict each other.
- **The chat reply follows the shared `## DELIVERY` block** in
  `cloud-prompts/_shared/PROMPT-BLOCKS.md` — prose opener, then `### Signal`,
  `### Method & caveats`, `### Files`, `### Push / errors`. Do **not** invent a reply
  layout for this routine; the shared block is the fleet standard.

---

## ARTIFACT FORMAT CONTRACT (v4 — load-bearing)

This section is the reason the fleet's briefs stopped drifting. Earlier revisions left the
artifact layout to the run, and the last four briefs used **three different section
skeletons** (2026-10-29, 2026-11-02, 2026-11-03), so a reader had to re-learn the document
every morning. **Follow the structure below exactly.** Do not add, drop, or reorder sections.
If a section has nothing in it, say so in one line — do not delete the heading.

**v4 = v3 + §10 (the universe floor) + §11 (the pre-open tape) + §12 (the delta pull), and
three amendments to v3.** The section skeleton, the one-table rule and the CSV column contract
are unchanged. What v4 adds:

1. **The gate has a third leg** (§2): market cap ≥ $200M. The floor is now part of the GATE,
   not a filter hidden inside the scanner query — so the brief can publish the names the floor
   excluded instead of losing them silently.
2. **The actionable table is capped per direction** (§2), and everything the cap left out is
   listed by name under `### Also cleared the gate`. A cap may shorten the table; it may never
   silently drop a name.
3. **The pre-open catalyst tape** (§11) is the first place to look for a catalyst — it is
   already published, already sourced, and it covers the names the $200M floor excludes.

### 1. Section skeleton (fixed order)

```
# NTRT gap brief — <Weekday, DD Month YYYY>
<mode banner: 2 lines>
## TL;DR
## Market backdrop
## Yesterday's short list
## Worth your attention
## Wider screen
## Flags
## Method, source health & caveats
```

- **Title** — `# NTRT gap brief — Tuesday, 03 November 2026`. Weekday spelled out; it tells the
  reader which session this is without a lookup.
- **Mode banner** — exactly two lines, immediately under the title, before anything else:

  ```
  **Mode B — screener fallback.** TradingView public scanner; the ntrt backend was unreachable
  (`GET /health` → HTTP 000). Snapshot 09:07 ET, 23 min before the open.
  ```

  In Mode A the first line names the backend and drops the screener sentence. Always state
  the snapshot time — the tape moves and the reader needs to know how live it is.
- **`## TL;DR`** — **exactly 3 bullets**, each one line:
  1. What the tape is doing (the shape), with the name count.
  2. **The %ADV reality check** — how many names cleared 5% of ADV vs how many cleared the gap
     threshold. This bullet is what stops the reader treating the screen as 261 tradeable names.
  3. **The single most consequential name** and why. If you cannot name one, name the theme.
- **`## Market backdrop`** — its own section, near the top, not a bullet buried at the bottom.
  Futures, oil, rates, and the day's macro (an election, a central-bank decision, a scheduled
  release). 3–6 lines. This is context that changes how every gap in the brief should be read,
  so it must not be demoted into a caveat list. If the tape's moves are macro-driven, say so
  here — otherwise the reader will read every name as idiosyncratic when it is not.
- **`## Yesterday's short list`** — a follow-up, not a second gap table. See §13.
  The evening sweep's Tier-A names are a different job from this morning's
  gappers. This section asks, for each of those names, whether this morning's
  own screen had it. It does not rank them and it does not repeat a catalyst.
- **`## Worth your attention`** — the actionable set. **Two tables, gap-down then gap-up.**
  See §2. It ends with two subsections: **`### Also cleared the gate`** — the names the
  table's cap left out, listed so nothing is dropped silently (§2) — and the
  **`### Gap vs catalyst`** subsection, the asymmetry table (§8).
- **`## Wider screen`** — **the names not already shown above**, for completeness. Two tables,
  gap-down then gap-up, top 10 each by absolute gap **among the remaining names**. Columns:
  ticker, gap %, % of 30d ADV, sector. **No catalyst column here** — that is what makes this
  section short. Because these are the names that failed the actionable gate, they are mostly
  thin-book prints; that is the point of the section, and it is why they carry no catalyst.
  It ends with **`### Below the $200M floor`** — the watchlist of names the universe floor
  excluded (§10).
- **`## Flags`** — numbers a human should distrust, and why. See §5.
- **`## Method, source health & caveats`** — sources tried (and failed), filters held, the
  importance measure, what could not be verified. Ends with the audit line.

### 2. One table per name — the no-double-listing rule

**Each name appears exactly once in the markdown, in exactly one table.** A name that appears in
a ranking table, an importance table, and a catalysts section three times is unreadable and
pushes the artifact toward 200 lines. The 2026-11-03 brief put SHOP in six sections and DT in
five; that is the failure this rule exists to prevent.

- **The actionable gate** — a name is in `## Worth your attention` when it has
  `|gap| ≥ 3%` **AND** `% of 30d ADV ≥ 5%` **AND** `market cap ≥ $200M`. The 5% ADV floor
  is what separates a market from a quote: a ±20% gap on 350 shares is a quote, and publishing
  it as a headline is misleading. The **$200M market-cap floor is the third leg**: it is the
  universe floor, and because it is part of the GATE (not a filter hidden inside the scanner
  query) the names it excludes can be published in the §10 watchlist without counting as
  gate-passers.
- **Within each direction**, sort by **absolute gap descending** — biggest move first, so the
  reader's eye lands on the most consequential name first.
- **The table is capped at 20 names per direction.** A tape can put 40 names on one side (the
  2026-11-05 screen had 40 down and 29 up), and a table that long is not a triage. **What the
  cap leaves out is published, not dropped**: the `### Also cleared the gate` subsection, at the
  end of `## Worth your attention`, lists every remaining gate-passing name and states the
  count. The exact format, because the checker parses it:

  ```
  ### Also cleared the gate
  Gate-passing names not in the table above: <N>.
  No catalyst was looked up for them — they are listed so that a cap never silently drops a
  name: <TICKER>, <TICKER>, …
  ```

  The count line must start with `Gate-passing names not in the table above:` and the names
  follow in the same or the next line. **No catalyst lookup is required for these names** —
  they are explicitly unchecked, and they are NOT part of the §8 asymmetry universe.
- **The catalyst rides in the row.** One table, columns:
  `Ticker | Gap % | PM print | Prev close | % of 30d ADV | Mkt cap | Why`. The `Why` cell is
  **one line, ≤ 200 characters**, naming the trigger and the number that matters. Do not write
  an essay in a table cell — a cell that wraps to four lines destroys the table.
- **Do not add a separate `## Catalysts` section.** The catalyst is the last column of the
  table above. A second prose pass over the same names is the duplication this rule bans.
- **Look the catalyst up for every published name — the actionable set AND the wider screen.**
  A one-line lookup per name, not an investigation: the wider screen's names are what the §8
  asymmetry table is built from, and a name whose driver is unknown cannot be placed in a cell.
  The **deep-dive cap of 5 does not cap the catalyst lookups** (see Hard rules) — a deep dive
  is a dossier, a catalyst lookup is one search. **The §10 below-the-floor watchlist is the one
  exception**: it is a watchlist, not a triage, and it carries no catalyst lookup.
- The **full screen** — every name at ≥3% gap, including the sub-5%-ADV ones and the
  below-the-floor ones — lives in the **CSV**, not the markdown. The markdown is the triage;
  the CSV is the data.

### 3. Numeric conventions

Pin these so two runs are comparable and so the markdown and the CSV agree:

| field | convention | example |
|---|---|---|
| price | 2 decimal places, both markdown and CSV | `9.87`, `131.82` |
| gap % | 1 dp in markdown, 2 dp in CSV | `+33.4`, `-15.6` / `33.40`, `-15.62` |
| % of 30d ADV | 1 dp in markdown, 3 dp in CSV | `18.9`, `32.4` / `18.913` |
| volume | integer; thousands separators in markdown | `396.0K`, `1,133,057` |
| market cap | `$M` under $1B, `$B` under $1T, `$T` above | `$458M`, `$200.97B`, `$4.94T` |

Never publish 4-decimal prices (`9.8719`) or 3-decimal percentages in the markdown. The CSV
keeps extra decimals only on the one computed ratio (`pct_of_adv`); every quoted price is the
same 2 dp in both files, so a reader can match a row across the markdown and the CSV by eye.

**Scale the market cap to its own unit.** `$4937.50B` is unreadable, and a mega-cap's cap is
read in trillions. The rule is exact, because the checker enforces it: **no decimals under $1B
(`$458M`), two decimals from $1B to $1T (`$200.97B`), two decimals above $1T (`$4.94T`)**.
A value of 4,937,500,000,000 renders as `$4.94T` and never as `$4937.50B`.
**A cap under $1M — only reachable in the §10 below-the-floor watchlist — renders as
`<$1M`, never `$0M`.** Measured on the 2026-11-06 fire: DBGI ($438,749) published `$0M`, which
reads like a zero-cap company rather than a sub-$1M one. The delivered 2026-11-06 brief keeps
`$0M` (it is the artifact of record and is not rewritten), so this rule applies from the next
fire.

### 4. The CSV companion (column contract)

The CSV is the machine-readable twin of the screen. It carries **every** name at ≥3% gap, not
just the actionable ones — **including the names below the $200M floor**, because the screen is
scanned without the market-cap filter (§10). It must never contradict the markdown.

```
ticker,premarket_change_pct,premarket_close,prev_close,premarket_volume,avg_volume_30d,pct_of_adv,mkt_cap_usd,sector,exchange,catalyst,noise
```

- `pct_of_adv` — 3 decimals (`18.913`), computed as `premarket_volume / average_volume_30d_calc * 100`.
  When a name has **no 30-day ADV history** (`average_volume_30d_calc` is null or 0) the value is
  **empty, never 0** — an unmeasurable denominator is not a zero-volume name.
- `noise` — `true` when `pct_of_adv` is **empty or below 1**, `false` otherwise. A downstream
  consumer must be able to filter the quotes out without re-deriving the threshold, and a name
  with no ADV history must not slip through as "real" on an empty value.
- `catalyst` — one line, quoted. Empty string when no catalyst could be confirmed. **A blank
  cell means "not found", not "there wasn't one"** — say so in the markdown's Flags section.
  It carries a lookup for **every published name** (the actionable set and the wider screen),
  because the §8 asymmetry table is computed from this column.
  **The one exception is a below-the-floor watchlist row (§10): no lookup was done for it, so
  its cell reads `watchlist (not checked)`** — never blank, so a consumer can tell "not found"
  from "not looked up". If the pre-open tape (§11) supplied a driver for that name, the cell
  carries that driver instead.
- `prev_close` — the prior **regular** close, with its date in the column name avoided; the
  date is in the filename and in the markdown front matter. **Derive it, never take it from the
  screener's `close` column**: once the session is open that column is the live intraday price,
  not the prior close. Use `premarket_close / (1 + premarket_change / 100)` (verified on
  2026-11-05 against an independent quote source: SPY 766.81, QQQ 691.95, APP 271.75 — all three
  exact), or read the prior close from a quote source and derive `premarket_change` from it
  instead. One number per field, one source per field.
- **Prices in the CSV are carried to 2 decimals** (the traded cent), the same as the markdown.
  Only `pct_of_adv` keeps 3 decimals, because it is a computed ratio rather than a quoted
  price.
- Write it in the same output directory as the markdown, `{date}.csv`.

### 5. Flags vs. caveats — two different jobs

Do not merge them. A caveat is about **the data**; a flag is about **a number a reader should
distrust**.

- **`## Flags`** — per-name, and only per-name:
  - a catalyst you could **not** confirm (say so explicitly, and say what you checked);
  - a large gap on a **thin book** (state the % of ADV and the share count — a −16% gap on
    5,500 shares is a price one seller printed);
  - a name whose move **contradicts the fundamental** (a beat-and-raise that sold off);
  - a name that **left the screen** between pulls (its gap crossed back through the 3%
    threshold while it was still trading heavy volume — say the gap it faded from and to);
  - a name that **moved 3 points or more** between the screen pull and the §12 delta pull —
    say the gap it moved from and to;
  - a %ADV figure that is **arithmetically distorted** (a high % on a tiny absolute volume).
- **Method, source health & caveats** — about the run, not about names: which source served
  which field, what was unreachable, what the denominator is, what could not be verified.

Every flag names a ticker and states the number that makes it suspect. "Some names may be
thin" is not a flag; "CWH −10.7% on 3,300 shares = 0.1% of ADV" is.

### 6. Source health is mandatory

`## Method, source health & caveats` must name every source tried and its status. At minimum:
the primary screener (and whether it answered), the ntrt backend probe (and its HTTP status),
and any secondary source used for verification. A source that failed is reported as a failure
with its status code — never silently dropped, and never described as "unavailable" when it
returned an error you did not read.

### 7. One pull per brief — and the one exception

**The tape is live.** Pull it once and make every section agree with that one pull. If you
re-pull to verify a name, the **first pull wins** for the tables, and the prose must match it.
If the tape moved between pulls, say so in Flags rather than publishing two different numbers
for the same ticker. A brief that contradicts itself is worse than a brief with less in it.

**THE ONE EXCEPTION — the delta pull (§12).** A pull made at **~09:25 ET**, about five minutes
before the open, is used **only to flag movement**. It never changes a published number: the
tables keep the first pull's numbers, and the delta pull's values appear only in Flags, as the
gap it faded from and to. That is what makes the "a name left the screen" flag (§5) possible —
a flag the contract asks for and that a single pull can never produce.

**The pull must be COMPLETE.** The scanner's `range` is a page size, not a filter: a pull that
returns fewer rows than `totalCount` is TRUNCATED, and the missing names are silently absent.
Check `totalCount` against the number of rows returned on **both** sides, and if the pull
truncated, re-pull the missing slice (a second `range` starting at the offset) until the two
numbers agree. A truncated pull is a failed pull — say so in the source-health section rather
than publishing a screen that is quietly half a screen.

### 8. The gap-vs-catalyst split — publish the asymmetry

The screen is not the story. **The story is the asymmetry** between a gap, a driver and a
tradeable book: a +8% gap on no volume is not the same trade as a +4% gap on 20% of ADV.
Publish it as a 2×2 at the end of `## Worth your attention`, as the **`### Gap vs catalyst`**
subsection. The section skeleton does not change — this is a subsection, not a new `##`
section, and it is not a catalyst listing.

The format is exact:

```
### Gap vs catalyst
Universe: the <N> names checked for a catalyst (<A> actionable + <W> wider screen) out of <S> screen names.

| | Catalyst sourced | No catalyst |
|---|---|---|
| **Passes the actionable gate** | <count> — e.g. <TICKER> | <count> — e.g. <TICKER> |
| **Fails the gate** | <count> — e.g. <TICKER> | <count> — e.g. <TICKER> |
```

- **The universe is the names the brief CHECKED** — every name in `## Worth your attention` and
  every name in `## Wider screen`. Those are the names the reader can see, and every one of them
  has been looked up. **State the universe in the caption**: a table whose denominator is hidden
  is a table nobody can read.
- **Two kinds of name are NOT in the universe, and the caption must not imply otherwise**: the
  names the actionable table's cap left out (listed under `### Also cleared the gate`, no
  catalyst looked up) and the below-the-floor watchlist (§10, never candidates for the gate).
  If either exists, add it to the caption as a separate clause — "plus N names unchecked" and
  "plus N below the floor" — so the reader knows the table's denominator.
- **The catalyst axis is the CSV's `catalyst` column** — sourced = non-empty, not sourced =
  empty ("no catalyst could be confirmed"). The counts are therefore computable from the
  artifact's own tables plus its CSV, which is exactly what the checker does.
- **The gate axis is the actionable gate** (§2): passes = in `## Worth your attention`, fails =
  in `## Wider screen`. **Classify on the RAW CSV values, never on the published 1 dp number** —
  a name at 4.995% of ADV FAILS the gate even though the published cell reads `5.0`. When a
  published number reads like it passes while the name sits in the wider screen, say so in Flags.
- **One example per populated cell**, and the example must really sit in that cell. A cell with
  a count of 0 says `none`.
- What each cell means:

  | cell | meaning |
  |---|---|
  | passes the gate + catalyst sourced | **the tradeable set** |
  | passes the gate + no catalyst | **a gap with no driver — a warning, not a trade** |
  | fails the gate + catalyst sourced | **a missed opportunity** — there IS a driver, the book is too thin to trade it |
  | fails the gate + no catalyst | **noise** |

- One worked example (2026-11-05): 89 names checked out of a 481-name screen, and the split was
  **69 tradeable · 0 with no driver · 19 missed opportunities · 1 noise**. Read it as: the
  screen's 481 names were 69 trades and 412 warnings, and 19 of the warnings had a real driver
  behind them that the pre-market book could not trade.

### 9. The contract check runs every time — the contract is a gate, not a document

`tools/check_ntrt_artifact.py` asserts the sixteen rules of this contract against the
artifact you just wrote; `tools/test_ntrt_contract.py` proves that each of the sixteen checks
actually bites. **Fetch the checker at RUN time and run it BEFORE you push.** A run that fails
a check does not publish a failing artifact: fix the artifact and re-run.

```bash
C=/workspace/check_ntrt_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_ntrt_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_ntrt_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_ntrt_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  # The CAPABILITY check is mandatory: an OLDER copy of this script is still published
  # and it checks fewer rules, so without the marker a stale file can win the ladder
  # and report a clean artifact it never checked. The CDNs cache `main` independently,
  # so one of them CAN serve stale bytes - the contents API is not CDN-cached, so it is
  # tried FIRST. v1 checked 14 rules; v2 checks 16 - the marker is what tells them apart.
  if [ -s "$C.tmp" ] && ! head -c 200 "$C.tmp" | grep -q '"message"' \
     && grep -q 'NTRT_CONTRACT_CHECK_V2' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
if [ ! -s "$C" ] || ! grep -q 'NTRT_CONTRACT_CHECK_V2' "$C" 2>/dev/null; then
  echo "contract-check: UNAVAILABLE - publish the brief, report contract: NOT RUN, errors: 1"
else
  python3 "$C" --md "/workspace/ntrt/{date}.md" --csv "/workspace/ntrt/{date}.csv"
fi
```

(`{date}` is the fire's **scheduled** date in US/Eastern — the same value you used for the
`## OUTPUT` path in the cron prompt, not the wall clock.)

- **The checker's exit code is the gate.** Exit 0 → publish. Exit 1 → the artifact breaks the
  contract: **fix the artifact and re-run**. Never push a failing brief, and never paste the
  failure into the brief to make it pass.
- **An AMENDMENT AFTER A PUSH must be re-checked.** If you edit the artifact after pushing it —
  the 2026-11-06 fire added its `degraded_sources: 3` line in a second commit, 85 seconds after
  the first push — **re-run the checker against the amended file and re-push**. A byte that was
  never checked is not a checked byte, and the checker is the only thing standing between the
  artifact and the reader.
- **The reply publishes the count.** One line in `### Files`, after the file list:
  `contract: 17/17`. A reader must be able to see that the artifact was **verified**, not
  assumed. (The checker also accepts `--reply <file>` and verifies that published count — use
  it if you keep the reply text on disk.)
- **Publish the number the checker PRINTS.** The checker behind the `NTRT_CONTRACT_CHECK_V2`
  marker runs **17** checks, and `--reply` FAILS if the published pair is anything other than
  `17/17`. An earlier revision of this section said `16/16` — a run that followed it literally
  would fail the REPLY check even with every artifact check green. Read the count off the
  checker's own output line, never from memory.
- **If the checker cannot be fetched**: still deliver the brief, publish
  `contract: NOT RUN (checker fetch failed)` on that line, and count it in `errors:`. Never
  claim a check that did not run.
- The seventeen checks, in one place: `SECTIONS · SECTION_EMPTY · NO_CATALYSTS · ONE_NAME_ONCE ·
  MD_CSV_AGREE · CSV_CONTRACT · PCT_ADV_EMPTY · MKTCAP_FORMAT · NOISE_FLAG · TLDR_BULLETS ·
  TLDR_ADV_CHECK · GATE · FOURCELL · FOURCELL_EX · SUBFLOOR · ALSO_CLEARED · YESTERDAY`.
  `YESTERDAY` is the seventeenth — it arrived with §13 and this list was never updated.
  Verified 2026-11-10 against the checker's own `CONTRACT_CHECKS` constant.

---

### 10. The universe floor must not hide the day's biggest mover

The $200M market-cap floor is a **liquidity** floor, and a liquidity floor can hide the most
violent name of the day. Measured on the 2026-11-04 tape: **PARA −88.6%** on a $1.8M cap
(16.2M shares, 331% of ADV), **CRIS +87.7%**, **CENN −57.2%**, **DKI +54.0%**, **FTCI +44.8%**,
**HPAI +27.1%** — six of the day's most consequential prints, none of them in the brief,
because the floor excluded them before the brief ever saw them. (This is the same class of
bug as the REITs: a universe filter that silently deletes the biggest mover.)

**The fix has two halves, and both are required.**

1. **Scan without the cap.** The screener request does **not** filter on `market_cap_basic`
   (§Mode B). The $200M floor is applied **after** the scan, in post-processing, so no name is
   deleted by a filter on a column that can be null.
2. **Publish the watchlist.** `## Wider screen` ends with a `### Below the $200M floor`
   subsection: the **top 5 names per direction** among the ≥3% names the floor excluded.

   ```
   ### Below the $200M floor
   The names the universe floor EXCLUDED. Watchlist only — no catalyst was looked up, and
   these rows are not part of the asymmetry table above.

   | Ticker | Gap % | % of 30d ADV | Mkt cap | Note |
   |---|---|---|---|---|
   | PARA | -88.6 | 330.8 | $2M | Below the floor; the biggest mover of the day |
   ```

- **The watchlist is required when the floor hides the biggest mover.** If the largest |gap|
  among the below-the-floor names is bigger than the largest |gap| in the actionable table,
  the watchlist MUST be published — otherwise the floor has hidden the day's extreme. The
  checker enforces exactly this (`SUBFLOOR`), so a run cannot pass by staying quiet.
- **The watchlist is NOT part of the asymmetry universe** (§8): those names were never
  candidates for the gate, so they do not belong in the "fails the gate" cell. The §8 caption
  states the checked universe; add the watchlist's size to it as a separate clause.
- **No catalyst lookup for the watchlist.** Its CSV rows carry `watchlist (not checked)` in the
  `catalyst` column (§4), unless the pre-open tape (§11) supplied a driver for that name.
- The watchlist holds **at most 5 rows per direction**, and the checker enforces it: a
  watchlist that grows is a second screen.

### 13. Yesterday's short list — look it up, do not hope it overlaps

The 18:30 sweep publishes a short Tier-A list. This brief publishes who is
gapping this morning. Those are different jobs. A name is on both only if it
was a setup yesterday and is also moving today. Do not treat a zero overlap as
a finding about either list. Do the follow-up on purpose.

**Whose list.** The last `daily-screens/<date>/tier-a.csv` on
`karizaco/minimax-cloud-outputs` `main` whose date is strictly before this
brief's fire date. Walk back at most five weekdays. Fetch it the same way §11
fetches the pre-open tape, contents API first. If no file comes back, the
section is one line: `No Tier-A board was published before this morning.` Do
not invent names.

**What to ask of each name.** Look the ticker up in the CSV this run just
wrote. That is this morning's full screen, not the markdown triage.

| This morning | When |
|---|---|
| `gapping` | the name is in the CSV and the absolute pre-market change is at least 3 |
| `under the line` | the name is in the CSV and the print is under 3% either way |
| `not in the feed` | the name is not in the CSV |

`not in the feed` is not a flat. It means this morning's screen did not quote
the name. Say that in one sentence above the table, so a blank is not read as
a zero.

**Format.** One table, after `## Market backdrop` and before
`## Worth your attention`:

```
## Yesterday's short list

Prior board: `2026-11-05` (`daily-screens/2026-11-05/tier-a.csv`), 6 names.
Each name was looked up in this morning's full screen. This row does not
repeat a catalyst. If the name also cleared today's gate, the tables below
still carry that row.

| Ticker | This morning | Status |
|---|---|---|
| DUOL | +4.2 | gapping |
| KD | — | not in the feed |
```

The status cell is exactly one of `gapping`, `under the line`, `not in the feed`.
No other word. The checker reads that column (`YESTERDAY`).

This table is a follow-up, not a listing of today's gappers. It carries no Why
column. It is not part of the one-table rule for today's screen: a name may
appear here and also in `## Worth your attention`.

### 11. The pre-open catalyst tape — look here FIRST

Cron #92 (`preopen-catalyst-capture`) publishes a **catalyst tape** for the same session:
`preopen-feed/{date}-{HHMM}.jsonl` in `karizaco/minimax-cloud-outputs`, one file per checkpoint
(the slots are `0830`, `0920`, `0950`). The **08:30 ET checkpoint exists before this brief is
written** (09:00 ET), and it carries, per name: the pre-market print, a one-line `why`, a `cat`
(`acquisition | merger | earnings | guidance | fda | trial | offering | halt | downgrade |
guidance-cut | spin | dividend | other`), a `conf` (`high | medium | low`, plus `unverified` for a
claim the merge could not tie to the scanner) and a `ref` — **the source URL**. A record with no
source URL is written `conf: low`.

Measured on the 2026-11-04 tape: **678 rows, covering 63 of the 66** actionable names, with 12
sourced catalysts (DOX guidance-cut, ALIT beat-and-raise, DUOL, DDOG, HELE acquisition,
NRIX/Sanofi, RIOT, FSLR) — and it covers **PARA, CRIS and DKI**, the names the $200M floor hides.

**Fetch it before you search.** It replaces a dozen `web_search` calls with one HTTP GET, and
every catalyst it supplies already has a URL behind it. A human-readable digest sits beside the
tape as `{date}-{HHMM}.md` — read it first if you want the movers without parsing JSONL.

```bash
T=/workspace/preopen-0830.jsonl
for U in \
  "https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/preopen-feed/{date}-0830.jsonl" \
  "https://cdn.jsdelivr.net/gh/karizaco/minimax-cloud-outputs@main/preopen-feed/{date}-0830.jsonl" ; do
  curl -sL --max-time 30 -o "$T.tmp" "$U" 2>/dev/null
  if [ -s "$T.tmp" ] && head -c 200 "$T.tmp" | grep -q '"ticker"'; then mv -f "$T.tmp" "$T"; break; fi
  rm -f "$T.tmp"
done
```

- **The tape is optional and it fails closed.** Cron #92 writes nothing when its key is
  unusable, so the file may simply not exist. **That is not an error** — fall back to
  `web_search` for the catalyst and record `pre-open tape: absent` in the source-health
  section. Never invent a tape.
- **A tape of ~120 rows is a REGRESSION SIGNATURE** — the checkpoint sorted by volume instead of
  by move. Do not treat a short tape as the day's screen — fall back to `web_search` and say so.
  **The tape's size is #92's to define, not this skill's**: it was 678 rows on 2026-11-04 and 700
  on 2026-11-05 under the old ±3% snapshot, and **849 on 2026-11-06** when #92's movers-sorted
  ±2.5% snapshot landed. A tape **longer** than the old band is normal, not a deviation; only a
  ~120-row tape is. Read the expected size out of `cloud-prompts/_shared/preopen-capture.md`
  (`PROCEDURE_VERSION`) if you need to quote it.
- **A short tape is not a screen.** Measured on the 2026-11-10 fire: the 08:30 checkpoint came
  back with **49 rows** — well under the size of a movers-sorted snapshot — and it covered only
  6 of the 50 published names, **none of which carried a source URL**. With no `ref`, §11's rule
  forbids publishing the tape's `why` as a catalyst, so a short tape means every catalyst has to
  come from a search instead. Say `pre-open tape: short (N rows)` in the source-health section
  and count it as a degraded source.
- **A tape row is a lead, not a verdict.** Use the tape's `why` as the catalyst **only when it
  carries a `ref` URL and its `conf` is not `low`**; then the cell names the driver and the
  source URL. For `conf: unverified` or a missing `ref`, **verify it with one fetch of the URL**
  before publishing it, or leave the cell blank and flag the name.
- **The tape's price is a second opinion, not the price of record.** It was pulled at 08:30 and
  the screen at ~09:04; the same name can differ by several points. The **screener's** number is
  what the brief publishes. A gap between the two is a **movement flag** (§12), not a correction.
- **The tape also names the below-the-floor movers** (§10) — use it for the watchlist's `Note`
  column where it has a driver.

### 12. The delta pull — flag movement, never re-publish it

Take **one more pull at ~09:25 ET**, five minutes before the open, and use it for **nothing but
flags**. It exists because the pre-market tape moves while the brief is being written: on
2026-11-04 PARA went −51% (07:13) → −57% (07:45) → −88.6% (09:35), and a name that had not
gapped at all when the screen was pulled (SUPN) was at −35% an hour later.

- The **tables keep the first pull's numbers.** The delta pull's values appear only in Flags,
  as the gap a name faded from and to.
- **The flag to write:** any published name whose gap moved **≥ 3 points** between the two
  pulls, or that crossed the 3% band in either direction. Name the ticker and both numbers.
- **A truncated delta pull is not a flag** — check `totalCount` against the rows returned
  (§7) and skip the flag if the pull did not complete.
- If the delta pull could not be made (the network failed), **say so in Flags** — one line — and
  carry on. Never publish a number from the delta pull.
- **A LATE delta pull is still worth taking.** The 09:25 window is a target, not a gate: a run
  whose own latency (50 catalyst lookups, the contract check) carries it to 09:30 can still take
  the pull, because TradingView keeps serving the last pre-market print for a short while after
  the open. Take it, use it for flags only, and **state the actual pull time in Flags** — a pull
  taken after the open may already include the opening trade, and the reader has to know that.
  Measured on the 2026-11-10 fire: the pull landed at 09:32 ET and produced 16 movement flags
  the 09:03 pull alone could not show (PXLW +18.9% → +38.3%, APPS −23.0% → −26.8%, SECZ
  +29.3% → +26.0%, and two names crossing back out of the screen).


---

## Steps

### Mode A: backend up

1. `GET {base}/health` → confirm 200.
2. `GET {base}/api/agent/briefing` (or MCP tool `get_briefing`) — drop any huge `llm_briefing` blob; use structured sections only.
3. `GET {base}/api/gappers?min_pct=3&direction=both&limit=20` (or MCP `list_gappers` with `min_pct=3`, `limit=20`).
4. Optional: pull premarket catalyst endpoints if present, or MCP `list_premarket_catalysts` then `watchlist_premarket`.
5. Cap deep dives at top 5 by importance: `GET /api/dossier/{ticker}` or MCP `explain_gap` / `explain_premarket`.

### Mode B: backend down → TradingView screener fallback

**Prefer the PUBLIC screener endpoint over the MCP tool.** The MCP tool
`mcp__tradingview_advanced__screen_stocks` is frequently NOT registered in the Cloud runtime
(verified 2026-11-01: catalog 133 tools, 0 finance). The public HTTP endpoint returns the same
columns — **including `premarket_volume`, which the MCP tool and every other free source omit** —
so the endpoint is the better path even where the MCP tool exists.

`POST https://scanner.tradingview.com/america/scan` with `Content-Type: application/json`,
`User-Agent: Mozilla/5.0`, `Origin: https://www.tradingview.com`:

```json
{"filter":[{"left":"type","operation":"equal","right":"stock"},
           {"left":"exchange","operation":"not_in_range","right":["OTC"]},
           {"left":"premarket_change","operation":"in_range","right":[3,1000]}],
 "options":{"lang":"en"},"markets":["america"],
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","close","premarket_close","premarket_change","premarket_volume",
            "market_cap_basic","average_volume_30d_calc","relative_volume_10d_calc",
            "sector","exchange"],
 "sort":{"sortBy":"premarket_change","sortOrder":"desc"},"range":[0,2000]}
```

**The market-cap filter is NOT in the request.** The $200M floor is applied **after** the scan
(§10): a filter on `market_cap_basic` deletes the name outright — including the day's biggest
mover — and the column can be null, which deletes a name the floor would have kept. Scan wide,
filter in post-processing.

**`range` is a page size, not a filter.** With the cap removed the ≥3% universe runs to ~1,000
names on a busy day, and a `range` of 600 truncates the gainers side silently: measured
2026-11-04, the unfiltered descending pull returned exactly 600 rows against a larger
`totalCount`. Use `range: [0,2000]`, and **check `totalCount` against the number of rows
returned on both sides**. If they differ, the pull is truncated — pull the missing slice with
a second `range` starting at the offset until they agree. A truncated pull is a failed pull.

Run it **twice** — once with `premarket_change` in `[3,1000]` (desc) and once in `[-1000,-3]`
(asc) — so both sides are carried. A single descending sort publishes only gainers.

Critical filter notes:

- **`type: "stock"` INCLUDES REITs.** Do not re-filter the result to common stock. A universe
  seeded on common stock only silently drops REITs — on 2026-10-30 that hid **ARI (-63.9%)**,
  the largest mover of the day.
- `exchange != OTC` is the other server-side floor, and it is kept. `market_cap_basic >= 200000000`
  was the third floor; it is now applied in post-processing, not in the query (§10).
- `market_cap_basic` is USD-normalised for US listings.
- **A gap can cross the 3% threshold between two pulls.** A name in one pull may be absent from
  the next. Never say "the screen did not contain X" without a per-ticker re-check
  (`{"left":"name","operation":"equal","right":"TICKER"}`) — it may simply have crossed the band.
  If a notable name leaves the screen, that is a Flag, not a silence.

Columns and what they are worth:

| column | use |
|---|---|
| `premarket_change` | the gap % vs the prior regular close — the brief's headline number |
| `premarket_close` | the pre-market print |
| `premarket_volume` | **pre-market shares — the importance measure.** Divide by `average_volume_30d_calc` for % of ADV. A ±20% gap on 100 shares is a quote, not a market. |
| `average_volume_30d_calc` | 30-session average daily volume (a daily proxy, not intraday) |
| `relative_volume_10d_calc` | TradingView's 10-day relative volume — also a daily proxy |
| `close` | **NOT the prior close.** Once the regular session is open this column carries the LIVE intraday price (verified 2026-11-05: SPY `close` 754.64 against the 04 Nov close of 766.81; QQQ `close` 667.905 against 691.95). See the derivation rule below. |

1. Screen with the filters above, then carry **both** sides. Rank by absolute `premarket_change`;
   a descending-only sort would hide the day's largest decliners. **Check the pull is complete**
   (`totalCount` vs rows returned, §7) and apply the $200M floor **after** the scan (§10).
2. **Fetch the pre-open catalyst tape (§11) before you search.** Use its sourced `why` + `ref`
   for the names it covers; look up the rest with `web_search` for `"<TICKER>" news catalyst
   <today>` (past 12 hours). A name with no confirmed catalyst keeps its row and is flagged — an
   empty `Why` cell must never be filled with a guess.
3. Surface what you have; clearly mark this as the screener fallback in the brief header.

### Mode B2: reconstructing a PAST session (a missed or delayed run)

If this brief is being rebuilt for a date that has already traded, TradingView's `premarket_*`
columns hold only the **most recent** session — so they are the right source for the last session
before today, and for anything older they are gone. For an older date:

- `premarketprice.com/premarket-gainers/<YYYY-MM-DD>` and `.../premarket-losers/<YYYY-MM-DD>`
  keep **date-stamped** archives with price, % change and RVOL. Use them to validate.
- Chartmill publishes dated articles (`Premarket Gainers and Losers on <date>`,
  `S&P 500 Premarket Movers: <date>`) with per-name pre-market prices and %.
- Yahoo `v8/finance/chart` / `v7/finance/spark` with `includePrePost=true` reconstruct the
  pre-market TAPE from 5-minute bars, but **`volume` is 0 on every pre-market bar** and the tape
  goes **stale** for thinly-traded names (a flat print left from hours earlier). Never publish a
  Yahoo pre-market price without checking it against the printed table, and never publish a
  Yahoo pre-market **range** for a name where the two sources disagree by more than ~0.6%.
- A reconstruction produced late is not an error — say so in the mode banner and rebuild for the
  **scheduled** date.

### Always

6. Compose the brief against the **ARTIFACT FORMAT CONTRACT** above. Section order, the one-table
   rule, the numeric conventions, the §8 asymmetry table, the §10 watchlist, the §12 delta-pull
   flags and the CSV column contract are all load-bearing.
7. Write **both** outputs: the markdown to the `## OUTPUT` path in the cron prompt, and the CSV
   beside it. Never overwrite a prior date's file.
8. **Run the contract checker (§9) on both files.** Exit 0 → publish. Exit 1 → fix the artifact
   and re-run; a failing brief is not pushed.
9. Append audit line: `brief_rendered target=ntrt-premarket:<date> mode=<A|B>`.

## Failure modes

- Backend down / connection refused → automatically try Mode B (MCP fallback). If both fail, write a short file noting both unavailable, do not invent data.
- Empty results on weekend/holiday → one-line quiet note (still write the file).
- Rate limits → stop extra dossier calls; deliver what you have.
- Auth 401/403 → report, don't retry in a loop.
- **Layout drift** → the section skeleton and the one-table rule exist because four briefs ran
  three different layouts. A run that invents its own structure is a failure, not a variation.
- **Double-listing** → a ticker appearing in two tables and a prose section is the same failure
  in miniature. Fix the layout, not the word count.
- **Two pulls, two numbers** → the tape moved mid-run and the prose took a different pull from
  the tables. One pull per brief; the first pull wins; note the movement in Flags. The §12
  delta pull is the only exception, and it never publishes a number.
- **A truncated pull** → `totalCount` did not match the rows returned, so the screen is quietly
  half a screen. Pull the missing slice (§7) or report the pull as failed. Never publish it.
- **The pre-open tape is absent** → cron #92 failed closed and wrote nothing. Not an error:
  fall back to `web_search` and record `pre-open tape: absent` in the source-health section.
- **The floor hid the biggest mover** → a below-the-floor name gapped harder than anything in
  the actionable table and the watchlist was not published. That is a `SUBFLOOR` failure; the
  watchlist is required (§10).
- **A catalyst asserted but not sourced** → an empty `Why` cell filled with a plausible story is
  fabrication. Leave it blank and flag it.
- **The checker fails** → the artifact breaks the contract. Fix the ARTIFACT, not the checker,
  and never weaken a check to make a brief pass. If the checker itself is unavailable, say so
  (`contract: NOT RUN`) and count it in `errors:`.

## Hard rules

- Never place trades.
- Do not scrape TipRanks/Yahoo in the browser when the API is up.
- Do not fan out to other trading agents unless the user explicitly asks.
- **Hard cap deep dives at 5 per run.** A *deep dive* is a dossier or multi-source investigation
  of one name (`/api/dossier/{ticker}`, `explain_gap`). It is **not** the one-line catalyst
  lookup that every published name needs — that is one search per name and is required by §2.
  Do not cap the catalyst column at 5; cap the investigations. The catalyst lookups cover
  **every** published name: the actionable set **and** the wider screen, because §8's table
  cannot place a name whose driver was never looked up.
- **Never publish a number you did not pull from a source you can name.** Every gap, price,
  volume and %ADV in the markdown and the CSV comes from the screener pull or a named
  verification source.
- **The universe floor never hides the day's biggest mover.** Scan without the market-cap
  filter and publish the `### Below the $200M floor` watchlist when the floor hides a mover
  bigger than the table's own (§10). The checker enforces it.
- **A pull must be complete.** `totalCount` vs rows returned, both sides (§7). A truncated
  screen is not a screen.
- **Do not publish a Yahoo pre-market price or range** without checking it against the printed
  table; Yahoo's pre-market tape goes stale on thin names.

## Out of scope

- Long-form analyst notes per ticker — only short, structured fields.
- Cross-broker or cross-asset class research — only US equities.

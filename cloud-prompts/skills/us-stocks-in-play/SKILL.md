---
name: US stocks in play
description: >-
  Weekday US (NYSE/NASDAQ/AMEX + liquid OTC + major ETFs) in-play scanner:
  pre-close (~15:50 ET) and midday (~12:30 ET) digests. Uses
  TradingView-advanced + Yahoo Finance MCPs, falls back to Finviz/Barchart
  browser only on block. Tier A → Soft-A → TECH_WATCH → B → C, USD session
  $ volume sort. Quiet chat unless actionable. Cron weekdays 15:50 ET.
---

# US stocks in play

Scan US equities that are actionable right now (gaps, unusual volume, breakouts, material news, halts) — weekday pre-close (~15:50, the deployed slot) and midday (~12:30) America/New_York digests. Uses the shared `stocks-in-play-pipeline` skill for normalize→merge, Soft-A, TECH_WATCH, holiday skip, source-health table, and chat rules.

**Finviz Elite is optional.** Free Finviz (~1 minute delayed) is enough for digests. Barchart is never required paid.

## Shared pipeline

Always run `stocks-in-play-pipeline` **after** gathering sources and **before** writing the dated digest. That pipeline covers Soft-A tiering, holiday skip, source health table, overnight carry, fetch→browser fallback, and stricter chat rules.

## Prior-digest continuity and research scoping (required)

This routine fires into a repo that already holds the previous slot's digest. **Read it before
researching anything.**

1. **Read the most recent prior digest** in `us-stocks-in-play/` from the output repo, plus the
   prior slot's screen CSV if present. From a shallow clone,
   `git show origin/main:us-stocks-in-play/<file>` is enough; the slot is named in the title.
2. **Build a `changed_since` list**: names new to the screen, plus names whose move changed by
   ≥ 3pp since the prior pull, plus any name whose tier moved.
3. **Scope catalyst research to that list.** Do **not** re-verify a catalyst the prior digest
   already documented with figures — cite it and move on. Re-verifying Intel or Reddit when
   yesterday's digest already carries the guidance and the consensus numbers is the single
   largest waste of a slot, and it crowds out the names that actually changed.
4. **Publish the delta.** The digest must carry a "what changed since the <prior slot> digest"
   section: the `changed_since` list with the move at each pull, and the names that were new.
   This section is usually more useful to a reader than the full board.

## TradingView-advanced MCP rate-limit

When calling `mcp__tradingview-advanced__run_screener` / `get_symbol_data` / `get_news` / `get_symbol_data_batch`, follow pipeline §2b:

1. **One** US `run_screener` for core movers, OR HTML movers seed with **no** screener at all.
2. On HTTP 429 or empty screener: **STOP** further screener retries.
3. Quotes: **one** `get_symbol_data_batch` (≤50, `NASDAQ:`/`NYSE:`/`AMEX:` prefixed) on the merged candidate set → serial `get_symbol_data` only for batch `missing` (cap ≤10); prefer Yahoo/local confirm.
4. `get_news` only for top floor-cleared candidates (cap ~5–8); local catalysts first.
5. Soft target ≤12–15 TV MCP calls per slot. Log 429 once in Source health.

## Universe

**Include:**
- Common stock on NYSE, NASDAQ, AMEX / NYSE American
- OTC / pink sheets only when they clear a hard $ volume gate (e.g. FNMA, liquid cannabis)
- Major ETFs (SPY, QQQ, IWM, DIA, sector SPDRs, GLD, TLT, similar broad/sector/commodity/bond ETFs)

**Exclude:**
- Leveraged / inverse / single-stock leveraged ETFs (2x/3x, Ultra, Direxion, ProShares single-name levered)
- Warrants, rights, units (suffix / name heuristics: `W`, `WS`, `.W`, `U`)
- Preferreds
- Blank-check SPACs (pre-deal); post-deal operating cos OK if liquid
- Illiquid OTC that fails the $ volume gate

**Dedupe:**
- Dual-class: one line (more liquid class)
- Canadian interlisted: US line only
- ADRs: include if liquid; tag as ADR

## Noise filters

- Prefer session USD volume for ranking (not share count alone).
- Strip warrants/units from halt feeds.
- Low float (<10–20M): flag, don't auto-promote.
- Reverse-split artifacts: down-rank ~5–10 sessions.
- Dilution / ATM / registered direct: tag and down-rank long-bias chase.
- Premarket % with token volume: ignore until PM $ vol clears.

## Definition

A name is **in play** when there is a fresh, tradeable reason to look **now**: price/volume dislocation and/or material catalyst — not hype alone.

### Liquidity floor (required)

| Filter | Pre-close ~15:50 ET (deployed) | Midday ~12:30 ET |
|---|---|---|
| Price | ≥ $1 | ≥ $1 |
| Market cap | ≥ $50m soft | same |
| Session $ volume | ≥ ~$2–5m | ≥ ~$2–5m |
| OTC / pink | Session $ vol ≥ ~$1–2m | same spirit |
| RVol | Soft preference ≥ ~1.5–2× if available | same |

`preclose` and `midday` share the same dollar-volume bar because both read a **full session's**
turnover. The `open` slot was lower (~$0.5–1m) only because it ran 20 minutes into the session;
that number must not be applied at pre-close, where it admits every micro-float that printed a
few million dollars on a quiet tape.

### Slot resolution (required)

The **deployed schedule determines the slot** — not the slot a previous run used. Map the fire
time to the nearest defined slot and apply that slot's floors and triggers.

| Fire time (ET) | Slot | Session $ volume floor |
|---|---|---|
| ~15:50 (deployed) | `preclose` | ≥ ~$2–5m (full session) |
| ~12:30 | `midday` | ≥ ~$2–5m (full session) |
| ~09:50 | `open` (not deployed) | ≥ ~$0.5–1m (partial session) |

**Pre-close timing caveat:** the `preclose` slot fires ~10 minutes **before** the 16:00 ET bell,
so the regular-session close is **not final at fire time**. Take the settled close from the
post-bell print — the cloud RUNTIME-CONTRACT documents the source whose `primaryData` field flips
to the after-hours print at 16:00 — and state in the artifact whether the numbers are live
intraday or settled.

### Pre-close two-phase procedure (required)

The `preclose` slot straddles the bell, so run it in two phases and publish **one** digest:

- **Phase 1 (~15:52, live intraday):** discovery, the universe and the floors, the intraday path
  (open → high → low → where it trades now), the gap annex, and catalyst research. Record the
  live price and its timestamp.
- **Phase 2 (after the 16:00 bell, ~16:02):** re-price the tiered names for the **settled**
  regular-session close and the settled session volume, recompute RVol on the settled volume, and
  take the close from the source's post-bell, field-flip-safe field. Re-check any name whose tier
  moved on the settled numbers.

The artifact must state that the numbers are **settled**, and the gap annex must separate a gap
that **held into the bell** from one that faded. Never publish an intraday price labelled as a
close. Do not wait for the after-close earnings slate — the fleet's post-market brief owns that;
the carry hands off to it.

### Gap provenance — the missing mechanism (required)

The gap rules above **mandate a computation that nothing else in the fleet performs**: whether a
gap held into the bell or faded, and what the catalyst was *at the open*. Compute it with the
shared helper, which rebuilds the intraday path from 5-minute bars and joins an optional
catalyst feed:

```bash
python3 /workspace/preopen_feed.py merge --date <YYYY-MM-DD> --symbols <A,B,C>
```

| verdict | meaning | treatment |
|---|---|---|
| `reverse` | the opening move flipped sign | strongest in-play signal; the gap and the tape disagree |
| `faded` | the opening move was substantially given back | in play, but the open buyer is gone |
| `held` | the move is largely intact | a trend, not a squeeze-and-fade |
| `no_move` | the open was inside the noise band | no gap to read; judge on the catalyst alone |

- The **catalyst feed is optional**. Without it the path and the verdict still stand — the verdict
  comes from 5-minute bars, not from the feed.
- Feed **prices are never trusted**: >2pp disagreement with the bars or the scanner ⇒ `unverified`.
- The helper's **premarket columns are LIVE ONLY** and come back blank for a past date. The
  09:30 / 10:00 / 12:00 path from 5-minute bars is historical and always valid.
- Tag affected names in the artifact and in chat: `GAP_FADED`, `REVERSED`.
- Self-test: `python3 /workspace/preopen_feed.py selftest` runs four known sessions and must
  print 4 PASS.

### Triggers (≥1 after the floor)

| Trigger | Guidance |
|---|---|
| Gap | ≥ ~3–5% vs prior close; prefer PM $ vol ≥ ~$200k when PM data exists. At pre-close, a gap that **held into the bell** is the signal; a gap that faded is not |
| Day move | |chg%| ≥ 5% large/liquid; ≥ 8% smaller (soft 3–5% with strong tape OK) |
| Unusual volume | When RVol is available and meaningful — bonus, not a must |
| Breakout / breakdown | Day high/low vs prior range with volume |
| Catalyst | Material 8-K / PR / major news (see include/exclude) |
| Halt / resume | LULD or news halt — candidate on resume if liquid |
| Buyout / deal | Special rule below — not automatic in-play |

### Catalyst include

Earnings / guidance surprises; M&A / strategic review (non-arb); material contracts; FDA/regulatory when confirmed; officer/governance shocks; halt news; price-sensitive 8-K items (1.01, 2.01, 5.02, 7.01, 8.01).

### Catalyst exclude / down-rank

Routine admin; empty IR calendar; chat/Stocktwits as sole source; near-offer buyout arb; pure ATM/offering dumps without a tradeable bounce thesis.

### Buyout / near-offer rule

| Situation | Treatment |
|---|---|
| Trading near stated cash deal / tight collar | Exclude / down-rank — sideways arb, not chase |
| Fresh deal with wide gap to terms | Tier C gap/halt watch only — not Tier A / Soft-A / B momentum |
| Contested / raised bid with real non-arb tape | C, or B only if independent liquidity + move |

Never promote solely because a buyout was announced.

### Ranking and sort

1. Tier A → Soft-A → TECH_WATCH → B → C.
2. Within tier: USD session $ volume descending.
3. Cap ~8–10 names (+ short halt/gap annex). Tag ETF, OTC, ADR, DILUTION, BUYOUT_GAP, SOFT_A, halt reason when relevant.

## TECH_WATCH tier (technical Soft-B)

Between Soft-A and B. For liquid technical setups that fail a hard pure-technical RVol bar but clearly trade on size (continuation / episodic pivot, bottom bounce, HTF breakout, unusual strength without fresh catalyst).

**Eligibility (all required):**
- Liquidity floors for the slot
- Day-move or gap meets soft guidance
- Session turnover ≥ slot floor — prefer USD dollar volume
- Soft / missing RVol or roughly 1.0–2.0×
- No same-session catalyst required
- Tag `TECH_WATCH`

**Sort:** after Soft-A, before B, by session turnover descending.

**Chat:** include material TECH_WATCH on midday / manual when turnover clearly clears the midday-scale floor; at the deployed pre-close slot, only if turnover already clears the midday-scale floor (~$2–5m).

## Persistence

Save every run to:

`C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`

- `<slot>` = `preclose` (~15:50, the deployed slot), `midday` (~12:30), or `manual`
- Include: run time ET, session state, sort note, tier tables, PM gap annex, halt watch, source health table, sources
- When after-close / AH 8-K / PR material catalysts exist, require an `overnight_carry` section
- **The `preclose` carry is written before tonight's prints.** Name the watch list — the scheduled
  reporters that intersect with today's tape — and say plainly that the results land after the
  carry is written. Do not guess the results and do not list every reporter: the fleet's
  post-market brief owns the after-close earnings reactions, so the carry's job is to hand off,
  not to duplicate.
- Include the fuel-log line in `us-stocks-in-play/logs.jsonl` in the digest's file list
- On the pre-close slot: load prior digest's `overnight_carry` into the Overnight → pre-close annex
- **Chat only if** any Tier A or Soft-A, material TECH_WATCH, or material Tier C

## Source stack

For each source: try HTTP fetch / API first; **if fetch blocked → open that URL only in the headed desktop browser**, scrape what you need, continue.

### Pass 1 — Movers (RTH)

1. **Yahoo** predefined JSON: `day_gainers`, `day_losers`, `most_actives`, `small_cap_gainers` (primary discovery).
2. **Finviz screener** (when HTML table renders): top gainers / losers / unusual volume / most active.
3. **TradingView-advanced MCP** — optional corroboration, under pipeline §2b budget.
4. **MCP-over-HTTP bridge** (see the cloud RUNTIME-CONTRACT): `market-recap` pack `get_quotes` / `top_movers` / `market_snapshot`, plus `stocktwits` and `shibui`. Reachable over plain HTTPS JSON-RPC with no agent.minimax.io registration — preferred over raw Yahoo because it is not rate-limited and returns `as_of` + `market_state` with every quote.
5. **TradingView scanner API** `POST https://scanner.tradingview.com/america/scan` — movers, `relative_volume_10d_calc` (RVol), `market_cap_basic`, `halted`, and `premarket_change`/`premarket_volume`/`premarket_close` in one call.

### Pass 1 screening rule (required)

Discover on the **trigger**, not on the close-to-close move. A name that gapped +4% and closed
+3.5% on heavy volume is in play; a name that closed flat after gapping +9% and fading is not.

1. Screen the universe for `(|change| >= 3%) OR (|gap| >= 3%)`. Do **not** screen on
   `|change| >= 5%` alone — that silently drops every gap-and-fade and every gap-that-held.
2. Apply the slot's floors (price, market cap, session $ volume) to the survivors.
3. **Price every survivor.** Do not cap the screen at "the top N by dollar volume": a mid-cap
   with a real 8-K routinely sits below that cap, and a silent cap is an invisible hole in the
   digest. If a cap is genuinely unavoidable, state it in the artifact along with the
   **priced / unpriced counts** and which candidates the cap dropped.
4. Record in the artifact: universe size, survivors after the trigger, survivors after the
   floors, number priced, number tiered.
5. Compute RVol as session volume ÷ the **trailing 10 settled sessions from the same series**
   and state that denominator. A screener's own RVol column uses a different denominator and is
   not comparable across sources.

#### RVol and session volume: use the market-wide feed, not per-symbol history (2026-11-03)

**Do NOT pull one `chart_data` call per ticker.** Each is one metered gateway call and the
anonymous Pipeworx allowance is **50 calls/day shared across the whole fleet** — a 209-name RVol
denominator alone burned 245 calls and exhausted the pool mid-run.

Use the shared helper `_shared/rvol_fetch.py` (polygon-io `grouped_daily`): **one call returns
OHLCV for every US symbol for one date**, so ten calls give a trailing-10-session volume
denominator for the whole market. It reproduces the `chart_data` denominator to **0.000075%**
across 209 names, so RVol stays comparable with previously published digests.

**The helper is a separate file and is NOT on disk in a fresh sandbox — fetch it first:**

```bash
D=/workspace/rvol_fetch.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/rvol_fetch.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/rvol_fetch.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/rvol_fetch.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "rvol_fetch.py fetch FAILED - fall back to the caller's own denominator source"
python3 "$RF" --date <YYYY-MM-DD> --sessions 10 --out /workspace/avg10.json
```

It is serialized internally (~13 s between calls — Massive's shared key allows 5 req/min) and
retries on HTTP 429, so a 10-session pull takes ~2.5 minutes.

**The session-volume numerator must be SETTLED.** A volume read from the quote bridge at
~16:01 ET is **not final** — the closing auction consolidates later. **`grouped_daily` may not have
published the bar for the session you are running** (measured 2026-11-03: six attempts over ~10
minutes, upstream had not consolidated it) — the denominator is unaffected because it excludes
today by construction, but the numerator needs a settled fallback (shibui, or Yahoo's daily bar
with a `ts >= 20:00Z` settle test). Measured 2026-11-02:
published volumes ran **0.7%–30.2% low** (median ~8%) versus the settled figure, and because
RVol divides by a fixed denominator, **RVol is understated too** — 7 names crossed the Tier-A
RVol ≥ 2.0 threshold once settled (EL 1.96→2.32, NXT 1.85→2.26, VG 1.73→2.16, CRH 1.47→2.11,
FROG 1.82→2.07, VLTO 1.56→2.05, ABNB 1.51→2.03). Dollar volume is understated by the same
factor, which also shifts the within-tier ranking.

So: take the numerator from `polygon-io grouped_daily` (which also returns `o/h/l/c`, so one call
cross-checks the whole day's settled close) or from shibui — **not** from a 16:01 ET bridge
snapshot. If a live snapshot volume is published, label it as such in the artifact and treat its
RVol as a floor. See `_shared/RUNTIME-CONTRACT.md` §1e.

### Pass 1b — Premarket / gap annex (also relevant at 15:50 — gaps that held into the close)

1. **TheStockCatalyst** `https://www.thestockcatalyst.com/NYSEPMMovers` — primary PM annex.
2. **Barchart** — plain curl is WAF-blocked (HTTP 202 challenge). Use the shared helper
   `_shared/barchart_fetch.py` (headless chromium) instead: `--symbols A,B` or `--list top-gainers`.
3. **Perplexity Finance** — browser catalyst Q&A.

### Pass 2 — Confirm

Yahoo chart API for last, % chg, volume → USD $ volume. **Finviz is egress-IP blocked** (403 on every
path, Cloudflare challenge) — use the TradingView scanner and `market-recap` instead. OTC: confirm
venue + $ vol gate.

### Pass 3 — Catalysts / halts

- SEC EDGAR 8-K Atom (descriptive User-Agent): items 1.01, 2.01, 5.02, 7.01, 8.01
- Halts: the TradingView scanner's `halted` column (the NASDAQ Trade Halt RSS returns an empty
  HTML shell every time) — strip warrants
- Finviz news + PR Newswire RSS — headline glue
- Apply buyout near-offer rule

### Pass 4 — Narrative (optional)

Perplexity Finance or major wires for large-cap colour only.

**Do not depend on:** MarketWatch (often blocked), CNBC movers URL, free Finviz CSV export (Elite), Benzinga Squawk, Unusual Whales as core, Barchart without browser, any paid Finviz Elite / paid Barchart RT as a gate.

## Timing emphasis

- **~15:50 ET (`preclose`, the deployed slot):** gaps that held into the close, late tape, halt resumes; PM gap annex; pull prior `overnight_carry`.
- **~12:30 ET (`midday`):** continuation vs fade; raise $ volume bar; RVol soft preference; write `overnight_carry` for AH-relevant names.

RTH: 09:30–16:00 ET.

## When

- Cron: `50 15 * * 1-5` America/New_York (weekdays, 15:50 ET — pre-close slot, 10 min before the cash close)
- Manual: user asks "what's in play today" or "run US stocks in play"
- For midday digest, run manually or as a separate cron (not added by default).

## Output

1. Write `C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`
2. Chat only if Tier A / Soft-A / material TECH_WATCH / material Tier C
3. Append **one** line to `us-stocks-in-play/logs.jsonl` in the output repo, per pipeline §7 —
   fetch the existing file first, then append; never overwrite it. The line carries `tier_a`,
   `soft_a`, `tech_watch`, `tier_c` and `chat`, so the fuel log and the digest's audit line
   always agree.
4. The Windows audit-file line is **skipped on Cloud** — the cron prompt says to skip audit log
   writes. The fuel-log line in (3) carries the same fields.

## Anti-patterns

- Treating Finviz delay as "broken" or requiring Finviz Elite
- Requiring paid Barchart / paid RT for a routine digest
- Hard-requiring RVol in the deployed slot
- Forcing Soft-A merely because RVol is unavailable (vs known soft)
- Including levered / single-stock levered ETFs
- Including illiquid pinks without $ vol gate
- Treating every buyout as Tier A / Soft-A / B chase
- Burying high-catalyst known-soft-RVol names only in Tier B when Soft-A fits
- Ranking separate source lists without normalize→merge
- Chat-only delivery with a Source health **line** instead of a **table**
- Silent empty catalysts when Barchart / blocked wires need a browser
- Marking Finviz `blocked` on an empty HTTP 200 shell without a **headed** browser attempt
- Using headless Chrome/curl alone as the "browser" fallback for Finviz/Barchart
- Burning `get_symbol_data_batch` immediately after a US `run_screener` 429 instead of Yahoo confirms
- Retrying TradingView `run_screener` after HTTP 429
- Serial `get_symbol_data` for dozens of names when one batch (≤50) would cover them
- `get_news` on every mover instead of top floor-cleared candidates only
- Forgetting overnight carry at the start of a slot after a big AH 8-K print
- Scanning through a full NYSE/NASDAQ holiday without the pipeline skip
- Dropping liquid technicals (soft RVol, large turnover) with no TECH_WATCH home
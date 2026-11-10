# IMPROVEMENTS — 2026-11-10: cron #26's market-cap GATE was decided on a stale share count

- **Date:** 2026-11-10 (correcting the 2026-11-09 08:30 ET fire)
- **Scope:** cron #26 `agentic-pre-market-brief`, and every routine that uses the TradingView
  `america` screen's `market_cap_basic` as a **gate input**.
- **Trigger:** a reader challenged the published claim that NWGL was a $143M market-cap stock.
  They were right.
- **Status:** fixed in the routine's own skill spec (`cloud-prompts/skills/agentic-pre-market-brief/SKILL.md`,
  §Step 2 + §Step 2b). The skill is fetched at RUN time, so the next fire picks this up with
  **no `cron_update` and no prompt drift**. The deployed cron #26 prompt was NOT touched, and
  **the prices and gaps in the brief were never wrong** — only the market cap, the gate it
  decided, and one row of the headline table.

---

## 1. What the reader caught

The 2026-11-09 brief's §3 "Pre-market gaps — top 25 market-wide" opened with:

```
| NWGL | CL Workshop Group Limited | 2.53 | 3.82 | +50.99% | 3.43–6.51 | prior close 2.53 | back to/below prior close 2.53 |
```

with `market_cap` = **$143,016,256** in the companion CSV, and the §2 metals cluster described
NWGL and GFR as "**$143M and $1.35B shells**".

**NWGL is not a $143M company.** Its real market cap is in the **$0.5M–$1.9M** range:

| source | market cap | basis |
|---|---|---|
| TradingView scanner `market_cap_basic` | $143,016,256 | close 2.53 × 56,529,352 implied shares |
| Nasdaq `/summary` MarketCap | $1,843,949 | implied 651,865 shares |
| shibui `valuation.market_cap` (2026-11-06) | $523,494 | 206,914 shares |
| stockanalysis.com | $1.02M (360,664 shares) | live |
| WallStreetZen | $523.49k (1,655,317 shares) | live |

Four independent sources say the same order of magnitude. The scanner was out by **75× to 280×**.

## 2. The root cause: a corporate action the scanner's share count never saw

**CL Workshop Group Limited (NWGL)** is an ADR. Nasdaq's Equity Corporate Actions Alert
#2026-787 records:

> CL Workshop Group Limited (NWGL) will effect a **one-for-eighty (1-80) reverse split** of its
> American Depositary Shares and ratio change from one (1) ADS representing **eight (8)** ordinary
> shares (1:8) to one (1) ADS representing **six hundred and forty (640)** ordinary shares (1:640).
> The reverse stock split and ADS ratio change will become effective on **Friday, November 6, 2026**.
> New CUSIP: 63903R205.

The scanner's `market_cap_basic` is `close × shares outstanding`. It kept the **pre-split** share
count (56.53M) and multiplied it by the **post-split** price (2.53):

```
2.53 × 56,529,352 = $143,016,256   <- the scanner
```

and the arithmetic is internally consistent, so **nothing in the scan looks wrong**. The identity
`close - close/(1 + change/100) == change_abs` still holds — it holds for a wrong `close` too.
Only a comparison against the source's OWN price fields catches this class, exactly like the
VISN defect in the same artifact (see
`IMPROVEMENTS-2026-11-09-cron26-scanner-close-reconciliation.md`): a checker that only compares
the artifact to itself cannot find a source defect.

The name's share count is genuinely in motion — an $200M at-the-market programme (Chaince
Securities, as sales agent) and a resale registration for 98.4M Class A ordinary shares — so the
four vendors bracket a range rather than agreeing on a point. **The gate verdict is the same on
all of them: far below $100M.**

## 3. The blast radius, measured

A sweep compared every screened name's implied share count against two independent caps —
Nasdaq's `/summary` MarketCap (re-based to the same prior close) and shibui's dated
`valuation.market_cap` (latest row ≤ 2026-11-06, already on the gate's basis):

| | count |
|---|---|
| names in the merged screen | 1,085 |
| scanner cap ≠ an independent source by >15% | **106 (9%)** |
| of those, with all three sources available | 93 |
| where Nasdaq and shibui agree within 15% | 15 |
| where they disagree (so the figure is an estimate, not a fact) | 78 |
| **published names whose TABLE MEMBERSHIP changed** | **1 (NWGL)** |

**The error runs in both directions.** Too high after a reverse split — NWGL 87×, PBK 23×,
SCAG 14×, BXBL 7×. Too low where the count predates a later issuance — HELP (scanner $1.36M vs
shibui $462M), BTQ ($5.6M vs $264M), WYHG ($27.4M vs $48M). A routine that trusts
`market_cap_basic` as a gate input is wrong in both directions and does not know which.

Gate-relevant names outside the published top-25/top-10 also flipped (PBK, BXBL both fail Gate B on
both independent sources; MGN fails on two of three). No other published table row changed.

## 4. The fix

**In the skill spec (fetched at run time — no `cron_update`, no prompt drift):**

- **`market_cap_basic` is `close × shares outstanding` and the scanner does not refresh the share
  count for corporate actions.** Gate B must be decided on a **reconciled** cap.
- **The sweep runs BEFORE the tables are built**, not after: compare the scanner's implied share
  count against Nasdaq's `/summary` MarketCap and shibui's dated `valuation.market_cap`; where
  they disagree by >15%, publish the **median** of the available sources and recompute
  `quality_screen` / `liquid_screen` from the published figure.
- **A name whose move is a corporate action is NOT a theme.** Before a name enters a cluster,
  check for a corporate action in the last few sessions; if there was one, publish it as a
  corporate-action artefact with the event cited — a Nasdaq Equity Corporate Actions Alert is the
  primary source — never as a catalyst.
- §Step 2b's Gate B line now points at the reconciled cap.

**In the artifact:** the 2026-11-09 brief and CSV were rebuilt and re-published. NWGL moved out of
the headline gap table and out of the metals cluster into the thin-tape block, with the split cited
in §3; 106 CSV rows carry the reconciled `market_cap` and recomputed gate flags; the front matter
carries `market_cap_reconciled: 106`. **Both contract checkers pass on the corrected artifact**
(`check_brief_consistency.py` and `check_premarket_brief.py`, 7/7 contract checks).

## 5. What did NOT need changing

- **The prices and the gaps were never wrong.** NWGL's pre-market print, prior close, range and
  +50.99% gap are all correct and unchanged; the same holds for every other name. Only the market
  cap, the gate it decided, and one table row changed.
- **The metals-breadth claim survives.** All 35 Non-Energy Minerals names that cleared the
  liquidity gate are still up, and not one is down — NWGL's presence in that count does not
  change the signal, and the brief now says so explicitly.
- **The `close`/`change`/`change_abs` identity check is still worth running** — it is simply not
  sufficient on its own, because it holds for a wrong `close` too (see the VISN doc).

## 6. Files touched

| File | Change |
|---|---|
| `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` | §Step 2 — the `market_cap_basic` reconciliation sweep; §Step 2b — Gate B points at the reconciled cap |
| `docs/IMPROVEMENTS-2026-11-10-cron26-market-cap-gate.md` | this record |
| `minimax-cloud-outputs`: `daily-briefs/2026-11-09-pre-market.md` / `.csv` | the corrected artifact (re-published) |

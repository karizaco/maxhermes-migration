# Pre-market refresh — 09:20 ET checkpoint for cron #26

The morning brief (cron #26, 08:30 ET) publishes a tape that is already 50+ minutes old by the
time the market opens, and the most actionable moment for a pre-market brief is the last twenty
minutes before the open. This procedure publishes a REFRESH, not a second brief.

**It does not re-research anything.** No news searches, no clustering, no rewriting. It re-pulls
the same screen and reports what moved.

---

## What this produces

`daily-briefs/{date}-pre-market-refresh.md` — a short addendum:

1. **Front matter** (machine-readable, like the morning brief):

   ```
   ---
   date: <YYYY-MM-DD>
   cron: 26-agentic-pre-market-brief-refresh
   fire_time_et: <YYYY-MM-DD HH:MM>
   snapshot_et: <HH:MM>
   source: TradingView america scanner
   status: ok
   changes_since_morning: <n>
   ---
   ```

2. **Refreshed top-of-book** — the same screen the morning brief used (the universe, the
   liquidity gate and the quality floor are defined in
   `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md`, Step 2 and Step 2b — read them, do
   not re-invent them):

   | Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector |
   |---|---|---|---|---|---|---|---|

   Top 15 gainers and top 10 decliners, with a note of the snapshot time on every row.

3. **What changed since the morning brief** — the names whose pre-market gap moved most, read
   against the morning brief's own CSV (`daily-briefs/{date}-pre-market.csv` on the outputs
   repo, branch `main`). Sort by the size of the change, not by the size of the gap.

4. **A one-line verdict** — is the tape more or less directional than it was at 08:30 ET?

## Inputs

| What | Where |
|---|---|
| the morning brief | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.md` |
| the morning screen (CSV) | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.csv` |
| the live screen | `POST https://scanner.tradingview.com/america/scan` — see the skill spec for the exact body |
| the morning brief's spec | `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` |

The morning brief's CSV is the reference: same rows, same screen, one pull earlier. If the live
screen and the CSV disagree on a name by more than 0.2 percentage points, the market moved —
that is the point of this file.

## Rules

- **One pull.** Pull the screen ONCE and use it for every table and every number, including the
  prose. The morning brief shipped an artifact that contradicted itself because two pulls fed
  two sections; do not repeat that.
- **Never invent a number.** Every price and percentage comes from the screen or from the
  morning CSV.
- **No catalysts.** This file reports moves, not reasons. If a name needs explaining, it belongs
  in the next brief, not here.
- **If the morning brief is missing** (the 08:30 fire failed), say so in one line and publish
  the refreshed screen alone, with no "changed since" section.
- **A thin tape is a valid result.** If the screen returns fewer names than expected, publish
  what it has and say so.

## Output and push

Write to `/workspace/daily-briefs/{date}-pre-market-refresh.md`, then push with the shared
helper, staging only `daily-briefs/`:

```bash
sh /workspace/push_artifact.sh --out daily-briefs --add daily-briefs/{date}-pre-market-refresh.md --branch main
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26
```

`--add` is passed ONCE. The script stages the routine's whole output tree, so the morning brief
and its CSV are not re-staged (they are already on the branch), and a second `--add` would
overwrite the first and wipe the routine number out of the commit subject.

## Reply

Under 10 lines: the snapshot time, how many names moved since the morning brief, the three
biggest changes, one line for push status, one line for `errors: <n>`.

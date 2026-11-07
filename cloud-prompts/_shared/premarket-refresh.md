# Pre-market refresh — 09:20 ET checkpoint for cron #26

The morning brief (cron #26, 08:30 ET) publishes a tape that is already 50+ minutes old by the
time the market opens, and the most actionable moment for a pre-market brief is the last twenty
minutes before the open. This procedure publishes a REFRESH, not a second brief.

**It does not re-research anything.** No news searches, no clustering, no rewriting. It re-pulls
the same screen and reports what moved.

---

## STEP 0 — THE WINDOW CHECK (run FIRST, before anything else)

The scheduler owns the day-of-week and the hour, so this gate exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including*
them. On a holiday the market is closed and there is nothing to report.

**Resolve the fire's scheduled instant FIRST, then judge the gate against it — never against
the wall clock.** The platform resumes a crashed cron conversation IN PLACE, hours or days
later, so on a replay "now" names the resume day, not the fire day.

Resolve it with ONE call, no cron_read needed:

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds) — the instant the platform dispatched THIS
fire — and pass it as `--scheduled-at-ms`. The script prints `fire-date:`; use THAT for the
artifact path, so the gate and the artifact can never disagree about which day they are.

```bash
# --- fetch the ONE shared window check (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY check below is mandatory, not decoration. An OLDER copy of this script is
# still published, and it silently IGNORES unknown flags - so without the check you would
# run a gate that never fires, and a holiday fire would publish a brief for a closed
# market. The CDNs also cache independently, so one of them can serve stale bytes for
# hours. The contents API is authoritative and is not CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script, and an older script silently
  # ignores the flags below. Require BOTH: a real script AND the capability marker.
  if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'WINDOW_CHECK_V2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'WINDOW_CHECK_V2' "$S" 2>/dev/null; then
  echo "window-check: UNAVAILABLE (no version of the shared script with the replay-aware gate)"
  echo "no artifact; no push"
  exit 1
fi

# SCHEDULED_AT_MS = session.created_at from the session_get call above (epoch ms).
sh "$S" --scheduled-at-ms "$SCHEDULED_AT_MS" \
   --out daily-briefs --name agentic_pre_market_brief_refresh \
   --label "Cron #26b agentic-pre-market-brief-refresh" \
   --nn 26b

If the script exits non-zero the fire is OUT OF WINDOW: write nothing, push nothing, and
reply:

```
out-of-window: <reason printed by the script>
file: no artifact (holiday skip — daily-briefs/$DATE-pre-market-refresh.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_agentic_pre_market_brief_refresh.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

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

Two more blocks are published, both unnumbered so that NO existing section number changes.
They sit directly under the front matter, because this file is read twenty minutes before the
open and the reader needs the decision first.

### `## Bottom line` — exactly three lines, the decision

```
## Bottom line

1. **The one setup** — <TICKER> — <level> is the trigger; invalidated by <side> <level>.
2. **The one risk** — <TICKER or group> — <what breaks it> — <level>.
3. **The one thing to watch at the open** — <TICKER> — <condition>.
```

- **EXACTLY three lines.** Not two, not four.
- The three labels are literal, capitalised, and in this order: `The one setup`, `The one risk`,
  `The one thing to watch at the open`.
- Line 1 MUST carry a digit **and** the word `invalidat*`. "ALIT is running" is not a setup.
  "ALIT above 8.04, invalidated by a trade back to/below prior close 5.97" is.
- Line 1 MUST name a name whose **Driver is anchored** — `CASH-OUT`, `CASH-IN`,
  `LIABILITY-RESOLVED`, `ASSET-VALUE` or `EARNINGS-RAISE`, carrying the `+ANCHORED` suffix.
  Those are the classes with measured evidence: on 2026-11-04 every name whose gap ran carried a
  hard number in its catalyst (a $37.00 offer, a $0.70 special dividend, a $7.35B settlement,
  $409.5M of loans resolved) and every name whose gap faded did not. If nothing carries an
  anchored catalyst, say so honestly — "no name carries an anchored catalyst this morning — the
  setup is cash" — rather than promoting a name that does not.
- Line 1's trigger level is the name's **PM high** (the level that must break for the gap to
  extend) and its invalidation is the name's prior close, written with its side.
- The pm %ADV band is NOT part of this gate. It is a descriptor of the print, not a predictor —
  see §`Gap quality`.

### `## What to watch at the open` — three names, their levels, and the two rules

A short table of the three names the bottom line refers to, then the rules that turn this file
into a plan rather than a list:

| Name | Prior close | PM last | PM low | PM high | Trigger | Invalidation |
|---|---|---|---|---|---|---|

- **Rule 1 — the open is the verdict on the gap.** An open BELOW the last pre-market print means
  the gap is being sold, not bought. Measured 2026-11-04: every name that gave back its gap
  opened below its last pre-market print (FTCI −0.48%, BRKR −1.67%, FTK −1.57%), and every name
  that ran opened at or above it. **This refresh fires at 09:20, so it cannot apply Rule 1 — it
  publishes the last pre-market print and the PM low so the reader can apply it at 09:31.**
- **Rule 2 — the 30-minute candle is the breakout test.** If, thirty minutes after the open, the
  session high is STILL the opening-range high, the gap is a fade, not a breakout; the levels in
  this file are then exit levels, not entry levels. A name that breaks its opening range and
  holds above it is a breakout. This is a 10:00 check, not a 09:45 one.

### `## Gap quality — can this gap hold?`

The ranking that justifies the bottom line. One row per headline name (the top 15 gainers and
the top 10 decliners), all from the SAME single pull:

| Ticker | Name | Gap % | PM range | Hold % | pm %ADV | Print | Driver | Key level | Invalidation |
|---|---|---|---|---|---|---|---|---|---|

- **PM range** = `premarket_low` – `premarket_high` (the scanner publishes both; a gap that has
  already been half-filled shows up here and nowhere else).
- **Hold %** = `(premarket_close - premarket_low) / (premarket_high - premarket_low) × 100`,
  rounded to 0 dp. 100 = the last print is AT the top of its pre-market range (the gap is
  holding); 0 = it is at the bottom (the gap is gone). `n/a` if the range is zero.
- **pm %ADV** = `premarket_volume / average_volume_30d_calc × 100`.
- **Print** — two independent DESCRIPTORS of the tape, joined with `+`. **They are not filters.
  Do not rank on them and do not gate the bottom line on them.** Measured counter-evidence, both
  days:
  - the auction flag, on pm %ADV: **`AUCTION`** if 2 ≤ pm %ADV ≤ 30; **`QUOTE`** if pm %ADV < 2
    (a print on almost no volume — it can gap further, or vanish, for free); **`CHURN`** if
    pm %ADV > 30 (the float is turning over; that is churn, not sponsorship).
  - the holding flag, on Hold %: **`holding`** if ≥ 80; **`half-filled`** if < 50; **`mid`**
    otherwise.
  - **Why they are not filters.** On 2026-11-04 CRCT (+49.8%) and MMM (+9.0%) both printed on
    `QUOTE`-thin volume and both ran, while FSLR and BRKR printed on `AUCTION` volume and both
    faded. On 2026-11-06 **zero of the 25 headline names** cleared `AUCTION+holding`, so gating
    on it would have published an empty bottom line on a day when the tape was fine. Read these
    two columns to understand HOW the gap was made and whether it is still holding — the
    **Driver** column is what ranks.
- **Driver** — the catalyst class, from the fixed vocabulary below.
- **Key level** — the **prior close**, the gap-fill level. (A level published by a sourced
  catalyst replaces it, with the source named in the cell.)
- **Invalidation** — always a DOWNSIDE trigger, always with its side:
  gap-up → `back to/below prior close <close>`; gap-down → `below PM low <premarket_low>`.

**The Driver vocabulary — fixed, and applied to the morning brief's OWN sourced catalyst:**

The refresh does **not** search for news and does **not** invent a reason. It reads the
catalyst the 08:30 brief already sourced (the morning brief's §2 theme clusters and their news
URLs) and classifies it. One vocabulary, applied the same way every day:

| Driver | Meaning |
|---|---|
| `CASH-OUT` | cash comes TO the holder — a dividend (incl. a special one), a buyback, a redemption |
| `CASH-IN` | an acquirer puts cash IN — a takeover offer, a merger at a price |
| `LIABILITY-RESOLVED` | a contingent liability is capped or settled — a litigation settlement, a provision taken |
| `ASSET-VALUE` | previously-impaired value is crystallised — loan resolutions, a NAV/discount-to-NAV event |
| `EARNINGS-RAISE` | a beat AND a guidance raise |
| `EARNINGS-RECONFIRM` | a beat with guidance unchanged |
| `EARNINGS-CUT` | a miss, a loss, or a guidance cut |
| `SECTOR-BETA` | a group move — policy, macro or a sector theme; no company-specific news |
| `NONE` | no sourced catalyst for this name |

- **`ANCHORED` suffix.** Append `+ANCHORED` when the catalyst carries a **hard number** — a
  price, a per-share amount, a settlement figure, a balance-sheet total. Measured 2026-11-04:
  every name whose gap ran carried one (a $37.00 offer, a $0.70 dividend, a $7.35B settlement,
  $409.5M of loans resolved) and every name whose gap faded did not (revenue doubled, "path to
  profitability", a policy hope). A narrative gap has to be built entirely by trading, and it is
  fragile.
- If the morning brief is missing, every Driver is `unclassified` and Source health says so once.
- If a name is in no theme cluster and `has_news = no` in the morning CSV, its Driver is `NONE`.
  **That is a finding, not a blank**: a gap with no sourced catalyst is the profile that faded.


## Inputs

| What | Where |
|---|---|
| the morning brief | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.md` |
| the morning screen (CSV) | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.csv` |
| the live screen | `POST https://scanner.tradingview.com/america/scan` — see the skill spec for the exact body |
| the morning brief's spec | `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` |

**The pull MUST carry `premarket_high` and `premarket_low`.** The skill spec's Step 2 column list
includes them; a pull without them cannot compute the PM range, the Hold % or the `half-filled`
flag, and the gap-quality table would be silently blank. If either column comes back missing or
null for every row, the gap-quality table is published as `n/a` with that stated once in Source
health — it is never quietly omitted.

**The morning brief's MD is read for the Driver column**, because the catalyst the refresh
classifies is the one the 08:30 brief already sourced (its §2 theme clusters and their news
URLs). That is a read of a published file, not a news search.

The morning brief's CSV is the reference: same rows, same screen, one pull earlier. If the live
screen and the CSV disagree on a name by more than 0.2 percentage points, the market moved —
that is the point of this file.

## Rules

- **One pull.** Pull the screen ONCE and use it for every table and every number, including the
  prose. The morning brief shipped an artifact that contradicted itself because two pulls fed
  two sections; do not repeat that.
- **Never invent a number.** Every price and percentage comes from the screen or from the
  morning CSV.
- **No catalyst SEARCH.** This file does not look for news and does not write a reason. It
  **carries** the catalyst the 08:30 brief already sourced and labels it with the fixed Driver
  vocabulary. A name with no sourced catalyst is `NONE`, and `NONE` is a finding.
- **The Driver is never a guess.** If the morning brief does not source a catalyst for a name,
  the Driver is `NONE` (or `unclassified` when the brief itself is missing) — never inferred
  from the price action. A gap that rose 40% because it rose 40% is not a driver.
- **Anchors are counted, not adjectives.** `+ANCHORED` requires a hard number in the sourced
  catalyst. "A record quarter" is not an anchor; "$0.70 special dividend" is.
- **If no name carries an anchored catalyst, publish that.** An empty bottom line is a
  legitimate result on a bad tape. Do not promote an unanchored name to fill the slot.
- **If the morning brief is missing** (the 08:30 fire failed), say so in one line and publish
  the refreshed screen alone, with no "changed since" section.
- **A thin tape is a valid result.** If the screen returns fewer names than expected, publish
  what it has and say so.

## Output and push

Write to `/workspace/daily-briefs/{date}-pre-market-refresh.md`, then push with the shared
helper, staging only `daily-briefs/`:

```bash
sh /workspace/push_artifact.sh --out daily-briefs --add daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26b
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26b
```

`--nn 26b` is MANDATORY on the push. The push script derives the commit subject's routine
number from a path table, and that table did not have a row for `*-pre-market-refresh.md`, so
the subject came out as `cron daily-briefs <date>` with no number — and cron #90's triage
greps subjects for `cron (#)?26b `, so it reported a delivered artifact as MISSING. Passing
`--nn` puts the number in the subject regardless of what the table knows.

`verify_delivery.sh` is a SEPARATE helper: it is not shipped inside `push_artifact.sh` and
`push_artifact.sh` does not fetch it. If the prompt's fetch block only downloads
`push_artifact.sh`, the verification step is a silent no-op. Fetch both.

`--add` is passed ONCE. The script stages the routine's whole output tree, so the morning brief
and its CSV are not re-staged (they are already on the branch), and a second `--add` would
overwrite the first and wipe the routine number out of the commit subject.

## Reply

Under 12 lines: the snapshot time; the one setup and its invalidation; how many names cleared
how many headline names carry an anchored catalyst; how many names moved since the morning
brief; the
three biggest changes; the name to watch at the open and the level; one line for push status;
one line for `errors: <n>`.

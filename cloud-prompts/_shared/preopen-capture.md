# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

PROCEDURE_VERSION: 2026-11-15.1

Captures the pre-open **catalyst tape**: for each US stock materially moving pre-market or at the
open, record WHO / WHAT / WHEN, with ground-truth prices. Cron #17 (`us-stocks-in-play`,
15:50 ET) reads the tape to explain why a stock moved and when the news broke — the one thing no
price feed can tell it.

**The whole capture is one script.** Fetch it and run it; do not improvise the procedure.

## WHAT THIS IS FOR

At 15:50 the digest sees where a stock IS, not where it came from, and — the gap — not the
catalyst as it was understood at the open. By 15:50 the wire has moved on: the 09:12 headline is
buried, and a name that gapped +12% on an FDA approval and now trades +2% looks identical to one
that never moved. The skill requires the gap annex to separate a gap that **held into the bell**
from one that faded, and to attribute the move.

## STEPS — execute IN ORDER

### 1. Fetch the capture script and the digest renderer

```bash
# The CONTENTS API is authoritative and is NOT CDN-cached; the two CDNs cache `main`
# independently (measured 2026-11-04: raw.githubusercontent served a stale blob for
# >17 minutes after a push while jsDelivr was fresh). Require the CAPABILITY MARKER,
# not just a non-empty body: an older script silently ignores the flags below, and a
# stale copy would run the gainers-only scan that misses the biggest decliners.
#
# AUTHENTICATE the fetch when a token is present. The unauthenticated contents API
# allows 60 requests/hour per egress IP, and this sandbox's egress is SHARED with
# every other routine - so an anonymous call to the AUTHORITATIVE source fails on
# rate limit, and the ladder silently falls through to the CDN copies that can be
# stale. Measured 2026-11-11 08:30 ET: the unauthenticated contents call returned no
# marker at all and the ladder only reached the fresh script through
# raw.githubusercontent. An empty token must NOT be sent (GitHub answers a malformed
# Authorization header with 401, which would break a fetch that worked anonymously),
# so the header is added only when the token is set.
S=/workspace/preopen_capture.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen_capture.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_capture.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_capture.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  fi
  # 2026-11-15.1 is the version that MEASURES THE COVERAGE OF THE MOVERS THE BOARD
  # PUBLISHES - the reader-facing number - and gates THAT at 50%. The 2026-11-13.3
  # version gated the WHOLE TAPE at 40%, which needed 66 explained rows on a 164-row
  # tape: a floor that could never be cleared, so every checkpoint was DEGRADED
  # forever. The 2026-11-11.2 dated the tape from the previous session's closes, and
  # it published a matched article's stamp without checking that stamp was inside
  # the window - both are defects this version fixes.
  if grep -q 'CAPTURE_SCRIPT_VERSION: 2026-11-15.1' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
[ -s "$S" ] || { echo "capture script fetch FAILED — write nothing"; exit 1; }

D=/workspace/preopen_digest.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen_digest.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_digest.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_digest.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$D.tmp" "$U" 2>/dev/null
  fi
  # PREOPEN_DIGEST_V2 is the version that renders the COVERAGE line and the
  # DEGRADED banner. A V1 renderer would pass a V1 grep and publish a board with no
  # coverage on it - the silent failure this version exists to stop - so the ladder
  # demands V2.
  #
  # PREOPEN_MOVER_COVERAGE_V1 is demanded as well, because the METRIC changed on
  # 2026-11-15: the board now gates the coverage of the MOVERS IT PUBLISHES (50%),
  # not the coverage of the whole tape (40%, which could never be cleared). A stale
  # V2 renderer publishes the old metric and the old floor, and it must not win the
  # ladder.
  if grep -q 'PREOPEN_DIGEST_V2' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_MOVER_COVERAGE_V1' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || { echo "digest renderer fetch FAILED — the board is part of the checkpoint"; exit 1; }
```

### 2. Run the capture — with the FIRE'S SLOT, never the wall clock

```bash
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
# The SLOT comes from the FIRE'S INSTANT (session.created_at), not from `date +%H%M`.
# A literal wall clock names an 08:35 execution "0835" — a slot cron #17 never reads,
# because it merges the checkpoints by slot name. The script asserts the slot is one of
# 0830 / 0920 / 0950 and snaps a late dispatch DOWN onto the slot it belongs to
# (<= 90 min); past that it writes a .DEVIATION.slot.md marker and writes NO tape.
# Measured 2026-11-05: the 08:30 slot's work began at 10:09 ET after a platform stall
# and a wall-clock slot would have named its file 1010 — a phantom slot that sorts
# AFTER 0950, so a consumer replaying oldest-first replays the 08:30 tape LAST.
export CP=0830        # <- the slot THIS fire was dispatched for
python3 "$S" --date "$DATE" --checkpoint "$CP" --top 20
```

The script prints one line: `preopen capture: wrote N records to <path> ...`.

- **It writes nothing and exits 0 if `PIPEWORX_API_KEY` is unset** — a missing key is not a
  failure, it is a missing tape. Never write an empty tape: the consumer would read it as
  "no news" for names that had a catalyst.
- The tape is written **atomically** (temp file + rename), so a slot's file holds exactly ONE
  snapshot. Appending was how two agents running the same slot against the same shared
  `/workspace` produced a 100-row tape for 53 tickers on 2026-11-09 — one row per ticker per
  run, which breaks the "one row per ticker" rule and makes cron #17 read a stale record as
  the latest one.

### 3. Render the digest — the board a trader reads before the open

```bash
python3 "$D" --tape /workspace/preopen-feed/${DATE}-${CP}.jsonl \
               --out  /workspace/preopen-feed/${DATE}-${CP}.md \
               --date "$DATE" --slot "$CP"
```

Every successful checkpoint writes **TWO files**: the tape (`.jsonl`) and the digest (`.md`).
The digest is rendered FROM the tape, never by hand, so the board can never disagree with the
data cron #17 reads at 15:50. It carries the record count, the provenance split, the
**mover coverage** of the table it publishes (see THE MOVER COVERAGE FLOOR below), the
whole-tape coverage as context, the top 15 movers by |%| with
their catalyst, their `conf` token and when the news broke, and the halt state —
`not measurable`, because the `halted` column is null on every row (never `0`).

### 4. Push

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out preopen-feed \
   --add preopen-feed/${DATE}-${CP}.jsonl \
   --add preopen-feed/${DATE}-${CP}.md \
   --branch main --nn 92
sh /workspace/verify_delivery.sh --path preopen-feed/${DATE}-${CP}.jsonl --branch main
```

**Stage only `preopen-feed/`. Never `git add -A`.**

## WHAT THE SCRIPT DOES (for the reply, not for reimplementation)

Five Pipeworx gateway calls plus one TradingView scanner POST, each with one job:

| Call | Pack | Job |
|---|---|---|
| `trending_symbols` | `stocktwits` | candidates + a natural-language reason + a `summary_at` timestamp for each. Live retail/WSB chatter — the X signal. |
| `top_movers` (gainers) | `market-recap` | YESTERDAY's movers universe, in one direction — the names being watched before they gap. |
| `top_movers` (losers) | `market-recap` | the same universe for the other direction. |
| TradingView scanner — **the band** | direct POST | **TODAY's pre-market movers**: every US stock trading more than ±2.5% pre-market, in two DISJOINT halves. **This is the tape's candidate source.** |
| `polygon_io_news` | `polygon-io` | the article feed, straight from the provider: `published_utc`, `article_url`, title and description. **This is where the catalyst gets its DATE — and it is consulted FIRST.** |
| `ask_pipeworx_grounded` | `market-recap` | a per-name catalyst with evidence and confidence, spent ONLY on a name the article feed could not date. It does **not** say WHEN the news broke. |
| TradingView scanner | direct POST | **the PRICE**: this session's `premarket_change` and `premarket_close` for every name on the tape. |

**THE CANDIDATE SOURCE IS TODAY'S PRE-MARKET BAND, NOT YESTERDAY'S MOVERS.**

`top_movers` is Yahoo's predefined screener over the **last completed regular session**, so
before the open it names YESTERDAY's movers. A tape built from it cannot serve a brief about
today's movers, and it did not: on the 2026-11-10 fire the 08:30 checkpoint carried **49 rows**
and covered **6 of the 50 names the brief published**; on 2026-11-12 it covered **21 of 693**
screen names (3.0%) and **9 of 21** actionable names.

So the candidates come from the **TradingView scanner's pre-market band** — every US stock
trading more than **±2.5%** pre-market, pulled in **two DISJOINT halves** (the gainers sorted
descending and the decliners sorted ascending, so a name cannot be in both and no record can
hold two prices). The band IS today's tape.

Measured on 2026-11-13 at 07:57 ET: the band held **458 names** (271 up / 187 down) and the
tape carries **130 priced rows** — against 47 rows before. The band is the same width as the
historical "±2.5% movers-sorted snapshot" (849 rows on 2026-11-06), so a tape of 200–900 rows
is normal and only a tape under ~120 rows is a regression signature.

**THE QUOTE FLOOR: a pre-market print of fewer than 25,000 SHARES is not on the tape.**
That is the same number, and the same instrument, as cron #25's fourth gate leg — one rule
across the fleet: below 25,000 pre-market shares is a quote, not a market. It is a SHARE count
and not a dollar notional because a share count is monotone in time (a name that printed
25,000 shares by 08:30 has printed more by 09:22) while a notional floor is not (the price can
fall under it), and because a notional floor deletes real movers: measured on 2026-11-13 a
$100K-notional floor kept 72 of 458 band names and DROPPED **CRIS (-10.6% on 39,053 shares)**
— a real mover on a cheap share, and one of the names cron #25 has to publish.

**Both directions are mandatory.** The gainers and losers halves are DISJOINT (a name cannot be
both a top gainer and a top loser), so merging them can never put two prices on one record.
A gainers-only scan is not a pre-open tape: measured 2026-11-09 it missed IRTC -30.7%,
DKNG -21.3% and AXON -18.2% — the day's three worst decliners. The grounded-call budget is
spent on the biggest movers by |%|, so a decliner competes with a gainer for its catalyst.

**Prices come from the SCANNER, not from the movers scan — and this is not optional.**
`top_movers` is Yahoo's predefined screener over the LAST COMPLETED REGULAR SESSION, so
before the open it returns YESTERDAY's movers carrying YESTERDAY's closes. Measured on the
2026-11-09 08:30 tape, 14 of 14 testable priced rows were exactly the previous session's
close and move (IRTC -30.70% at 90.22, from 130.19 on Nov 5 to 90.22 on Nov 6), while
TradingView's own pre-market for IRTC that morning was +0.86% at 91.00. The tape was
publishing Friday's move as if it were Monday's pre-market.

So the **band** decides WHICH names are on the tape, and the scanner supplies the NUMBER that
belongs to the session the tape is about (the band rows are priced by the pull that chose
them; the few names the band did not cover are priced by a second scanner call). The movers
scan still contributes the names that have not moved yet. Two rules follow:
  * A name the scanner does not carry has **no pre-market print**. It keeps `pct`/`price`
    NULL and is published as a narrative row (`src: stocktwits`) — it did not trade
    pre-market, and the tape must not invent a number for it.
  * The grounded-call budget is spent on the biggest movers by **this session's** |%|.
    Ranked by the movers scan's move, the budget would buy catalysts for yesterday's
    movers and today's would never get one.

**Prices are never taken from the narrative calls.** The script also drops a grounded answer
that merely restates the price move, and drops one whose source was a filing index rather than
news — a name with no findable catalyst is left with no catalyst, which is the honest result.

## THE CATALYST PIPELINE — ARTICLE FIRST, THEN THE ROUTER, BOTH IN PARALLEL

**The article feed goes FIRST.** It costs **0.21–0.24 s** per name and it answers directly,
with the publication stamp and the article URL; the router costs **15 s** when it answers and
**21 s** when it *refuses*. Measured 2026-11-13 at 22:49 ET on 8 large names: the direct feed
returned a dated article for **6 of 8**, while the router's own polygon path returned
`tool_error` on **4 of the same 8**. The router is 60–100× more expensive and less reliable
at the one thing it cannot do — say WHEN.

**THE CATALYST IS THE ARTICLE'S TICKER-SCOPED INSIGHT, NOT ITS HEADLINE.** Every article
carries `insights`: a per-ticker entry with a `sentiment` and a one-clause
`sentiment_reasoning`. THAT entry is the catalyst. Measured 2026-11-13 23:14 ET: the newest
headline for **SST (System1, −38.92 %)** was *"NIQ Global Intelligence plc (NIQ) Q3 Earnings
and Revenues Surpass Estimates"* — a story about a **different company**, and a **positive** one,
on a row that fell 39 %. The provider tags that article to both tickers, so the article's
`tickers` list does **not** exclude it; but its `insights` carry a separate entry per ticker,
and the SST entry reads *"Expected to post a quarterly loss of $1.30 per share with a 43.5 %
year-over-year deterioration, and revenues projected to decline 50.7 % from the year-ago
quarter"* — at `sentiment: negative`, which is the direction of the move. The insight is the
ticker-scoped, direction-scoped explanation; the headline is neither. The insight is matched
**exactly**, so a `SST.WS` warrant entry cannot pass for `SST`.

**AND THE DIRECTION COMES FROM THE PROVIDER, NOT FROM A WORD LIST.** The `sentiment` field is
the provider's own judgement of that ticker, which is exact; a direction-word probe over prose
is a guess. So a row that carries a sentiment is judged by it, and the word probe is the
fallback for a router or a chatter catalyst that carries none.

So the pipeline is: **one article fetch per name in contention** → if the provider holds an
**in-window** article, that article's TITLE is the catalyst (dated, with its URL) and the
router is never called; only a name the feed **could not date** spends a router call. The
article that is published is the provider's **newest** one, so its stamp IS the provider's
freshest stamp — the ARWR/NOVT defect (a months-old article matched by text and published as
today's news) **cannot arise from this path at all**.

**Both phases run in parallel.** Measured 2026-11-13: 8 concurrent grounded calls in
**20.19 s** against **101.77 s** serial — 5.0× — with no rate limiting and no HTTP failure.
The sequential grounded calls had been ~264 s of the capture's 270 s: **98 % of the capture's
wall clock**, while the four feed calls took 2.6 s.

**THE CONFIDENCE TOKEN now means something.** `high`/`medium` is reserved for a catalyst that
is **DATED, in-window and checkable**; a retail-chatter reason — no publication stamp, no
article behind it — can never earn more than `low`. Measured on the 2026-11-12 tape: **10 of
the 12 `high` rows were chatter**, undated and uncheckable, while only 2 were dated grounded
catalysts. The old rule (`conf` was `high` whenever the row carried any reason at all) is
why.

**A CREDIT FAILURE IS NOT "NO NEWS".** The gateway answers an exhausted account with *"Insufficient
credits. This tool costs 200 credits"* — and to a caller that cannot tell that from an empty
result it looks exactly like a quiet news day. Measured 2026-11-13 23:40 ET, every pack
answered that way after the balance ran out mid-run: the tape published 193 rows with **no
catalysts at all** and would have reported **no error**. So the capture recognises the credit
failure, does not retry it, and **reports it** (`article_errors=`, `provider_errors=`,
`errors=`). A quiet tape with a loud error beats a loud-looking tape with a silent one.

**THE PROVIDER SPEND IS BOUNDED.** The pool of names put in contention for a cause **is** the
budget (`--top`), not twice it: every article call is a metered provider call (200 credits,
measured 2026-11-13) and the wallet is finite.

**THE SIGN PROBE.** A cause that points the **other way** from the move is not an explanation
of that move. The capture compares the catalyst's direction with the sign of the move; a row
that contradicts is demoted to `low` and flagged `sign_conflict: true` (the board marks it
`low ⚠`). With a provider sentiment the comparison is exact; otherwise it is a direction-word
probe, and that one reads only the text **before** the hedge clause (*"… though some question
whether backlog can convert"*), because the negative words in a debate belong to the bears and
not to the cause, and it stays silent unless the move is material (|%| ≥ 2.5 %). Measured
against every catalyst on the 2026-11-12 and 2026-11-13 tapes, the probe flags exactly the
rows whose published cause does not explain the move — DGII −20.50 % on *"beat Q4 2026
earnings expectations"*, GLW −5.93 % on *"strong Q3 results"*, ONDS −5.41 % on *"stronger
revenue outlook"* — and nothing else.

**A ROW WITH NEITHER A NUMBER NOR A CAUSE IS NOT A ROW** and is not published. Measured on the
2026-11-12 tape: 11 of its 45 rows were exactly this.

**`pm_notional`** — the pre-market dollar notional behind each print (shares × price) — rides
on every priced row, so a consumer can tell a real mover from a thin one. Measured on the
2026-11-13 tape: of the board's 15 rows, 10 sat on under $3M of pre-market notional.

## THE CATALYST IS DATED, AND AGE-CHECKED

A catalyst without a date is a claim with nothing behind it. Measured on the 2026-11-09 09:50
checkpoint, **ARWR (-16.59%)** carried Arrowhead's **2026-01-06** press release — *"announced
significant positive interim trial results … with stock surging 17.81% to a new 52-week
high"*, a story about the opposite move from ten months earlier — at `conf: high`, and the
board printed `09:53:48` in its **When it broke** column, because that column fell back to the
CAPTURE clock. The board therefore told a trader, in the one column that exists to date the
catalyst, that a January press release broke forty minutes ago.

So the tape now carries, on every row:

- `news_date` — the article's `published_utc` (ISO-8601), or null when no date could be
  resolved.
- `news_url` — the article the catalyst came from, so the claim can be checked.

and the capture applies two rules:

1. **STALE ⇒ DROPPED.** If the newest dated article the provider holds for that company is
   older than `CATALYST_MAX_AGE_DAYS` (four days — a Monday board still has to reach Friday's
   and the weekend's news), the catalyst is removed: `why` goes to null, the row reverts to
   `src: scanner` (its price, and nothing else) and the name is counted in the run's
   `stale_dropped=` figure. A cause that cannot be today's news is not a cause.
2. **UNDATED ⇒ DEMOTED, NOT DROPPED.** If no date could be resolved at all, the catalyst is
   kept but demoted to `conf: low` with `news_date: null`. An undated cause is a weaker
   claim, not a false one.
3. **A MATCH OUTSIDE THE WINDOW ⇒ THE STAMP IS DROPPED, THE CAUSE IS KEPT.** Rule 1 asks the
   provider for its NEWEST dated article and rule 2 asks whether ANY date resolved, but the
   tape publishes a third thing: the date of the article the answer TEXTUALLY matched. That
   match can land on a months-old article from the same company while the provider holds a
   fresh one — measured 2026-11-11 08:30 ET, NOVT carried a catalyst dated **2026-02-22**
   (262 days old) because the match picked that article, even though Novanta's feed held
   something newer. A published stamp outside the window is a cause dated to the wrong year,
   so the stamp (and its URL) is dropped and the row is demoted to `conf: low` with
   `news_date: null`; the cause itself survives, because the provider's fresh article makes
   it plausible. Never publish a `news_date` the checker would reject: `tools/check_preopen_checkpoint.py`
   asserts that no row's date is outside `CATALYST_MAX_AGE_DAYS`.

The gate reads the provider's newest article for the name rather than the article that best
matches the answer, because the router reads the same provider: if the newest thing it holds
for a name is old, the router cannot have found anything newer, however confident it sounds.

**Cost.** Call 5 is one provider call per grounded name (the same provider the grounded
router already calls internally), so the marginal cost is one extra article fetch per
catalyst — a few cents per checkpoint. The router alone is not enough: it returns a
summary with no date and no URL, which is exactly what makes the defect invisible.

**The board's "When it broke" now reads `news_date`, then the trending snapshot's own stamp,
and otherwise prints an em-dash.** It never falls back to the capture clock — that is the
clock when the script ran, not when the news broke. `tools/check_preopen_checkpoint.py`
enforces all of this, and the ARWR row is itself a fault-injection case in
`tools/test_preopen_checkpoint_contract.py`.

**xAI/Grok is NOT used.** The xAI chat API no longer serves live search (`search_parameters`
returns HTTP 410, "Live search is deprecated") and the Agent Tools API that replaces it is not
enabled on most keys. Pipeworx does the job on its own. If `XAI_API_KEY` is present it is
ignored, not used as a fallback. The measured Grok cost is therefore **$0.0000**.

The tape's `src` field is the row's PROVENANCE, not a vendor: `scanner` = the movers scan gave
this row its price; `pipeworx` = the grounded router gave this row its catalyst; `stocktwits` =
a narrative row with no ground truth.

## THE MOVER COVERAGE FLOOR — THE MOVERS THE BOARD PUBLISHES MUST BE EXPLAINED

The tape's whole job is **WHO / WHAT / WHEN** for every name materially moving pre-market. On
Friday 2026-11-13 it priced the movers and explained almost none of them, and **not one word
of the artifact or of the reply said so**:

| Checkpoint | Records | With a catalyst | Whole-tape coverage (CONTEXT) | **Published movers explained (GATED)** |
|---|---|---|---|---|
| 2026-11-13 08:30 | 164 | 16 | 16/164 (10%) | **4/15 (27%)** |
| 2026-11-13 09:50 | 218 | 20 | 20/218 (9%) | **6/15 (40%)** |

LFTO (+25.07% on a Q3 beat) and SBC (+9.6% on a Q3 print and an 8-K) sat on the 08:30 tape
with `cat: "other"`, `why: null`, `conf: "low"` and `news_date: null` — two names that needed
an explanation most, carrying none.

**A tape that is 90% unexplained reads exactly like a tape that found no news**, and that is a
SILENT failure. The fleet's own rule is that a degraded run must say it degraded; this run
did not, because nothing measured it.

### THE MEASUREMENT — THE READER-FACING ONE

```
mover_coverage = (published movers carrying a catalyst) / (published movers)
```

The **published movers** are the rows of the digest's **top-movers table** — the 15 rows the
board publishes, ranked by |%| — that carry a pre-market price. That is the table the reader
actually reads before the open, and it is the coverage they experience. A row with no price is
a catalyst without a move (the board sorts it last by design and says so in its own footer),
so it is not a mover and it is not in the denominator.

**The WHOLE-TAPE coverage is still measured and published, as CONTEXT.** It says how much of a
130–220 row band was explained — a fact about the band's width. It is **NOT** the gated number,
and the board labels it as context so the two can never be confused.

### THE FLOOR: 50% OF THE PUBLISHED MOVERS

`MOVER_COVERAGE_FLOOR = 0.50` — half of the movers on the board must carry a cause.

**The arithmetic, so the floor's reachability is obvious and checkable:**

```
a 15-row movers table needs ceil(0.50 x 15) = 8 explained movers
  7/15 = 46.7%  -> BELOW the floor
  8/15 = 53.3%  -> CLEARS the floor
```

**Why the floor is REACHABLE.** The catalyst pool **is** the budget (`--top 20`, step 2) and the
pool is ranked by |%| — the same ranking the table is published in — so the pool (20) is
**wider** than the table (15). A run whose budget lands on the movers the board publishes can
explain up to 15 of them, and **8 of 15 clears the floor with room to spare**. A gate that
can never be cleared is not a gate: it is a ratchet, and a ratchet that fires on every
checkpoint trains the reader to ignore the label.

**Why the previous floor was wrong.** The 2026-11-13 floor gated the WHOLE TAPE at 40%: on a
164-row tape that needs **66 explained rows**, while the pool can supply at most ~20. It could
never be cleared, so **every** checkpoint would have been labelled DEGRADED, forever — alarm
fatigue, and a label the reader learns to skip.

**Read the arithmetic before the verdict.** On Friday the budget was already spent on the
movers the board publishes — the pool is the top 20 by |%| and the table is the top 15 — and
still only 4 of 15 (08:30) and 6 of 15 (09:50) came back with a cause, because the provider
held no in-window article for the rest and the router refused them. So Friday's failure is a
**provider-answer** failure, not a budget failure, and the board now says exactly that:
"4 of the 15 movers on this board carry a cause". Widening the catalyst pool is a **SPEND
DECISION for the fleet** (every article call is metered — 200 credits, measured 2026-11-13)
and it was **not taken**; the floor's job is to make the gap LOUD, not to spend the wallet.

### WHAT THE FLOOR DOES — AND WHAT IT NEVER DOES

**THE FLOOR NEVER SUPPRESSES THE CHECKPOINT.** The tape and the board are written either way.
The floor changes how the result is **LABELLED**, never whether it is produced. A capture that
FAILED is a different failure and keeps its own path (the errors ledger, the credit
recogniser, the skip marker).

When the mover coverage falls below the floor:

1. **the board says so, in the file a reader opens** — a `DEGRADED` banner above the table, in
   plain words (*the movers on this board are priced but unexplained*), naming the CAUSE (the
   grounded catalyst call did not explain them) and listing the **unexplained movers it
   publishes**;
2. **the reply says so** — a `degraded:` line naming it;
3. **the checkpoint's `errors:` count goes up by ONE** for it. The capture already counts the
   degradation in its OWN ledger (`errors=`), so the reply's number is measured, never
   remembered — and the degradation is never counted twice.

**IF THE BOARD PUBLISHES NO MOVERS TABLE, THE METRIC IS UNDEFINED.** A checkpoint that cannot
show an explained mover cannot claim coverage, so it is DEGRADED:
`mover coverage: n/a — the digest published no movers table`.

### THE LABELS (exact)

In the board's header block, next to the record count and the provenance split — the marker on
its own line (the house pattern, cron #17's `**Contract:**`), the gated measurement on the
next, and the whole-tape number on the line after that, clearly marked as context:

```
- **Coverage contract:** `preopen-coverage-v2`
- **mover coverage:** 4/15 (27%) · **floor:** 50% · **BELOW FLOOR** · published movers: 15 (8 up / 7 down)
- **catalyst coverage (whole tape):** 16/164 (10%) · **unexplained:** 148 records (138 price-only · 10 narrative-only) · CONTEXT ONLY — not the gated number
```

and, only when the mover coverage is below the floor, the banner above the table:

```
> ⚠ **DEGRADED — mover coverage 27% is below the 50% floor.** The movers on this board are priced but unexplained: the catalyst budget did not reach them. **11 of the 15 published movers carry no cause at all** — read those names as MOVERS, not as explained moves.
> **Cause:** the grounded catalyst call did not explain them — 11 of the 15 movers this board publishes carry the pre-market scan price only (the movers scan / the pre-market band). The tape is complete; the EXPLANATION is not.
```

The unexplained movers are listed in the header too, so a reader can look up the tickers the
board publishes and did not explain:

```
- **Unexplained movers in the published table (a price, no catalyst captured):** 11 of 15 published movers — ZBAO, OGEN, MRLN, …
```

In the reply, one line, ALWAYS:

```
mover coverage: 4/15 (27%) · floor 50% · BELOW FLOOR
```

the whole-tape context on the next line:

```
catalyst coverage (whole tape): 16/164 (10%)
```

and, only when the mover coverage is below the floor, one more line:

```
degraded: mover coverage 27% is below the 50% floor — 11 of the 15 published movers carry no cause; the movers this board publishes are priced but unexplained
```

At or above the floor the line reads `mover coverage: 8/15 (53%) · floor 50% · OK`, there
is NO `degraded:` line, and the error count does not move.

### THE FLOOR DOES NOT RETRO-FIRE

A digest published before this rule existed is not failed for it. The board carries a **coverage
contract marker** (`preopen-coverage-v2`), and a board that carries NO marker and predates the
floor's effective date — **2026-11-16**, the first checkpoint under the floor — is
**GRANDFATHERED**: it is checked against the rules in force when it was written. A board dated
on or after the effective date MUST carry the marker and the coverage line — otherwise the
checker fails it, because a board that quietly stopped publishing its coverage is exactly the
silent failure this rule exists to stop. A board carrying the **previous** marker
(`preopen-coverage-v1`, the whole-tape floor) and published on or after the effective date is
NOT grandfathered either: it must publish the current metric.

## REPLY

Under 6 lines: the checkpoint, the number of records written, the **mover coverage** line,
one line for push status, one line for `errors: <n>`. **EIGHT lines when the mover coverage is
below the floor** — the whole-tape context line and the `degraded:` line are not optional, and
the floor is not a footnote.

**THE MOVER COVERAGE LINE REPLACES THE OLD "how many movers carry a catalyst" LINE.** It
carries the same count and the arithmetic around it, so it is the same line with the
measurement attached:

- `mover coverage: 4/15 (27%) · floor 50% · BELOW FLOOR` — the `4` is the number of the
  **published movers** that carry a cause, the `15` is the number of movers the board
  publishes, and the floor is 50%.
- `mover coverage: 8/15 (53%) · floor 50% · OK` — at or above the floor.

The whole-tape number travels on its own line, as context:

- `catalyst coverage (whole tape): 16/164 (10%)` — the band's coverage. It is NOT the gate.

**Read the coverage from the BOARD, not from the capture's stdout.** The board is rendered
FROM the tape, so it is the same measurement over the same rows; the capture's stdout carries
the same numbers plus the budget (`pool=`), which is what you need to name the CAUSE.

**When the mover coverage is below the floor, the reply says so in plain words and the error
count goes up by ONE.** The capture already counted the degradation in its own ledger
(`errors=`), so the number in the reply is the capture's `errors=` plus any stall error —
never plus a second copy of the degradation:

- `degraded: mover coverage 27% is below the 50% floor — 11 of the 15 published movers carry no cause; the movers this board publishes are priced but unexplained`
- Name the budget too when the capture printed it: `pool=20` is the size of the catalyst
  budget, and the capture's `mover_coverage=4/15` is the number of those movers the provider
  answered for. A degradation with no cause named is half a finding.

**The push line carries the DELIVERY LATENCY, and a platform stall counts in `errors:`.** The
platform's run record measures the DISPATCH of the prompt to the agent (~1 s), not the work: on
2026-11-05 cron #26b's run record closed in 1.008 s with `status: 1` and its first tool call
did not execute until 49.8 minutes later. `window_check.sh` prints `stall_min:` — the platform's
delay before the turn actually started — and the window check is the first action, so read it.

- `push: ok (verified) — delivered 10:15 ET, 55 min after the 09:20 fire` — the latency is the
  wall clock at the push minus this routine's own scheduled fire time.
- `stall_min` over 5 ⇒ the fire was BLOCKED. Count ONE error for it and add a `stalled:` line.
  To name the cause, read your OWN session's previous turn (`session_messages` on your own
  session id) and quote the error it ended on — e.g.
  `42212: Token Plan usage limit reached … (2056)` — or say
  `stalled: the fire was blocked <n> min before its first tool call (no error recorded)`.
  `errors: 0` on a stalled fire is a lie: the artifact may be perfect and the schedule was not.

**The halt state is `not measurable`** — the `halted` column is null on every row, so never
publish a halt count, and never publish `0`.

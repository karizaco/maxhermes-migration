# Plan — pre-open catalyst feed (n8n → repo → cron #17)

**Status:** proposal, awaiting owner approval. Two gating items in §3.
**Scope:** fill the 09:00–09:50 information hole for cron #17 (`us-stocks-in-play`, fires **15:50 ET**,
pre-close slot) and, optionally, for #02 / #08 / #16 / #26.
**Prepared:** 2026-11-01.

---

## 1. The problem, stated precisely

Cron #17 runs at 15:50 ET. At that moment it **can** see today's prices, volume and the gap —
and, as of 2026-10-31, it can reconstruct the intraday path from Yahoo's 5-minute bars. What it
**cannot** see:

| Missing | Why it matters |
|---|---|
| **The catalyst as it was understood at the open** | A wire search at 15:50 returns today's headlines; the reason a name moved at 09:35 may be buried or superseded by then. |
| **When the catalyst broke** | Distinguishes "gapped on news" from "drifted" from "halted and resumed". |
| **LULD halts and resumes** | The NASDAQ halt RSS is broken (empty shell, 6/6 attempts). The TradingView `halted` column only helps if someone reads it *during* the session. |
| **X-only chatter** | `web_search` cannot see X. Grok can. |
| **Pre-market prints *with their reason*** | The prices are obtainable (§2); the reasons are not. |

Evidence from this series that the gap is real: the **BRZE** Salesforce deal (10-13), the
**LQDA**–UTHR settlement (10-14) and the **SKYD** warrant adjustment (10-14) were all found
*after* the digest was written, not during the window when they moved the stocks.

---

## 2. What is already solvable without n8n — do this first

| Capability | Source | Verified |
|---|---|---|
| Pre-market prints (price, %chg, volume) | TradingView scanner `premarket_change` / `premarket_volume` / `premarket_close` | 2026-10-31: SPY read `761.37 / -1.04%` vs Thursday's close of 769.36 — exactly Friday's real premarket print. **Readable at 15:50.** |
| Intraday path (09:30 → 10:00 → 12:00 → 15:50), cumulative volume, gap held vs faded | Yahoo chart API, `interval=5m` | Proven 2026-10-31 (5m bars retained ~60 days) |
| Quotes, float, short ratio | Yahoo `quoteSummary` + crumb | Verified |
| Movers, screens, RVol | `market-recap.top_movers`, TradingView scanner, `financekit`, `tradingview-mcp` | Verified |
| Filings / 8-K | SEC EDGAR full-text + per-company Atom | Verified |
| Barchart quotes + movers screener | `_shared/barchart_fetch.py` (headless chromium) | Verified |

**Conclusion: the only irreducible gap is narrative + timing + halts + X.** That is precisely what
Grok provides and nothing else does. So n8n's job is small and well-defined — it is **not** a
data-fetching relay, it is a **catalyst-tape recorder**.

---

## 3. Two gating items — I need these from you before building

### 3a. An xAI API key, placed in n8n as a credential

Without it the lane degenerates into "another screener" and **I would recommend not building it** —
the scanner and the bridge already cover that half.

- Target model: `grok-4` with live web + X enabled via `search_parameters`. Tell me the exact
  model id your key can reach (`GET https://api.x.ai/v1/models` will list it).
- Cost: sized to ~$0.01–0.05 per run, ~21 runs/session-day. The frequency cap in §5 is what
  keeps this bounded; I will trim the late-day checkpoints first if you want it cheaper.

### 3b. A GitHub PAT inside n8n with `contents:write` on `karizaco/minimax-cloud-outputs`

**Recommended transport: n8n writes straight to the repo.** The repo is already the fleet's data
bus, so this needs no inbound endpoint, no new credential in the sandbox, and no polling step —
cron #17 reads the file with the GitHub connector it already has.

Alternative (worse): n8n POSTs to a webhook URL the sandbox polls. That adds a secret in the
sandbox, a poll loop, and a failure mode. **Not recommended.**

**Also a separate decision, unchanged:** whether to also relay **Finviz**. Do the one-node test
first (RUNTIME-CONTRACT §2f): a `403` + `cf-mitigated: challenge` from your n8n means your egress
is still a flagged datacenter ASN and a relay will not help.

---

## 4. The design

**Transport:** append-only JSONL at `preopen-feed/{date}.jsonl` on branch `main`.
Append-only, not one JSON file: a failed run loses one checkpoint instead of the whole day, and
the consumer can slice by timestamp.

**Schema** — one JSON object per line:

```json
{"ts":"2026-11-03T09:15:23-04:00","src":"grok","ticker":"BRZE","name":"Braze",
 "pct":51.2,"price":45.40,"cat":"acquisition","why":"Salesforce to acquire for $47.50/sh cash",
 "ref":"https://…","conf":"high"}
```

`src` is `grok` (narrative) or `tv` (scanner data). `cat` is a controlled vocabulary:
`acquisition | merger | earnings | guidance | fda | trial | offering | halt | downgrade |
guidance-cut | other`.

**Two-source rule (important).** Grok can hallucinate a ticker or a percentage. The scanner
gives ground truth on prices. Therefore: **prices are only ever taken from the scanner or the
bridge; Grok supplies the reason, never the number.** A Grok record whose `pct` disagrees with the
scanner by more than 2pp is written with `"conf":"unverified"` and the consumer prints it as
unconfirmed. This is the whole reason the workflow has two branches.

**Workflow nodes** (I write the importable JSON):

1. **Schedule trigger** — cron, America/New_York, §5 cadence.
2. **HTTP Request → xAI Grok** — prompt asks for the current pre-market/intraday movers with
   catalyst, source URL and timestamp; response constrained to the schema.
3. **Code node** — parse, coerce, drop junk rows, enforce the vocabulary.
4. **HTTP Request → TradingView scanner** — `premarket_change`, `premarket_volume`,
   `premarket_close`, `relative_volume_10d_calc`, `halted`, `market_cap_basic`, `volume`.
   The *data* twin of Grok's *narrative* twin.
5. **Merge + normalise** — one JSONL row per name per checkpoint.
6. **GitHub node** — append to `preopen-feed/{date}.jsonl` on `main`.
7. **Error branch** — on any failure, write nothing and exit quietly. **The consumer must never
   block on a missing feed.**

**Cadence** — dense where the information edge is, sparse where the routine's own scan covers it:

| Window | Frequency | Checkpoints |
|---|---|---|
| 08:30 → 10:00 ET | every 10 min | 9 |
| 10:00 → 16:00 ET | every 30 min | 12 |

Total ≈ 21 runs per session-day. The three that matter most are **08:30** (overnight catalyst
catch), **09:20** (the gap) and **09:50** (the open flush).

---

## 5. Consumer side — the part that makes it pay

Without this the feed is a file nobody reads. Two pieces:

### 5a. `_shared/preopen_feed.py` — fetch, validate, and merge

- Fetches `preopen-feed/{date}.jsonl` via the GitHub connector or raw URL.
- Parses, validates, and **joins against the scanner/bridge data**.
- Emits a **gap-provenance table**:

| ticker | premkt % | 09:30 % | 12:00 % | now % | verdict | catalyst |
|---|---|---|---|---|---|---|
| XLAB | -8.2 | -8.2 | +20.1 | **+49.6** | **gap faded (downward)** | $8.2m NVIDIA GPU server contract |
| CCI | +17.2 | +17.6 | +13.0 | +11.1 | gap held | SpaceX in talks for 80k cell sites |
| BRZE | 0.0 | +51.0 | +50.0 | +0.3 | **arb, not momentum** | $47.50/sh cash |

- **Degrades cleanly**: missing file, malformed line, or a stale date → `feed_absent` with a
  reason. Never blocks, never fabricates.

### 5b. Cron #17 prompt + skill patch

- New step **PRE-OPEN FEED** before the tier tables: read the feed, merge, attach.
- New tier rule — **gap-that-faded**: a name that gapped beyond the floor pre-market and has since
  given the move back is flagged. This is the classic "in play" setup *and* the classic trap, and
  today the routine can only see the endpoint, never the journey.
- Two new Source health rows: `preopen-feed` and `grok`, each with row counts and the reason
  for any gap.
- The skill's chat rules get the same flag so the chat line can say "gapped +12% on the FDA nod,
  now +2%".

---

## 6. Acceptance — how we will know it works

**Functional**
1. One n8n run commits a feed file with ≥1 well-formed record.
2. `preopen_feed.py` parses it and the gap-provenance table renders.
3. **Degradation:** withhold the feed → cron #17 still writes its artifact and says
   `preopen feed absent`.
4. **Fabrication:** inject a Grok record with a wrong price → it is flagged `unverified`, not
   printed as fact.

**Regression** — I have ground truth for these sessions, so this is a real test, not a demo:

| Session | Premarket | Close | Expected verdict |
|---|---|---|---|
| 10-23 CCI | +17.2% (scanner + TheStockCatalyst agree) | +11.1% | gap held |
| 10-23 YMAT | +62.2% | +39.7% | held, faded 22pp |
| 10-15 XLAB | -8.2% | **+49.6%** | **gap faded (downward)** |
| 10-14 SKYD | -18% | -23.8% | gap held (downward) |
| 10-23 BRZE | ~0% | +0.3% | **arb, not momentum** — the rule that must not be broken |

---

## 7. Risks and costs

| Risk | Mitigation |
|---|---|
| Grok hallucinates a ticker or price | Two-source rule; >2pp disagreement → `unverified`; prices never taken from Grok |
| xAI spend | Frequency cap (§4); late-day checkpoints trimmed first; `max_tokens` bounded |
| n8n outage | Append-only JSONL — one failed run loses one checkpoint; consumer degrades gracefully |
| Repo write contention | `preopen-feed/` has exactly one writer (n8n); no cron writes there — "one owner per output directory" holds |
| Concurrent fleet edits | Repo first, scheduler second, parity verified — the same order used for the #17 prompt change |

---

## 8. Phasing — and Phase 0 needs nothing from you

**Phase 0 — implement now on approval, no n8n and no key required.**
`_shared/preopen_feed.py` plus the cron #17 consumer patch, built so it works **without** a feed:
the gap-provenance table is reconstructed from Yahoo 5-minute bars and the scanner alone. This is
most of the value and it removes the dependency on n8n for the *prices and the path*, leaving
n8n to supply only the *reasons*. Delivered: a routine that can already say "gapped +12% on the
FDA nod, now +2%".

**Phase 1 — you provide the xAI key and the n8n repo PAT.** I write the importable workflow JSON
and the README; you import it and enable it. One manual run to seed the file.

**Phase 2 — first live session.** Regression against §6, then decide on the Finviz relay
(residential-IP test first).

---

## 9. What I will write, file by file

| Path | Repo | Purpose |
|---|---|---|
| `cloud-prompts/_shared/preopen_feed.py` | migration | fetch + validate + gap-provenance merge |
| `cloud-prompts/n8n/workflow-preopen-feed.json` | migration | importable n8n workflow |
| `cloud-prompts/n8n/README.md` | migration | credentials, schedule, first-run verification |
| `cloud-prompts/cron-prompts/17-us-stocks-in-play.md` | migration | the PRE-OPEN FEED step + tier rule |
| `cloud-prompts/skills/us-stocks-in-play/SKILL.md` | migration | gap-that-faded rule + chat flag |
| `refs/preopen-feed-contract.md` | outputs | the feed contract, for other routines |

The deployed prompt is a byte-for-byte mirror of the repo file, so each prompt change is followed
by a `cron_update` and a parity check, in that order.

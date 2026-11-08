---
name: NTRT gap brief
description: >-
  Produce a morning gapper brief from `karizaco/ntrt_mtrt` backend when it's
  reachable, or fall back to MCP-driven screener. Replaces the paused
  `ntrt-pre-market-brief-paused` Grok routine (paused pending URL).
---

# NTRT gap brief

Generates the weekday pre-market gapper brief. Replaces the paused `ntrt-pre-market-brief-paused` Grok routine.

## When

- Cron: `30 6 * * 1-5` America/New_York (weekdays, 06:30 ET)
- Manual: user asks "run the ntrt brief" or "what's gapping today"

## Backend discovery

- If env var `NTRT_BASE_URL` is set (e.g. `http://127.0.0.1:8000` or VPS URL), use it.
- Otherwise default to `http://127.0.0.1:8000`.
- If env var `NTRT_AUTH_TOKEN` is set, send `Authorization: Bearer <token>`.
- Probe `GET {base}/health` first. If not 200, fall back to MCP mode.

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-ntrt-premarket.md`
- Return a short TL;DR + top gappers table to chat.

## Steps

### Mode A: backend up

1. `GET {base}/health` → confirm 200.
2. `GET {base}/api/agent/briefing` (or MCP tool `get_briefing`) — drop any huge `llm_briefing` blob; use structured sections only.
3. `GET {base}/api/gappers?min_pct=3&direction=both&limit=20` (or MCP `list_gappers` with `min_pct=3`, `limit=20`).
4. Optional: pull premarket catalyst endpoints if present, or MCP `list_premarket_catalysts` then `watchlist_premarket`.
5. Cap deep dives at top 5 by importance: `GET /api/dossier/{ticker}` or MCP `explain_gap` / `explain_premarket`.

### Mode B: backend down → MCP fallback

1. Use the host-wired TradingView MCP `screen_stocks` with filters:
   - `{ field: "premarket_change_percent", operator: "greater_or_equal", value: 3 }` OR `less_or_equal -3`
   - `{ field: "market_cap_basic", operator: "greater", value: 200000000 }` (>= $200m)
   - Markets: `["america"]`
   - Sort: by `premarket_change_percent` desc, limit 20.
2. For each top 5 by abs(premarket_gap), pull a one-line catalyst via `web_search` for `"<TICKER>" news catalyst <today>` (past 12 hours).
3. Surface what you have; clearly mark this as MCP-fallback in the brief header.

### Always

6. Compose the brief:
   - TL;DR (≤ 3 bullets)
   - Top gappers table (ticker, gap%, importance/relative-vol, sector, one-line why)
   - Catalysts
   - Anything needing human eyes
7. Save under `research/briefs/YYYY-MM-DD-ntrt-premarket.md` (don't overwrite prior files).
8. Append audit line: `brief_rendered target=ntrt-premarket:<date> mode=<A|B>`.

## Failure modes

- Backend down / connection refused → automatically try Mode B (MCP fallback). If both fail, write a short file noting both unavailable, do not invent data.
- Empty results on weekend/holiday → one-line quiet note (still write the file).
- Rate limits → stop extra dossier calls; deliver what you have.
- Auth 401/403 → report, don't retry in a loop.

## Hard rules

- Never place trades.
- Do not scrape TipRanks/Yahoo in the browser when the API is up.
- Do not fan out to other trading agents unless the user explicitly asks.
- Hard cap deep dives at 5 per run.

## Out of scope

- Long-form analyst notes per ticker — only short, structured fields.
- Cross-broker or cross-asset class research — only US equities.

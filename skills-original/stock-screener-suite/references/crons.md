# Crons — schedule + prompt

All times US/Eastern. All prompts target `agent_name: mavis`. Owner: the current user.

The prompt text is what the Agent turn sees when the cron fires. Each prompt loads the
`stock-screener-suite` skill automatically because the trigger phrase matches the skill
description; the Agent follows the skill procedure to do the work.

---

## daily-screen-sweep — 18:30 ET weekdays

```
Run stock-screener-suite for today's date. Produce the daily-screens directory
under C:/Users/admin/<user>/research/markets/daily-screens/<YYYY-MM-DD>/ with all
per-stylist Markdown + the merged master/stalk/focus/tier-a Markdown and the
_regime.json payload. Do NOT post to chat — the pre-market brief at 07:37 ET will
pick up the output. Just write the files. Print "DONE" and exit.
```

---

## breadth-snapshot — 06:30 ET weekdays

```
Run the breadth/regime portion of stock-screener-suite (step 3 only) for today's
date. Write breadth/<YYYY-MM-DD>.md and _regime.json under the daily-screens
directory. Do NOT re-run the full sweep — only the breadth + regime SQL. Quiet
output.
```

---

## reversal-bullish-355 — 15:30 + 15:55 ET weekdays

Two crons share the name; the prompt is the same:

**Directive fallback boundary** — every fallback branch ends with an explicit
"accept-and-stop" instruction so the Agent does not enter a decision loop.

```
Run the 3:55 PM ET reversal-bullish scan AND entry alert in one pass.

**IMPORTANT — how to call python:**
Call python directly with forward-slash paths. Do NOT wrap in `powershell -Command "..."`. Example:
  python "C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/scripts/screen.py" <subcommand> <args>

Steps:
1. Load the skill at C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/SKILL.md (step 5).
2. Resolve today's US/Eastern date.
3. Emit the SQL via either:
     python "C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/scripts/screen.py" reversal-bullish <YYYY-MM-DD>
   (top-level alias) OR
     python "C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/scripts/screen.py" emit-sql reversal_bullish <YYYY-MM-DD>
4. PRIMARY: call mcp__shibui-finance__stock_data_query with the SQL.
   On error / timeout / rate_limited, fall back to Finviz:
     python "C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/scripts/screen.py" finviz-url reversal_bullish
   then web_fetch that URL, then:
     python "C:/Users/admin/.minimax/agents/mavis/skills/stock-screener-suite/scripts/screen.py" finviz-parse --html-file <saved.html> --out <csv>
   **If you used Finviz fallback:** the URL already encodes "today down + above SMA50 + liquid + large-cap." Accept those rows as-is with `_source=finviz_fallback`. Do NOT chain per-ticker yahoo-finance for OHLC confirmation — that's not what the playbook says and burns 10+ calls. Cap at 10 rows.
   **If Finviz returns 0 rows or the parse fails:** write an empty CSV with `_source=finviz_fallback, error=<reason>` and skip step 5 (no chat alerts).
5. For each candidate (cap 10), send ONE chat line of the form:
   "REVERSAL-BULLISH 3:55: <symbol> entry ~<entry_price> stop <next_day_stop> funds held <proxy>"
   Only emit chat lines if `_source=mcp` (i.e., the MCP path actually returned rows). For Finviz fallbacks, skip chat alerts — the Finviz URL does not encode the 3-candle shape, so a chat alert would be misleading.
6. Write reversal-bullish-3:55.md and reversal-bullish-3:55.csv to today's daily-screens directory. Set _source=mcp or _source=finviz_fallback per row.
7. Append audit line: stock-screener-reversal-355 target=daily-screens:<date>:reversal_355 alerts=<n> source=<mcp|finviz_fallback>.
8. Return ≤5-line summary. Quiet if zero candidates.

Forward slashes in paths, not backslashes. Direct python invocation, not powershell -Command wrapper.
```

Schedule: `55 15 * * 1-5` (single cron — the 15:30 pre-fire was removed because the data is T+1 and 15:30 ET has no advantage over 15:55).

---

## premarket-gapper — 09:00 ET weekdays

```
Run the pre-market gapper sub-screen (step 6 of stock-screener-suite). For each
ticker in yesterday's focus.md, pull stock_extended_hours and flag names with
gap > 4% and pre-market volume > 50k. Send ONE chat line per flagged ticker.
Quiet if no flags.
```

---

## focus-rvol-rerank — 09:45 / 10:15 / 10:45 / 11:15 ET weekdays

```
Run step 7 of stock-screener-suite for today's date. Pull coin_analysis for each
Focus ticker, sort by intraday RVOL desc, split into RVOL Required vs Liquid
buckets, write focus-rvol-snapshot.md. If any ticker's RVOL crossed from < 1 to
> 3 since the last tick, emit one chat alert per crossed ticker. Quiet if no
crossings.
```

Schedule: `45 9 * * 1-5`, `15 10 * * 1-5`, `45 10 * * 1-5`, `15 11 * * 1-5`.

---

## pre-market-brief-hook — 07:37 ET weekdays (existing)

Add to the existing `agentic-pre-market-brief` prompt:

```
Before producing the brief, read yesterday's tier-a.md and _regime.json from
C:/Users/admin/<user>/research/markets/daily-screens/<yesterday>/. Prepend a
4-bullet section to the brief: regime state, tier-A names, today's parabolic
short/long candidates, and 3:55 PM reversal-bullish list (only if yesterday's
file exists).
```

---

## weekly-universe-refresh — Sunday 17:47 ET (existing)

Add to the existing `agentic-weekly-brief` prompt:

```
Before producing the brief, also run the IPO and High-Short-Float weekly
refresh (filters N + O in stock-screener-suite) and the theme-of-the-week
calculation (filter R). Append these as new sections to the brief output.
```

---

## pattern-study-backlog — Saturday 10:00 ET (weekly)

```
Run the peoplewish 1000%-in-10-years pattern-study refresh. Use shibui SQL
to find all symbols with at least one 1000%+ move in the last 10 years, then
tag each with chart-shape attributes (coil / VCP / breakout / EP). Append the
newly-tagged names to C:/Users/admin/<user>/research/markets/pattern-study/
peoplewish-1000pct-backlog.md. Quiet output.
```

---

## One-time — skill install + first sweep (manual)

Run once after the crons above are scheduled:

```
Run stock-screener-suite for today's date in --force mode (skip cache). This
populates the daily-screens directory for the first time so subsequent cron
runs can pick up the cache. After the sweep, print a one-line summary of how
many tickers landed in each tier and what the regime flag is. Quiet output.
```

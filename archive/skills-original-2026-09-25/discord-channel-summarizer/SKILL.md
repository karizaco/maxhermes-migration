---
name: Discord channel summarizer
description: >-
  Summarize recent Discord channel activity using fmarcac/discord-mcp (works
  for any server the user is a member of — no bot required). Accepts a guild
  + channel or a saved config of multiple channels, fetches the most recent
  N messages, and returns a structured digest: themes, key claims, watchlist
  tickers, sentiment bias. Use for manual analysis or as a scheduled digest.
---

# Discord channel summarizer

Read-only summarization layer on top of the `discord` MCP (`fmarcac/discord-mcp`). Pulls recent messages from one or more Discord channels, clusters them into themes, extracts tradeable signals (tickers, levels, catalysts), and writes a dated digest file.

## When
- Manual: user asks "summarize <channel>", "what did <server>/<channel> talk about today", "scan the trading discords"
- Cron-able: see "Scheduled digest mode" at the bottom — designed to be invoked for a configured channel list at a chosen time.

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\discord-digests\YYYY-MM-DD-<slug>.md`
- Compact ≤ 20-line summary in chat reply.

## Prerequisites

1. **Discord desktop client** running with `--remote-debugging-port` enabled.
2. **fmarcac/discord-mcp** launched via `C:\Users\admin\.minimax\bin\discord-launch.ps1` (the script kills any existing Discord, relaunches with debugging, runs `doctor` to confirm).
3. The `discord` MCP registered in `mcp.json` (already wired — see `mavis mcp list`).

If the MCP returns "no Discord process / no DevTools target found": instruct the user to run the launcher script before retrying.

## MCP tools you'll use
- `mcp__discord__guild_list` — discover guild (server) IDs the user belongs to
- `mcp__discord__guild_channels` — enumerate channels for a guild
- `mcp__discord__channel_history` — page through recent messages
- `mcp__discord__message_get` — fetch a single message by ID (rarely needed)
- `mcp__discord__search_channel` — keyword search across a single channel (use to find a known topic quickly)

## Config file

Channel targets live at `C:\Users\admin\.minimax\projects\coding-shared\research\discord-channels.yaml`. Format:

```yaml
# Each entry: human-readable slug -> {guild_id, channel_id, display_name, topic}
targets:
  - slug: wsb-flow
    guild: "WallStreetBets"
    guild_id: "1234567890"
    channel: "#daily-discussion"
    channel_id: "0987654321"
    topic: "Retail flow / ticker chatter"
    cadence: hourly   # how often this target should be scanned in scheduled mode
  - slug: options-flow
    guild: "Options Flow Hub"
    guild_id: "5555555555"
    channel: "#unusual-options"
    channel_id: "6666666666"
    topic: "Unusual options chatter"
    cadence: hourly
```

If the file is absent: prompt the user once to pick a guild + channel via `guild_list` + `guild_channels`, then save it.

## Steps

1. **Resolve targets.** If a config file exists, load `targets[]`. Else, accept a single ad-hoc `{guild_id, channel_id}` pair from the user's prompt.
2. **Pre-flight.** Call `mcp__discord__guild_list` to confirm target guilds are still in the user's account (members can leave). If a target is gone, skip it and log.
3. **Fetch messages per target.** `mcp__discord__channel_history(guild_id, channel_id, limit=200)` — defaults to most-recent. Reduce to 100 if the channel is high-velocity (>5 msg/min) to keep token usage bounded. **Read-only** — never call `message_send`, `message_edit`, `message_react`, `message_ack`, `thread_create`, `forum_post`.
4. **Normalize.** Strip embeds, attachment-only messages, bot noise (filter `author.bot == true` unless explicitly wanted). Keep messages with text > 5 chars or that contain a tickercaser.
5. **Cluster themes.** Group messages by topic:
   - Tickers mentioned (regex `\$?[A-Z]{1,5}\b` and explicit ticker mentions)
   - Catalysts (FDA, M&A, earnings, guidance, halts)
   - Sentiment tags (bullish / bearish / sarcastic / shitpost)
   - Concrete data points (price targets, levels, dates)
6. **Build digest.** For each target:
   - TL;DR (≤3 lines)
   - Top 3 tickers mentioned, with aggregate sentiment (bullish count, bearish count, mixed)
   - Notable claims (≥3 thumbs-up equivalent, or author has high karma — note source caveats)
   - Key catalysts named
   - Source health (msg count, time range, truncation)
7. **Cross-target rollup.** If >1 target, add a "Cross-target consensus" section listing tickers/themes that appeared in 2+ targets.
8. **Watchlist candidate flag.** Any ticker mentioned in ≥3 messages across targets, OR with a concrete price target + sentiment, gets flagged as `POTENTIAL_WATCHLIST_ADD` (still requires user confirmation — never auto-add).
9. **Write markdown file.** Save at `research/discord-digests/YYYY-MM-DD-<scope>.md` (scope = single-channel slug OR "multi" for full rollup).
10. **Append audit line:** `discord-summarizer target=discord-digests:<date>:<scope> channels=<n> messages=<n> potential_adds=<n> mcp_status=<ok|failed>`.

## Hard rules
- **Strictly read-only.** Never invoke any write tool from the discord MCP (the destructive tools aren't registered by default — leave them off).
- **Never post / react / ack / edit / send** to any channel. This protects both the user's account and the summarizer's reputation.
- **Cap messages per run:** 200 per target, 500 across all targets in one digest — beyond that, summarize the most recent and note truncation.
- **Citation required for claims.** Every "people are saying X" line must point to at least one message ID + author handle. The audit trail is more important than the headline.
- **No PII forwarding.** Strip email addresses, phone numbers, Discord user IDs from the digest unless they appear in the user's own watchlist context.
- **Quiet on noise.** If a channel's TL;DR is "all shitpost, no actionable content", write the file but skip the chat summary.

## Anti-patterns
- Pasting raw message logs as the digest — always summarize
- Forwarding messages verbatim with author handles attached (privacy)
- Summarizing DMs into a public-style file (always separate scope)
- Treating Discord chatter as a trade signal on its own — it's color, not signal
- Running this skill without verifying Discord is up first (always pre-flight with `guild_list`)

## Scheduled digest mode (optional)

A cron can run this skill over the configured channel list. Suggested crons:

- **Hourly weekday 09:30–16:30 ET** — for trading channels during market hours, captures intraday chatter
- **Twice daily (08:00 ET + 17:00 ET)** — pre-market and post-market recap
- **Daily 20:00 ET** — overnight scan of all channels

Example cron prompt:

```
Run discord-channel-summarizer in scheduled mode.

1. Load C:\Users\admin\.minimax\agents\mavis\skills\discord-channel-summarizer\SKILL.md.
2. Load C:\Users\admin\.minimax\projects\coding-shared\research\discord-channels.yaml.
3. Pre-flight: mcp__discord__guild_list. Skip any target whose guild is missing.
4. For each target: mcp__discord__channel_history(limit=100). Cluster themes per skill steps 5-6.
5. Write research\discord-digests\YYYY-MM-DD-multi.md with cross-target rollup.
6. Chat only if any POTENTIAL_WATCHLIST_ADD OR notable catalyst (FDA / M&A / guidance cut) appears.
7. Append audit line.

cd C:\Users\admin\.minimax\projects\coding-shared\ first.
```

Disable the cron if Discord desktop isn't running that day — the launcher is the user's responsibility.

## Out of scope
- Sending messages or any write action.
- Listening to DMs (discord MCP supports it but not recommended for routine digests — see DMs-only alt if you really need it).
- Forwarding digest content to Slack/email — that's a separate skill (use the AgentMail MCP once added).
- Trade execution. This is a research digest, never a signal.
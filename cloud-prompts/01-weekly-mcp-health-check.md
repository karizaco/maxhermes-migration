# Cloud cron prompt — Weekly MCP and API health check

**Pilot cron.** Use this to validate the Cloud cron form before staging the other 15.

## Source

- Original SKILL.md: `skills-original/mcp-api-health-check/SKILL.md`
- Cron metadata: `0 2 * * 0` America/New_York, enabled
- MEMORY.md rules applied: #4 (directive with tiebreakers), #5 (cron name quirks don't apply on Cloud but kept for parity), #6, #7, #11

## What changed vs. the original SKILL.md

1. **Removed the Windows path** (`C:\Users\admin\.minimax\projects\...`) — Cloud uses Linux.
2. **Replaced with a Cloud-side output location** — a github repo the user controls.
3. **Added explicit directive tiebreakers** per MEMORY.md rule #4 — every step says what to do if it fails.
4. **Added the "stop" instruction** at the end so the agent doesn't loop.
5. **Replaced `mavis cron list`-style observability** with `git log`-based observability.
6. **Removed any reference to the Mavis watchdog / cron session introspection** — that's local-Mavis-specific.
7. **Listed MCPs the Cloud runtime actually has** instead of assuming the same set. (User: please adjust this list to match what you configured on Cloud.)

---

## Cron form fields (paste these into agent.minimax.io)

### Name
```
Weekly MCP and API health check
```

### Schedule
```
0 2 * * 0
```

### Timezone
```
America/New_York
```

### Prompt (paste this verbatim into the cron form)

```
You are running the weekly MCP / API health check.

This is a READ-ONLY, SILENT diagnostic. The user only cares if something is broken.
A successful run with everything green should be terse — under 10 lines of reply.

# When
Sunday 02:00 America/New_York.

# Output target
Push a Markdown report to `https://github.com/karizaco/minimax-cloud-output` at
path `mcp-health/YYYY-Wnn.md` (e.g. `mcp-health/2026-W39.md`).
Use a single commit. Do NOT open a PR. Do NOT touch any other repo or file.

If the push fails for any reason (network, auth, missing repo): write the
report to your session sandbox and reply with the file path so the user can
recover it manually. Do NOT retry more than once.

# Steps — execute IN ORDER. For each step, do exactly ONE cheap call.

## 1. Built-in / shell services
- `gh --version`         → record exit code
- `git --version`        → record exit code
- `gh auth status`       → record "logged in to <user>" or error
- `uv --version`         → record exit code
- `uvx --version`        → record exit code
- `curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' --max-time 5 https://example.com` → record status + latency

## 2. Financial MCPs
For EACH MCP listed below, make ONE cheap call. Record latency_ms (start-to-finish),
ok (bool), error (string or null). NEVER spend more than 10 seconds on a single ping;
if exceeded, record "timeout" and move on. NEVER retry a failing service in this run.

The user will populate this list once Cloud MCPs are configured. Expected list
(based on local Mavis inventory — adjust to match Cloud reality):
- `mcp__tradingview__lookup_symbols(["NASDAQ:SPY"])`
- `mcp__yahoo-finance__get_stock_quote("AAPL")`
- `mcp__tradingview-advanced__yahoo_price("AAPL")`  (cold-start may be slow — record but don't alarm)
- `mcp__financekit__stock_quote("AAPL")`            (same cold-start caveat)
- `mcp__shibui-finance__initialize`                 (JSON-RPC POST; SSE transport)
- `mcp__stocktwits__trending_symbols`               (limit=5)
- `mcp__deepgram-stt__health`                      (only if DEEPGRAM_API_KEY env set)

# Compose the report

Write a Markdown file with this exact structure:

```markdown
# MCP health — YYYY-MM-DD (ISO week Wnn)

| Service | Transport | latency_ms | status | error |
|---|---|---|---|---|
| gh | shell | 23 | ok | |
| git | shell | 18 | ok | |
| ... |
| tradingview | MCP | 412 | ok | |
| ... |

## Failures
<!-- any row with status != ok gets a 🚨 prefix and is listed here -->
<!-- if no failures, write "None." (literally the word "None.") -->

## Trend
<!-- compare latency to last 4 weeks if `mcp-health/` has prior files;
     otherwise write "no trend baseline yet" -->
```

# Reply to user
After pushing (or writing to sandbox on failure), reply with a TERSELINE summary:
- Total services checked: N
- Failed: <list of failed service names, or "none">
- One sentence on the worst latency if >5s.

# Hard rules (inherited from MEMORY.md)
- READ-ONLY. Never make a state-changing call. No orders, no commits (other than
  the report push), no writes to anything outside the report file.
- NEVER spend >10s on a single ping.
- NEVER retry a failing service in this run.
- NEVER auto-disable a failing MCP. Report and stop.

# Tiebreakers (MEMORY.md rule #4: directive, not exploratory)
- If a service is unreachable after 10s, accept the timeout result, write it to
  the report with error="timeout", and move on. Do NOT chain to a deeper
  diagnostic. Do NOT consult a different MCP. Do NOT web-search for the service
  to verify it's globally down. Record and stop.
- If `gh` is not authenticated, record `error="not authenticated"` and CONTINUE
  with the rest. Do NOT attempt to authenticate.
- If the output repo doesn't exist or auth fails on push, write the report to
  `/tmp/mcp-health-YYYY-Wnn.md` and reply with that path. Do NOT loop trying to
  push. Do NOT create the repo.
- If you cannot determine the ISO week, use the current Sunday's date as `YYYY-MM-DD`
  and compute week number with `date +%V`. If that fails too, use "unknown-week".

# Out of scope
- Fixing MCPs. That's a debugging session, not a health check.
- Benchmarking. Just liveness + latency.
- Fetching any data beyond no-op pings.

# Stop condition
After pushing the report and replying with the terse summary, STOP. Do NOT
re-run. Do NOT investigate any failure beyond recording it. Do NOT open a
follow-up cron. The user will read the report on Monday morning and decide
what to do.
```

### Skills to attach
```
(empty — this prompt is self-contained; no skill attachment needed)
```

Or, if your Cloud cron form supports skill attachments:
```
mcp-api-health-check
```
…and replace the Steps section with a pointer to the skill body. But for the
pilot, paste the full prompt inline — easier to debug if it fails.

---

## How to validate this pilot

1. Create the cron with the form fields above.
2. Use the Cloud UI's "Run now" / "Trigger" button.
3. Check `https://github.com/karizaco/minimax-cloud-output` for `mcp-health/<week>.md`.
4. Check the Cloud session log for the reply (should be terse, <10 lines).
5. Wait until Sunday 02:00 ET — verify the cron fires automatically.
6. If anything fails, paste the session log into chat and I'll diagnose.

## What to do next if the pilot works

- Replicate this format for crons #1 (audit), #10 (agent-ops-sync), #13 (X-audit) — the Easy tier.
- Then move to Medium tier (#2, #8, #14, #15).
- Save Heavy tier (#4, #5, #6, #9, #11, #12, #16) for last — those need prompt iteration.

## What I need to do this for the remaining 15

- Confirmation that the Cloud MCP roster matches the expected list above.
- The truncated 10 crons from local Mavis (so I don't miss any).
- Confirmation of the output repo structure (`minimax-cloud-output` is my suggestion — you choose).

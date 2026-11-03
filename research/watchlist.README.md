# The watchlist — where it lives and how to publish it

**Status (2026-11-03): NOT PUBLISHED.** No watchlist file exists at the published path, so cron
#26's watchlist section is omitted from the brief and cron #19's watchlist section is omitted
from the earnings reminder. Both say so once in their `## Source health` / notes and ship no
empty table.

This directory holds the **schema and the publish instructions**. It deliberately does NOT hold a
live `watchlist.yaml` — a file with no tickers in it would make the routine publish an empty
"Watchlist" section every morning, which is exactly the failure mode this replaces.

## Why it moved out of the sandbox

The skill's original watchlist was `research/watchlist.yaml` on the local Windows Mavis host. That
path is not reachable from the Cloud runtime, so the watchlist leg has **never** succeeded there:
every artifact since 2026-10-14 has carried the same "not published" line, and the brief has
carried a permanent explanatory section. Cron #19's own review reached the same conclusion
(`docs/IMPROVEMENTS-cron19-earnings-reminder.md`, item 4).

The fix is to make the watchlist a **published artifact** that both routines fetch at run time,
rather than a local file that only one machine can see.

## The published path

```
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
```

`refs/` in the outputs repo is already the fleet's home for shared reference files
(`refs/cron-ops.md`, `refs/preopen-feed-contract.md`, `refs/skipped-markers/`), so the watchlist
belongs there and not in a routine's own output directory.

Both routines fetch this URL at run time:

| Routine | Fetches it at | Behaviour if present | Behaviour if 404 |
|---|---|---|---|
| #26 `agentic-pre-market-brief` | Step 7 | publishes the watchlist section | omits the section, one Source-health line |
| #19 `earnings-reminder-daily` | Step 1 | publishes "Your watchlist" | omits the section, one note |

## How to publish it

1. Copy `research/watchlist.example.yaml` to your own working copy and fill in the tickers.
2. Commit it to the outputs repo at `refs/watchlist.yaml` on branch `main`:

   ```bash
   git clone --depth 1 https://github.com/karizaco/minimax-cloud-outputs.git
   cd minimax-cloud-outputs
   cp /path/to/your/watchlist.yaml refs/watchlist.yaml
   git add refs/watchlist.yaml
   git commit -m "refs: publish the watchlist"
   git push origin HEAD:main
   ```

   Do **not** use `git add -A` in that repo — a fresh sandbox clone stages every other file on the
   branch as deleted. Stage only `refs/watchlist.yaml`. If the push is rejected (another routine
   pushed in the same minute), `git fetch origin main` and re-commit on top of the new tip.

3. Verify:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" \
     https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
   ```

   `200` = published, and the next brief carries a real watchlist section. `404` = not published.

## Schema

See `research/watchlist.example.yaml`. The rules the routines rely on:

- `watchlist` is a list of tickers. `ticker` is required; everything else is optional.
- `ticker` is the plain US symbol (`AAPL`, not `NASDAQ:AAPL`).
- `earnings_flag: true` marks a name the earnings reminder should always highlight.
- `note` is free text carried into the brief.
- Unknown keys are ignored, so the file can grow without a routine change.

## Rules

- **Do not extend the user's watchlist unilaterally.** The routines publish what is in the file and
  nothing else. If a name is not in the file, it does not appear in the watchlist section.
- **Do not publish a placeholder.** A watchlist file with no real tickers is worse than no file:
  it turns an honest "no watchlist today" into an empty section that reads as a bug.

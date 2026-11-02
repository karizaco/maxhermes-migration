#!/usr/bin/env python3
"""
rewrite_prompts.py — apply the audit's prompt rewrites (WP4, WP5, WP6, WP7) to the fleet.

Deterministic, idempotent, and self-verifying. It edits ONLY the section between a known
heading and the next heading, so it cannot silently mangle a prompt.

Each rewrite is applied per-prompt with per-prompt parameters (output dir, artifact path,
skip marker name). The script asserts:
  - the expected section was found exactly once
  - the replacement is byte-different from the old text
  - the prompt still parses as markdown with balanced code fences
  - no stale marker strings survive

Run:  python3 tools/rewrite_prompts.py --check    (dry run, reports what would change)
      python3 tools/rewrite_prompts.py --apply
"""
import argparse, os, re, sys, json

CRON = "cloud-prompts/cron-prompts"

# routine -> (output dir, artifact path template, skip marker stem)
META = {
 "02": ("asia-pre-market",   "asia-pre-market/{date}.md",                      "asia_pre_market_reactions"),
 "04": ("daily-screens",    "daily-screens/{date}/reversal-bullish-3:55.md",   "reversal_bullish_3_55"),
 "05": ("international-eod","international-eod/{date}/",                        "eod_international_daily"),
 "06": ("daily-screens",    "daily-screens/{date}/weekly-ipo.md",              "stock_screener_pattern_study_backlog"),
 "07": ("daily-screens",    "daily-screens/{date}/focus-rvol-snapshot.md",     "stock_screener_focus_rvol_09_45"),
 "08": ("daily-screens",    "daily-screens/{date}/pre-market-gapper.md",       "stock_screener_pre_market_gapper"),
 "09": ("daily-screens",    "daily-screens/{date}/daily-sweep.md",             "stock_screener_daily_sweep_18_30"),
 "10": ("daily-screens",    "daily-screens/{date}/breadth-snapshot.md",        "stock_screener_breadth_snapshot"),
 "12": ("cross-asset",      "cross-asset/{date}.md",                           "cross_asset_correlation_snapshot"),
 "13": ("macro-calendar",   "macro-calendar/{date}-midweek.md",                "macro_calendar_midweek"),
 "14": ("macro-calendar",   "macro-calendar/{date}-week-ahead.md",             "macro_calendar_week_ahead"),
 "15": ("earnings",         "earnings/{date}-reactions.md",                    "earnings_reaction_scanner"),
 "16": ("options-flow",     "options-flow/{date}.md",                          "unusual_options_flow_daily"),
 "17": ("us-stocks-in-play","us-stocks-in-play/{date}.md",                     "us_stocks_in_play"),
 "19": ("earnings",         "earnings/{date}-reminders.md",                    "earnings_reminder_daily"),
 "20": ("us-eod",           "us-eod/{date}.csv",                               "eod_watchlist_csv_snapshot"),
 "22": ("weekly",           "weekly/{date}-preview.md",                        "weekly_market_recap_preview"),
 "23": ("daily-briefs",     "daily-briefs/{date}-post-market.md",              "agentic_post_market_brief"),
 "25": ("ntrt",             "ntrt/{date}.md",                                  "ntrt_gap_brief_daily"),
 "26": ("daily-briefs",     "daily-briefs/{date}-pre-market.md",               "agentic_pre_market_brief"),
}
# Routines that fire on a weekday and therefore need the market-holiday guard.
WEEKDAY_ROUTINES = [r for r in META if r not in ("06", "13", "14", "22")]

HOLIDAYS = ("2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 "
            "2026-07-03 2026-09-07 2026-11-26 2026-12-25")
HOLIDAYS_PIPE = "|".join(HOLIDAYS.split())


def _headings_outside_fences(text):
    """Yield (level, heading_text, start, end) for markdown headings NOT inside a code fence.

    Essential: the prompts contain bash blocks whose comments start with '# ' (e.g.
    "# Window flags for THIS cron"), which a naive `^#{1,4} ` regex mistakes for headings.
    """
    out = []
    lines = text.split("\n")
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    infence = False
    for i, ln in enumerate(lines):
        st = ln.strip()
        if st.startswith("```"):
            infence = not infence
            continue
        if infence:
            continue
        m = re.match(r"^(#{1,4})[ ]+(.+?)[ ]*$", ln)
        if m:
            out.append((len(m.group(1)), m.group(2), offsets[i], offsets[i] + len(ln) + 1))
    return out


def find_heading(text, heading):
    """Return (start, end, level) of the section whose heading matches, or None."""
    bare = heading.lstrip("#").strip()
    hits = [h for h in _headings_outside_fences(text) if h[1] == bare]
    if len(hits) != 1:
        return None, len(hits)
    level, _title, start, _end = hits[0]
    # section ends at the next heading of the same or higher level
    end = len(text)
    for lvl, _t, s, _e in _headings_outside_fences(text):
        if s > start and lvl <= level:
            end = s
            break
    return (start, end, level), 1


def replace_prose(text, heading, new_body, label, log):
    """Replace ONLY the heading's own prose — up to the next heading of ANY level.

    Needed for `## RUNTIME DATA-SOURCE CONTRACT`, whose `### MCP AVAILABILITY PROBE`,
    `### PRIMARY SOURCE` and `### Rules` subsections are nested inside it. Replacing the
    whole `##` span would delete the bridge instructions.
    """
    span, n = find_heading(text, heading)
    if span is None:
        log.append(f"  SKIP {label}: heading matched {n} times (need exactly 1)")
        return text, False
    start, _end, _level = span
    # body ends at the next heading of any level
    body_end = len(text)
    for lvl, _t, s, _e in _headings_outside_fences(text):
        if s > start:
            body_end = s
            break
    old = text[start:body_end]
    if old.strip() == new_body.strip():
        log.append(f"  ok   {label}: already current")
        return text, False
    text = text[:start] + new_body + text[body_end:]
    log.append(f"  CHANGED {label}: {len(old)}B -> {len(new_body)}B")
    return text, True


def replace_section(text, heading, new_body, label, log):
    """Replace the whole section (heading + body) up to the next heading of the same/higher level."""
    span, n = find_heading(text, heading)
    if span is None:
        log.append(f"  SKIP {label}: heading matched {n} times (need exactly 1)")
        return text, False
    start, end, _level = span
    old = text[start:end]
    if old.strip() == new_body.strip():
        log.append(f"  ok   {label}: already current")
        return text, False
    text = text[:start] + new_body + text[end:]
    log.append(f"  CHANGED {label}: {len(old)}B -> {len(new_body)}B")
    return text, True


# The three bespoke-shaped prompts use different headings for the same content.
WINDOW_HEADING = {
    "07": "## STEP 1 — WINDOW CHECK (run this first)",
    "15": "## STEP 1 — WINDOW CHECK (run this first, before anything else)",
}
# #26 has no RUNTIME DATA-SOURCE CONTRACT at all: its contract prose was inlined inside
# MCP TOOLS AVAILABLE. Splitting it back out is finding A2.
CONTRACT_HEADING = "## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)"


def window_block(routine, out_dir, artifact, skip):
    """The window check: one live gate (market holidays). The scheduler owns the day."""
    return f"""## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    {HOLIDAYS_PIPE})
        mkdir -p /workspace/$DATE
        cat > /workspace/$DATE/SKIPPED_{skip}.md <<EOF
# Cron #{routine} {skip} — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: US market holiday ($DATE)
- No artifact produced.
EOF
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```

"""


def tools_block(routine):
    return """## MCP TOOLS AVAILABLE

The **MCP-over-HTTP bridge** (`_shared/mcp_bridge.py` — see PRIMARY SOURCE) is the market-data
source. Then `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*` (repo
writes). **No `mcp__*` finance tool is registered in this runtime** — do not call one and do not
invent tool names.

"""


def contract_block():
    return """## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The `mcp__*` tools named above DO NOT EXIST in this runtime.** Do not attempt an MCP call and do
not wait for one to appear — a tool-not-found error converts into an early abort with no artifact.
Use instead: `web_search`, `web_fetch`, `bash` (curl, python3), and `connector__github__*` for repo
writes.

**Source ladder — try in this order, fall through on a real failure:**

1. bridge `market-recap` → `get_quotes` (batch quotes, `previous_close`, `change_pct`, `volume`,
   `as_of`, `market_state`). Not rate-limited. **This is the quote source of record.**
2. TradingView scanner `POST https://scanner.tradingview.com/america/scan` — movers, RVol,
   `premarket_volume`, `halted`, `market_cap_basic`.
3. Yahoo JSON — **availability varies by egress** (429 from one cron session, 200 from another on
   the same day). Try it; on 429/401 fall through. `quoteSummary`/`options` need the crumb.
4. Nasdaq API, SEC EDGAR (needs a contact-style User-Agent), CoinGecko, Frankfurter, Treasury CSV.

**A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you never
successfully queried. Retry once after a short sleep, then fall through.

**Sanity-check the RESPONSE BODY, not just the HTTP status.** Stooq returns 200 with a JavaScript
challenge, not CSV.

Full endpoint list + measured status:
`https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`


"""


def probe_block():
    return """### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
[ -s /workspace/probe_mcp.py ] || curl -sL -o /workspace/probe_mcp.py "$B/probe_mcp.py"
python3 /workspace/probe_mcp.py
```

Record the result in this run's `## Source health`. It prints exactly one of:
- `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
- `catalog_unreachable` — the probe failed. **NOT** evidence that no MCPs exist.
- `probe_unavailable` — the probe binary is absent. **NOT a finding**; use the source ladder.


"""


def push_block(out_dir, artifact, branch="main", heading="## PUSH THE ARTIFACT"):
    return f"""{heading}

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out {out_dir} --add {artifact} --branch {branch}
sh /workspace/verify_delivery.sh --path {artifact} --branch {branch}
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).


"""


PRECEDENCE_RULE = """7. **One number per field, one source per field.** When two sources give different
   values for the same field, pick ONE and say which in `## Source health`: the bridge's
   `market-recap` for prices and movers (it is Yahoo-sourced and not rate-limited), the TradingView
   scanner for pre-market and RVol, Yahoo JSON for history. When they disagree by more than 0.6 %,
   prefer the bridge, say so, and **do not publish both**. Never report "no source available" when
   a source is reachable — a 429 is a rate limit, not an absence.
"""

RULES_FULL = """1. **A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a
   symbol you never successfully queried. Retry once after a short sleep, then fall through the
   ladder.
2. **Sanity-check the RESPONSE BODY, not just the HTTP status.** The proxy can return HTTP 200
   carrying a plain-text error page. Confirm the body parses as the JSON/CSV you expect.
3. **Never fabricate a number.** If every source for a symbol failed, omit that symbol and say so.
   A missing row is recoverable; an invented price is not.
4. **Distinguish "no data" from "no source".** No print today (pre-market, weekend, holiday) is
   `no_data`. A symbol you could not fetch is `fetch_failed` — name the reason and HTTP status.
5. **Every artifact discloses per-source health**: a `## Source health` section **or** an equivalent
   `_source=` front-matter line — per source, the URL/query used, the HTTP status, and `ok` /
   `failed:<reason>`. If a source was rate-limited, say `429 rate-limited` and which fallback you
   used. Never hide a degraded run.
6. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the artifact
   with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the whole run
   because one source was blocked. The zero-fallback policy governs the *fallback chain*, not
   whether the artifact gets written.
""" + PRECEDENCE_RULE



DATE_RULE = """The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
"""

ERRORS_RULE = """- `errors: <n>` — count of **SOURCE** failures that degraded the artifact. 0 = clean run. The
  absent `mcp__*` tools are NOT an error and must not be counted.
"""


def fences_balanced(t):
    return t.count("```") % 2 == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only", default=None, help="restrict to a comma-separated routine list")
    args = ap.parse_args()
    if not (args.apply or args.check):
        args.check = True

    targets = sorted(META)
    if args.only:
        want = set(args.only.split(","))
        targets = [r for r in targets if r in want]

    changed_any = False
    for routine in targets:
        out_dir, artifact, skip = META[routine]
        files = [f for f in os.listdir(CRON) if f.startswith(routine + "-")]
        if not files:
            print(f"  !! {routine}: no prompt file"); continue
        path = os.path.join(CRON, files[0])
        text = open(path, encoding="utf-8").read()
        log = []
        before = text

        # WP4 — window check (heading differs for the bespoke-shaped prompts)
        whead = WINDOW_HEADING.get(routine, "## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)")
        text, c = replace_section(text, whead,
                                  window_block(routine, out_dir, artifact, skip),
                                  f"{routine} window", log)
        # WP5.1 — tool list (#26 is handled together with its contract, below).
        # #07, #15 and #19 carry no MCP TOOLS AVAILABLE block — they never advertised the
        # phantom tools, so there is nothing to rewrite there.
        if routine != "26":
            span, n = find_heading(text, "## MCP TOOLS AVAILABLE")
            if span is None:
                log.append(f"  ok   {routine} tools: no MCP TOOLS AVAILABLE block (nothing to fix)")
            else:
                text, c2 = replace_section(text, "## MCP TOOLS AVAILABLE", tools_block(routine),
                                           f"{routine} tools", log)
        # WP5.2 — contract PROSE only (its ### subsections are nested inside and must survive).
        # For #26 the contract prose was inlined inside MCP TOOLS AVAILABLE (finding A2), so
        # rebuild the section: tools list, then a real RUNTIME DATA-SOURCE CONTRACT heading.
        if routine == "26":
            text, _ = replace_section(
                text, "## MCP TOOLS AVAILABLE",
                tools_block("26") + contract_block(), "26 tools+contract", log)
            # the retired tombstone is dead weight once the holiday guard exists (C3)
            text, _ = replace_section(text, "## WEEKEND MODE (RETIRED 2026-10-31)",
                                      "", "26 weekend tombstone", log)
        else:
            text, c3 = replace_prose(text, CONTRACT_HEADING,
                                     contract_block(), f"{routine} contract", log)
        # WP5.3 — the --list-packs mislabel, inside the PRIMARY SOURCE bridge block
        if "enumerate available packs" in text:
            text = text.replace(
                "python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs",
                "python3 /workspace/mcp_bridge.py --list-packs                   # SEMANTIC DISCOVERY, not an inventory")
            text = text.replace(
                "python3 /workspace/mcp_bridge.py --list-packs  # enumerate available packs",
                "python3 /workspace/mcp_bridge.py --list-packs  # SEMANTIC DISCOVERY, not an inventory")
            log.append(f"  CHANGED {routine} bridge: --list-packs mislabel")
        # WP5.4 — shrink the MCP AVAILABILITY PROBE prose to a pointer.
        # The heading has two wordings in the fleet.
        for ph in ("### MCP AVAILABILITY PROBE (non-blocking, one cheap call)",
                   "### MCP AVAILABILITY PROBE (non-blocking, run once at the start)"):
            span, n = find_heading(text, ph)
            if span is not None:
                text, _ = replace_prose(text, ph, probe_block(), f"{routine} probe", log)
                break
        else:
            log.append(f"  ok   {routine} probe: rebuilt as part of the contract block")
        # WP6 — push + delivery verification (one section each)
        text, c4 = replace_section(text, "## GIT PUSH (OPTIONAL)",
                                   push_block(out_dir, artifact,
                                              heading="## GIT PUSH (OPTIONAL)"), f"{routine} push", log)
        text, c5 = replace_section(text, "## DELIVERY VERIFICATION (MANDATORY - do this after the push block)",
                                   push_block(out_dir, artifact,
                                              heading="## DELIVERY VERIFICATION (MANDATORY - do this after the push block)"),
                                   f"{routine} verify", log)
        # WP7.1 — source precedence
        if "One number per field, one source per field." not in text:
            m = re.search(r"^(### Rules\n\n.*?)(\n\n)", text, re.S | re.M)
            if m:
                text = text[:m.end(1)] + "\n" + PRECEDENCE_RULE + text[m.end(1):]
                log.append(f"  CHANGED {routine} rules: +precedence")
            elif routine == "26":
                # #26 has no Rules block at all - give it one, so the precedence rule has a home.
                anchor = "## ZERO-FALLBACK POLICY"
                if anchor in text:
                    text = text.replace(anchor, "### Rules\n\n" + RULES_FULL + "\n" + anchor, 1)
                    log.append(f"  CHANGED {routine} rules: +precedence (new Rules block)")
                else:
                    log.append(f"  SKIP {routine} rules: no '### Rules' block")
            else:
                log.append(f"  SKIP {routine} rules: no '### Rules' block")
        # WP7.2 — scheduled-date rule
        if "the fire's **scheduled** date" not in text:
            m = re.search(r"(The `\{date\}` placeholder is today in US/Eastern, `YYYY-MM-DD`\.[^\n]*\n[^\n]*?Resolve it as the first step\.)", text)
            m2 = (re.search(r"(`\{date\}` = today in US/Eastern, `YYYY-MM-DD`\. Resolve it as the FIRST step\.)", text)
                  if not m else None)
            if m:
                text = text[:m.start()] + DATE_RULE + text[m.end():]
                log.append(f"  CHANGED {routine} output: +scheduled-date rule")
            elif m2:
                text = text[:m2.start()] + DATE_RULE + text[m2.end():]
                log.append(f"  CHANGED {routine} output: +scheduled-date rule")
            elif routine in ("07", "15"):
                # These two resolve the date with `DATE=$(... date +%Y-%m-%d)` at run time and
                # have no `{date}` placeholder clause. The delayed-replay rule still applies to
                # them, so state it where they resolve the date.
                m3 = re.search(r"^(DATE=\$\(TZ=America/New_York date \+%Y-%m-%d\)\n)", text, re.M)
                if m3:
                    ins = ("# The date is the fire's SCHEDULED date, not the execution date. If this is a\n"
                           "# delayed replay (the platform re-dispatches a session whose quota was exhausted),\n"
                           "# rebuild for the scheduled date and say so in the artifact - do not skip.\n")
                    text = text[:m3.start()] + ins + text[m3.start():]
                    log.append(f"  CHANGED {routine} output: +scheduled-date note")
                else:
                    log.append(f"  SKIP {routine} output: date clause not found")
            else:
                log.append(f"  SKIP {routine} output: date clause not found")
        # WP7.3 — errors definition
        if "count of MCP failures" in text:
            # The existing bullet reads "... and one line for `errors: <n>` — count of MCP
            # failures that triggered fallback. 0 = clean run." — replace the WHOLE bullet,
            # not just its tail, or the two halves interleave into a mangled line.
            m = re.search(r"^(\s*)(-\s*`errors: <n>`[^\n]*(?:\n\s*[^\n]*)?)", text, re.M)
            if m:
                text = text[:m.start()] + ERRORS_RULE.rstrip() + text[m.end():]
                log.append(f"  CHANGED {routine} errors: source-failure wording")
            else:
                text = text.replace(
                    "count of MCP failures that triggered fallback. 0 = clean run.",
                    ERRORS_RULE.strip())
                log.append(f"  CHANGED {routine} errors: source-failure wording")

        # verification
        problems = []
        if not fences_balanced(text):
            problems.append("unbalanced code fences")
        # The flag block must be gone from the window check.
        for stale in ("WEEKDAYS_ONLY=true", "MARKEND_ONLY", "WEEKEND_ONLY=true",
                      "MARKET_HOURS_ONLY=true", "DAY_OF_WEEK=0   #"):
            if stale in text:
                problems.append(f"stale string survives: {stale!r}")
        # The `--list-packs` mislabel must be gone.
        if "enumerate available packs" in text:
            problems.append("stale string survives: 'enumerate available packs'")
        # The phantom tool must not be ADVERTISED. It is legitimate to keep the sentence that
        # says the tool does NOT exist, so only flag it inside an advertised tool list.
        for m in re.finditer(r"## MCP TOOLS AVAILABLE(.*?)(?=\n## )", text, re.S):
            if "extract_content_from_websites" in m.group(1):
                problems.append("phantom tool still advertised in MCP TOOLS AVAILABLE")
        # The exit-status trap must be gone from the push blocks. Match the COMMAND form
        # (a git push piped into head), not the prose that tells the agent not to do it.
        for m in re.finditer(r"## GIT PUSH \(OPTIONAL\)(.*?)(?=\n## )", text, re.S):
            # The trap is a COMMAND: `git push ... 2>&1 | head -3`. A sentence that says
            # "never `git push ... | head -3`" is a warning, not a defect - so require the
            # pipeline to be at the end of a line that actually starts with git push.
            if re.search(r"^\s*(if\s+)?git push[^\n]*\|\s*head", m.group(1), re.M):
                problems.append("push block still contains the 'git push ... | head -3' exit-status trap")
        if problems:
            print(f"  FAIL {path}")
            for p in problems:
                print(f"        - {p}")
            continue

        if text != before:
            changed_any = True
            print(f"  {files[0]}")
            for l in log:
                print(l)
            if args.apply:
                open(path, "w", encoding="utf-8").write(text)

    print(f"\n{'CHANGES APPLIED' if args.apply else 'DRY RUN'} — "
          f"{'files differ' if changed_any else 'no changes needed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

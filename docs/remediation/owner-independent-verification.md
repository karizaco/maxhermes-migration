# Owner-side independent verification (Mavis, session 458676653531358)

These are observations I made MYSELF while the four audit tracks were running, from the
ROOT session (458676653531358). They are **not** from any track file. Several of them
CORRECT or QUALIFY what a track asserted, because the sandbox environment differs between
sessions. The synthesis must treat this file as a fifth input.

## Why this file exists — the central methodological caveat

Two of the runtime facts a track measured are **environment-dependent, not absolute**. The
same URL returns different results from different cron sessions. Any finding that states a
runtime status as a universal truth is wrong. The correct instruction form is
"handle both states", never "state is X".

## ENV-1 — `mcode-tools` IS installed in the root session (contradicts track-b B6)

Track-b asserted (B6): "`mcode-tools` is not installed in this sandbox" and built a
high-severity finding on it, recommending a new `probe_unavailable` catalog state.

In the ROOT session it works:

```
$ which mcode-tools
/usr/local/bin/mcode-tools
$ mcode-tools connector tools | head -c 300
{
  "tools": [
    {
      "tool_name": "connector__email_workbench_credentials__exchange",
...
$ mcode-tools connector tools >/dev/null 2>&1; echo $?
0
$ python3 /workspace/probe_mcp.py
catalog_ok total=133 finance_tools=0 | bridge bridge_ok packs=tradier,fmp,market-recap
```

So the catalog IS enumerable as `catalog_ok total=133 finance_tools=0` from a session where
the binary is present, and the deployed/repo claim of **133 tools, 0 finance** is CONFIRMED
(not merely "unverified").

**Implication for the report:** B6 is a property of ONE sandbox image, not of the runtime.
The genuine, actionable finding is the weaker and more useful one: *the MCP AVAILABILITY
PROBE's three states do not cover "the probe binary is missing"*, and a session without
`mcode-tools` reports `catalog_unreachable` — which the prompts explicitly define as
"NOT evidence that no MCPs exist". That is already handled correctly by the prompts, so the
probe is fine; what must be added is that the probe is **not portable across sandbox
images**, and a routine should degrade to its normal source ladder rather than treat it as a
finding. The report must NOT tell the operator to stop using `mcode-tools`.

## ENV-2 — Yahoo JSON is 429 in the ROOT session but 200 in the track-b session

Track-b's endpoint table says Yahoo chart = **200**, so "repo accurate / deployed stale".

In the ROOT session, Yahoo JSON is **429** — consistently, across both hosts and with a
retry after a pause:

```
Yahoo chart (SPY)        HTTP 429   (query1, UA set)
Yahoo screener           HTTP 429   (query1)
Yahoo quoteSummary       HTTP 429   (query2)
Yahoo options            HTTP 429   (query2)
Yahoo chart retry (8s)   HTTP 429
Yahoo chart via query2   HTTP 429
crumb handshake          HTTP 404 (consent) -> crumb='Too Many Requests' -> chart HTTP 000
```

6 spaced attempts were all `429 Too Many Requests` (19 B body).

**Interpretation:** Yahoo's JSON rate limiting is **per egress IP**, and cron sessions land
on different egresses. Both observations are simultaneously true. The repo's
"Measured 2026-10-31 — Yahoo's JSON endpoints are working again" was true on 2026-10-31 and
is false again on 2026-11-02.

**Implication for the report:** the repo text is not simply "stale" — it is
**time-unstable**. The right fix is a *conditional* instruction (try Yahoo, fall through on
429, never treat 429 as "no data"), NOT a new absolute claim. Recommending the repo's current
wording be deployed as-is would replace one unstable claim with another. This is a
first-order correction to the synthesis.

## ENV-3 — the bridge resolves by TOOL NAME across packs (adds to track-b's list-packs finding)

`mcp_bridge.py --list-packs` is semantic discovery over a discovery query — confirmed: the
default query returned only `tradier, fmp, market-recap` while `stocktwits` and `shibui`
answer perfectly when called directly.

A stronger fact the track may not have stated: the Pipeworx gateway resolves **by tool name
across packs**, not strictly by pack name.

```
stocktwits get_quotes  -> identical payload to market-recap get_quotes
                          (same retrieved_at 2026-11-02T05:39:36.317Z)
market-recap get_quotes -> same payload
stocktwits top_movers   -> works, returns market-recap top movers
stocktwits bogus_tool   -> "Unknown tool ... No pack in the Pipeworx catalog exports that name"
some-random-pack-xyz    -> "Unknown pack ... Browse every pack at https://pipeworx.io/directory"
```

So `stocktwits get_quotes` and `market-recap get_quotes` are **the same server**, and the
"two independent sources agree" framing only holds for tools that genuinely differ:
`stocktwits chart_data` (gateway host) vs `shibui stock_data_query` (mcp.shibui.finance host)
did return the same SPY close 755.72 from two different hosts — that cross-check IS valid.

## ENV-4 — `shibui` has NO `get_quotes` tool, so #01's weekly probe always logs a false degradation

#01's Bridge-packs probe loops `get_quotes` over `stocktwits shibui market-recap`:

```
stocktwits   -> works (actually market-recap's tool)
shibui       -> {"error":"tool_error","detail":[{"text":"Unknown tool: 'get_quotes'"}]}
market-recap -> works
```

`shibui` therefore **errors every single week** — but not because shibui is broken. The
prompt then says "A pack that errors is a **degradation**, not a failure of the routine",
so the weekly `mcp-health/ledger.md` accumulates a **false degradation row for shibui every
week**. The fix is to probe each pack with a tool that pack actually exports
(`shibui` -> `stock_data_query`; `market-recap` -> `get_quotes`), or to treat
"Unknown tool" as "not applicable" rather than "degraded".

## ENV-5 — Stooq is a 200 + JS challenge, not a 404 (corrects the "Stooq CSV is blocked (404)" line)

The prompt line `Stooq CSV is blocked (404)` is wrong in a way that matters:

```
status=200 size=796
<!DOCTYPE html>...This site requires JavaScript to verify your browser...
```

Stooq returns **HTTP 200** with a JavaScript proof-of-work challenge, not a 404. An agent
that checks only the HTTP status (which the prompts elsewhere tell it to do via the
"sanity-check the RESPONSE BODY" rule) would parse this HTML as CSV. The prompt's own Rule 2
already covers the correct behaviour; the factual label is what is wrong.

## ENV-6 — Frankfurter moved host; `curl -s` without `-L` silently yields an HTML 301

```
https://api.frankfurter.app/latest?from=EUR&to=USD   -> HTTP 301, Location: https://api.frankfurter.dev/v1/latest?...
curl -s  (no -L) -> <html><head><title>301 Moved Permanently</title></head>...
https://api.frankfurter.dev/v1/latest?from=EUR&to=USD -> {"amount":1.0,"base":"EUR","date":"2026-10-30","rates":{"USD":1.1172}}
```

18 prompt curl examples use `curl -s` without `-L`; 23 use `curl -sL`. Any routine that copies
the `curl -s` form against `api.frankfurter.app` gets an HTML body. Fix: name the canonical
host `api.frankfurter.dev/v1/latest` (or mandate `-L`).

## ENV-7 — the "## Source health" compliance check is a literal-string trap

Mandated by 19 of the 20 template prompts ("Every artifact carries a `## Source health`
section"). A literal grep over the outputs repo gives:

```
asia-pre-market   16/16  100%
cross-asset        4/4   100%
us-stocks-in-play 16/16  100%
macro-calendar     5/5   100%
earnings           7/14   50%
daily-briefs       8/19   42%
ntrt               4/12   33%
options-flow       0/9     0%   <-- but the artifact DOES disclose sources
weekly             0/2     0%
```

`options-flow/2026-10-30.md` opens with a `_source=cboe delayed-quote CDN option chains
(8/8 underlyings, HTTP 200) · nasdaq public quote API ...` line and a "## 0. Read this
first — data-quality caveat" section naming every degraded source. The information IS
disclosed; it is simply not under the mandated heading. **The finding is about the CHECK, not
about the agents.** A compliance check keyed on the literal heading produces a false
"0% compliance" for routines that are in fact disclosing more than most. Recommend the
instruction say "disclose per-source health (heading `## Source health`, or an equivalent
`_source=` frontmatter line)" and any audit match either form.

## ENV-8 — the window-check blocks are dead EXCEPT #19's holiday guard

Track-c's C1 ("every window-check block is unreachable code") is correct for the
day-of-week / market-hours branches, but it over-states by covering the holiday guard too.
#19 carries a REAL, reachable guard — the scheduler fires Mon-Fri **including market
holidays**, and only the in-prompt holiday list can catch them:

```bash
# US MARKET HOLIDAYS — the weekend test above is not sufficient. On a market holiday the market
# is closed and there is no "today's earnings" to report. 2026 NYSE closures (non-weekend):
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        SKIP_REASON="US market holiday ($DATE)"
```

I verified the list against the 2026 NYSE calendar: all 10 dates are real weekdays
(01-01 Thu, 01-19 Mon, 02-16 Mon, 04-03 Fri, 05-25 Mon, 06-19 Fri, 07-03 Fri, 09-07 Mon,
11-26 Thu, 12-25 Fri) and no 2026 NYSE holiday is missing.

So the correct fix is NOT "delete the window check and replace with a holiday guard" — it is
"delete only the day-of-week and market-hours branches (dead, since the scheduler owns the
day), and PROMOTE #19's holiday guard to all market-facing routines, because the holiday
guard is the one branch the scheduler genuinely cannot express". The other 19 prompts
currently have **no** holiday guard at all, which is a live gap the C1 wording can obscure.
Flag it as such.

## ENV-9 — deployed-vs-repo drift, independently confirmed

My own measurement against the persisted `cron_read view=list` JSON:

```
deployed prompts containing "exposes 15 tools"        : 18/23
deployed prompts containing the 2026-10-28 Yahoo-429 text: 18/23
deployed prompts containing "133 tools"                 :  1/23   (#17)
deployed prompts containing "probe_mcp.py"              :  0/23
deployed prompts containing "Barchart"                  :  0/23
deployed prompt byte-identical to repo file            :  2/23   (#17, #90)
```

This matches track-b's drift table. **Only #17 has the corrected contract deployed**, and
#17 is the one routine that is also byte-identical to the repo. The repo's 2026-10-31
contract rewrite (133 tools, Yahoo working, market-recap, Barchart, probe_mcp.py) reached
**exactly one** of 23 live routines.

## ENV-10 — skill URL integrity: all 21 skill URLs resolve; sharing is high

Every SKILL SPEC URL in the 20 template prompts resolves to a file that exists in
`cloud-prompts/skills/`. Zero broken. But sharing is heavy:

```
stock-screener-suite/SKILL.md     -> #04, #06, #07, #08, #09, #10   (6 routines)
eod-watchlist-snapshot/SKILL.md   -> #05, #20                       (2 routines)
macro-calendar-week/SKILL.md     -> #13, #14                       (2 routines)
```

So 10 of 21 skill-fetching routines read only 8 distinct skill documents. When one shared
skill is wrong, 6 routines are wrong at once. Worth an explicit note in the report: the
blast radius of a skill edit is much larger than the count of skill directories suggests.

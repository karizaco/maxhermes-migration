#!/usr/bin/env python3
"""
rvol_fetch.py — trailing-N session volume for the WHOLE US market in N calls.

WHY THIS EXISTS
---------------
The 2026-11-02 US-stocks-in-play run spent 245 of the Pipeworx gateway's
50-call/day anonymous pool on RVol denominators alone: one `stocktwits
chart_data` call per ticker, each costing one metered gateway call.

Measured facts (2026-11-03, Pipeworx gateway headers):
  * anonymous tier = 50 tool calls/day PER EGRESS IP, `X-RateLimit-*`
  * the pool is SHARED with every other caller on that IP
  * the Cloud sandbox egress rotates between ~2 IPs, so the fleet gets ~2 counters
  * a free key (`X-API-Key` header or `?apikey=`) raises the tier to 200/day

`polygon-io grouped_daily` returns OHLCV for EVERY US symbol for ONE date in
ONE call. Ten calls give a trailing-10-session volume denominator for the
entire market — including ETFs and names the screener never surfaced.

VERIFIED 2026-11-03: the trailing-10 average computed from `grouped_daily`
reproduces the `stocktwits chart_data` denominator to within 0.000075%
(max absolute relative error across 209 names) — it is the same series, so
RVol values are directly comparable with previously published digests.

USAGE
    python3 rvol_fetch.py --date 2026-11-02 --sessions 10
    python3 rvol_fetch.py --date 2026-11-02 --sessions 10 --out avg10.json

Prints a JSON object: {"<TICKER>": {"avg": float, "n": int}, ...}
`avg` is the mean session share volume over the N sessions ENDING at (and
including) the session before `--date`; `n` is how many sessions were found.

CAPABILITY
  * `RVOL_FETCH_V2` (2026-11-10). The output JSON carries `"capability":
    "RVOL_FETCH_V2"` and a new `"prior_session"` block. A consumer that needs the
    PRIOR session's own daily volume (the open slot's per-symbol volume-basis
    factor) must demand this marker: an older copy of this script has no such
    field, and the symptom is a silent fallback to a second, per-symbol price
    pull that costs ~3 minutes of a 15-minute budget.

    `prior_session` = {"date": "<the most recent session actually fetched>",
    "volumes": {"<TICKER>": <share volume that session>}}. It is the SAME
    series as the `avg10` denominator, so a numerator built on it and the
    denominator are on one basis (measured 2026-11-10: the Yahoo daily bar
    divided by the polygon daily bar has a median of 0.9996 over 1,158 names,
    so mixing the two carries a ~0.04% bias in every published pace).

LIMITS
  * Massive (upstream) allows 5 requests/minute on the shared free key, so the
    fetches are serialized with a delay. 11 sessions ~= 2.5 minutes.
  * The upstream key can be overridden with `--api-key` / PIPEWORX_API_KEY.
"""

CAPABILITY = "RVOL_FETCH_V2"

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

GATEWAY = "https://gateway.pipeworx.io"
POLYGON_MCP = f"{GATEWAY}/polygon-io/mcp"
MASSIVE_RATE_LIMIT_PER_MIN = 5


def rpc(url, payload, api_key=None, timeout=90):
    """One JSON-RPC round trip over the MCP endpoint."""
    cmd = [
        "curl", "-s", "-N", "--max-time", str(timeout), "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
    ]
    if api_key:
        cmd += ["-H", f"X-API-Key: {api_key}"]
    cmd += ["-d", json.dumps(payload)]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=timeout + 20).stdout
    try:
        return json.loads(out)
    except Exception:
        for line in reversed(out.splitlines()):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except Exception:
                    continue
    return {"error": "unparseable", "raw": out[:300]}


def call_tool(tool, args, api_key=None):
    resp = rpc(POLYGON_MCP,
               {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": args}},
               api_key=api_key)
    if "result" not in resp:
        return {"_error": resp}
    chunks = [c.get("text", "") for c in resp["result"].get("content", [])
              if c.get("type") == "text"]
    try:
        return json.loads("\n".join(chunks))
    except Exception:
        return {"_error": "unparseable_tool_text", "raw": "\n".join(chunks)[:300]}


def sessions_before(end_date, n):
    """The n weekday sessions before end_date, oldest first (best effort)."""
    out, d = [], end_date - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:          # Mon-Fri; holidays are simply absent from the feed
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def fetch_session(day, api_key=None, delay=13.0):
    """OHLCV for every US symbol on one date, with upstream rate-limit backoff."""
    attempts = 0
    while attempts < 6:
        res = call_tool("grouped_daily", {"date": day}, api_key=api_key)
        if "results" in res:
            return {r["T"]: r for r in res["results"]}
        attempts += 1
        msg = json.dumps(res)[:200]
        if "429" in msg or "rate limit" in msg.lower():
            time.sleep(delay)
            continue
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="session date, YYYY-MM-DD")
    ap.add_argument("--sessions", type=int, default=10,
                    help="trailing sessions for the denominator (default 10)")
    ap.add_argument("--api-key", default=os.environ.get("PIPEWORX_API_KEY", ""))
    ap.add_argument("--delay", type=float, default=13.0,
                    help="seconds between upstream calls (default 13)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    end = date.fromisoformat(args.date)
    days = sessions_before(end, args.sessions)

    vols = {}
    fetched = []
    for i, day in enumerate(days):
        data = fetch_session(day, api_key=args.api_key, delay=args.delay)
        if data is None:
            print(f"  WARN could not fetch {day}", file=sys.stderr)
            continue
        fetched.append(day)
        for t, r in data.items():
            v = r.get("v")
            if v:
                vols.setdefault(t, {})[day] = v
        print(f"  {day}: {len(data)} symbols", file=sys.stderr)
        if i < len(days) - 1:
            time.sleep(args.delay)

    avg = {}
    for t, byday in vols.items():
        vals = [byday[d] for d in days if d in byday]
        if len(vals) >= args.sessions:
            avg[t] = {"avg": sum(vals) / len(vals), "n": len(vals)}

    # The PRIOR session's own daily volume, on the SAME series as the denominator.
    # The prior session is the most recent session actually fetched; if that day's
    # call failed, fall back to the most recent one that succeeded and REPORT which
    # date it is, so a consumer never silently pairs a factor from one session
    # with a denominator that ends on another.
    prior_day = fetched[-1] if fetched else None
    prior_volumes = {}
    if prior_day:
        for t, byday in vols.items():
            v = byday.get(prior_day)
            if v:
                prior_volumes[t] = v
    payload = {"date": args.date, "sessions": args.sessions,
               "days": days, "fetched_days": fetched,
               "symbols": len(avg), "capability": CAPABILITY,
               "prior_session": {"date": prior_day, "volumes": prior_volumes},
               "avg10": avg}
    text = json.dumps(payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"  wrote {args.out} ({len(avg)} symbols)", file=sys.stderr)
    else:
        print(json.dumps(payload))


if __name__ == "__main__":
    main()

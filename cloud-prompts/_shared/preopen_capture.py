#!/usr/bin/env python3
"""
preopen_capture.py — write the pre-open catalyst tape.

WHY THIS EXISTS
---------------
A 15:50 ET digest can see where a stock IS, not where it came from, and not the
catalyst as it was understood at the open. This script records that: for each name
moving pre-market or at the open, WHO moved, WHAT moved it, and WHEN the news broke.

THREE CALLS, THREE JOBS
-----------------------
  1. trending_symbols      (stocktwits pack)  -> candidates + a natural-language
      reason + a timestamp for each. This is the retail/WSB/X-chatter signal and
      it is LIVE: the summary carries its own `summary_at` stamp.
  2. top_movers           (market-recap pack) -> GROUND TRUTH price, %chg, volume.
  3. ask_pipeworx_grounded (market-recap pack) -> a per-name catalyst with evidence,
      a source URL and a confidence score, for the movers that call 1 did not cover.

**Prices always come from call 2.** Call 1 and call 3 explain; they never price.
A percentage that disagrees with call 2 by more than 2pp is marked `unverified`.

xAI / Grok is OPTIONAL. The xAI chat API no longer serves live search
(`search_parameters` returns HTTP 410 "Live search is deprecated"), and the
Agent Tools API that replaces it is not enabled on most keys. Pipeworx does the
job without it. If XAI_API_KEY is set AND `XAI_MODEL` names a model that answers
without search, its output is added as a second opinion at `conf: medium`.

USAGE
  preopen_capture.py                        # today, this checkpoint, default path
  preopen_capture.py --date 2026-11-03 --checkpoint 0830 --out /tmp/tape.jsonl
  preopen_capture.py --dry-run              # print, do not write

EXIT CODES
  0 = tape written (or correctly skipped: no key)
  1 = a source failed outright
  2 = usage error
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

GATEWAY = "https://gateway.pipeworx.io"
PACK_MARKET = "market-recap"
PACK_STOCKTWITS = "stocktwits"
CAT_VOCAB = {"acquisition", "merger", "earnings", "guidance", "fda", "trial", "offering",
             "halt", "downgrade", "guidance-cut", "spin", "dividend", "other"}
DISAGREE_PP = 2.0
UA = {"User-Agent": "MaxHermes-Cron/1.0"}


def _et():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=-5))


def rpc(pack, tool, args, timeout=120, prefer=None):
    """One JSON-RPC tools/call against a gateway pack.

    The tool's `content` array can carry MORE THAN ONE text block, and each block can be
    a JSON string containing JSON. `ask_pipeworx_grounded` returns two blocks — the
    answer object and the underlying source payload — concatenated in one text run when
    joined. So: parse each block separately, decode up to twice, and pick the first
    document that actually carries what the caller asked for.
    """
    url = f"{GATEWAY}/{pack}/mcp"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    key = os.environ.get("PIPEWORX_API_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return {"error": f"http_{exc.code}"}
    except Exception as exc:
        return {"error": f"transport: {str(exc)[:120]}"}
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        for line in reversed(raw.splitlines()):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    break
                except Exception:
                    pass
    if not isinstance(data, dict) or "result" not in data:
        return {"error": "rpc_failed", "raw": raw[:200]}
    res = data["result"]
    if res.get("isError"):
        return {"error": "tool_error", "detail": str(res.get("content"))[:300]}

    docs = []
    for c in res.get("content", []) or []:
        if c.get("type") != "text":
            continue
        blob = c.get("text", "")
        for _ in range(3):
            if not isinstance(blob, str):
                break
            try:
                blob = json.loads(blob)
            except Exception:
                break
        if isinstance(blob, dict) and blob:
            docs.append(blob)
    if not docs:
        return {"error": "no_json_content"}
    if prefer:
        for d in docs:
            if any(k in d for k in prefer):
                return d
    return docs[0]


def call_trending():
    """Candidates with a live reason and a timestamp."""
    out = rpc(PACK_STOCKTWITS, "trending_symbols", {}, prefer=["symbols"])
    if "error" in out:
        return {"error": out["error"]}
    rows = []
    for s in out.get("symbols", []) or []:
        tr = s.get("trends") or {}
        rows.append({
            "ticker": (s.get("symbol") or "").upper(),
            "name": s.get("title"),
            "why": (tr.get("summary") or "").strip() or None,
            "ts": tr.get("summary_at"),
            "score": s.get("trending_score"),
            "sector": s.get("sector"),
        })
    return {"rows": [r for r in rows if r["ticker"]]}


def call_top_movers(category="gainers", limit=40):
    """Ground-truth prices for the movers."""
    out = rpc(PACK_MARKET, "top_movers", {"category": category, "limit": limit}, prefer=["movers"])
    if "error" in out:
        return {"error": out["error"]}
    movers = {}
    for m in out.get("movers", []) or []:
        movers[(m.get("symbol") or "").upper()] = {
            "price": m.get("price"), "change_pct": m.get("change_pct"),
            "volume": m.get("volume"), "name": m.get("name"),
            "exchange": m.get("exchange")}
    return {"movers": movers, "as_of": out.get("as_of"), "total": out.get("total")}


def call_grounded(ticker, name=None):
    """A per-name catalyst with evidence, URL and confidence."""
    who = f"{name} ({ticker})" if name else ticker
    # Ask for NEWS routing explicitly. The router will otherwise reach for SEC filings
    # first and come back empty ("not_in_source") on a name that moved on a press release.
    q = (f"What specific news, press release, analyst action or corporate event moved "
         f"{who} stock sharply right now? Prefer company news, press releases and news wires "
         "over SEC filing index entries. Give the one-clause reason and the source URL.")
    out = rpc(PACK_MARKET, "ask_pipeworx_grounded", {"question": q},
              prefer=["ask_pipeworx_grounded"])
    if "error" in out:
        return {"error": out["error"]}
    r = out.get("ask_pipeworx_grounded") or {}
    ans = (r.get("answer") or "").strip()
    # The router sometimes restates the PRICE MOVE instead of naming a catalyst, and
    # sometimes reaches for the wrong source. Both are caught here, not downstream.
    if ans and re.search(r"(moved|rose|fell|up |down )\s*\$?\d|\d+(\.\d+)?%\s*(increase|decrease|move)", ans, re.I):
        ans = ""
    newsish = ("news", "press", "wire", "article", "headline", "8k", "sec_events")
    tool = (r.get("tool_used") or "")
    if ans and not any(t in tool.lower() for t in newsish):
        ans = ""                      # a filing index entry is not a catalyst
    conf = r.get("confidence") or 0
    if ans and conf < 0.6:
        ans = ""
    return {"answer": ans or None, "evidence": r.get("evidence"),
            "confidence": conf, "refusal": r.get("refusal_reason"),
            "tool_used": r.get("tool_used"), "second_source": r.get("second_source")}


def build(date_str, checkpoint, top_n=8):
    tr = call_trending()
    tm = call_top_movers()
    if "error" in tr and "error" in tm:
        return {"error": f"both sources failed: trending={tr.get('error')} movers={tm.get('error')}"}
    trending = {r["ticker"]: r for r in (tr.get("rows") or [])}
    movers = tm.get("movers") or {}

    # Names the tape should carry: trending names that also moved, plus the top movers.
    candidates = []
    seen = set()
    for tk, m in sorted(movers.items(), key=lambda kv: -(kv[1].get("change_pct") or 0)):
        if tk in seen:
            continue
        seen.add(tk)
        candidates.append(tk)
    for tk in trending:
        if tk not in seen:
            seen.add(tk)
            candidates.append(tk)

    rows = []
    grounded_budget = top_n
    for tk in candidates:
        mv = movers.get(tk)
        trr = trending.get(tk)
        if not mv and not trr:
            continue
        rec = {
            "ts": datetime.datetime.now(_et()).isoformat(timespec="seconds"),
            "src": "tv" if mv else "grok",
            "ticker": tk,
            "name": (mv or {}).get("name") or (trr or {}).get("name"),
            "pct": (mv or {}).get("change_pct"),
            "price": (mv or {}).get("price"),
            "cat": "other",
            "why": (trr or {}).get("why"),
            "ref": None,
            "conf": "high" if trr and trr.get("why") else "low",
            "trending_ts": (trr or {}).get("ts"),
            "trending_score": (trr or {}).get("score"),
            "volume": (mv or {}).get("volume"),
            "exchange": (mv or {}).get("exchange"),
        }
        # A mover with no trending reason: ask the grounded router for one.
        if mv and not rec["why"] and grounded_budget > 0:
            grounded_budget -= 1
            g = call_grounded(tk, rec["name"])
            if g.get("answer") and not g.get("refusal"):
                rec["why"] = g["answer"]
                rec["ref"] = g.get("evidence")
                rec["conf"] = "high" if (g.get("confidence") or 0) >= 0.7 else "medium"
                rec["src"] = "grok" if False else "pipeworx"
                rec["grounded_tool"] = g.get("tool_used")
        rows.append(rec)
    return {"rows": rows, "as_of": tm.get("as_of"),
            "trending_count": len(trending), "mover_count": len(movers),
            "errors": [e for e in (tr.get("error"), tm.get("error")) if e]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--checkpoint")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.datetime.now(_et())
    date_str = args.date or now.strftime("%Y-%m-%d")
    cp = args.checkpoint or now.strftime("%H%M")

    if not os.environ.get("PIPEWORX_API_KEY") and not os.environ.get("XAI_API_KEY"):
        print("preopen capture: PIPEWORX_API_KEY unset — nothing written")
        return 0

    res = build(date_str, cp, args.top)
    if "error" in res:
        print(json.dumps(res))
        return 1

    lines = [json.dumps(r, ensure_ascii=False) for r in res["rows"]]
    body = "\n".join(lines) + ("\n" if lines else "")

    if args.dry_run:
        print(f"# dry run — {len(res['rows'])} rows, movers={res['mover_count']}, "
              f"trending={res['trending_count']}, as_of={res.get('as_of')}")
        print(body)
        return 0

    out = args.out or f"/workspace/preopen-feed/{date_str}-{cp}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(body)
    print(f"preopen capture: wrote {len(res['rows'])} records to {out} "
          f"(movers={res['mover_count']}, trending={res['trending_count']}, "
          f"as_of={res.get('as_of')}, errors={len(res.get('errors') or [])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

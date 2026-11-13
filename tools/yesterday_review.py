#!/usr/bin/env python3
"""
yesterday_review.py — build the cron #26 brief's `## Yesterday's brief — what happened`
table from REAL data.

WHY
---
The 2026-11-03 pre-market brief was 44 KB of excellent analysis with no follow-up: the
last section was an open research queue, and nothing anywhere recorded what happened to
yesterday's calls. A brief that cannot be scored is a brief nobody can trust — and the
routine never learns.

This is the loop. It reads the most recent prior DAILY brief (cron #26's own artifact,
not the #26b refresh), takes the setups that brief published — the rows its CSV marks
`setup_published = yes`, with the `key_level` and `invalidation` those rows carry —
and measures what happened to them:

  * the session bars come from the MCP bridge (`market-recap price_history`: close,
    previous_close, daily_return_pct) and the Yahoo chart API (the intraday high/low,
    which is what a "traded through the level" test needs);
  * the invalidation the brief published is the TEST — it is not a re-judgement. If the
    level was traded through, the thesis broke; if it was not, the thesis held or merely
    failed to work;
  * the previous evening's post-market brief (cron #23) is the cross-check on the
    closes, and a disagreement is reported rather than smoothed over.

It is honest about gaps: a day with no brief (the 2026-11-05 fire published nothing on
a quota wall) is skipped and named, and a name with no price is `UNJUDGED` with a
reason. It never invents a level.

USAGE
    python3 yesterday_review.py --date 2026-11-06
    python3 yesterday_review.py --date 2026-11-06 --json /workspace/_yesterday_review.json
    python3 yesterday_review.py --date 2026-11-06 --offline     # local files only, no network

OUTPUT (stdout)
    a legend line and a markdown table:

      | Name | Setup (yesterday) | Yesterday's close | Today's move | Thesis held? |

EXIT CODES
    0 = a table was produced (possibly with `UNJUDGED` rows)
    1 = no prior brief / no setups / no prices — the caller must publish the section
        with the reason line this script prints
    2 = bad arguments
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

OUTPUTS_REPO = "karizaco/minimax-cloud-outputs"
BRANCH = "main"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")

MAX_LOOKBACK_DAYS = 8
VERDICTS = ("WORKED", "HELD", "SURVIVED", "BROKE", "PARTIAL", "UNJUDGED")


# ----------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------
def gh_contents(path: str) -> tuple[str | None, str]:
    """(content, error) for a file in the outputs repo, branch main.

    The CONTENTS API is authoritative and is NOT CDN-cached — raw.githubusercontent and
    jsDelivr cache `main` independently, and one of them served a stale blob for
    >17 minutes after a push on 2026-11-04.
    """
    url = (f"https://api.github.com/repos/{OUTPUTS_REPO}/contents/{path}?ref={BRANCH}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        **({"Authorization": f"Bearer {GH_TOKEN}"} if GH_TOKEN else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as fh:
            return fh.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def yahoo_bars(symbol: str) -> dict:
    """{date: {o,h,l,c}} for the symbol's daily bars (Yahoo chart API, no crumb)."""
    out: dict[str, dict] = {}
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=3mo&interval=1d")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as fh:
            data = json.load(fh)
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            return out
        r = res[0]
        ts = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        for i, t in enumerate(ts):
            d = datetime.utcfromtimestamp(t).date().isoformat()
            row = {}
            for k, src in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
                v = (q.get(src) or [None] * len(ts))[i]
                if v is not None:
                    row[k] = float(v)
            if row:
                out[d] = row
    except Exception:
        return out
    return out


def bridge_price_history(symbols: list[str], start: str, end: str,
                         bridge: str | None) -> dict:
    """{symbol: [{date, close, previous_close, daily_return_pct}, ...]}"""
    if not symbols or not bridge:
        return {}
    payload = {"symbols": symbols, "start_date": start, "end_date": end}
    tmp = "/workspace/_yr_price_history.json"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        proc = subprocess.run([sys.executable, bridge, "market-recap",
                               "price_history", tmp],
                              capture_output=True, text=True, timeout=180)
    except Exception:
        return {}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out = {}
    for res in (data.get("results") or []):
        sym = res.get("symbol")
        if sym and res.get("found"):
            out[sym] = res.get("days") or []
    return out


def find_bridge(explicit: str | None) -> str | None:
    cands = [explicit, os.environ.get("MCP_BRIDGE_PATH"),
              "/workspace/mcp_bridge.py",
              os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "cloud-prompts", "_shared", "mcp_bridge.py")]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


# ----------------------------------------------------------------------------------
# the reviewed brief
# ----------------------------------------------------------------------------------
def parse_cluster_tables(md: str) -> list[tuple[str, list[str]]]:
    """[(cluster headline, [tickers])] from the brief's `## 2. Theme clusters`.

    The section ends at the next heading of the SAME OR A HIGHER level — the `###`
    cluster headings live INSIDE it, and stopping at the first of them would hide
    every table.
    """
    lines = md.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,4})\s+(.*?)\s*$", ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    out: list[tuple[str, list[str]]] = []
    for n, (i, lvl, title) in enumerate(heads):
        if not norm(title).startswith("2themeclusters"):
            continue
        end = len(lines)
        for (j, lvl2, _t) in heads[n + 1:]:
            if lvl2 <= lvl:
                end = j
                break
        body = lines[i + 1:end]
        cluster = ""
        j = 0
        while j < len(body):
            m = re.match(r"^#{3,4}\s+(.*?)\s*$", body[j])
            if m:
                cluster = m.group(1).strip()
                j += 1
                continue
            if body[j].strip().startswith("|") and j + 1 < len(body) and \
                    re.match(r"^\|[\s:|-]+\|$", body[j + 1].strip()):
                header = [c.strip() for c in body[j].strip().strip("|").split("|")]
                ti = 0
                for k, h in enumerate(header):
                    if norm(h) in ("ticker", "symbol", "name"):
                        ti = k
                        break
                k = j + 2
                tickers = []
                while k < len(body) and body[k].strip().startswith("|"):
                    cells = [c.strip() for c in body[k].strip().strip("|").split("|")]
                    if ti < len(cells):
                        t = cells[ti].strip().strip("*")
                        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", t):
                            tickers.append(t)
                    k += 1
                if tickers:
                    out.append((cluster or "theme cluster", tickers))
                j = k
                continue
            j += 1
    return out


def postmarket_closes(md: str) -> dict:
    """{ticker: close} from cron #23's post-market brief.

    HEADER-AWARE on purpose: the post-market brief's tables carry several numeric
    columns (close, % change, volume, market cap) and a positional parse picks up the
    first one — which on 2026-11-05 was a % change, so WULF came back as -0.37 against
    a close of 10.08 and the cross-check cried "disagreement" that was never there.
    Only a column whose header says close/price/last is a close.
    """
    out: dict[str, float] = {}
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        if (lines[i].strip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())):
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            ci = None
            for k, h in enumerate(header):
                n = norm(h)
                if ("close" in n or "price" in n or n == "last") and "chg" not in n \
                        and "change" not in n and "%" not in h:
                    ci = k
                    break
            if ci is not None:
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    t = cells[0].strip().strip("*") if cells else ""
                    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", t) and ci < len(cells):
                        try:
                            out[t] = float(cells[ci].replace("$", "").replace(",", "")
                                           .replace("%", "").strip("*"))
                        except ValueError:
                            pass
                    j += 1
                i = j
                continue
        i += 1
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def pick_reviewed_brief(today: date) -> tuple[str | None, str]:
    """(iso date, note) of the most recent prior DAILY brief."""
    note_bits = []
    skipped: list[str] = []
    d = today - timedelta(days=1)
    checked = 0
    while checked < MAX_LOOKBACK_DAYS:
        checked += 1
        iso = d.isoformat()
        md, err = gh_contents(f"daily-briefs/{iso}-pre-market.md")
        if md:
            if skipped:
                note_bits.append(
                    f"no daily brief on {', '.join(skipped)} — this reviews the {iso} brief")
            return iso, "; ".join(note_bits)
        if err and "404" in err:
            skipped.append(iso)
        d -= timedelta(days=1)
    return None, ("no prior daily brief found in the last "
                  f"{MAX_LOOKBACK_DAYS} sessions ({', '.join(skipped) or 'none'})")


# ----------------------------------------------------------------------------------
# the setups
# ----------------------------------------------------------------------------------
def pick_setups(brief_date: str, md: str, csv_text: str | None):
    """[{ticker, setup, key_level, invalidation, gap_pct, premarket_last, prior_close}]"""
    setups = []
    csv_rows = {}
    if csv_text:
        try:
            for r in csv.DictReader(io.StringIO(csv_text)):
                t = (r.get("ticker") or "").strip()
                if t:
                    csv_rows[t] = r
        except Exception:
            csv_rows = {}

    clusters = parse_cluster_tables(md)
    cluster_of = {}
    for headline, tickers in clusters:
        for t in tickers:
            cluster_of.setdefault(t, headline)

    if csv_rows:
        published = [t for t, r in csv_rows.items()
                     if (r.get("setup_published") or "").strip().lower() == "yes"]
        if published:
            names = published
        else:
            names = [t for t in cluster_of if t in csv_rows] or list(cluster_of)
    else:
        names = list(cluster_of)

    for t in names:
        r = csv_rows.get(t, {})
        key_level = (r.get("key_level") or "").strip()
        invalidation = (r.get("invalidation") or "").strip()
        prior_close = r.get("prior_close") or r.get("prev_close") or ""
        premarket_last = r.get("premarket_last") or r.get("premarket_close") or ""
        gap_pct = r.get("gap_pct") or r.get("premarket_change_pct") or ""
        premarket_high = r.get("premarket_high") or ""
        premarket_low = r.get("premarket_low") or ""
        derived = ""
        if not invalidation:
            # A brief published before the v2 contract carries no invalidation column.
            # Its OWN published prices still define the level (the C2 ladder: the
            # prior close is the gap-fill), so the loop can still be closed — the row
            # says the level was derived, it does not pretend the brief published it.
            try:
                pc = float(prior_close)
            except (TypeError, ValueError):
                pc = None
            if pc is not None:
                key_level = key_level or f"{pc:g}"
                try:
                    g = float(gap_pct)
                except (TypeError, ValueError):
                    g = None
                if g is None:
                    invalidation = f"a trade through {pc:g} (derived: the reviewed brief " \
                                  f"predates the invalidation column)"
                elif g >= 0:
                    invalidation = f"a trade back to or below {pc:g} — the gap filled " \
                                  f"(derived: the reviewed brief predates the " \
                                  f"invalidation column)"
                else:
                    invalidation = f"a trade back above {pc:g} — the breakdown failed " \
                                  f"(derived: the reviewed brief predates the " \
                                  f"invalidation column)"
                derived = "derived"
        setups.append({
            "ticker": t,
            "setup": cluster_of.get(t) or (r.get("setup_theme") or "") or
                     f"setup published in the {brief_date} brief",
            "key_level": key_level,
            "invalidation": invalidation,
            "gap_pct": gap_pct,
            "premarket_last": premarket_last,
            "prior_close": prior_close,
            "premarket_high": premarket_high,
            "premarket_low": premarket_low,
            "level_derived": derived,
        })
    return setups


def level_and_direction(text: str):
    """(level, breach_direction) parsed out of an invalidation cell.

    A break to the DOWNSIDE through the level means the level was traded BELOW; a break
    to the UPSIDE means it was traded ABOVE. Returns (None, None) when the cell carries
    no level — the caller then reports UNJUDGED rather than guessing.
    """
    if not text:
        return None, None
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return None, None
    level = float(nums[-1])
    low = text.lower()
    up_words = ("above", "over ", "back above", "higher than", "through to the upside")
    down_words = ("below", "under", "back to", "lower than", "through to the downside",
                  "back below")
    has_up = any(w in low for w in up_words)
    has_down = any(w in low for w in down_words)
    if has_down and not has_up:
        return level, "down"
    if has_up and not has_down:
        return level, "up"
    if has_up and has_down:
        # ambiguous wording: the level's side is decided by its relation to the
        # pre-market price, which the caller knows.
        return level, "auto"
    return level, "auto"


# ----------------------------------------------------------------------------------
# the outcome
# ----------------------------------------------------------------------------------
def sessions_between(bars: dict, first: str, last: str):
    return [d for d in sorted(bars) if first <= d <= last]


def evaluate(setups, brief_date, bars_by_sym, closes_by_sym):
    """Attach the outcome to each setup."""
    last_session = ""
    for sym_bars in bars_by_sym.values():
        if sym_bars:
            last_session = max(last_session, max(sym_bars))
    if not last_session:
        for days in closes_by_sym.values():
            for d in days:
                last_session = max(last_session, d.get("date", ""))

    out = []
    for s in setups:
        sym = s["ticker"]
        bars = bars_by_sym.get(sym, {})
        days = closes_by_sym.get(sym, [])
        last_close = last_move = None
        for d in days:
            if d.get("date") == last_session:
                last_close = d.get("close")
                last_move = d.get("daily_return_pct")
        if last_close is None and bars:
            last_close = bars.get(last_session, {}).get("c")
        if last_move is None and bars:
            # the bridge did not carry this name (or this session): derive the move
            # from the chart's own closes so the row is never blank.
            ds = sorted(bars)
            if last_session in ds:
                idx = ds.index(last_session)
                if idx > 0:
                    pc = bars[ds[idx - 1]].get("c")
                    lc = bars[last_session].get("c")
                    if pc and lc:
                        last_move = (lc / pc - 1.0) * 100.0
                if last_close is None:
                    last_close = bars[last_session].get("c")

        level, direction = level_and_direction(s.get("invalidation") or "")
        side_assumed = False
        if direction == "auto" and level is not None:
            # The cell carries a LEVEL but no side (a brief published before the side was
            # required). The side is then ASSUMED from the gap's sign, and the row says so.
            # The assumption is not a guess dressed up as knowledge: post-fix briefs publish
            # the side, so this path only runs for legacy briefs — and the legacy briefs
            # were built with the convention the assumption encodes.
            try:
                gap = float(s.get("gap_pct"))
            except (TypeError, ValueError):
                gap = None
            direction = "down" if gap is None or gap >= 0 else "up"
            side_assumed = True

        covered = sessions_between(bars, brief_date, last_session) if bars else []
        if not covered and days:
            covered = [d["date"] for d in days if brief_date <= d["date"] <= last_session]

        broke_on = ""
        for d in covered:
            b = bars.get(d, {})
            if not b:
                continue
            if direction == "down" and b.get("l") is not None and b["l"] <= level:
                broke_on = d
                break
            if direction == "up" and b.get("h") is not None and b["h"] >= level:
                broke_on = d
                break

        # The trigger direction tells us which way the setup was betting: a DOWNSIDE
        # invalidation means the setup was long (it dies if price falls), an UPSIDE
        # invalidation means it was short (it dies if price rises).
        thesis_long = direction != "up"

        # THE TRIGGER is the level the setup had to REACH before it was a live trade.
        # Without it "the invalidation held" is a very low bar: for a gap-up long it
        # only means the gap did not fully fill, which a +2% drift clears. The reviewed
        # brief publishes the trigger in its own CSV:
        #   a gap-up long   -> a break of the pre-market high it published;
        #   a gap-down long -> a reclaim of the prior close (the C2 key level);
        #   a short         -> a break of the pre-market low it published.
        trigger = None
        trigger_desc = ""
        try:
            _gap = float(s.get("gap_pct"))
        except (TypeError, ValueError):
            _gap = None
        if thesis_long:
            if _gap is not None and _gap < 0:
                _cand = s.get("key_level") or s.get("prior_close")
                trigger_desc = "prior-close reclaim"
            else:
                _cand = s.get("premarket_high")
                trigger_desc = "pre-market-high break"
        else:
            _cand = s.get("premarket_low")
            trigger_desc = "pre-market-low break"
        try:
            trigger = float(_cand) if _cand not in (None, "") else None
        except (TypeError, ValueError):
            trigger = None

        triggered_on = ""
        if trigger is not None:
            for d in covered:
                b = bars.get(d, {})
                if not b:
                    continue
                if thesis_long and b.get("h") is not None and b["h"] >= trigger:
                    triggered_on = d
                    break
                if not thesis_long and b.get("l") is not None and b["l"] <= trigger:
                    triggered_on = d
                    break

        verdict = ""
        reason = ""
        if level is None:
            verdict = "UNJUDGED"
            reason = "no invalidation level was published"
        elif not covered:
            verdict = "UNJUDGED"
            reason = "no session bar for this name since the brief"
        elif broke_on:
            verdict = "BROKE"
            reason = f"the {level:g} invalidation was traded through on {broke_on}"
        else:
            move = last_move
            if move is None:
                verdict = "UNJUDGED"
                reason = "no close for the last completed session"
            elif (move >= 0) if thesis_long else (move <= 0):
                if trigger is not None and triggered_on:
                    verdict = "WORKED"
                    reason = (f"the {level:g} invalidation held, the {trigger:g} "
                              f"{trigger_desc} was reached on {triggered_on}, and the "
                              f"session moved with the setup")
                elif trigger is not None:
                    verdict = "SURVIVED"
                    reason = (f"the {level:g} invalidation held but the {trigger:g} "
                              f"{trigger_desc} was never reached - the setup never "
                              f"activated")
                else:
                    verdict = "HELD"
                    reason = (f"the {level:g} invalidation held and the session moved with "
                              f"the setup")
            else:
                verdict = "PARTIAL"
                reason = (f"the {level:g} invalidation held but the session moved against "
                          f"the setup")

        out.append({**s, "last_session": last_session, "last_close": last_close,
                    "last_move": last_move, "verdict": verdict, "reason": reason,
                    "covered": covered, "level": level})
        if side_assumed:
            out[-1]["reason"] += (" — the reviewed brief published the level without its "
                                  "side, so the side was assumed from the gap's sign")
        if s.get("level_derived"):
            out[-1]["reason"] += (" — level derived from the reviewed brief's own "
                                  "published prior close (that brief predates the "
                                  "invalidation column)")
    return out, last_session


# ----------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="the brief's date (YYYY-MM-DD)")
    ap.add_argument("--json", default=None, help="write the structured result here")
    ap.add_argument("--bridge", default=None, help="path to mcp_bridge.py")
    ap.add_argument("--offline", action="store_true",
                    help="do not use the network for the price pulls")
    args = ap.parse_args()

    try:
        today = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print("bad --date")
        return 2

    brief_date, brief_note = pick_reviewed_brief(today)
    if not brief_date:
        print(f"NO PRIOR BRIEF: {brief_note}")
        return 1

    md, err = gh_contents(f"daily-briefs/{brief_date}-pre-market.md")
    if md is None:
        print(f"NO PRIOR BRIEF: {brief_date} could not be fetched ({err})")
        return 1
    csv_text, csv_err = gh_contents(f"daily-briefs/{brief_date}-pre-market.csv")
    setups = pick_setups(brief_date, md, csv_text)
    if not setups:
        print(f"NO SETUPS: the {brief_date} brief carries no published setups "
              f"(CSV {'fetched' if csv_text else 'unavailable: ' + str(csv_err)})")
        return 1

    symbols = [s["ticker"] for s in setups]
    start = (datetime.strptime(brief_date, "%Y-%m-%d").date() - timedelta(days=10)).isoformat()
    end = today.isoformat()

    bridge = find_bridge(args.bridge)
    closes_by_sym = {} if args.offline else bridge_price_history(symbols, start, end, bridge)

    bars_by_sym = {}
    if not args.offline:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for sym, bars in zip(symbols, pool.map(yahoo_bars, symbols)):
                if bars:
                    bars_by_sym[sym] = bars

    # the closes the bridge missed come from the chart (and vice versa)
    for sym in symbols:
        if sym not in bars_by_sym and sym in closes_by_sym:
            bars_by_sym[sym] = {}
        for d in closes_by_sym.get(sym, []):
            if d.get("date") not in bars_by_sym.setdefault(sym, {}):
                c = d.get("close")
                if c is not None:
                    bars_by_sym[sym][d["date"]] = {"c": float(c)}

    # DROP THE IN-PROGRESS SESSION. The review runs pre-market on day D, so the last
    # COMPLETED regular session is the last one before D. A feed that has already
    # published a bar for D (a partial, still-trading session) must not be treated as a
    # settled close — it was the cause of a KeyError here, and a settled close it is not.
    for sym, bars in list(bars_by_sym.items()):
        bars_by_sym[sym] = {d: b for d, b in bars.items() if d < today.isoformat()}
    for sym, days in list(closes_by_sym.items()):
        closes_by_sym[sym] = [d for d in days if d.get("date", "") < today.isoformat()]

    rows, last_session = evaluate(setups, brief_date, bars_by_sym, closes_by_sym)
    if not last_session:
        print(f"NO PRICES: no session bar was returned for {len(symbols)} name(s)")
        return 1

    # cross-check the closes against the previous evening's post-market brief (cron #23)
    crosscheck = ""
    pm_md, _ = gh_contents(f"daily-briefs/{last_session}-post-market.md")
    if pm_md:
        pm_closes = postmarket_closes(pm_md)
        clashes = []
        for r in rows:
            pc = pm_closes.get(r["ticker"])
            if pc and r["last_close"] and abs(pc - r["last_close"]) / max(abs(pc), 1e-9) > 0.005:
                clashes.append(f"{r['ticker']}: post-market brief {pc:g} vs {r['last_close']:g}")
        crosscheck = ("; ".join(clashes)) if clashes else \
            (f"closes agree with the {last_session} post-market brief"
             if any(r["ticker"] in pm_closes for r in rows) else
             f"the {last_session} post-market brief names none of these names")

    derived_rows = [r for r in rows if r.get("level_derived")]
    legend = (f"Reviewed the **{brief_date}** pre-market brief"
              + (f" — {brief_note}" if brief_note else "")
              + f". \"Yesterday's close\" is the close of the last completed regular session "
                f"(**{last_session}**); \"Today's move\" is that session's % change vs its own "
                f"prior close. \"Thesis held?\" is tested against the invalidation level the "
                f"{brief_date} brief published, across every session from {brief_date} to "
                f"{last_session}: **WORKED** = the invalidation held, the setup's trigger "
                f"was reached and the session moved with it, **HELD** = the invalidation held "
                f"and the session moved with the setup but the trigger could not be resolved, "
                f"**SURVIVED** = the invalidation held but the trigger was never reached, so "
                f"the setup never activated, **BROKE** = the level was traded through, "
                f"**PARTIAL** = the level held but the session moved against it, "
                f"**UNJUDGED** = no level or no price."
              + (f" {len(derived_rows)} of these names are from a brief published before the "
                 f"invalidation column existed, so their level is derived from that brief's own "
                 f"published prior close (the gap-fill level) — the row says so."
                 if derived_rows else "")
              + f" Price cross-check: {crosscheck}.")

    print()
    print("| Name | Setup (yesterday) | Yesterday's close | Today's move | Thesis held? |")
    print("|---|---|---|---|---|")
    for r in rows:
        close = f"{r['last_close']:,.2f}" if r["last_close"] is not None else "n/a"
        move = f"{r['last_move']:+.2f}%" if r["last_move"] is not None else "n/a"
        setup = re.sub(r"\s+", " ", r["setup"]).strip()
        verdict = r["verdict"]
        if r["reason"]:
            verdict = f"{verdict} ({r['reason']})"
        print(f"| {r['ticker']} | {setup} | {close} | {move} | {verdict} |")
    print()
    print(legend)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"reviewed_brief": brief_date, "note": brief_note,
                       "last_session": last_session, "legend": legend,
                       "rows": rows}, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())

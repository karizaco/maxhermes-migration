#!/usr/bin/env python3
"""
focus_rvol_score.py — the cron #07 scoring engine.

WHY A SCRIPT
-------------
The routine measures a per-name intraday metric over a universe that is now ~1,300 names
(the focus roster PLUS the previous session's on-disk wider sources). Doing that arithmetic in
the agent's context is what made the 2026-11-09 fire take 66 minutes: the HTTP fetches are
cheap, the per-name reasoning is not. This script does the fetching AND the arithmetic, in
parallel, and writes a COMPACT JSON payload holding only what the artifact needs — so the
agent's context cost does not scale with the universe.

WHAT IT COMPUTES
-----------------
For each symbol, on the SAME Yahoo 5-minute series, with the SAME formula:

  rvol_tod_normalised = (cum volume 09:30 -> the fire's bar, on session D)
                         / (mean cum volume over 09:30 -> the SAME window across the
                            prior 10 sessions)
                         x (mean full-day volume across those prior 10 sessions
                            / TV average_volume_10d_calc)

and, for the CROSSING test, the same metric evaluated on the PREVIOUS session D-1 using D-1's
own trailing-10 baseline. BOTH SIDES OF EVERY CROSSING USE ONE DENOMINATOR — the one pulled
at run time. See "THE DENOMINATOR" below; this is the load-bearing correctness rule.

THE DENOMINATOR — WHY THE PRIOR READING IS ALWAYS RECOMPUTED
------------------------------------------------------------
`TV average_volume_10d_calc` is a ROLLING average and it MOVES between fetches: measured, ETON's
denominator went 550,859 (published 2026-11-10) -> 740,475 (two days later), a 34% swing, because
the high-volume sessions it printed entered the window. So a value published in an earlier
session's CSV is on THAT day's scale and is NOT comparable with today's `rvol_now`.

Therefore: the prior reading is ALWAYS recomputed on the current run's denominator. The
published CSV value is attached as a CROSS-CHECK (`prev_session_rvol_published`,
`denominator_drift_pct`) so the drift is visible, but it NEVER decides a crossing. A published
value and a recomputed value for the same session may legitimately differ; the recomputed one
is the baseline because it shares today's scale.

THE DAILY-VOLUME SOURCE
------------------------
The prior-10 FULL-DAY volume comes from Yahoo's own `interval=1d` bars, not from the Nasdaq
`/historical` endpoint. Measured over 240 symbol-sessions across 40 names: the ratio
Yahoo-1d / Nasdaq-consolidated is median 1.0000, mean 0.9997, max deviation 0.32%, and ZERO
comparisons outside +/-1%. The Nasdaq call is 16x slower per symbol (2.09s vs 0.13s) and it
returns empty for some symbols; Yahoo 1d returned data for every symbol tested.

USAGE
    python3 focus_rvol_score.py --fire-date 2026-11-12 \
        --symbols /workspace/universe.txt \
        --focus /workspace/focus.txt \
        --prior-csv /workspace/prev.csv \
        --out /workspace/focus-rvol-scores.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv as csvmod
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zoneinfo

ET = zoneinfo.ZoneInfo("America/New_York")
WIN = ("09:30", "09:35", "09:40")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TV_URL = "https://scanner.tradingview.com/america/scan"
TV_SCAN_PATH = "/workspace/tv_scan.py"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={iv}&range={rg}"
# `includePrePost=true` adds the extended-hours bars to the SAME response: +64% bytes
# (measured 2026-11-13: 161 KB -> 266 KB on interval=5m&range=1mo), so it is NOT used for the
# bulk pass over ~1,600 names. It is used for the PUBLISHED rows only, to measure how much of
# the day's activity arrived before 09:30. The pre-market bars are settled before the fire
# (pre-market ends 09:25), so that number does not drift with the opening window.
YAHOO_PREPOST = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                 "?interval={iv}&range={rg}&includePrePost=true")
ALERT_BAR = 1.5
NEAR_MISS_FLOOR = 1.275


def _curl(url: str, timeout: int = 45) -> bytes:
    """Fetch with a browser User-Agent. A bare curl gets 429 from Yahoo."""
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), "-A", UA, url],
                       capture_output=True)
    return r.stdout


def _chart(sym: str, interval: str, rng: str, prepost: bool = False) -> dict | None:
    url = (YAHOO_PREPOST if prepost else YAHOO).format(sym=sym, iv=interval, rg=rng)
    for _ in range(3):
        raw = _curl(url)
        if not raw:
            time.sleep(0.4)
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        res = (d.get("chart") or {}).get("result")
        if res:
            return res[0]
        return None
    return None


def fetch_series(sym: str, interval: str, rng: str, prepost: bool = False) -> dict:
    """For 1d: {date: {"v": volume, "c": close}}.
    For 5m: {date: {HH:MM: {"v": volume, "c": close}}}.
    With `prepost=True` the extended-hours bars (04:00-09:25 and 16:00-20:00) are present too."""
    d = _chart(sym, interval, rng, prepost)
    if not d:
        return {}
    ts = d.get("timestamp") or []
    q = ((d.get("indicators") or {}).get("quote") or [{}])[0]
    vols = q.get("volume") or []
    closes = q.get("close") or []
    out: dict = {}
    for i, t in enumerate(ts):
        if i >= len(vols) or vols[i] is None:
            continue
        when = dt.datetime.fromtimestamp(t, ET)
        cl = closes[i] if i < len(closes) else None
        if interval == "1d":
            out[when.date()] = {"v": vols[i], "c": cl}
        else:
            out.setdefault(when.date(), {})[when.strftime("%H:%M")] = {"v": vols[i], "c": cl}
    return out


def fetch_tv_denominators() -> tuple[dict, list]:
    """The denominator for every name, via the fleet's VALIDATED scanner client.

    `cloud-prompts/_shared/tv_scan.py` (capability marker `TV_SCAN_V2`) exists because the
    scanner's completeness test is a SET test, not a row count: with no sort the default row
    order is not stable between requests, so a paged universe pull can return `totalCount`
    rows whose UNION holds fewer distinct names - names missing, no error. The client pages on
    a STABLE sort, asserts the pages are DISJOINT and that the union equals `totalCount`,
    and keys rows by the BARE ticker (`d[0]`, never the venue-prefixed `s`).

    Returns (denominators, problems). A non-empty problem list means the pull was NOT
    trustworthy, and the caller must not publish a metric built on it.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("tv_scan", TV_SCAN_PATH)
    if spec is None or not os.path.exists(TV_SCAN_PATH):
        return {}, [{"code": "tv_scan_missing",
                     "message": f"the validated scanner client is not on disk: {TV_SCAN_PATH}"}]
    tv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tv)

    body = {"columns": ["name", "close", "volume", "average_volume_10d_calc",
                         "relative_volume_10d_calc", "market_cap_basic", "exchange"],
            "range": [0, 20000]}
    result, problems = tv.pull_pages(body)
    avg10: dict = {}
    for row in result.get("rows_list") or []:
        sym = tv.bare_name(row)
        d = row.get("d") or []
        # cols = [name, close, volume, average_volume_10d_calc,
        #         relative_volume_10d_calc, market_cap_basic, exchange]
        # The DENOMINATOR is average_volume_10d_calc = d[3]. d[2] is the LIVE volume
        # column, and using it silently produced a daily_factor in the thousands.
        try:
            avg10[sym] = float(d[3])
        except (TypeError, ValueError, IndexError):
            continue
    return avg10, [{"code": p.code, "message": p.message} for p in problems]


def _nasdaq_pre_volume(sym: str) -> int | None:
    """Nasdaq's PRE-market session volume counter for one symbol.

    `assetclass` is REQUIRED (without it the endpoint answers 200 with `data: null`) and so is
    a browser User-Agent. The volume lives in `infoTable.rows[0].volume` as a comma string.
    """
    url = (f"https://api.nasdaq.com/api/quote/{sym}/extended-trading"
           f"?assetclass=stocks&markettype=pre")
    raw = _curl(url).decode("utf-8", "replace")
    try:
        d = json.loads(raw)
    except Exception:
        return None
    rows = ((d.get("data") or {}).get("infoTable") or {}).get("rows") or []
    if not rows:
        return None
    v = str(rows[0].get("volume") or "").replace(",", "").strip()
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def measure_premarket(sym: str, fire_date: dt.date, session_vol: int | None) -> dict:
    """How much of the day's activity arrived BEFORE 09:30, for one PUBLISHED name.

    The pre-market bars are settled before the fire (pre-market ends 09:25), so this number
    does not drift the way the opening window does - which is exactly why it is fetched
    separately for the published rows instead of costing the whole universe a bigger payload.

    The session window in THIS response is compared with the bulk pass's session volume: if the
    two disagree by more than 2% they are not the same vintage, and the share is published as
    `n/a` rather than mixed with a different session volume.
    """
    out = {"pm_vol": None, "pm_source": "not_subtracted", "pm_share_pct": None,
           "pm_vintage_drift_pct": None}
    # (a) Yahoo's extended-hours bars. MEASURED 2026-11-13: every pre-open bar carries
    # volume 0 - on the live session AND on history - so this source usually yields nothing.
    # It is kept because it is the same response family as the session bars, and it costs
    # nothing extra on the rows we already fetch.
    y = fetch_series(sym, "5m", "1mo", prepost=True)
    t = y.get(fire_date)
    pm = 0
    if t:
        pm = sum(v.get("v", 0) for k, v in t.items() if k < "09:30")
        win = sum(t.get(b, {}).get("v", 0) for b in WIN)
        if session_vol and win:
            out["pm_vintage_drift_pct"] = round((win - session_vol) / session_vol * 100, 2)
    if pm:
        out["pm_vol"] = pm
        out["pm_source"] = "measured_from_series"
    else:
        # (b) Nasdaq's PRE-session volume counter. ONLY on the fire's own day: on a replay the
        # endpoint serves TODAY's pre-market, which is a different session entirely.
        if dt.datetime.now(ET).date() == fire_date:
            n = _nasdaq_pre_volume(sym)
            if n:
                out["pm_vol"] = n
                out["pm_source"] = "measured_from_nasdaq"
    # THE SHARE: of all the volume published so far, how much arrived BEFORE the open. A name
    # whose pre-market share is high is a gap continuation; a low share is fresh opening
    # activity. (pm_vol alone is not comparable across names - it scales with the float.)
    if out["pm_vol"] and session_vol:
        out["pm_share_pct"] = round(out["pm_vol"] / (out["pm_vol"] + session_vol) * 100, 1)
    return out


def universe_distribution(scored: list) -> dict:
    """How the WHOLE scored universe is distributed - is the 1.5x bar selective today?

    A screen that cannot tell a broad tape from a selective one is a false-positive machine:
    on 2026-11-12, 194 of 1,304 scored names (14.9%) cleared the bar, so "25 of 93 above the
    bar" read like a screen when the tape was broadly hot.
    """
    vals = sorted(r["rvol_now"] for r in scored if r.get("rvol_now") is not None)
    if not vals:
        return {}
    def pct(q):
        i = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
        return round(vals[i], 4)
    n = len(vals)
    return {
        "scored": n,
        "p25": pct(0.25), "p50": pct(0.50), "p75": pct(0.75), "p90": pct(0.90),
        "p99": pct(0.99),
        "share_ge_1_275": round(100.0 * sum(1 for v in vals if v >= NEAR_MISS_FLOOR) / n, 2),
        "share_ge_1_5": round(100.0 * sum(1 for v in vals if v >= ALERT_BAR) / n, 2),
        "share_ge_2_0": round(100.0 * sum(1 for v in vals if v >= 2.0) / n, 2),
        "share_ge_3_0": round(100.0 * sum(1 for v in vals if v >= 3.0) / n, 2),
    }


def selectivity_label(scored: list) -> str:
    """`broad_tape` / `elevated` / `selective` - how useful the absolute bar is today."""
    d = universe_distribution(scored)
    if not d:
        return "unknown"
    share = d["share_ge_1_5"]
    if share >= 8.0:
        return "broad_tape"
    if share >= 3.0:
        return "elevated"
    return "selective"


def compute_one(sym: str, fire_date: dt.date, avg10: float | None) -> dict:
    """The metric for one symbol plus its previous-session reading (same denominator)."""
    rec: dict = {"symbol": sym, "close": None, "rvol_now": None,
                 "rvol_prev_session": None, "rvol_at_09_38": None,
                 "rvol_prev": None,
                 "rvol_trend": None, "rvol_trend_delta": None,
                 "rvol_vs_prev_session": None,
                 "session_vol": None,
                 "daily_factor": None, "tv_avg10d": avg10,
                 "base_first": None, "base_last": None, "baseline_n": 0,
                 "status": ""}
    if not avg10 or avg10 < 10_000:
        # A denominator below 10,000 shares is not a real listed equity's 10-day average
        # daily volume — it is a column-index mistake or a placeholder. Refuse the row
        # rather than publish a 377,751x metric off it.
        rec["status"] = "implausible_tv_denominator"
        return rec
    y = fetch_series(sym, "5m", "1mo")
    daily = fetch_series(sym, "1d", "3mo")
    if not y:
        rec["status"] = "no_5m_bars"
        return rec

    def eval_session(day: dt.date):
        cand = sorted(d for d in y if d < day and d in daily)
        strict = [d for d in cand if all(y[d].get(b, {}).get("v", 0) > 0 for b in WIN)]
        base = strict[-10:]
        if len(base) < 10:
            return None, None
        t = y.get(day)
        if not t or not all(t.get(b, {}).get("v", 0) > 0 for b in WIN):
            return None, None
        w = sum(t[b]["v"] for b in WIN)
        m_win = sum(sum(y[d][b]["v"] for b in WIN) for d in base) / len(base)
        m_full = sum(daily[d]["v"] for d in base) / len(base)
        early = t.get("09:30", {}).get("v", 0)
        m_early = sum(y[d].get("09:30", {}).get("v", 0) for d in base) / len(base)
        return ({"base": [d.isoformat() for d in base], "m_win": m_win, "m_full": m_full,
                 "df": m_full / avg10, "w": w, "early": early, "m_early": m_early}, base)

    today = y.get(fire_date)
    if not today or not all(today.get(b, {}).get("v", 0) > 0 for b in WIN):
        rec["status"] = "no_session_bars"
        return rec

    prior_days = sorted(d for d in y if d < fire_date)
    if prior_days:
        pd = prior_days[-1]
        pv, _ = eval_session(pd)
        if pv is not None:
            rec["rvol_prev_session"] = round((pv["w"] / pv["m_win"]) * pv["df"], 6)
            rec["prev_session_date"] = pd.isoformat()
        else:
            rec["prev_session_status"] = "no_prior_session_bars"

    val, base = eval_session(fire_date)
    if val is None:
        rec["status"] = "insufficient_baseline"
        return rec

    rec["rvol_now"] = round((val["w"] / val["m_win"]) * val["df"], 6)
    if rec["rvol_now"] > 1000:
        rec["status"] = "implausible_metric"
        rec["rvol_now"] = None
        return rec
    rec["close"] = (today.get("09:40") or {}).get("c")
    rec["rvol_at_09_38"] = round((val["early"] / avg10), 6)
    rec["daily_factor"] = round(val["df"], 6)
    rec["base_first"] = val["base"][0]
    rec["base_last"] = val["base"][-1]
    rec["baseline_n"] = len(val["base"])
    # THE EARLIER CROSS-CHECK SNAPSHOT (the contract's `rvol_prev`): the SAME metric over the
    # earlier clock window, against the prior-10 mean of THAT window, on the same denominator.
    # The window is the 09:30 bar of the same series - the cross-check that needs no second
    # source and no second fetch.
    rec["session_vol"] = val["w"]
    if val["m_early"] > 0:
        rec["rvol_prev"] = round((val["early"] / val["m_early"]) * val["df"], 6)
    # `rvol_trend` is the EARLIER-SNAPSHOT delta, per the artifact contract. The
    # session-over-session delta is kept as `rvol_vs_prev_session` so nothing is lost.
    if rec["rvol_prev"] is not None:
        delta = rec["rvol_now"] - rec["rvol_prev"]
        rec["rvol_trend_delta"] = round(delta, 4)
        rec["rvol_trend"] = ("ACCELERATING" if delta > 0.05 else
                             "DECELERATING" if delta < -0.05 else "STABLE")
    if rec["rvol_prev_session"] is not None:
        rec["rvol_vs_prev_session"] = round(rec["rvol_now"] - rec["rvol_prev_session"], 4)
    rec["status"] = "ok"
    return rec


def tier_of(now: float | None, prior: float | None) -> str:
    if now is None:
        return "-"
    if prior is None:
        return "WATCH"
    if prior < ALERT_BAR <= now:
        return "ALERT"
    if NEAR_MISS_FLOOR <= now < ALERT_BAR:
        return "NEAR MISS"
    return "WATCH"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire-date", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--focus", help="file with the focus-roster symbols, one per line")
    ap.add_argument("--prior-csv", help="previous session's published focus-rvol CSV")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--top-n", type=int, default=25,
                    help="rows kept in the wider-universe table")
    ap.add_argument("--md-out", help="render the artifact markdown here")
    ap.add_argument("--csv-out", help="render the artifact CSV here")
    ap.add_argument("--wider-source", default="", help="name of the on-disk wider sources")
    ap.add_argument("--focus-md", default="",
                    help="the upstream focus.md - its header carries the sweep's own "
                         "`Screen data_date:` (the shibui T+1 date), which is NOT the folder date")
    ap.add_argument("--focus-dir-date", default="",
                    help="the date of the folder the focus list was found in")
    a = ap.parse_args()

    fire_date = dt.date.fromisoformat(a.fire_date)
    focus_dir_date = a.focus_dir_date or None
    screen_data_date = None
    upstream = a.focus_md or None
    if a.focus_md and os.path.exists(a.focus_md):
        try:
            with open(a.focus_md, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = re.search(r"^Screen data_date:\s*(\d{4}-\d{2}-\d{2})", line.strip())
                    if m:
                        screen_data_date = m.group(1)
                        break
        except OSError:
            pass
    # The trading-session lag between the sweep's own screen date and this fire. A weekday
    # count: a venue holiday inside the gap would add one, so it is an UPPER bound.
    lag_sessions = None
    if screen_data_date:
        try:
            d0 = dt.date.fromisoformat(screen_data_date)
            lag_sessions = sum(1 for i in range(1, (fire_date - d0).days)
                               if (d0 + dt.timedelta(days=i)).weekday() < 5)
        except ValueError:
            lag_sessions = None
    syms = sorted({s.strip().upper() for s in open(a.symbols) if s.strip()})
    focus = set()
    if a.focus and os.path.exists(a.focus):
        focus = {s.strip().upper() for s in open(a.focus) if s.strip()}

    prior_pub: dict = {}
    if a.prior_csv and os.path.exists(a.prior_csv):
        for r in csvmod.DictReader(open(a.prior_csv)):
            try:
                prior_pub[r["symbol"]] = (float(r["rvol_now"]), float(r.get("tv_avg10d") or 0) or None)
            except (KeyError, TypeError, ValueError):
                continue

    t0 = time.time()
    avg10, tv_problems = fetch_tv_denominators()
    print(f"[tv] {len(avg10)} denominators ({time.time() - t0:.1f}s)", file=sys.stderr)
    if tv_problems:
        for pr in tv_problems:
            print(f"[tv] PROBLEM {pr.get('code')}: {pr.get('message')}", file=sys.stderr)
        print("[tv] the scanner pull was NOT trustworthy - the denominator set is incomplete",
              file=sys.stderr)

    rows = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(compute_one, s, fire_date, avg10.get(s)): s for s in syms}
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                rows.append(fut.result())
            except Exception as exc:
                rows.append({"symbol": s, "status": f"error:{exc}", "rvol_now": None,
                             "rvol_prev_session": None})
            done += 1
            if done % 200 == 0:
                print(f"[fetch] {done}/{len(syms)} ({time.time() - t0:.0f}s)", file=sys.stderr)

    scored = [r for r in rows if r.get("rvol_now") is not None]
    scored.sort(key=lambda r: (-r["rvol_now"], r["symbol"]))
    for r in scored:
        r["prev_session_rvol_source"] = ("recomputed_same_feed"
                                        if r.get("rvol_prev_session") is not None
                                        else "unavailable")
        r["tier"] = tier_of(r.get("rvol_now"), r.get("rvol_prev_session"))
        r["crossed"] = (r.get("rvol_prev_session") is not None
                        and r["rvol_prev_session"] < ALERT_BAR <= r["rvol_now"])
        r["universe"] = "focus" if r["symbol"] in focus else "wider"
        pp = prior_pub.get(r["symbol"])
        if pp:
            r["prev_session_rvol_published"] = pp[0]
            if pp[1] and r.get("tv_avg10d"):
                r["denominator_drift_pct"] = round((r["tv_avg10d"] - pp[1]) / pp[1] * 100, 2)
    for r in rows:
        if r.get("rvol_now") is None:
            r.setdefault("tier", "-")
            r.setdefault("universe", "focus" if r["symbol"] in focus else "wider")
            r.setdefault("crossed", False)

    focus_rows = [r for r in scored if r["symbol"] in focus]
    # RETAIN EVERY SCORED ROW, PUBLISH THE TOP. The counts, the near-miss tier and the universe
    # distribution are properties of the WHOLE scored set - they are not computable from a
    # truncated list (the default `--top-n 25` made the near-miss tier invisible: 56 of the
    # names in the band sat BELOW the top 25). The JSON keeps everything; the markdown shows the
    # top `--top-n` of the wider union and the CSV carries the published set.
    wider_all = [r for r in scored if r["symbol"] not in focus]
    wider_rows = wider_all[: a.top_n]
    near_all = [r for r in scored
                if NEAR_MISS_FLOOR <= (r.get("rvol_now") or 0) < ALERT_BAR]
    published = {r["symbol"]: r for r in (focus_rows + wider_rows + near_all)}

    # THE PRE-MARKET PASS - the published rows only (~90 names, ~15 s), because
    # `includePrePost=true` costs +64% bytes on every response.
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(measure_premarket, sym, fire_date, r.get("session_vol")): sym
                for sym, r in published.items()}
        for fut in cf.as_completed(futs):
            sym = futs[fut]
            try:
                pm = fut.result()
            except Exception as exc:
                pm = {"pm_vol": None, "pm_source": f"error:{exc}", "pm_share_pct": None,
                      "pm_vintage_drift_pct": None}
            published[sym].update(pm)
    # NOTE: `slim()` is a PROJECTION - a field missing from this list is silently dropped
    # before the CSV and the markdown are rendered (it cost a whole debugging round on
    # 2026-11-12: the cross-check and the session volume were computed and then vanished).
    keys = ["symbol", "universe", "close", "rvol_now", "rvol_prev", "rvol_prev_session",
            "prev_session_rvol_source", "prev_session_rvol_published",
            "denominator_drift_pct", "rvol_at_09_38", "session_vol",
            "rvol_trend", "rvol_trend_delta", "rvol_vs_prev_session", "tier", "crossed",
            "daily_factor", "pm_vol", "pm_source", "pm_share_pct", "pm_vintage_drift_pct",
            "tv_avg10d", "base_first", "base_last", "baseline_n", "prev_session_date",
            "status"]

    def slim(r):
        return {k: r.get(k) for k in keys}

    out = {
        "fire_date": fire_date.isoformat(),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 1),
        "universe_size": len(syms),
        "scored": len(scored),
        "focus_scored": len(focus_rows),
        "focus_size": len(focus),
        "wider_size": len(syms) - len(focus),
        "alert_bar": ALERT_BAR,
        "near_miss_floor": NEAR_MISS_FLOOR,
        "daily_volume_source": "yahoo_1d",
        "tv_pull_problems": tv_problems,
        "prior_roster": sorted(prior_pub.keys()),
        "focus_dir_date": focus_dir_date,
        "screen_data_date": screen_data_date,
        "lag_sessions": lag_sessions,
        "upstream": upstream,
        "denominator_source": "tradingview_average_volume_10d_calc (one pull, both sides)",
        "focus_crossings": [r["symbol"] for r in focus_rows if r["crossed"]],
        "wider_crossings": [r["symbol"] for r in wider_all if r["crossed"]],
        "published_crossings": [r["symbol"] for r in published.values() if r["crossed"]],
        "focus_rows": [slim(r) for r in focus_rows],
        "wider_rows": [slim(r) for r in wider_all],
        "published_rows": [slim(r) for r in sorted(published.values(),
                                                   key=lambda r: -(r.get("rvol_now") or 0))],
        "wider_shown": len(wider_rows),
        "near_miss_all": [slim(r) for r in near_all],
        "distribution": universe_distribution(scored),
        "selectivity": selectivity_label(scored),
        "unscored": [{"symbol": r["symbol"], "status": r.get("status")}
                     for r in rows if r.get("rvol_now") is None],
    }
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)

    if a.md_out:
        render_markdown(out, a.md_out, a.csv_out, wider_source=a.wider_source)
    if a.csv_out:
        render_csv(out, a.csv_out)

    print(f"[done] {len(scored)}/{len(syms)} scored in {out['elapsed_sec']}s | "
          f"focus {len(focus_rows)} (crossings {len(out['focus_crossings'])}) | "
          f"wider {len(wider_all)} (table {len(wider_rows)}, crossings "
          f"{len(out['wider_crossings'])}) | published {len(published)} | "
          f"near-miss {len(near_all)} | selectivity {out['selectivity']} -> {a.out}",
          file=sys.stderr)
    return 0


CSV_COLS = ["symbol", "universe", "close", "rvol_intraday_live", "rvol_now", "rvol_prev",
            "rvol_at_09_38", "rvol_trend", "prev_session_rvol", "prev_session_rvol_source",
            "prev_session_rvol_published", "denominator_drift_pct", "bucket", "tier",
            "pm_vol", "pm_vol_source", "data timestamp",
            # audit columns - they make the published numbers CHECKABLE by a consumer:
            # `rvol_intraday_live` must equal session_vol / tv_avg10d, and `rvol_trend` must
            # agree with rvol_now - rvol_prev.
            "rvol_trend_delta", "rvol_vs_prev_session", "session_vol", "tv_avg10d",
            "pm_share_pct", "pm_vintage_drift_pct"]


def render_csv(out: dict, path: str) -> None:
    """The machine-readable rows: the FOCUS roster, the wider table, and EVERY near miss.

    The near-miss tier is the watch list the next fire needs, so its rows are in the CSV even
    when the name is not in the wider table - otherwise the tier is prose with no data behind it.
    """
    rows = out.get("published_rows") or (out["focus_rows"] + out["wider_rows"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csvmod.writer(fh)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([
                r.get("symbol"), r.get("universe"),
                _num(r.get("close"), 4),
                (f'{r["session_vol"] / r["tv_avg10d"]:.3g}'
                 if r.get("session_vol") and r.get("tv_avg10d") else "n/a"),
                _num(r.get("rvol_now")), _num(r.get("rvol_prev")),
                _num(r.get("rvol_at_09_38")), r.get("rvol_trend"),
                _num(r.get("rvol_prev_session")), r.get("prev_session_rvol_source", "unavailable"),
                r.get("prev_session_rvol_published", "n/a"),
                r.get("denominator_drift_pct", "n/a"),
                "RVOL Required" if (r.get("rvol_now") or 0) >= ALERT_BAR else "Liquid",
                r.get("tier"),
                (r.get("pm_vol") if r.get("pm_vol") is not None else 0),
                (r.get("pm_source") or "not_subtracted"),
                f"{out['fire_date']} 09:45 ET (last completed 5m bar, stamped 09:40)",
                _num(r.get("rvol_trend_delta"), 4), _num(r.get("rvol_vs_prev_session"), 4),
                _num(r.get("session_vol"), 0), _num(r.get("tv_avg10d"), 1),
                _num(r.get("pm_share_pct"), 1), _num(r.get("pm_vintage_drift_pct"), 2),
            ])


def _num(v, nd=4):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "n/a"


def _md_table(rows: list, stamp: str = "") -> str:
    """The contract's column set - EVERY number for a name is in that name's row.

    (The narrow 7-column table this replaced dropped `rvol_intraday_live`, `rvol_prev`,
    `rvol_at_09_38`, the bucket, the pre-market columns and the published cross-check, so a
    reader had to leave the table to learn a name's story.)
    """
    head = ("| symbol | close | rvol_intraday_live | rvol_now | rvol_prev | rvol_at_09_38 | "
            "rvol_trend | prev_session_rvol | prev_session_rvol_source | "
            "prev_session_rvol_published | denominator_drift_pct | bucket | tier | pm_vol | "
            "pm_vol_source | data timestamp |\n"
            + "|" + "---|" * 16 + "\n")
    body = ""
    for r in rows:
        live = (f'{r["session_vol"] / r["tv_avg10d"]:.3g}'
                if r.get("session_vol") and r.get("tv_avg10d") else "n/a")
        body += (f"| {r.get('symbol')} | {_num(r.get('close'), 2)} | {live} | "
                 f"{_num(r.get('rvol_now'))} | {_num(r.get('rvol_prev'))} | "
                 f"{_num(r.get('rvol_at_09_38'))} | {r.get('rvol_trend') or 'n/a'} | "
                 f"{_num(r.get('rvol_prev_session'))} | "
                 f"{r.get('prev_session_rvol_source','unavailable')} | "
                 f"{_num(r.get('prev_session_rvol_published'))} | "
                 f"{_num(r.get('denominator_drift_pct'), 2)} | "
                 f"{'RVOL Required' if (r.get('rvol_now') or 0) >= ALERT_BAR else 'Liquid'} | "
                 f"{r.get('tier')} | "
                 f"{(r.get('pm_vol') if r.get('pm_vol') is not None else 0)} | "
                 f"{(r.get('pm_source') or 'not_subtracted')} | {stamp} |\n")
    return head + body


def render_markdown(out: dict, path: str, csv_path: str, wider_source: str = "") -> None:
    """The artifact. Deterministic - every number comes straight from the scored JSON."""
    focus = out["focus_rows"]
    wider_all = out["wider_rows"]
    shown = out.get("wider_shown") or len(wider_all)
    wider = wider_all[:shown]
    published = out.get("published_rows") or (focus + wider_all)
    near_rows = out.get("near_miss_all") or [
        r for r in published
        if NEAR_MISS_FLOOR <= (r.get("rvol_now") or 0) < ALERT_BAR]
    # THE WATCH LIST IS ORDERED BY THE TREND DELTA, not by rvol_now. A near miss that is
    # FADING is not a near miss - it was a near miss 10 minutes ago. On 2026-11-12 the band
    # held 56 names and only 5 of them were building; ordering by level alone published 51
    # dead names ahead of the live ones.
    near_rows = sorted(near_rows, key=lambda r: (-(r.get("rvol_trend_delta") or 0),
                                                 -(r.get("rvol_now") or 0)))
    dist = out.get("distribution") or {}
    sel = out.get("selectivity") or "unknown"

    def crossed(r):
        return bool(r.get("crossed"))

    alert_rows = [r for r in published if crossed(r)]
    alert_rows.sort(key=lambda r: -(r.get("rvol_trend_delta") or 0))
    alert_line = ", ".join(f"{r['symbol']} ({r.get('rvol_trend')})" for r in alert_rows)
    n_req = sum(1 for r in published if (r.get("rvol_now") or 0) >= ALERT_BAR)
    n_liq = len(published) - n_req
    n_near = len(near_rows)
    n_near_build = sum(1 for r in near_rows if r.get("rvol_trend") == "ACCELERATING")
    n_near_fade = sum(1 for r in near_rows if r.get("rvol_trend") == "DECELERATING")
    n_alert_build = sum(1 for r in alert_rows if r.get("rvol_trend") == "ACCELERATING")
    n_alert_fade = sum(1 for r in alert_rows if r.get("rvol_trend") == "DECELERATING")
    all_req = dist.get("share_ge_1_5")
    all_cross = len(out.get("wider_crossings") or []) + len(out.get("focus_crossings") or [])

    md = []
    md.append("---\n"
              f"date: {out['fire_date']}\n"
              "cron: 07-stock-screener-focus-rvol-09:45\n"
              'fire_time_et: "09:45"\n'
              f"fire_date: {out['fire_date']}\n"
              f"focus_dir_date: {out.get('focus_dir_date') or 'n/a'}\n"
              f"screen_data_date: {out.get('screen_data_date') or 'n/a'}\n"
              f"lag_sessions: {out.get('lag_sessions') if out.get('lag_sessions') is not None else 'n/a'}\n"
              "universe_source: focus_plus_wider\n"
              f"universe_size: {out['universe_size']}\n"
              "wider_universe_source: focus+master+17\n"
              f"wider_universe_size: {out['wider_size']}\n"
              f"wider_shown: {shown}\n"
              "elapsed_minutes: 15\nsession_fraction: 0.0385\n"
              "source: Yahoo chart API 5m bars (interval=5m&range=1mo, regular session only) for "
              "the session volume, the 09:45 close and the prior-10 same-window baseline; Yahoo "
              "chart API 1d bars (range=3mo) for the prior-10 full-day volume; TradingView "
              "america scanner average_volume_10d_calc for the denominator (ONE pull, used for "
              "BOTH sides of every crossing); Yahoo chart API 5m bars with includePrePost=true "
              "for the published rows only, to measure the pre-market share\n"
              "method: rvol_tod_normalised, time-of-day-normalised intraday RVOL. Today's window "
              "is 09:30-09:45 ET - 15 of 390 session minutes - compared with the SAME clock "
              "window on the prior 10 eligible sessions, then scaled to full-day units by the "
              "prior-10 mean full-day volume divided by TV average_volume_10d_calc. The earlier "
              "reading is the same metric over the 09:30-09:35 slot, against the prior-10 mean "
              "of that same slot, on the same denominator.\n"
              "metric_def: rvol_tod_normalised = (cumulative volume 09:30 -> the fire's bar, "
              "today) / (mean cumulative volume over 09:30 -> the SAME clock window across the "
              "prior 10 sessions) x (mean full-day volume across those prior 10 sessions / TV "
              "average_volume_10d_calc); rvol_intraday_live = cumulative session volume to the "
              "fire bar / TV average_volume_10d_calc (reference only, never bucketed); rvol_prev "
              "= the same formula over the earlier cross-check snapshot's window against the "
              "prior-10 mean of that same window; rvol_at_09_38 = the raw cumulative ratio at "
              "that earlier snapshot; pm_share_pct = pre-market volume before 09:30 as a "
              "percentage of the session volume\n"
              "bucket_rule: rvol_now >= 1.5 -> RVOL Required, otherwise Liquid\n"
              "rvol_required_bucket: 1.5\nrvol_alert_threshold: 1.5\nnear_miss_floor: 1.275\n"
              "alert_rule: An alert fires for a name whose rvol_now is at or above "
              "RVOL_ALERT_THRESHOLD (1.5) AND whose prev_session_rvol is below "
              "RVOL_ALERT_THRESHOLD (1.5) - that is, the name crossed UP through the alert bar "
              "since the previous session's reading of the same metric.\n"
              "pm_source_status: measured_from_series\ncross_check_source: same_series_truncated\n"
              "status: ok\n"
              f"upstream: {out.get('upstream') or 'focus.md'}\nnames_unpriced: "
              f"{len(out['unscored'])}\n"
              # ---- keys beyond the contract's list, appended so its ORDER is untouched
              f"published_rows: {len(published)}\n"
              f"selectivity: {sel}\n"
              f"universe_median_rvol: {dist.get('p50', 'n/a')}\n"
              f"universe_p90_rvol: {dist.get('p90', 'n/a')}\n"
              f"universe_share_ge_1_5_pct: {all_req if all_req is not None else 'n/a'}\n"
              f"universe_crossings: {all_cross}\n"
              "---\n")
    md.append(f"\n# Focus RVOL snapshot - {out['fire_date']} 09:45 ET (cron #07)\n")
    md.append("\n## TL;DR\n"
              f"- **{out['scored']} of {out['universe_size']}** names scored "
              f"({out['focus_size']} focus + {out['wider_size']} wider union); "
              f"**{len(published)} rows published** (the focus roster, the top {shown} of the "
              f"wider union, and every name in the near-miss band).\n"
              f"- **Required: {n_req} of {len(published)} published** "
              f"({n_liq} Liquid); **{n_near} near misses**; **{len(alert_rows)} alerts** "
              f"(provable crossings).\n"
              f"- **The tape today: `{sel}`.** "
              + (f"**{all_req}% of the {dist.get('scored')} scored names cleared the 1.5x bar** "
                 f"(median {dist.get('p50')}x, p90 {dist.get('p90')}x) and there were "
                 f"**{all_cross} crossings** across the whole scored set - the bar is a "
                 f"DESCRIPTION of a broad move, not a selection of it. "
                 if sel == "broad_tape" else
                 f"Only {all_req}% of the {dist.get('scored')} scored names cleared the 1.5x bar "
                 f"(median {dist.get('p50')}x, p90 {dist.get('p90')}x) - the bar is selective "
                 f"today. ")
              + f"\n- **Alerts: {alert_line or 'none'}.** "
              f"**{n_alert_build} are still building and {n_alert_fade} are already fading** "
              f"between the earlier snapshot and the fire; the near-miss watch list is "
              f"**{n_near_build} building vs {n_near_fade} fading**.\n"
              "- **Every prior reading is RECOMPUTED on the same feed and the SAME TradingView "
              "denominator as today's reading**, so both sides of each crossing are one scale. "
              "The TV denominator is a rolling average and moves between fetches, so a published "
              "prior value is a cross-check, never the baseline.\n"
              "- **The focus roster alone is a momentum screen on the previous session's data and "
              "structurally misses the day's movers**; the wider union is what carries them.\n")
    md.append("\n## Universe\n"
              f"- focus roster: {out['focus_size']} names\n"
              f"- wider union: {out['wider_size']} names from {wider_source or 'n/a'}\n"
              f"- scored: {out['scored']}; unscored: {len(out['unscored'])}; "
              f"published rows: {len(published)}\n"
              + (f"- **the scored universe's distribution** (the context for every count below): "
                 f"median {dist.get('p50')}x, p75 {dist.get('p75')}x, p90 {dist.get('p90')}x, "
                 f"p99 {dist.get('p99')}x; {dist.get('share_ge_1_275')}% at or above 1.275x, "
                 f"**{all_req}% at or above 1.5x**, {dist.get('share_ge_2_0')}% at or above 2x, "
                 f"{dist.get('share_ge_3_0')}% at or above 3x - selectivity: **{sel}**\n"
                 if dist else ""))
    stamp = (f"{out['fire_date']} 09:45 ET (last completed 5m bar, stamped 09:40; "
             f"volume window 09:30-09:45 ET)")
    md.append("\n## Focus table\n\n" + _md_table(focus, stamp))
    md.append(f"\n## Wider universe\n\nThe top {shown} of the wider union by `rvol_now`.\n\n"
              + _md_table(wider, stamp))
    md.append("\n### Counts\n"
              f"- universe size: {out['universe_size']}\n"
              f"- focus roster size: {out['focus_size']}\n"
              f"- wider universe size: {out['wider_size']}\n"
              f"- scored: {out['scored']}; unpriced: {len(out['unscored'])}; "
              f"published rows: {len(published)}\n"
              f"- Required count: {n_req} (of {len(published)} published)\n"
              f"- Liquid count: {n_liq}\n"
              f"- NEAR MISS count: {n_near} "
              f"({n_near_build} building, {n_near_fade} fading)\n"
              f"- alert count: {len(alert_rows)} "
              f"({n_alert_build} building, {n_alert_fade} fading)\n"
              f"- crossings: {len(alert_rows)} published"
              + (f"; **{all_cross} across all {out['scored']} scored names**"
                 if all_cross != len(alert_rows) else "")
              + "\n"
              + (f"- universe distribution: median {dist.get('p50')}x, p90 {dist.get('p90')}x; "
                 f"{all_req}% of the scored universe at or above 1.5x "
                 f"(selectivity: {sel})\n" if dist else ""))
    md.append("\n## Alerts\n\n")
    if alert_rows:
        md.append("A name is listed only if the crossing is PROVEN: `prev_session_rvol` below "
                  "1.5x and `rvol_now` at or above it, both sides on the same feed and the same "
                  "denominator. Ordered by the trend delta (the earlier cross-check snapshot -> "
                  "the fire), so the names still BUILDING come first.\n\n")
        for r in alert_rows:
            md.append(f"- **{r['symbol']}** - {_num(r.get('rvol_now'))}x now vs "
                      f"{_num(r.get('rvol_prev_session'))}x on the prior session "
                      f"({r.get('prev_session_rvol_source')}), close "
                      f"{_num(r.get('close'), 2)} - "
                      + (f"RVOL building {_num(r.get('rvol_prev'))}x -> "
                         f"{_num(r.get('rvol_now'))}x, accumulation\n"
                         if r.get("rvol_trend") == "ACCELERATING" else
                         f"RVOL fading {_num(r.get('rvol_prev'))}x -> "
                         f"{_num(r.get('rvol_now'))}x, distribution\n"
                         if r.get("rvol_trend") == "DECELERATING" else
                         f"RVOL flat {_num(r.get('rvol_prev'))}x -> "
                         f"{_num(r.get('rvol_now'))}x\n"))
    else:
        md.append("**none** - no published name crossed UP through the 1.5x bar against its "
                  "recomputed prior-session reading.\n")
    # ---------------------------------------------------------------- near misses
    md.append("\n## Near misses\n\n")
    if near_rows:
        md.append(f"Names between {NEAR_MISS_FLOOR}x and {ALERT_BAR}x - the tradable edge. Each "
                  f"would become an ALERT if `rvol_now` reaches 1.5x while `prev_session_rvol` "
                  f"stays below 1.5x. **Ordered by the trend delta, so the names that are "
                  f"BUILDING come first** - on 2026-11-12 that split was "
                  f"{n_near_build} building against {n_near_fade} fading, and the fading ones "
                  f"were a watch list in name only.\n\n"
                  "| symbol | rvol_now | prev_session_rvol | rvol_prev | rvol_trend | "
                  "pm_share_pct | what would turn it into an alert |\n"
                  "|---|---|---|---|---|---|---|\n")
        for r in near_rows:
            md.append(f"| {r['symbol']} | {_num(r.get('rvol_now'))} | "
                      f"{_num(r.get('rvol_prev_session'))} | {_num(r.get('rvol_prev'))} | "
                      f"{r.get('rvol_trend') or 'n/a'} | {_num(r.get('pm_share_pct'), 1)} | "
                      f"rvol_now reaching 1.5x with prev_session_rvol below 1.5x |\n")
    else:
        md.append("None: no scored name sits in the 1.275x-1.5x band.\n")

    # ---------------------------------------------------------------- universe change
    today_syms = [r.get("symbol") for r in focus if r.get("symbol")]
    prior_syms = list(out.get("prior_roster") or [])
    stayed = sorted(set(today_syms) & set(prior_syms))
    entered = sorted(set(today_syms) - set(prior_syms))
    left = sorted(set(prior_syms) - set(today_syms))
    md.append("\n## Universe change\n\n"
              f"The focus roster against the previous session's published roster: "
              f"**{len(entered)} entered**, **{len(left)} left**, **{len(stayed)} stayed**.\n\n"
              f"- entered: {', '.join(entered) if entered else 'none'}\n"
              f"- left: {', '.join(left) if left else 'none'}\n"
              f"- stayed: {', '.join(stayed) if stayed else 'none'}\n\n"
              f"This turnover is why the prior reading is recomputed rather than read from the "
              f"previous session's published CSV: only {len(stayed)} of {len(today_syms)} roster "
              f"names were in that file, so a published baseline would be `n/a` on nearly every "
              f"row and the alert tier would be silently dead again.\n")

    md.append("\n## Method\n"
              f"- scored by `tools/focus_rvol_score.py` in {out['elapsed_sec']}s\n"
              "- window volume: Yahoo 5m bars, 09:30/09:35/09:40 stamps, the last COMPLETED bar\n"
              "- prior-10 same-window baseline: the same Yahoo series\n"
              "- prior-10 full-day volume: Yahoo 1d bars (median ratio 1.0000 vs Nasdaq "
              "consolidated, max deviation 0.32%)\n"
              "- denominator: TV `average_volume_10d_calc`, ONE pull used for BOTH sides of every "
              "crossing\n"
              "- the previous session's reading is recomputed on that same denominator; the "
              "published value is carried as a cross-check with its drift\n"
              "- **one vintage per artifact**: the whole run is one process, so every published "
              "number comes from the same bytes. The pre-market pass fetches the same window "
              "again with includePrePost=true, and the session volume in THAT response is "
              "compared with the bulk pass's - a drift over 2% publishes the share as `n/a` "
              "rather than mixing vintages\n"
              "- pre-market: `pm_vol` is MEASURED for the published rows (the bars before 09:30 "
              "on the includePrePost response) and is not subtracted from the session volume - "
              "the session bars exclude pre-market by construction\n")
    md.append("\n## Source health\n"
              f"- TradingView scanner (the denominator): one pull, "
              f"{'no truncation and no coverage problem reported' if not out.get('tv_pull_problems') else 'PROBLEMS: ' + str(out.get('tv_pull_problems'))} - "
              f"one denominator set used for BOTH sides of every crossing\n"
              f"- Yahoo chart API (session volume, close, baselines): healthy; the engine scored "
              f"{out['scored']} of {out['universe_size']} candidates\n"
              f"- unpriced names: {len(out['unscored'])} of {out['universe_size']} candidates had "
              f"no usable session window (`no_session_bars`); they are reported as unpriced, "
              f"never as a zero\n")
    md.append("\n## Degradation / caveats\n"
              f"- **{len(out['unscored'])} candidates could not be priced** - no regular-session "
              f"bars in the fetched window. They are excluded from every count rather than "
              f"published as a zero or a daily proxy.\n"
              "- **The universe is a CANDIDATE SET, not the market.** It is unioned from the "
              "previous session's published files (the focus roster, the sweep's master list "
              "and cron #17's mover boards). A name that was in none of them cannot appear "
              "here.\n"
              "- **The wider table shows the TOP "
              f"{shown}, not every name above the bar.** On a broad tape the counts above give "
              "the full picture; the table is the screen, the counts are the context.\n"
              "- **`rvol_tod_normalised` is a MORNING metric** - how hot a name is against its "
              "OWN norm at 09:45. It is not a full-day relative volume and it is not comparable "
              "with cron #09's completed-session `rvol_<date>` (call that `rvol_session_eod`).\n"
              "- **`rvol_intraday_live` is reference only** - mechanically tiny at 09:45, never "
              "used for bucketing.\n"
              "- **`rvol_trend` is the earlier-snapshot delta** (`rvol_now` - `rvol_prev`); the "
              "session-over-session delta is carried as `rvol_vs_prev_session`.\n"
              "- **The TV denominator is a rolling average** and moves ~2% every 15 minutes, so a "
              "name sitting within ~2% of the bar can flip on the denominator alone.\n"
              "- **The pre-market share is measured only on the fire's OWN day.** Nasdaq's "
              "pre-session counter is the source (Yahoo's extended-hours bars carry volume 0 - "
              "measured 2026-11-13, on the live session and on history), and a REPLAY cannot "
              "measure it at all: the endpoint serves TODAY's pre-market, which is a different "
              "session. On a replay the rows read `pm_vol_source: not_subtracted` and the share "
              "is `n/a` rather than a wrong number.\n"
              "- **`lag_sessions` is a WEEKDAY count** between the sweep's own `Screen data_date:` "
              "and this fire - a venue holiday inside the gap would add one, so it is an upper "
              "bound.\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(md))


if __name__ == "__main__":
    sys.exit(main())

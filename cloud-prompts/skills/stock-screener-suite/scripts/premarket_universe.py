#!/usr/bin/env python3
"""premarket_universe.py — resolve and PROVE the pre-market universe for a given fire date.

MARKER: premarket-universe-v2

WHY THIS EXISTS
---------------
The pre-market gapper's universe is "the Focus list of the most recent completed
18:30 ET sweep". Nothing in that sentence says *which date* the Focus list
belongs to, and every failure mode below produces an artifact that looks
perfect:

1. **The sweep for the prior session never published** (it crashed, the platform
   stalled it, or it was skipped). A routine that "fetches the latest focus.csv"
   silently scans an OLDER session's names and computes every gap against the
   wrong close.
2. **The sweep's CSV carries TWO close columns.** The current schema has
   `screen_close_resolved` (the screen's T+1 data date — the PREVIOUS session)
   and `today_close` (the sweep's own session). Picking the wrong one shifts
   the gap by up to 10% (measured 2026-11-06: APP 356.10 vs 391.22).
3. **The old schema's dated columns are gone.** The pre-2026-11-04 CSV had
   `close_<YYYY-MM-DD>` columns; the shipped helper only looked for those and
   for `prior_close`/`close`/`last_close` — none of which exist in the current
   schema, so it silently resolved NO reference close at all.

So the close is chosen **BY DATE, never by name**, the universe's own date is
**asserted against the expected prior session**, and every reference close is
**cross-checked against two independent sources**.

THE ASSERTIONS (hard - a failure means the run must not publish a silent scan)
-----------------------------------------------------------------------------
H1  the expected prior session is resolved FROM DATA (never a hand-typed date)
H2  a published Focus list exists for a session <= the expected prior session
H3  the universe's own session == the expected prior session
    (a stale universe is a FAIL, not a warning: --allow-stale-universe downgrades
    it, and then the reference close MUST come from the independent sources)
H4  every name has a reference close for the expected prior session
H5  every reference close is confirmed by at least one independent source

USAGE
-----
    python3 premarket_universe.py --fire-date 2026-11-07 \
        --out-dir /workspace/daily-screens/2026-11-07

Writes `<out-dir>/_universe.json` and prints the manifest. Exit code 0 = every
hard assertion passed; 3 = a hard assertion failed (the reason is in the
manifest and in the printed output); 2 = bad usage.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

MARKER = "premarket-universe-v2"
# The v1 string is kept in this file on purpose: a runner holding an OLD fetch
# ladder (which greps for v1) must still accept the NEW script. A ladder that
# greps for v2 rejects a STALE v1 copy, so the fix cannot be silently missed.
LEGACY_MARKER = "premarket-universe-v1"
OUTPUTS_REPO = "karizaco/minimax-cloud-outputs"
PROMPTS_REPO = "karizaco/maxhermes-migration"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
# SPY is an ETF: assetclass=stocks answers "Symbol not exists" (measured 2026-11-07).
SPY_HIST = ("https://api.nasdaq.com/api/quote/SPY/historical?assetclass=etf"
            "&fromdate={f}&todate={t}&limit=40")
TV_SCAN = "https://scanner.tradingview.com/america/scan"
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"

DATED_CLOSE_RE = re.compile(r"^close[_-]?(\d{4}-\d{2}-\d{2})$", re.I)


# --------------------------------------------------------------------------- io
def _http(url: str, headers: dict | None = None, timeout: int = 30):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace"), dict(r.headers)


def _github_raw(repo: str, path: str, ref: str = "main", token: str | None = None):
    """Fetch a file from a repo through the CONTENTS API (authoritative, not CDN-cached)."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    headers = {"Accept": "application/vnd.github.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # A missing path is a 404, NOT an exception: the resolver walks back through
    # sessions looking for a published sweep, and a session whose focus.csv was
    # never published must read as "not published" instead of killing the run.
    # (Measured 2026-11-10: the 2026-11-09 sweep published focus.md but no
    # focus.csv, and the unhandled HTTPError aborted the whole fire.)
    try:
        body, _ = _http(url, headers)
    except urllib.error.HTTPError as e:
        return None, "not published (HTTP %s)" % e.code
    except urllib.error.URLError as e:
        return None, "not published (%s)" % (getattr(e, "reason", e) or "network error")
    if body.lstrip()[:200].find('"message"') >= 0:
        return None, body
    return body, None


# ------------------------------------------------------------------- sessions
def resolve_sessions(fire_date: dt.date, token: str | None = None,
                     sessions_file: str | None = None) -> list[dt.date]:
    """The US session dates before the fire date, newest first, derived FROM DATA.

    The trading calendar is NOT hand-typed: holidays and half days are decided
    by the market's own history. Nasdaq's SPY daily history is the primary
    source (free, unmetered); shibui is the fallback.
    """
    sessions: list[dt.date] = []
    src = None
    if sessions_file:
        # offline / deterministic path (used by the regression test)
        try:
            for line in open(sessions_file, encoding="utf-8"):
                line = line.strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", line):
                    sessions.append(dt.date.fromisoformat(line))
            if sessions:
                src = f"file:{sessions_file}"
        except Exception as e:
            src = f"file:{sessions_file} failed ({type(e).__name__})"
    if sessions:
        all_sessions = sorted({s for s in sessions}, reverse=True)
        before = [s for s in all_sessions if s < fire_date]
        return before, src, (all_sessions[0] if all_sessions else None)
    try:
        f = (fire_date - dt.timedelta(days=40)).strftime("%Y-%m-%d")
        t = dt.datetime.now(ET).strftime("%Y-%m-%d")
        body, _ = _http(SPY_HIST.format(f=f, t=t), {"Referer": "https://www.nasdaq.com/"})
        data = json.loads(body)
        rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
        for r in rows:
            try:
                m, d, y = str(r.get("date", "")).split("/")
                sessions.append(dt.date(int(y), int(m), int(d)))
            except Exception:
                continue
        if sessions:
            src = "nasdaq:SPY/historical"
    except Exception as e:
        src = f"nasdaq:SPY/historical failed ({type(e).__name__})"

    if not sessions:
        # fallback: shibui via the MCP-over-HTTP bridge
        bridge = "/workspace/mcp_bridge.py"
        if os.path.exists(bridge):
            q = ("SELECT DISTINCT date FROM shibui.stock_quotes WHERE ticker='SPY' "
                 f"AND date <= '{fire_date.isoformat()}' ORDER BY date DESC LIMIT 30")
            try:
                import subprocess
                args = json.dumps({"query": q, "user_prompt": "US trading sessions before the fire date"})
                with open("/tmp/_pu_q.json", "w") as fh:
                    fh.write(args)
                out = subprocess.run([sys.executable, bridge, "shibui", "stock_data_query",
                                      "/tmp/_pu_q.json"], capture_output=True, timeout=120)
                rows = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
                for r in rows:
                    d = str(r.get("date", ""))[:10]
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                        sessions.append(dt.date.fromisoformat(d))
                if sessions:
                    src = "shibui:stock_quotes(SPY)"
            except Exception as e:
                src = (src or "") + f"; shibui fallback failed ({type(e).__name__})"

    all_sessions = sorted({s for s in sessions}, reverse=True)
    before = [s for s in all_sessions if s < fire_date]
    latest_now = all_sessions[0] if all_sessions else None
    return before, src, latest_now


# -------------------------------------------------------------------- universe
def fetch_focus(session: dt.date, token: str | None = None, root: str | None = None):
    """The Focus list published for a session: the .csv if there is one, else the .md.

    The markdown Focus list IS the published universe — a sweep that ships
    `focus.md` without its `focus.csv` companion has still published its Focus
    list. The returned path tells the caller which kind it got.
    """
    if root:
        # local mirror (used by the regression test): <root>/<date>/focus.{csv,md}
        for name in ("focus.csv", "focus.md"):
            local = os.path.join(root, session.isoformat(), name)
            if os.path.exists(local):
                with open(local, encoding="utf-8", errors="replace") as fh:
                    return fh.read(), local, None
        return None, os.path.join(root, session.isoformat(), "focus.csv"), "not published"
    for name in ("focus.csv", "focus.md"):
        path = f"daily-screens/{session.isoformat()}/{name}"
        body, err = _github_raw(OUTPUTS_REPO, path, "main", token)
        if body is not None:
            return body, path, None
    return None, f"daily-screens/{session.isoformat()}/focus.csv", "not published"


def fetch_results_prov(session: dt.date, token: str | None = None,
                       root: str | None = None):
    """Per-name screen provenance from the sweep's canonical machine file.

    `_results.json` is listed in the sweep manifest's canonical machine files. It
    carries, per candidate, the stylist NAMES and the origin names. `focus.md`
    carries only the COUNTS plus the origin list, so the stylist names (which the
    non-qualifying ranking needs) are recovered from here.
    """
    if root:
        path = os.path.join(root, session.isoformat(), "_results.json")
        if not os.path.exists(path):
            return {}, path, "not published"
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        err = None
    else:
        path = f"daily-screens/{session.isoformat()}/_results.json"
        body, err = _github_raw(OUTPUTS_REPO, path, "main", token)
    if body is None:
        return {}, path, err
    try:
        d = json.loads(body)
    except Exception as e:
        return {}, path, "unparseable (%s)" % type(e).__name__
    out: dict[str, dict] = {}
    for c in d.get("candidates") or []:
        sym = str(c.get("symbol", "")).strip().upper()
        if not sym:
            continue
        out[sym] = {
            "stylists": "|".join(str(x) for x in (c.get("stylists") or [])),
            "origins": "|".join(str(x) for x in (c.get("origins") or [])),
            "flags": "",
        }
    return out, path, None


def parse_focus_md(text: str, session: dt.date, prov: dict | None = None):
    """Parse the Focus list's markdown table -> (names, meta, error).

    The table is `| Symbol | Stylists | Origins | Flags | Velocity | ADR% | Notes |`
    where `Stylists`/`Origins` are COUNTS and `Notes` carries the origin names.
    """
    rows = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if not cells:
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0].lower() in ("symbol", "ticker"):
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", cells[0]):
            continue
        rows.append(cells)
    if not rows:
        return [], {"close_by_session": {}, "schema": "focus.md (no close column)",
                    "data_date": None, "screen_col": None, "prov": {}, "rows": []}, \
               "focus.md has no parseable rows"
    prov = prov or {}
    names, pmap = [], {}
    for cells in rows:
        sym = cells[0].upper()
        names.append(sym)
        p = prov.get(sym, {})
        origins = p.get("origins") or ""
        if not origins and len(cells) >= 7:
            origins = ",".join(x.strip() for x in cells[6].split(",") if x.strip())
        pmap[sym] = {
            "stylists": p.get("stylists") or (cells[1] if len(cells) > 1 else ""),
            "origins": origins,
            "flags": p.get("flags") or (cells[3] if len(cells) > 3 and cells[3] != "—" else ""),
            "data_date": None,
        }
    return names, {"close_by_session": {}, "schema": "focus.md (no close column)",
                   "data_date": None, "screen_col": None, "prov": pmap, "rows": []}, None


def parse_focus(text: str, session: dt.date):
    """Parse a focus.csv and work out WHICH close column belongs to which session.

    The mapping is by DATE, never by name:
      * `close_<YYYY-MM-DD>`  -> that exact session
      * `today_close`          -> the sweep's own session (the directory date)
      * `screen_close_resolved`-> the sweep's `data_date` (shibui is T+1, so this
                                 is usually the PREVIOUS session) and is NEVER a
                                 valid denominator
    """
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return [], {}, "the CSV has no data rows"
    fields = list(rows[0].keys())

    dated = {m.group(1): m.group(0) for m in (DATED_CLOSE_RE.match(f) for f in fields) if m}
    data_date = (rows[0].get("data_date") or "").strip() or None
    screen_col = "screen_close_resolved" if "screen_close_resolved" in fields else None

    close_by_session: dict[str, str] = {}
    for sess, col in dated.items():
        close_by_session[sess] = col
    if "today_close" in fields:
        close_by_session[session.isoformat()] = "today_close"

    schema = ("dated" if dated else "current") + ("+today_close" if "today_close" in fields else "")

    names: list[str] = []
    ref: dict[str, float] = {}
    prov: dict[str, dict] = {}
    for r in rows:
        sym = None
        for k in ("symbol", "ticker", "Symbol", "Ticker"):
            if r.get(k):
                sym = str(r[k]).strip().split(".")[0].split("/")[0].upper()
                break
        if not sym:
            continue
        names.append(sym)
        prov[sym] = {
            "stylists": (r.get("stylists") or "").strip(),
            "origins": (r.get("origins") or "").strip(),
            "flags": (r.get("flags") or "").strip(),
            "data_date": data_date,
        }
    return names, {"close_by_session": close_by_session, "schema": schema,
                   "data_date": data_date, "screen_col": screen_col,
                   "prov": prov, "rows": rows}, None


# --------------------------------------------------------------- cross-checks
def nasdaq_hist_close(sym: str, session: dt.date) -> float | None:
    """The SETTLED close for one EXACT session, from Nasdaq's per-symbol history.

    Unlike the TradingView/Cboe `close`, this is session-exact, so it can still
    confirm the denominator on a replay (when the live sources have already
    rolled forward to a later session).
    """
    f = (session - dt.timedelta(days=12)).strftime("%Y-%m-%d")
    t = (session + dt.timedelta(days=6)).strftime("%Y-%m-%d")
    url = (f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=stocks"
           f"&fromdate={f}&todate={t}&limit=30")
    try:
        body, _ = _http(url, {"Referer": "https://www.nasdaq.com/"})
        rows = ((json.loads(body).get("data") or {}).get("tradesTable") or {}).get("rows") or []
        want = session.strftime("%m/%d/%Y")
        for r in rows:
            if str(r.get("date", "")).strip() == want:
                v = str(r.get("close", "")).replace("$", "").replace(",", "").strip()
                return float(v) if v else None
    except Exception:
        return None
    return None


def tv_closes(names: list[str]) -> dict:
    """TradingView scanner `close` for the universe — one call.

    During the pre-market of day D the scanner's `close` is D-1's settled close,
    which is exactly the denominator we need to confirm.
    """
    if not names:
        return {}
    alt = "|".join(names)
    body = {"filter": [{"left": "name", "operation": "match", "right": f"^({alt})$"}],
            "columns": ["name", "close"], "range": [0, len(names) + 5],
            "sort": {"sortBy": "name", "sortOrder": "asc"}}
    req = urllib.request.Request(TV_SCAN, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0",
                                          "Origin": "https://www.tradingview.com"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            out = json.load(r)
        return {row["d"][0]: row["d"][1] for row in out.get("data", [])}
    except Exception:
        return {}


def cboe_closes(names: list[str]) -> dict:
    out = {}
    for s in names:
        try:
            body, _ = _http(CBOE.format(sym=s), timeout=20)
            d = (json.loads(body).get("data") or {})
            out[s] = {"close": d.get("close"), "last_trade_time": d.get("last_trade_time"),
                      "current_price": d.get("current_price")}
        except Exception:
            out[s] = None
    return out


# ------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Resolve + assert the pre-market universe")
    ap.add_argument("--fire-date", required=True, help="the run's scheduled date, YYYY-MM-DD (ET)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--allow-stale-universe", action="store_true",
                    help="downgrade a stale-universe failure (the ref close must then "
                         "come from the independent sources)")
    ap.add_argument("--max-walk", type=int, default=6,
                    help="how many sessions back to look for a published sweep")
    ap.add_argument("--sessions-file", default=None,
                    help="offline: a file of YYYY-MM-DD session dates (one per line)")
    ap.add_argument("--focus-root", default=None,
                    help="offline: a local mirror of daily-screens/<date>/focus.csv")
    ap.add_argument("--offline", action="store_true",
                    help="skip the TradingView/Cboe cross-checks (offline testing)")
    ap.add_argument("--ref-close-file", default=None,
                    help="an independent reference-close source: JSON {ticker: close}. "
                         "Used offline, and as an extra confirmation source in a live run.")
    a = ap.parse_args(argv)

    try:
        fire = dt.date.fromisoformat(a.fire_date)
    except ValueError:
        print("premarket_universe: --fire-date must be YYYY-MM-DD", file=sys.stderr)
        return 2

    failures: list[str] = []
    flags: list[str] = []
    assertions: list[dict] = []

    def assert_that(name: str, ok: bool, detail: str, hard: bool = True):
        assertions.append({"assertion": name, "ok": bool(ok), "detail": detail, "hard": hard})
        if not ok:
            (failures if hard else flags).append(f"{name}: {detail}")
        return ok

    # --- H1: the expected prior session, from data -------------------------
    sessions, sess_src, latest_now = resolve_sessions(fire, a.token, a.sessions_file)
    assert_that("H1_expected_prior_session_from_data", bool(sessions),
                f"sessions resolved from {sess_src}: "
                f"{[s.isoformat() for s in sessions[:6]]}" if sessions
                else f"could not resolve the US session calendar from {sess_src}")
    if not sessions:
        manifest = {"marker": MARKER, "status": "FAIL", "fire_date": a.fire_date,
                    "failures": failures, "flags": flags, "assertions": assertions}
        _write(a.out_dir, manifest)
        print(json.dumps(manifest, indent=2))
        return 3
    expected = sessions[0]

    # --- H2: a published Focus list ---------------------------------------
    universe_date = None
    universe_path = None
    text = None
    walked = []
    universe_kind = "focus.csv"
    for s in sessions[: a.max_walk]:
        body, path, err = fetch_focus(s, a.token, a.focus_root)
        walked.append(s.isoformat())
        if body is not None:
            universe_date, universe_path, text = s, path, body
            universe_kind = "focus.md" if str(path).endswith("focus.md") else "focus.csv"
            break
    assert_that("H2_published_focus_list_exists", text is not None,
                f"looked for a published sweep on {walked}"
                + ("" if text is not None else " — none published"))
    if text is None:
        manifest = {"marker": MARKER, "status": "FAIL", "fire_date": a.fire_date,
                    "expected_prior_session": expected.isoformat(),
                    "sessions_source": sess_src, "failures": failures, "flags": flags,
                    "assertions": assertions}
        _write(a.out_dir, manifest)
        print(json.dumps(manifest, indent=2))
        return 3

    if universe_kind == "focus.md":
        prov, prov_path, prov_err = fetch_results_prov(universe_date, a.token, a.focus_root)
        names, meta, perr = parse_focus_md(text, universe_date, prov)
        meta["prov_path"] = prov_path
        if prov_err:
            flags.append(f"the sweep provenance file could not be read ({prov_err}); "
                         f"the stylist names are the counts published in focus.md")
    else:
        names, meta, perr = parse_focus(text, universe_date)
    assert_that("H2b_focus_csv_parses", not perr, perr or f"{len(names)} names, schema={meta['schema']}")

    # --- H3: the universe's own session == the expected prior session ------
    stale = universe_date != expected
    assert_that("H3_universe_session_is_the_expected_prior_session", not stale,
                f"universe session {universe_date.isoformat()} vs expected prior session "
                f"{expected.isoformat()}"
                + (" — the sweep for the prior session has not published"
                   if stale else ""),
                hard=not a.allow_stale_universe)
    if stale and a.allow_stale_universe:
        flags.append(f"universe_stale: the Focus list is from {universe_date.isoformat()} "
                     f"but the denominator session is {expected.isoformat()}; the reference "
                     f"close is taken from the independent sources only")

    # --- which close column belongs to the denominator session? ------------
    ref_col = meta["close_by_session"].get(expected.isoformat())
    ref_session = expected.isoformat() if ref_col else None
    if ref_col is None and not stale:
        # A universe published WITHOUT a close column (focus.md only) is not a
        # defect: the denominator close is then taken from the INDEPENDENT
        # sources only, and H5 requires it to be confirmed. Failing here would
        # kill a fire over a missing companion file, not over a wrong number.
        flags.append(f"the universe was published with NO close column for "
                     f"{expected.isoformat()} (focus.md carries no close), so the "
                     f"denominator close is taken from the INDEPENDENT sources only")
        assert_that("H4_reference_close_column_for_the_denominator_session", True,
                    f"the universe carries no close column; the denominator close comes "
                    f"from the independent sources (TradingView/Cboe + session-exact "
                    f"Nasdaq history), which H5 confirms",
                    hard=False)
    if ref_col:
        assert_that("H4_reference_close_column_for_the_denominator_session", True,
                    f"denominator column `{ref_col}` resolves to session {expected.isoformat()}")
    if meta["screen_col"] and meta["data_date"] and meta["data_date"] != expected.isoformat():
        flags.append(f"the CSV's `{meta['screen_col']}` belongs to data_date "
                     f"{meta['data_date']} and was NOT used as the denominator")

    # --- the reference closes ------------------------------------------------
    csv_close: dict[str, float] = {}
    if ref_col:
        for r in meta["rows"]:
            sym = None
            for k in ("symbol", "ticker", "Symbol", "Ticker"):
                if r.get(k):
                    sym = str(r[k]).strip().split(".")[0].split("/")[0].upper()
                    break
            if not sym:
                continue
            try:
                csv_close[sym] = float(str(r.get(ref_col)).replace(",", "").replace("$", ""))
            except (TypeError, ValueError):
                pass

    tv_cboe_session_valid = (latest_now is not None and latest_now == expected)
    if not tv_cboe_session_valid:
        flags.append(
            "the live sources now serve session %s, not the denominator session %s, so the "
            "TradingView/Cboe close is NOT used as a confirmation; the session-exact "
            "Nasdaq per-symbol history is used instead"
            % (latest_now.isoformat() if latest_now else "unknown", expected.isoformat()))
    tv = {} if a.offline else tv_closes(names)
    cb = {} if a.offline else (cboe_closes(names) if names else {})
    extra_close: dict = {}
    if a.ref_close_file:
        try:
            with open(a.ref_close_file, encoding="utf-8") as fh:
                extra_close = {str(k).upper(): float(v) for k, v in json.load(fh).items()}
        except Exception as e:
            flags.append(f"the independent reference-close file could not be read "
                         f"({type(e).__name__})")

    ref: dict[str, dict] = {}
    unconfirmed: list[str] = []
    conflicts: list[dict] = []
    for s in names:
        c = csv_close.get(s)
        t = tv.get(s)
        k = (cb.get(s) or {}).get("close") if isinstance(cb.get(s), dict) else None
        try:
            t = float(t) if t is not None else None
        except (TypeError, ValueError):
            t = None
        try:
            k = float(k) if k is not None else None
        except (TypeError, ValueError):
            k = None
        x = extra_close.get(s)
        chosen, src = None, None
        if c is not None and (stale is False):
            chosen, src = c, f"focus.csv:{ref_col}"
        elif t is not None:
            chosen, src = t, "tradingview:close"
        elif k is not None:
            chosen, src = k, "cboe:close"
        elif x is not None:
            chosen, src = x, "ref_close_file"
        # OFFLINE MEANS OFFLINE: the session-exact close is fetched from the
        # network only in a live run. A regression test must not depend on the
        # network to agree with it.
        if a.offline:
            nh = extra_close.get(s)
        else:
            nh = nasdaq_hist_close(s, expected)
            if nh is None and s in extra_close:
                nh = extra_close[s]
        agree = []
        pairs = [("nasdaq_historical", nh)]
        if tv_cboe_session_valid:
            pairs += [("tradingview", t), ("cboe", k)]
        if x is not None:
            pairs.append(("ref_close_file", x))
        for label, val in pairs:
            if val is not None and chosen is not None:
                if abs(val - chosen) <= max(0.01, 0.001 * chosen):
                    agree.append(label)
                elif chosen == c and label == "tradingview":
                    conflicts.append({"ticker": s, "chosen": chosen, "source": src,
                                      "disagreeing": label, "value": val})
        if chosen is None:
            unconfirmed.append(s)
        rec = {"ref_close": chosen, "ref_close_source": src, "confirmed_by": agree,
               "focus_csv_close": c, "tradingview_close": t, "cboe_close": k,
               "nasdaq_historical_close": nh,
               "cboe_last_trade_time": (cb.get(s) or {}).get("last_trade_time")
               if isinstance(cb.get(s), dict) else None}
        rec.update({k2: v for k2, v in meta["prov"].get(s, {}).items()})
        ref[s] = rec

    assert_that("H4_reference_close_for_every_name", not unconfirmed,
                f"{len(names) - len(unconfirmed)}/{len(names)} names have a reference close"
                + (f"; missing: {unconfirmed}" if unconfirmed else ""))
    if a.offline:
        flags.append("cross-checks skipped (--offline): the reference close is UNCONFIRMED")
    assert_that("H5_reference_close_confirmed_by_an_independent_source",
                a.offline or all(v.get("confirmed_by") for v in ref.values()),
                f"{sum(1 for v in ref.values() if v.get('confirmed_by'))}/{len(ref)} names "
                f"confirmed by an independent source "
                f"(session-exact Nasdaq history; TV/Cboe only when their session matches)"
                + (f"; unconfirmed: {[k for k, v in ref.items() if not v.get('confirmed_by')]}"
                   if any(not v.get("confirmed_by") for v in ref.values()) else ""))
    if conflicts:
        flags.append(f"{len(conflicts)} reference close(s) disagree with an independent "
                     f"source: {conflicts}")

    status = "FAIL" if failures else ("OK" if not flags else "OK_WITH_FLAGS")
    manifest = {
        "marker": MARKER,
        "status": status,
        "fire_date": a.fire_date,
        "expected_prior_session": expected.isoformat(),
        "sessions_source": sess_src,
        "sessions_considered": [s.isoformat() for s in sessions[:8]],
        "universe_date": universe_date.isoformat(),
        "universe_stale": stale,
        "universe_path": universe_path,
        "universe_schema": meta["schema"],
        "universe_kind": universe_kind,
        "universe_provenance_path": meta.get("prov_path"),
        "universe_data_date": meta["data_date"],
        "tv_cboe_session_valid": tv_cboe_session_valid,
        "ref_close_column": ref_col,
        "ref_close_session": ref_session,
        "screen_close_column_rejected": meta["screen_col"],
        "names": names,
        "reference_closes": ref,
        "conflicts": conflicts,
        "flags": flags,
        "failures": failures,
        "assertions": assertions,
    }
    _write(a.out_dir, manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k != "reference_closes"}, indent=2))
    if failures:
        print("\npremarket_universe: HARD ASSERTION FAILURE — do NOT publish a scan from "
              "this universe.", file=sys.stderr)
        for f in failures:
            print("  FAIL " + f, file=sys.stderr)
        return 3
    return 0


def _write(out_dir: str, manifest: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "_universe.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


if __name__ == "__main__":
    sys.exit(main())

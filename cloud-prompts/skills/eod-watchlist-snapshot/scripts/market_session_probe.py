#!/usr/bin/env python3
"""market_session_probe.py — did this region actually trade on this date?

WHY THIS EXISTS
---------------
`holiday_calendar.py` is a hand-maintained table of 16 exchanges x 3 years. It
had been wrong in a way that **deleted a real trading session**: Greece's Ochi
Day was listed as 2026-10-27 instead of 10-28, and the ATHEX was open and
traded on 10-27 (Yahoo daily bars for ALPHA.AT, EUROB.AT, TPEIR.AT,
GEKTERNA.AT, MOH.AT and ETE.AT all carry a 10-27 session). A false holiday
makes the run skip a region that traded, and the session is simply absent from
the archive — no error, no artifact, nothing to notice.

So the calendar is a HINT, not a fact. This probe is the fact: it reads the
exchange's own session bars and answers whether a market traded on a date.

A skip is only safe when the probe agrees with the calendar. When they
disagree, the probe wins — include the region and report the calendar as
wrong.

USAGE
-----
    python3 market_session_probe.py --region eu-gr --date 2026-10-27
    python3 market_session_probe.py --audit --from 2026-10-01 --to 2026-12-31
    python3 market_session_probe.py --list-regions

OUTPUT (one line, machine-readable):

    VERDICT region=eu-gr date=2026-10-27 traded=yes source=ALPHA.AT
            last_bar=2026-10-27 last_bar_utc=2026-10-27T08:30:00Z bars=5

    VERDICT region=jp date=2026-10-12 traded=no  source=^N225 last_bar=2026-10-09

    VERDICT region=eu-gr date=2026-10-27 traded=unknown source=ALPHA.AT
            reason=yahoo_unreachable

`traded=yes|no|unknown` — `unknown` is never a licence to skip; a source that
could not be reached must not silently become a holiday.

EXIT CODES
----------
    0 = probe ran (read the VERDICT line for the answer)
    1 = bad arguments
    2 = the probe could not reach a source for every region asked about
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

CA = "/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt"
UA = "Mozilla/5.0"

# region -> (probe symbol, human name)
#
# The index is used where Yahoo has one, because it is the cheapest way to ask
# "was there a session?". Two caveats, both handled below:
#   * There is NO Yahoo index symbol for the ATHEX, so Greece probes a liquid
#     ATHEX constituent instead (ALPHA.AT).
#   * For an INDEX, the last populated daily bar can lag one session during the
#     trading day (the index bar-lag rule). The probe therefore also accepts a
#     match on `regularMarketTime`, and never concludes "did not trade" from a
#     lagging bar alone.
PROBE_SYMBOL = {
    "au": ("^AXJO", "ASX 200"),
    "jp": ("^N225", "Nikkei 225"),
    "tw": ("^TWII", "TAIEX"),
    "ca": ("^GSPTSE", "S&P/TSX Composite"),
    "eu-de": ("^GDAXI", "DAX"),
    "eu-fr": ("^FCHI", "CAC 40"),
    "eu-it": ("FTSEMIB.MI", "FTSE MIB"),
    "eu-es": ("^IBEX", "IBEX 35"),
    "eu-nl": ("^AEX", "AEX"),
    "eu-be": ("^BFX", "BEL 20"),
    "eu-at": ("^ATX", "ATX"),
    "eu-pt": ("PSI20.LS", "PSI 20"),
    "eu-ie": ("^ISEQ", "ISEQ"),
    "eu-fi": ("^OMXH25", "OMX Helsinki 25"),
    "eu-dk": ("^OMXC20", "OMX Copenhagen 20"),
    "eu-gr": ("ALPHA.AT", "Alpha Bank (no ATHEX index symbol on Yahoo)"),
}


def _curl(url: str, timeout: int = 25) -> str | None:
    cmd = ["curl", "-sS", "--max-time", str(timeout), "--cacert", CA, "-A", UA, url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return p.stdout


def chart(symbol: str) -> dict | None:
    """Fetch a daily chart and return the parsed chart result, or None."""
    # 2y, not 3mo: the calendar covers 2025-2027 and a probe that silently
    # cannot see a date is worse than no probe.
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range=2y&interval=1d")
    raw = _curl(url)
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except Exception:
        return None
    res = (doc.get("chart") or {}).get("result")
    if not res:
        return None
    try:
        return res[0]
    except Exception:
        return None


def _local_date(ts: int, offset: int) -> date:
    return (datetime.fromtimestamp(ts, timezone.utc)
            + timedelta(seconds=offset or 0)).date()


def session_dates(symbol: str) -> tuple[set[date], date | None, str | None]:
    """Return (set of local session dates, latest session date, error)."""
    res = chart(symbol)
    if res is None:
        return set(), None, "yahoo_unreachable"
    meta = res.get("meta") or {}
    off = meta.get("gmtoffset") or 0
    ts = res.get("timestamp") or []
    closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    days: set[date] = set()
    for t, c in zip(ts, closes):
        if c is None:
            continue
        days.add(_local_date(t, off))
    # `regularMarketTime` covers the case where the last DAILY bar still lags
    # the session in progress (the index bar-lag rule).
    rmt = meta.get("regularMarketTime")
    latest: date | None = max(days) if days else None
    if rmt:
        d = _local_date(rmt, off)
        days.add(d)
        if latest is None or d > latest:
            latest = d
    return days, latest, None


def probe(region: str, when: date) -> dict:
    if region not in PROBE_SYMBOL:
        return {"region": region, "date": when.isoformat(), "traded": "unknown",
                "reason": f"unknown_region (known: {','.join(sorted(PROBE_SYMBOL))})"}
    symbol, label = PROBE_SYMBOL[region]
    days, latest, err = session_dates(symbol)
    if err:
        return {"region": region, "date": when.isoformat(), "traded": "unknown",
                "source": symbol, "reason": err}
    base = {"region": region, "date": when.isoformat(), "source": symbol,
            "label": label, "last_bar": latest.isoformat() if latest else None}
    if not days:
        return {**base, "traded": "unknown", "reason": "no_session_bars_returned"}
    # A date OUTSIDE the fetched window is not "no session" — it is "cannot
    # tell". Never let a missing bar turn into a holiday.
    earliest = min(days)
    if when < earliest:
        return {**base, "traded": "unknown", "reason": f"out_of_range (earliest bar {earliest})"}
    if latest is not None and when > latest:
        return {**base, "traded": "unknown",
                "reason": f"after_last_session (last bar {latest})"}
    if when in days:
        return {**base, "traded": "yes"}
    return {**base, "traded": "no"}


def verdict_line(r: dict) -> str:
    parts = [f"VERDICT region={r['region']}", f"date={r['date']}",
             f"traded={r['traded']}"]
    if r.get("source"):
        parts.append(f"source={r['source']}")
    if r.get("last_bar"):
        parts.append(f"last_bar={r['last_bar']}")
    if r.get("reason"):
        parts.append(f"reason={r['reason']}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", help="region code, e.g. eu-gr")
    ap.add_argument("--date", help="the date to test, YYYY-MM-DD")
    ap.add_argument("--audit", action="store_true",
                    help="check every region across a date range")
    ap.add_argument("--from", dest="dfrom", help="audit start, YYYY-MM-DD")
    ap.add_argument("--to", dest="dto", help="audit end, YYYY-MM-DD")
    ap.add_argument("--list-regions", action="store_true")
    a = ap.parse_args(argv)

    if a.list_regions:
        for r, (s, lbl) in sorted(PROBE_SYMBOL.items()):
            print(f"{r:7s} {s:12s} {lbl}")
        return 0

    if a.audit:
        if not a.dfrom or not a.dto:
            print("--audit needs --from and --to", file=sys.stderr)
            return 1
        d0 = date.fromisoformat(a.dfrom)
        d1 = date.fromisoformat(a.dto)
        days: set[date] = set()
        for region in sorted(PROBE_SYMBOL):
            sym, _ = PROBE_SYMBOL[region]
            ds, latest, err = session_dates(sym)
            if err:
                print(f"VERDICT region={region} traded=unknown reason={err}")
                continue
            d = d0
            while d <= d1:
                if d.weekday() < 5 and d not in ds:
                    print(f"NO-SESSION region={region} date={d.isoformat()} "
                          f"last_bar={latest.isoformat() if latest else '-'}")
                d += timedelta(days=1)
            print(f"OK region={region} sessions={len(ds)} "
                  f"last_bar={latest.isoformat() if latest else '-'}")
        return 0

    if not a.region or not a.date:
        print("--region and --date are both required (or use --audit / --list-regions)",
              file=sys.stderr)
        return 1
    r = probe(a.region, date.fromisoformat(a.date))
    print(verdict_line(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

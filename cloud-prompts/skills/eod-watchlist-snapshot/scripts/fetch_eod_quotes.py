#!/usr/bin/env python3
"""Batch the Yahoo v7/finance/quote snapshot for the US EOD universe.

EOD_SETTLE_V1
EOD_QUOTES_V2

WHAT THIS SUPPLIES
------------------
* `regularMarketPreviousClose` - the DIVIDEND/SPLIT-ADJUSTED prior close, which is what
  `eod_derive.py` needs as `--quote-prev` to tell a reverse split (quote >5% above the
  published prior close) from an ex-distribution (quote >0.5% below it). Without it a split
  cannot be told from a move.
* `trailingPE` - the published trailing P/E (the vendor's `fundamentals_derived_daily` is
  days stale and null for ~40% of the universe).
* `marketCap` - the issuer-level cap, used to CORRECT the vendor's T+1 carrier cap when the
  two readings disagree on the implied share count (see `build_eod_base.py`).

THE COOKIE HANDSHAKE IS A TRAP
------------------------------
`https://fc.yahoo.com` answers **HTTP 404 and still SETS the cookie**. `urllib` raises on the
404 and never reaches `Set-Cookie`, so a urllib handshake reports "no crumb available" and the
whole quote path gets abandoned - while `curl` captures the cookie fine. So the whole exchange
runs through curl here, and the cookie jar is used with `-b` rather than parsed.

Yahoo's availability is PER-EGRESS: query2 and query1 are tried in rotation and a 429 on one
host is a rate limit, never an absence.

CLASS-SHARE SYMBOL FORMS ARE PER VENDOR
---------------------------------------
shibui writes `ABR-P-D`; Yahoo serves `ABR-PD`. A plain-base fallback (`LEN-B` -> `LEN`) would
publish the Class A COMMON line's price under the Class B ticker, so it is never used.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse

MARKER = "EOD_SETTLE_V1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
COOKIE = os.environ.get("EOD_YAHOO_COOKIE", "/workspace/work/yc.txt")
FIELDS = ("symbol,shortName,regularMarketPrice,regularMarketPreviousClose,marketCap,"
          "trailingPE,regularMarketVolume,averageDailyVolume3Month,fullExchangeName,"
          "regularMarketDayHigh,regularMarketDayLow")


def curl(url: str, timeout: int = 40) -> str:
    p = subprocess.run(["curl", "-s", "-b", COOKIE, "-A", UA, "--max-time", str(timeout), url],
                       capture_output=True, text=True)
    return p.stdout or ""


def _probe_quote(host: str, crumb: str) -> dict | None:
    """A crumb is only USABLE if the quote endpoint actually answers with a row.

    The old check (`len(crumb) < 40`, no "html", no "Unauthorized") accepted the literal
    string "Too Many Requests" - 17 characters, no spaces rejected - as a valid crumb, and
    every subsequent query went to that host and came back
    `{"error":{"code":"Unauthorized"}}`. Measured 2026-11-27 (cron #20): the run reported
    `quotes=0/4902` while `query1` served the SAME endpoint with a valid crumb, so the
    quote source (the adjusted prior close, the trailing P/E and the second market-cap
    reading) was silently absent for the whole universe. A crumb is validated by USING it.
    """
    body = curl(f"{host}/v7/finance/quote?symbols=AAPL&fields=symbol,regularMarketPrice"
                f"&crumb={urllib.parse.quote(crumb)}")
    try:
        doc = json.loads(body)
    except Exception:  # noqa: BLE001 - an unparseable body is a failed probe
        return None
    err = (doc.get("quoteResponse") or {}).get("error") or doc.get("error") or {}
    if err:
        return None
    res = (doc.get("quoteResponse") or {}).get("result") or []
    return res[0] if res else None


def handshake() -> tuple[str | None, str | None]:
    os.makedirs(os.path.dirname(COOKIE), exist_ok=True)
    for host in HOSTS:
        subprocess.run(["curl", "-s", "-c", COOKIE, "-A", UA, "--max-time", "25",
                        "https://fc.yahoo.com"], capture_output=True, text=True)
        crumb = curl(f"{host}/v1/test/getcrumb").strip()
        if not crumb or len(crumb) >= 40 or "html" in crumb.lower() \
                or "Unauthorized" in crumb or "Too Many" in crumb \
                or " " in crumb.strip():
            print(f"  handshake {host}: crumb rejected=[{crumb[:60]}]", file=sys.stderr)
            continue
        probe = _probe_quote(host, crumb)
        if probe is None:
            print(f"  handshake {host}: crumb=[{crumb[:20]}...] but the quote endpoint "
                  f"refused it - this host is gated for this egress", file=sys.stderr)
            continue
        return host, crumb
    return None, None


def yahoo_form(t: str) -> str:
    t = t.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        return f"{base}-{rest.replace('-', '')}"
    return t


def main() -> int:
    symbols = []
    with open(sys.argv[1], newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            t = (row.get("ticker") or "").strip()
            if t:
                symbols.append(t)
    out_path = sys.argv[2]
    batch = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    host, crumb = handshake()
    if not crumb:
        print("NO_CRUMB - the quote source is unavailable; the run continues without a "
              "quote-service prior close, so splits cannot be told from moves", file=sys.stderr)
        json.dump({}, open(out_path, "w"))
        return 1
    print(f"handshake ok host={host} crumb_len={len(crumb)}", flush=True)

    out: dict[str, dict] = {}
    # the output is keyed by the SHIBUI ticker (the pipeline's canonical key), because the
    # vendor's class lines (`ABR-P-D`) and Yahoo's (`ABR-PD`) are different strings
    yahoo_to_ticker = {}
    for s in symbols:
        yahoo_to_ticker.setdefault(yahoo_form(s), s)
    t0 = time.time()
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        syms = ",".join(yahoo_form(s) for s in chunk)
        url = (f"{host}/v7/finance/quote?symbols={urllib.parse.quote(syms)}"
               f"&fields={FIELDS}&crumb={urllib.parse.quote(crumb)}")
        body = curl(url)
        got_rows = []
        try:
            doc = json.loads(body)
            err = (doc.get("quoteResponse") or {}).get("error") or doc.get("error") or {}
            if err:
                raise RuntimeError(f"quote error {json.dumps(err)[:120]}")
            got_rows = ((doc.get("quoteResponse") or {}).get("result") or [])
        except Exception as e:  # noqa: BLE001 - a failed batch is a data fact
            print(f"  batch {i} failed: {type(e).__name__}: {e} :: {body[:120]}", file=sys.stderr)
        if not got_rows:
            # A mid-run refusal (a gate that engaged after the handshake, a 429, an empty
            # body) must not silently drop the REST of the universe. Re-handshake on the
            # other host and retry the same chunk once.
            alt = [h for h in HOSTS if h != host]
            for h2 in alt:
                subprocess.run(["curl", "-s", "-c", COOKIE, "-A", UA, "--max-time", "25",
                                "https://fc.yahoo.com"], capture_output=True, text=True)
                c2 = curl(f"{h2}/v1/test/getcrumb").strip()
                if not c2 or len(c2) >= 40 or " " in c2.strip() \
                        or "Too Many" in c2 or "Unauthorized" in c2:
                    continue
                if _probe_quote(h2, c2) is None:
                    continue
                host, crumb = h2, c2
                url = (f"{host}/v7/finance/quote?symbols={urllib.parse.quote(syms)}"
                       f"&fields={FIELDS}&crumb={urllib.parse.quote(crumb)}")
                body = curl(url)
                try:
                    doc = json.loads(body)
                    got_rows = ((doc.get("quoteResponse") or {}).get("result") or [])
                except Exception:  # noqa: BLE001
                    got_rows = []
                if got_rows:
                    print(f"  batch {i}: rotated to {host} and recovered", file=sys.stderr)
                    break
            if not got_rows:
                print(f"  batch {i}: unrecoverable, {len(chunk)} symbols not quoted",
                      file=sys.stderr)
        for r in got_rows:
            key = yahoo_to_ticker.get(r["symbol"], r["symbol"])
            # Yahoo's v7 quote serves the day range as `regularMarketDayHigh/Low`; the
            # builder reads `dayHigh`/`dayLow`. Without this alias the Yahoo range
            # candidate was ALWAYS empty (the field names in the request were wrong), so
            # a row whose close no other candidate bracketed lost its range for no reason.
            if r.get("dayHigh") is None and r.get("regularMarketDayHigh") is not None:
                r["dayHigh"] = r.get("regularMarketDayHigh")
                r["dayLow"] = r.get("regularMarketDayLow")
            out[key] = r
        if (i // batch) % 5 == 0:
            print(f"  {i+len(chunk)}/{len(symbols)} got={len(out)} {time.time()-t0:.0f}s", flush=True)
    json.dump(out, open(out_path, "w"))
    print(f"done quotes={len(out)}/{len(symbols)} in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

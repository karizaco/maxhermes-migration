#!/usr/bin/env python3
"""Patch the session bar's close with the venue's settled print.

EOD_DERIVE_V2
EOD_BASE_V1

The DERIVED columns (pct_vs_sma_50/200, atr_pct, pct_from_52w_high/low, gap_pct) are
computed from the price history. If the published close is the venue's print and the
history's session bar close is Yahoo's pre-auction print, those columns would sit on a
different price than the row publishes. Patching the session bar's close keeps ONE price
per row: the venue's close of record.

Only the session bar's close is touched. The bar's high/low and volume stay the series'
own (they are the series measures), and the flag RANGE_ADJUSTED then correctly marks the
rows whose daily bar did not bracket the published close.
"""
from __future__ import annotations
import json, sys, time

INP = sys.argv[1]
NAS = sys.argv[2]
OUT = sys.argv[3]
SESSION = sys.argv[4] if len(sys.argv) > 4 else "2026-11-11"

nas = json.load(open(NAS))
patched = 0
n = 0
with open(OUT, "w") as out:
    for line in open(INP):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        t = rec.get("ticker", "")
        bars = rec.get("bars") or []
        newbars = []
        hit = False
        for b in bars:
            if len(b) >= 5 and time.strftime("%Y-%m-%d", time.gmtime(int(b[0]))) == SESSION:
                c = nas.get(t, {}).get("close")
                if c:
                    nb = list(b)
                    nb[4] = float(c)
                    b = nb
                    hit = True
                    patched += 1
            newbars.append(b)
        rec["bars"] = newbars
        n += 1
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
print(f"session closes patched to the venue's print: {patched} of {n} records")

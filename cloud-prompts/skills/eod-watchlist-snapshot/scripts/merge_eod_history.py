#!/usr/bin/env python3
"""Merge the two history passes — the LATER pass wins the session bar.

EOD_DERIVE_V2
EOD_BASE_V1

The close keeps drifting for ~10-40 minutes after the volume freezes, so one early pull
publishes hundreds of closes that are not the official close. Bars are keyed by timestamp,
so the merge keeps the earlier bars from either pass and lets the later pass overwrite.
"""
from __future__ import annotations
import json, sys

P1 = sys.argv[1]
P2 = sys.argv[2]
OUT = sys.argv[3]


def load(path):
    out = {}
    try:
        fh = open(path)
    except FileNotFoundError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[rec.get("ticker", "")] = rec
    return out


p1, p2 = load(P1), load(P2)
merged = {}
session_close_changed = 0
for t, rec2 in p2.items():
    if t not in p1:
        merged[t] = rec2
        continue
    rec1 = p1[t]
    bars2 = {int(b[0]): b for b in (rec2.get("bars") or []) if len(b) >= 5 and b[4] is not None}
    bars1 = {int(b[0]): b for b in (rec1.get("bars") or []) if len(b) >= 5 and b[4] is not None}
    c1 = None
    c2 = None
    for b in rec1.get("bars") or []:
        c1 = b[4]
    for b in rec2.get("bars") or []:
        c2 = b[4]
    if c1 is not None and c2 is not None and abs(float(c1) - float(c2)) > 1e-9:
        session_close_changed += 1
    allbars = sorted(bars1.keys() | bars2.keys())
    bars = [bars2.get(k) or bars1.get(k) for k in allbars]
    merged[t] = {"ticker": t, "yahoo_symbol": rec2.get("yahoo_symbol", rec1.get("yahoo_symbol")),
                 "status": rec2.get("status"), "bars": bars}

with open(OUT, "w") as fh:
    for t in sorted(merged):
        fh.write(json.dumps(merged[t], separators=(",", ":")) + "\n")

print(f"merged={len(merged)} p1={len(p1)} p2={len(p2)} session_close_changed={session_close_changed}")

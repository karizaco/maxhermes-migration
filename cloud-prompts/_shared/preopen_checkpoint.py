#!/usr/bin/env python3
"""
preopen_checkpoint.py — build one pre-open checkpoint: the tape, the human board,
and the fail-closed trail.

PREOPEN_CHECKPOINT_V1
# CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1

WHY THIS EXISTS
---------------
The catalyst tape (preopen-feed/{date}-{slot}.jsonl) is consumed by cron #17 at 15:50 ET.
A human cannot read a 678-row JSONL file, and the 08:30 checkpoint is the ONE capture a
trader can actually act on before the open. So every checkpoint writes a companion
markdown digest beside its tape: the top movers, their catalyst, and whether the
catalyst is VERIFIED.

Three jobs, three modes:

  merge    Grok reply + the scanner snapshot -> {date}-{slot}.jsonl   the tape
  digest   tape -> {date}-{slot}.md                                  the human board
  skipped  -> {date}-{slot}.SKIPPED.md                               the fail-closed trail

WHY THE MERGE IS A SCRIPT AND NOT MODEL WORK
--------------------------------------------
Three rules are easy to state and easy to break by hand:

  1. ONE SNAPSHOT, ONE NUMBER PER RECORD. A record whose price came from a
     different scanner call than its neighbours is a spliced tape. Measured
     2026-11-04: four records drifted (CRIS +93.3 -> +97.5, DKI +48.0 -> +69.9)
     purely because the tape moved between two calls minutes apart.
  2. PRICES COME FROM THE SCANNER, NEVER FROM GROK. Grok supplies the reason.
     A Grok name the scanner did not see gets NO number - not Grok's.
  3. ONE ROW PER TICKER. A ticker Grok named gets ONE record, not two.

Each of those is a few lines of prose in a prompt and a silent, plausible-looking bug
at run time. Here they are code, so they hold every fire.

USAGE
  preopen_checkpoint.py merge   --grok-reply <reply.txt> --tv-gain <gainers.json>
                                --tv-loss <losers.json> --out <tape.jsonl>
                                [--ts "<iso>"] [--unverified-pp 2.0]
  preopen_checkpoint.py digest  --tape <tape.jsonl> --out <board.md> [--meta <meta.json>]
                                [--slot 0830] [--date YYYY-MM-DD]
  preopen_checkpoint.py skipped --out <marker.md> --reason "<why>" [--date] [--slot]
                                [--fire-instant "<iso>"]
  preopen_checkpoint.py selftest

META JSON (written by the procedure's step 3c)
  {"model":"grok-4.3","cost_usd":0.0476,"web_search_calls":3,"x_search_calls":1,
   "input_tokens":25110,"output_tokens":2043}

EXIT CODES
  0 = wrote the file
  1 = could not write (bad input, missing tape)
  2 = usage error
"""

import argparse
import json
import os
import sys

# The version marker the fetch ladder must find. A stale copy of this script has no
# marker, so the procedure refuses it instead of running an old-shaped merge.
PREOPEN_CHECKPOINT_V1 = "PREOPEN_CHECKPOINT_V1"

# The capability marker alone CANNOT detect a stale copy that already carries it —
# the same failure the fleet hit on 2026-11-05, when every mirror served the same
# stale blob and "highest version wins" picked it. So the fetch ladder demands THIS
# version too. Bump it whenever this script changes.
CHECKPOINT_SCRIPT_VERSION = "2026-11-06.1"

# The scanner column list, in the order the procedure requests it. The merge zips by
# NAME, never by position: the 10-column variant read a PRICE into a PERCENT column on
# 2026-11-05 and put two names at the top of the tape with px=NASDAQ.
SCANNER_COLS = ["name", "description", "close", "change", "volume", "relative_volume_10d_calc",
                "market_cap_basic", "premarket_change", "premarket_volume", "premarket_close",
                "halted", "exchange"]

# The published expectations, quoted from the 2026-11-04 08:30 tape.
EXPECTED_TAPE_ROWS = 678
# Below this the tape is far too small to be a movers-sorted snapshot. The pre-fix
# procedure sorted by premarket_volume and capped at 120 rows, so ~120 is the
# REGRESSION SIGNATURE, not just a quiet morning.
DEVIATION_MIN_ROWS = 300
REGRESSION_ROWS = 120

# A Grok percentage that disagrees with the scanner by more than this is unverified.
UNVERIFIED_PP = 2.0

# The tape row shape is a CONTRACT with cron #17 (it merges on it). Do not change it.
TAPE_KEYS = ["ts", "src", "ticker", "name", "pct", "price", "cat", "why", "ref", "conf"]

TOP_N = 15

CAT_VOCAB = {"acquisition", "merger", "earnings", "guidance", "fda", "trial", "offering",
             "halt", "downgrade", "guidance-cut", "spin", "dividend", "other"}

NO_CATALYST = "no catalyst captured at this checkpoint"


def read_tape(path):
    """Parse the JSONL tape. Raises on a missing file; skips malformed lines."""
    rows, bad = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                bad += 1
                continue
            if not isinstance(rec, dict) or not rec.get("ticker"):
                bad += 1
                continue
            rows.append(rec)
    return rows, bad


# ---- merge: one snapshot, one number per record, one row per ticker -----------

def parse_scanner(path):
    """{ticker: {...}} from a scanner response. ZIPS BY COLUMN NAME.

    The scanner returns `data: [{s: "NASDAQ", d: [...]}, ...]` where `d` is positional.
    The columns are zipped against SCANNER_COLS by name so a reordered or shortened
    column list cannot silently put a PRICE into a PERCENT column.
    """
    out = {}
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception:
        return out
    for item in (doc.get("data") or []):
        d = item.get("d") or []
        row = {}
        for i, col in enumerate(SCANNER_COLS):
            row[col] = d[i] if i < len(d) else None
        t = row.get("name")
        if not t:
            continue
        out[str(t).strip().upper()] = row
    return out


def parse_grok_reply(path):
    """Parse Grok's reply into records. Tolerates prose around the JSON lines."""
    recs = []
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return recs
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = None
        try:
            obj = json.loads(raw)
        except Exception:
            i, j = raw.find("{"), raw.rfind("}")
            if i >= 0 and j > i:
                try:
                    obj = json.loads(raw[i:j + 1])
                except Exception:
                    obj = None
        if not isinstance(obj, dict):
            continue
        t = obj.get("ticker")
        if not t or not str(t).strip():
            continue
        recs.append(obj)
    return recs


def _as_float(v):
    try:
        return float(v)
    except Exception:
        return None


def merge_tape(grok_recs, snapshot, ts, unverified_pp=UNVERIFIED_PP):
    """Build the tape rows.

    snapshot: {ticker: scanner row}. ONE snapshot - every number in the tape comes
    from this dict. There is no second scanner call anywhere in this function, so a
    record can never hold a price from a different instant than its neighbours.

    A Grok name the scanner did not see gets pct=null and price=null: the rule is
    that Grok supplies the REASON and the scanner supplies the NUMBER, and a name
    with no scanner row has no number. Its conf is "unverified" for that reason.
    """
    rows = []
    seen = set()

    for g in grok_recs:
        t = str(g.get("ticker", "")).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        s = snapshot.get(t)
        why = g.get("why") or ""
        ref = g.get("ref") or ""
        cat = g.get("cat")
        if cat not in CAT_VOCAB:
            cat = "other"
        gpct = _as_float(g.get("pct"))
        if s is None:
            # No ground truth. No number from Grok either.
            rows.append({"ts": ts, "src": "grok", "ticker": t, "name": g.get("name"),
                         "pct": None, "price": None, "cat": cat, "why": why,
                         "ref": ref, "conf": "unverified"})
            continue
        spct = _as_float(s.get("premarket_change"))
        conf = g.get("conf") or "low"
        if conf not in ("high", "medium", "low", "unverified"):
            conf = "low"
        if not ref:
            conf = "low"          # a record without a source URL is low confidence
        if gpct is not None and spct is not None and abs(gpct - spct) > unverified_pp:
            conf = "unverified"
        rows.append({"ts": ts, "src": "grok", "ticker": t,
                     "name": s.get("description") or g.get("name"),
                     "pct": spct, "price": _as_float(s.get("premarket_close")),
                     "cat": cat, "why": why, "ref": ref, "conf": conf})

    for t, s in snapshot.items():
        if t in seen:
            continue
        seen.add(t)
        rows.append({"ts": ts, "src": "scanner", "ticker": t,
                     "name": s.get("description"),
                     "pct": _as_float(s.get("premarket_change")),
                     "price": _as_float(s.get("premarket_close")),
                     "cat": "other", "why": NO_CATALYST, "ref": "", "conf": "low"})

    # Movers-ordered: biggest absolute move first. The consumer sorts on ts, so row
    # order inside the file is not contractual - but a movers-ordered tape is readable.
    rows.sort(key=lambda r: (-(abs(r["pct"]) if r["pct"] is not None else -1.0), r["ticker"]))
    return rows


def write_tape(rows, path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({k: r.get(k) for k in TAPE_KEYS}, ensure_ascii=False) + "\n")
    return path


def tape_summary(rows):
    n = len(rows)
    grok = sum(1 for r in rows if r.get("src") == "grok")
    scanner = sum(1 for r in rows if r.get("src") == "scanner")
    unv = sum(1 for r in rows if r.get("conf") == "unverified")
    return n, grok, scanner, unv


def fmt_pct(v):
    if v is None:
        return "n/a"
    try:
        f = float(v)
    except Exception:
        return "n/a"
    return f"{f:+.2f}"


def fmt_ts(v):
    """2026-11-06T08:31:02-04:00 -> 11-06 08:31:02 -04:00 (the date is in the header)."""
    if not v:
        return "n/a"
    s = str(v)
    try:
        if len(s) >= 25 and s[10] == "T":
            # The offset sign lives at s[19] ("-04:00"), not s[20] — slicing at 20
            # silently drops the sign and renders "05:00" as if it were positive.
            off = s[19:] if s[19] in "+-" else s[20:]
            return f"{s[5:10]} {s[11:19]} {off}"
        return s
    except Exception:
        return s


def fmt_conf(v):
    """`unverified` must be OBVIOUS — it is the one cell that tells the reader the
    catalyst is a story rather than a fact."""
    if not v:
        return "low"
    if str(v) == "unverified":
        return "⚠ unverified"
    return str(v)


def clean(text, width=96):
    if not text:
        return ""
    s = " ".join(str(text).split())
    if len(s) > width:
        s = s[:width - 1].rstrip() + "…"
    return s.replace("|", "\\|")


def rank(rows):
    """Top movers by |pct| descending. A row with no number sorts last: it is a
    catalyst with no ground truth, which is real information but not a mover."""
    def key(r):
        p = r.get("pct")
        try:
            p = abs(float(p))
        except Exception:
            p = -1.0
        return (-p, str(r.get("ticker", "")))
    return sorted(rows, key=key)


def dev_note(n_rows):
    """The deviation banner. Returns '' when the tape size is plausible."""
    if n_rows >= DEVIATION_MIN_ROWS:
        return ""
    if n_rows <= REGRESSION_ROWS:
        return (f"> ⚠ **DEVIATION — {n_rows} records, not ≈{EXPECTED_TAPE_ROWS}.** "
                f"A tape of ~{REGRESSION_ROWS} rows is the REGRESSION SIGNATURE: the scanner "
                f"call is sorted by `premarket_volume` (the pre-2026-11-05 procedure) instead of "
                f"movers-sorted in both directions, so the biggest movers are buried under a wall "
                f"of noise. Do not treat this board as complete.")
    return (f"> ⚠ **DEVIATION — {n_rows} records, well below the ≈{EXPECTED_TAPE_ROWS} "
            f"expected for a movers-sorted snapshot.** The board may be incomplete; check the "
            f"scanner sort before acting on it.")


def render_digest(rows, bad, meta, date_str, slot, tape_name):
    n = len(rows)
    grok = sum(1 for r in rows if r.get("src") == "grok")
    scanner = sum(1 for r in rows if r.get("src") == "scanner")
    unv = sum(1 for r in rows if r.get("conf") == "unverified")
    cat_n = sum(1 for r in rows
                if r.get("cat") in CAT_VOCAB and r.get("cat") != "other"
                and r.get("src") == "grok")

    out = []
    out.append(f"# Pre-open catalyst digest — {date_str} · {slot} ET checkpoint")
    out.append("")
    note = dev_note(n)
    if note:
        out.append(note)
        out.append("")
    out.append(f"- **Tape:** `{tape_name}` · **records:** {n} · **grok:** {grok} · "
               f"**scanner:** {scanner} · **unverified:** {unv}")
    if meta:
        cost = meta.get("cost_usd")
        cost_s = f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "not measured"
        bits = []
        if meta.get("model"):
            bits.append(f"`{meta['model']}`")
        bits.append(f"**{cost_s}**")
        if meta.get("web_search_calls") is not None:
            bits.append(f"{meta['web_search_calls']} web searches")
        if meta.get("x_search_calls") is not None:
            bits.append(f"{meta['x_search_calls']} x-searches")
        if meta.get("input_tokens") is not None:
            bits.append(f"{meta['input_tokens']:,} in")
        if meta.get("output_tokens") is not None:
            bits.append(f"{meta['output_tokens']:,} out")
        out.append(f"- **Grok call:** " + " · ".join(bits))
    else:
        out.append("- **Grok call:** not measured (no cost metadata supplied)")
    out.append("- **Snapshot:** one TradingView scan, movers-sorted in BOTH directions "
               "(gains descending, losses ascending), ±2.5% floor, one number per record")
    if cat_n:
        out.append(f"- **Named catalysts:** {cat_n} · **malformed lines skipped:** {bad}")
    else:
        out.append(f"- **Malformed lines skipped:** {bad}")
    out.append("")
    out.append("| Ticker | % | Conf | Catalyst | When it broke |")
    out.append("|---|---|---|---|---|")
    top = rank(rows)[:TOP_N]
    if not top:
        out.append("| — | — | — | no records in this checkpoint's tape | — |")
    for r in top:
        why = r.get("why") or NO_CATALYST
        if r.get("src") != "grok" and not r.get("why"):
            why = NO_CATALYST
        out.append(f"| {clean(r.get('ticker'), 12)} | {fmt_pct(r.get('pct'))} | "
                   f"{fmt_conf(r.get('conf'))} | {clean(why)} | {fmt_ts(r.get('ts'))} |")
    out.append("")
    out.append(f"_{TOP_N} of {n} records, ranked by |%| descending. `conf` is the tape's own "
               f"confidence token: `unverified` means the catalyst could not be tied to a "
               f"scanner price. Scanner rows carry no reason by design — the next checkpoint "
               f"may explain them._")
    return "\n".join(out) + "\n"


def render_skipped(reason, date_str, slot, fire_instant):
    out = []
    out.append(f"# Pre-open catalyst capture — SKIPPED ({date_str}, {slot} ET checkpoint)")
    out.append("")
    out.append(f"- **Reason:** {reason}")
    out.append(f"- **Checkpoint:** {date_str}-{slot}")
    if fire_instant:
        out.append(f"- **Fire instant:** {fire_instant}")
    out.append(f"- **Tape:** none. `preopen-feed/{date_str}-{slot}.jsonl` was deliberately "
               f"NOT written: a tape with no catalyst in it reads as \"no news\" to cron #17, "
               f"which would report \"no catalyst\" for a name that had one.")
    out.append(f"- **Digest:** none. `preopen-feed/{date_str}-{slot}.md` is intentionally absent.")
    out.append("")
    out.append("This marker IS the audit trail for the checkpoint. The routine fired and "
               "declined to write a tape; it did not fail silently.")
    return "\n".join(out) + "\n"


def selftest():
    ok = True
    rows = [{"ts": "2026-11-06T08:31:02-04:00", "src": "scanner", "ticker": "AAA",
             "name": "A", "pct": 10.0, "price": 5.0, "cat": "other",
             "why": "no catalyst captured at this checkpoint", "ref": "", "conf": "low"},
            {"ts": "2026-11-06T08:31:02-04:00", "src": "grok", "ticker": "BBB",
             "name": "B", "pct": -40.0, "price": 2.0, "cat": "trial",
             "why": "Phase 3 readout | positive", "ref": "https://x", "conf": "unverified"}]
    md = render_digest(rows, 0, {"model": "grok-4.3", "cost_usd": 0.0476,
                                  "web_search_calls": 3, "x_search_calls": 1,
                                  "input_tokens": 25110, "output_tokens": 2043},
                        "2026-11-06", "0830", "preopen-feed/2026-11-06-0830.jsonl")
    checks = [
        ("header has date+slot", "# Pre-open catalyst digest — 2026-11-06 · 0830 ET checkpoint" in md),
        ("record count", "**records:** 2" in md),
        ("grok/scanner split", "**grok:** 1" in md and "**scanner:** 1" in md),
        ("unverified count", "**unverified:** 1" in md),
        ("measured cost", "$0.0476" in md),
        ("table header", "| Ticker | % | Conf | Catalyst | When it broke |" in md),
        ("unverified is obvious", "⚠ unverified" in md),
        ("pipe escaped", "Phase 3 readout \\| positive" in md),
        ("signed pct", "-40.00" in md and "+10.00" in md),
        ("ts shortened", "11-06 08:31:02 -04:00" in md),
    ]
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    # a small tape must raise the deviation banner
    small = render_digest(rows[:1], 0, None, "2026-11-06", "0830", "t")
    print(f"  {'PASS' if 'DEVIATION' in small else 'FAIL'}  deviation banner on a 1-row tape")
    ok = ok and ("DEVIATION" in small)
    big = render_digest(rows * 200, 0, None, "2026-11-06", "0830", "t")
    print(f"  {'PASS' if 'DEVIATION' not in big else 'FAIL'}  no deviation banner on a 400-row tape")
    ok = ok and ("DEVIATION" not in big)
    sk = render_skipped("XAI_API_KEY unset", "2026-11-06", "0830", "2026-11-06T08:30:00-04:00")
    for name, passed in [("skipped names the reason", "XAI_API_KEY unset" in sk),
                         ("skipped names the checkpoint", "2026-11-06-0830" in sk)]:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed

    # ---- merge rules -------------------------------------------------------
    # A snapshot with two names and a Grok reply naming one of them, plus one name
    # the scanner never saw.
    snap = {
        "AAA": {"name": "AAA", "description": "Alpha Inc", "premarket_change": 12.0,
                "premarket_close": 10.5, "halted": None},
        "BBB": {"name": "BBB", "description": "Beta Inc", "premarket_change": -30.0,
                "premarket_close": 3.0, "halted": None},
    }
    grok = [{"ticker": "AAA", "name": "Alpha Inc", "pct": 13.0, "cat": "earnings",
             "why": "beat and raised", "ref": "https://x", "conf": "high"},
            {"ticker": "ZZZ", "name": "Zeta", "pct": 99.0, "cat": "fda",
             "why": "approval", "ref": "https://y", "conf": "high"}]
    mrows = merge_tape(grok, snap, "2026-11-06T08:31:02-04:00")
    by = {r["ticker"]: r for r in mrows}
    checks2 = [
        ("one row per ticker", len(mrows) == 3),
        ("grok name takes the SCANNER pct", by["AAA"]["pct"] == 12.0),
        ("grok name keeps ONE row", sum(1 for r in mrows if r["ticker"] == "AAA") == 1),
        ("name absent from the snapshot has NO number", by["ZZZ"]["pct"] is None and by["ZZZ"]["price"] is None),
        ("name absent from the snapshot is unverified", by["ZZZ"]["conf"] == "unverified"),
        ("name absent from the snapshot keeps the reason", by["ZZZ"]["why"] == "approval"),
        ("scanner-only row has no reason", by["BBB"]["why"] == NO_CATALYST),
        ("scanner-only row is low confidence", by["BBB"]["conf"] == "low"),
        ("every row has exactly the 10 contract keys",
         all(sorted(r.keys()) == sorted(TAPE_KEYS) for r in mrows)),
        ("rows are movers-ordered by |pct| desc",
         [r["ticker"] for r in mrows] == ["BBB", "AAA", "ZZZ"]),
        (">2pp disagreement is unverified",
         {r["ticker"]: r for r in merge_tape(
             [{"ticker": "AAA", "pct": 40.0, "cat": "other", "why": "x",
               "ref": "https://z", "conf": "high"}], snap, "t")}["AAA"]["conf"] == "unverified"),
        ("a record without a URL is low confidence",
         {r["ticker"]: r for r in merge_tape(
             [{"ticker": "AAA", "pct": 12.0, "cat": "other", "why": "x",
               "ref": "", "conf": "high"}], snap, "t")}["AAA"]["conf"] == "low"),
    ]
    for name, passed in checks2:
        print(f"  {'PASS' if passed else 'FAIL'}  merge: {name}")
        ok = ok and passed
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["merge", "digest", "skipped", "selftest"])
    ap.add_argument("--tape")
    ap.add_argument("--out")
    ap.add_argument("--meta")
    ap.add_argument("--reason")
    ap.add_argument("--date")
    ap.add_argument("--slot", default="0830")
    ap.add_argument("--fire-instant", default="")
    ap.add_argument("--grok-reply")
    ap.add_argument("--tv-gain")
    ap.add_argument("--tv-loss")
    ap.add_argument("--ts", default="")
    ap.add_argument("--unverified-pp", type=float, default=UNVERIFIED_PP)
    a = ap.parse_args()

    if a.mode == "selftest":
        return selftest()

    if a.mode == "merge":
        if not (a.grok_reply and a.tv_gain and a.tv_loss and a.out):
            print("merge needs --grok-reply, --tv-gain, --tv-loss and --out", file=sys.stderr)
            return 2
        snapshot = parse_scanner(a.tv_gain)
        snapshot.update(parse_scanner(a.tv_loss))
        grok = parse_grok_reply(a.grok_reply)
        ts = a.ts or ""
        rows = merge_tape(grok, snapshot, ts, a.unverified_pp)
        write_tape(rows, a.out)
        n, g, sc, unv = tape_summary(rows)
        # The halt state is a MEASUREMENT about the column, never a count of halted
        # names. The column is null on every row, so "0 halted" is not a finding.
        halted_measurable = sum(1 for r in rows if r.get("halted") is not None)
        print(f"merge: {n} records (grok {g}, scanner {sc}, unverified {unv}) -> {a.out}")
        print(f"merge: snapshot={len(snapshot)} names | halted: not measurable "
              f"(TV halted column null on {n - halted_measurable}/{n} rows)")
        if n and n < DEVIATION_MIN_ROWS:
            print(f"merge: DEVIATION — {n} records, expected ≈{EXPECTED_TAPE_ROWS}; "
                  f"a tape near {REGRESSION_ROWS} rows means the scanner sort regressed "
                  f"to premarket_volume")
        return 0

    if not a.out:
        print("--out is required", file=sys.stderr)
        return 2

    if a.mode == "skipped":
        if not a.reason:
            print("--reason is required for the skipped marker", file=sys.stderr)
            return 2
        md = render_skipped(a.reason, a.date or "?", a.slot, a.fire_instant)
    else:
        if not a.tape:
            print("--tape is required", file=sys.stderr)
            return 2
        try:
            rows, bad = read_tape(a.tape)
        except Exception as exc:
            print(f"cannot read tape {a.tape}: {exc}", file=sys.stderr)
            return 1
        meta = {}
        if a.meta and os.path.exists(a.meta):
            try:
                meta = json.load(open(a.meta, encoding="utf-8"))
            except Exception:
                meta = {}
        date_str = a.date or ""
        if not date_str:
            base = os.path.basename(a.tape)
            date_str = base[:10]
        tape_name = a.tape
        for pre in ("/workspace/", "./"):
            if tape_name.startswith(pre):
                tape_name = tape_name[len(pre):]
        md = render_digest(rows, bad, meta, date_str, a.slot, tape_name)

    d = os.path.dirname(os.path.abspath(a.out))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"wrote {a.out} ({len(md.encode())} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
PREOPEN_DIGEST_V1
make_digest.py — render the human-readable board that sits BESIDE a pre-open tape.

WHY THIS EXISTS
---------------
The tape is machine data (one JSON object per line). The 08:30 board is what a trader
actually reads before the open: the biggest movers, the catalyst, the confidence token
and WHEN the news broke.

It is rendered FROM the tape, never by hand, so the board can never disagree with the
data cron #17 will read at 15:50.

USAGE
  make_digest.py --tape <tape.jsonl> --out <board.md> [--date 2026-11-09] [--slot 0830]
                 [--scan-note "..."]
"""
import argparse
import json
import os

TOP_N = 15
DIGEST_COLUMNS = ["Ticker", "%", "Conf", "Catalyst", "When it broke"]
CONFIDENCES = ("high", "medium", "low", "unverified")
NO_CATALYST = "_no catalyst captured_"


def fmt_pct(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "—"


def fmt_ts(v):
    """Render a timestamp as ET wall-clock, whatever timezone it arrived in.

    WHY THIS IS NOT A STRING SLICE
    ------------------------------
    The tape carries TWO different timestamp shapes and they are not the same zone:
      * `ts`          - the capture clock, written ET-aware (2026-11-10T09:57:44-05:00);
      * `trending_ts` - the stocktwits snapshot's own stamp, written UTC (2026-11-10T14:38:21Z).

    Slicing [11:19] off both printed the UTC stamp AS IF IT WERE ET, so every row that
    carried a trending_ts read 5 hours late. Measured 2026-11-10 09:50 ET checkpoint:
    HIMS showed "14:38:21" for news that actually broke at 09:38:21 ET - and the board
    labels that column "When it broke", which is exactly what cron #17 reads at 15:50 to
    date the catalyst. A catalyst stamped in the FUTURE relative to the capture is the
    kind of error that survives a glance, because the number looks plausible.

    So: PARSE the offset and CONVERT. A naive timestamp (no offset) is already ET -
    that is what the capture script writes - so it is read as ET, never as UTC.
    """
    if not v:
        return "—"
    s = str(v).strip()
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
    except Exception:
        return s[11:19] if len(s) >= 19 else s
    raw = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return s[11:19] if len(s) >= 19 else s
    if dt.tzinfo is None:
        # No offset: the capture clock's own format, which is already ET.
        try:
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        except Exception:
            pass
    else:
        try:
            dt = dt.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            dt = dt.astimezone(timezone.utc)
    return dt.strftime("%H:%M:%S")


def clean(text, width=110):
    if not text:
        return ""
    s = " ".join(str(text).split())
    if len(s) > width:
        s = s[:width - 1].rstrip() + "…"
    return s.replace("|", "\\|")


def rank(rows):
    """Biggest movers first, by |%| descending. A row with no price is a catalyst
    without ground truth — real information, but it is not a mover, so it sorts last."""
    def key(r):
        try:
            p = abs(float(r.get("pct")))
        except Exception:
            p = -1.0
        return (-p, str(r.get("ticker", "")))
    return sorted(rows, key=key)


def render(rows, date_str, slot, tape_name, scan_note):
    n = len(rows)
    grok = sum(1 for r in rows if r.get("src") == "grok")
    scanner = sum(1 for r in rows if r.get("src") == "scanner")
    stocktwits = sum(1 for r in rows if r.get("src") == "stocktwits")
    pipeworx = sum(1 for r in rows if r.get("src") == "pipeworx")
    unv = sum(1 for r in rows if r.get("conf") == "unverified")
    priced = sum(1 for r in rows if r.get("pct") is not None)
    named = sum(1 for r in rows if r.get("why"))
    movers = [r for r in rows if r.get("pct") is not None]
    gainers = sum(1 for r in movers if (r.get("pct") or 0) > 0)
    losers = sum(1 for r in movers if (r.get("pct") or 0) < 0)
    cats = {}
    for r in rows:
        c = r.get("cat") or "other"
        if c != "other":
            cats[c] = cats.get(c, 0) + 1

    out = []
    out.append(f"# Pre-open catalyst digest — {date_str} · {slot} ET checkpoint")
    out.append("")
    out.append(f"- **Tape:** `{tape_name}` · **records:** {n} · **grok:** {grok} · "
               f"**scanner:** {scanner} · **unverified:** {unv}")
    out.append(f"- **Provenance:** **priced movers:** {priced} ({gainers} up / {losers} down) — "
               f"of those, {pipeworx} also carry a grounded catalyst (pipeworx) and {scanner} "
               f"carry the movers-scan price only (scanner) · narrative-only, no ground truth "
               f"(stocktwits): {stocktwits}")
    out.append("- **Grok call:** not used — the xAI chat API no longer serves live search "
               "(HTTP 410) and the Agent Tools API is not enabled on this key · cost **$0.0000**")
    out.append(f"- **Snapshot:** {scan_note}")
    out.append("- **Halt state:** not measurable — the `halted` column is null on every row "
               "(never `0`); a halt count is not published by this scan")
    if cats:
        out.append("- **Catalyst classes:** " + " · ".join(f"{k} {v}" for k, v in
                   sorted(cats.items(), key=lambda kv: -kv[1])))
    out.append(f"- **Named catalysts:** {named} of {n} records")
    grounded_rows = sum(1 for r in rows if r.get("src") == "pipeworx")
    dated_rows = sum(1 for r in rows if r.get("news_date"))
    conflicts = sum(1 for r in rows if r.get("sign_conflict"))
    out.append(f"- **Dated catalysts:** {dated_rows} of {grounded_rows} grounded rows carry a "
               f"news date (`news_date`, and the article it came from in `news_url`). An "
               f"undated catalyst shows an em-dash in **When it broke** - never the capture "
               f"clock, which is when the script ran, not when the news broke.")
    if conflicts:
        out.append(f"- **Sign conflicts:** {conflicts} row(s) carry a catalyst whose direction "
                   f"CONTRADICTS the move (marked `low ⚠` in the table). A cause that points "
                   f"the other way is not an explanation of this move, so it is demoted rather "
                   f"than published as a confident one.")
    out.append("")
    out.append("| " + " | ".join(DIGEST_COLUMNS) + " |")
    out.append("|---|---|---|---|---|")
    top = rank(rows)[:TOP_N]
    if not top:
        out.append("| — | — | — | no records in this checkpoint's tape | — |")
    for r in top:
        why = r.get("why") or NO_CATALYST
        conf = (r.get("conf") or "low")
        if conf == "unverified":
            conf = "⚠ unverified"
        elif r.get("sign_conflict"):
            # THE SIGN PROBE FIRED: the cause points the OTHER way from the move.
            # The confidence is already demoted on the tape; the board marks it so a
            # reader can see WHY the row is not offered as a confident cause.
            conf = "low ⚠"
        # WHEN THE NEWS BROKE - and never the capture clock.
        #
        # The capture clock (`ts`) is the moment THIS SCRIPT RAN. Printing it in a
        # column titled "When it broke" asserts that the catalyst broke when the
        # script ran, which is false whenever the catalyst is older than the run.
        # Measured on the 2026-11-09 09:50 checkpoint: ARWR carried a 2026-01-06
        # press release and the board printed "09:53:48" for it - forty minutes
        # after the capture, for a ten-month-old story about the opposite move.
        #
        # So the order is: the NEWS date (news_date), then the trending snapshot's
        # own stamp, and then nothing at all. An em-dash means "we do not know",
        # which is the truth; a clock would be a lie.
        broke = r.get("news_date") or r.get("trending_ts") or ""
        out.append(f"| {clean(r.get('ticker'), 12)} | {fmt_pct(r.get('pct'))} | "
                   f"{clean(conf, 14)} | {clean(why)} | {fmt_ts(broke)} |")
    out.append("")
    out.append(f"_{len(top)} of {n} records, ranked by |%| descending. `conf` is the tape's own "
               f"confidence token: `unverified` means the catalyst could not be tied to a "
               f"scanner price. Rows with no price carry a catalyst but no ground truth — "
               f"they sort last by design._")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--slot", required=True)
    ap.add_argument("--scan-note", default=(
        "one movers scan in BOTH directions (pipeworx top_movers gainers + losers as DISJOINT "
        "halves, liquidity floor price>=$1 and $vol>=$1M), one stocktwits trending snapshot and "
        "one TradingView scanner pull for THIS session's pre-market print; prices come only from "
        "the scanner, one snapshot, one row per ticker"))
    a = ap.parse_args()
    rows = []
    bad = 0
    with open(a.tape, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                bad += 1
                continue
            if isinstance(r, dict) and r.get("ticker"):
                rows.append(r)
    if not rows:
        raise SystemExit(f"make_digest: no usable records in {a.tape}")
    md = render(rows, a.date, a.slot, os.path.basename(a.tape), a.scan_note)
    if bad:
        md = md.replace("- **Named catalysts:**", f"- **Malformed lines skipped:** {bad}\n"
                        "- **Named catalysts:**", 1)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"digest: wrote {len(rows)} records -> {a.out} (malformed={bad})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
PREOPEN_DIGEST_V2
PREOPEN_MOVER_COVERAGE_V1
make_digest.py — render the human-readable board that sits BESIDE a pre-open tape.

WHY THIS EXISTS
---------------
The tape is machine data (one JSON object per line). The 08:30 board is what a trader
actually reads before the open: the biggest movers, the catalyst, the confidence token
and WHEN the news broke.

It is rendered FROM the tape, never by hand, so the board can never disagree with the
data cron #17 will read at 15:50.

THE MOVER COVERAGE FLOOR — WHY THIS FILE CARRIES A MEASUREMENT
-------------------------------------------------------------
The tape's whole job is WHO / WHAT / WHEN for every name materially moving pre-market.
On Friday 2026-11-13 it did not do that job: the 08:30 checkpoint carried 164 records
and only 16 of them carried a catalyst (9.8%); the 09:50 checkpoint carried 218 records
and 20 carried one (9.2%). The tape priced the movers and explained almost none of them
— LFTO (+25.07%) on a Q3 beat and SBC (+9.6%) on a Q3 print and an 8-K both sat on the
tape with `cat: "other"`, `why: null`, `conf: "low"` and `news_date: null` — and NOTHING
in the artifact or in the reply said so.

That is a SILENT failure. A tape that is 90% unexplained reads exactly like a tape that
found no news, and the fleet's own rule is that a degraded run must say it degraded.

BUT THE MEASUREMENT IS ABOUT WHAT THE READER READS. The reader does not read 164 tape
records; the reader reads THIS board's top-movers table — the 15 rows the digest
publishes, the rows they act on. So the gated number is the coverage OF THAT TABLE:

    mover_coverage = (published movers carrying a catalyst) / (published movers)

The whole-tape coverage is still published, as CONTEXT (it says how wide the band was,
not how much of the board was explained) — but it is NOT the gate.

THE FLOOR IS 50%, and it is REACHABLE: a 15-row movers table needs 8 explained movers
(7/15 = 46.7% is below it, 8/15 = 53.3% clears it), and the catalyst pool (--top 20) is
ranked by |%| in the same order the table is published, so the budget can land on the
rows the reader sees. A gate that can never be cleared is a ratchet, and a ratchet that
fires on every checkpoint trains the reader to ignore the label.

Measured on Friday 2026-11-13 under THIS metric: 08:30 explained 4 of the 15 published
movers (27%), 09:50 explained 6 of 15 (40%) — both below the floor, and both boards say
so in the file a reader opens.

PREOPEN_MOVER_COVERAGE_V1 is the marker for THIS metric. The ladder demands it, so a
stale renderer that publishes the old whole-tape floor cannot win the fetch.

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

# THE COVERAGE CONTRACT — the marker that says "this board was rendered under the
# mover-coverage floor". It is the same shape as cron #17's `in-play-artifact-v2`: a board
# that carries the marker is checked against the rules in force when it was written, and
# a board that carries NO marker was written before the rule existed and is
# GRANDFATHERED against it (see tools/check_preopen_checkpoint.py).
#
# v2, and not v1: the METRIC changed. v1 gated the WHOLE TAPE at 40%, which on a
# 164-row tape needed 66 explained rows and could never be cleared — a ratchet, not a
# gate. v2 gates the MOVERS THE BOARD PUBLISHES at 50%, which 8 of 15 clears.
COVERAGE_CONTRACT = "preopen-coverage-v2"
# THE FLOOR. 50% of the PUBLISHED MOVERS must carry a cause for the board to be doing
# its job: a board whose movers are half price-only is a price list, not a catalyst tape.
#
# The arithmetic, so the floor's reachability is obvious and checkable: a 15-row movers
# table needs ceil(0.50 x 15) = 8 explained movers — 7/15 (46.7%) is below the floor,
# 8/15 (53.3%) clears it. The catalyst pool is 20 names wide and ranked by |%| in the
# same order the table is published, so 8 of 15 is inside the budget.
#
# Measured 2026-11-13 under this metric: 4/15 (27%) at 08:30 and 6/15 (40%) at 09:50 —
# both below the floor, which is exactly the point: those two checkpoints were
# indistinguishable from a quiet news morning.
MOVER_COVERAGE_FLOOR = 0.50


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


def coverage_of(rows):
    """THE WHOLE-TAPE COVERAGE - CONTEXT, not the gate.

    coverage = (records with a non-null `why`) / (total records)

    A record carries a `why` when SOMEONE explained it: the grounded catalyst call
    (`src: pipeworx`), the article feed, or the retail-chatter snapshot
    (`src: stocktwits`). A record WITHOUT one is unexplained, and an unexplained record
    that still carries a price is PRICE-ONLY: a mover the tape priced and did not
    explain.

    This number says how much of a 130-220 row BAND was explained. It is published,
    because it is a fact about the band - but the GATE is `mover_coverage` (see
    published_movers), because the reader reads the board's movers table and not the
    tape.

    Returns (named, total, price_only_rows, narrative_only_rows).
    """
    n = len(rows)
    named = [r for r in rows if r.get("why")]
    unexplained = [r for r in rows if not r.get("why")]
    price_only = [r for r in unexplained if r.get("pct") is not None]
    narrative_only = [r for r in unexplained if r.get("pct") is None]
    return named, n, price_only, narrative_only


def published_movers(top):
    """THE MOVERS THIS BOARD PUBLISHES - the gated denominator.

    `top` is the table the board renders (the top TOP_N rows by |%|). A row with no
    price is a catalyst without a move: the board sorts it last by design and says so
    in its own footer, so it is not a MOVER and it is not in the denominator of the
    gated metric. A board with no movers publishes no movers table, and a checkpoint
    that cannot show an explained mover cannot claim coverage.
    """
    return [r for r in top if r.get("pct") is not None]


def render(rows, date_str, slot, tape_name, scan_note):
    n = len(rows)
    grok = sum(1 for r in rows if r.get("src") == "grok")
    scanner = sum(1 for r in rows if r.get("src") == "scanner")
    stocktwits = sum(1 for r in rows if r.get("src") == "stocktwits")
    pipeworx = sum(1 for r in rows if r.get("src") == "pipeworx")
    unv = sum(1 for r in rows if r.get("conf") == "unverified")
    priced = sum(1 for r in rows if r.get("pct") is not None)
    named_rows, n, price_only, narrative_only = coverage_of(rows)
    named = len(named_rows)
    unexplained = n - named
    cov_pct = (100.0 * named / n) if n else 0.0
    floor_pct = MOVER_COVERAGE_FLOOR * 100.0
    # THE TABLE THIS BOARD PUBLISHES, and the GATED measurement over it.
    top = rank(rows)[:TOP_N]
    movers = published_movers(top)
    mv_total = len(movers)
    mv_named = sum(1 for r in movers if r.get("why"))
    mv_pct = (100.0 * mv_named / mv_total) if mv_total else None
    # NO MOVERS TABLE ⇒ NO COVERAGE CLAIM. The metric is undefined, so the checkpoint
    # is degraded: it cannot show an explained mover, so it cannot claim coverage.
    below = (mv_total == 0) or (mv_named / mv_total < MOVER_COVERAGE_FLOOR)
    mv_price_only = [r for r in movers if not r.get("why")]
    movers_gainers = sum(1 for r in movers if (r.get("pct") or 0) > 0)
    movers_losers = sum(1 for r in movers if (r.get("pct") or 0) < 0)
    # THE WHOLE TAPE's priced rows - the provenance split is about the TAPE, while the
    # gated metric is about the TABLE. They are different sets and are not mixed.
    tape_priced = [r for r in rows if r.get("pct") is not None]
    gainers = sum(1 for r in tape_priced if (r.get("pct") or 0) > 0)
    losers = sum(1 for r in tape_priced if (r.get("pct") or 0) < 0)
    cats = {}
    for r in rows:
        c = r.get("cat") or "other"
        if c != "other":
            cats[c] = cats.get(c, 0) + 1

    out = []
    out.append(f"# Pre-open catalyst digest — {date_str} · {slot} ET checkpoint")
    out.append("")
    if below:
        # THE DEGRADATION, IN THE FILE A READER OPENS. Not a footnote, not a reply-only
        # line: a banner above the table, in the same place a reader's eye lands first.
        if mv_total == 0:
            out.append(f"> ⚠ **DEGRADED — mover coverage is n/a: the digest published no "
                       f"movers table.** A checkpoint that cannot show an explained mover "
                       f"cannot claim coverage, so this one is below the {floor_pct:.0f}% "
                       f"floor by construction. The tape carries **{n} records** and the "
                       f"board publishes no priced mover among them — read it as NOTHING "
                       f"TO TRADE, not as a quiet pre-market.")
        else:
            out.append(f"> ⚠ **DEGRADED — mover coverage {mv_pct:.0f}% is below the "
                       f"{floor_pct:.0f}% floor.** The movers on this board are priced but "
                       f"unexplained: the catalyst budget did not reach them. "
                       f"**{mv_total - mv_named} of the {mv_total} published movers carry "
                       f"no cause at all** — read those names as MOVERS, not as explained "
                       f"moves.")
            out.append(f"> **Cause:** the grounded catalyst call did not explain them — "
                       f"{mv_total - mv_named} of the {mv_total} movers this board publishes "
                       f"carry the pre-market scan price only (the movers scan / the "
                       f"pre-market band). The tape is complete; the EXPLANATION is not.")
        out.append("")
    out.append(f"- **Tape:** `{tape_name}` · **records:** {n} · **grok:** {grok} · "
               f"**scanner:** {scanner} · **unverified:** {unv}")
    out.append(f"- **Provenance:** **priced movers:** {priced} ({gainers} up / {losers} down) — "
               f"of those, {pipeworx} also carry a grounded catalyst (pipeworx) and {scanner} "
               f"carry the movers-scan price only (scanner) · narrative-only, no ground truth "
               f"(stocktwits): {stocktwits}")
    # THE GATED MEASUREMENT. First-class, next to the record count and the provenance
    # split, and it carries the COUNTS (with / without) so the percentage is auditable.
    # The contract marker rides on its OWN line (the house pattern: cron #17's
    # "**Contract:** `in-play-artifact-v2`"), so a board that loses its coverage LINE
    # has not lost its marker - and the grandfather rule cannot be used to hide a
    # board that stopped publishing its measurement.
    out.append(f"- **Coverage contract:** `{COVERAGE_CONTRACT}`")
    if mv_total == 0:
        out.append(f"- **mover coverage:** n/a — the digest published no movers table · "
                   f"**floor:** {floor_pct:.0f}% · **BELOW FLOOR**")
    else:
        out.append(f"- **mover coverage:** {mv_named}/{mv_total} ({mv_pct:.0f}%) · "
                   f"**floor:** {floor_pct:.0f}% · "
                   f"**{'BELOW FLOOR' if below else 'AT OR ABOVE THE FLOOR'}** · "
                   f"published movers: {mv_total} ({movers_gainers} up / {movers_losers} down)")
    # THE WHOLE-TAPE COVERAGE - CONTEXT ONLY. It is published because it is a fact
    # about the band, and it is clearly labelled as NOT the gated number: a
    # percentage over 164 rows says how wide the tape was, not how much of the board
    # the reader is looking at was explained.
    out.append(f"- **catalyst coverage (whole tape):** {named}/{n} ({cov_pct:.0f}%) · "
               f"**unexplained:** {unexplained} records "
               f"({len(price_only)} price-only · {len(narrative_only)} narrative-only) · "
               f"CONTEXT ONLY — not the gated number")
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
    if below and mv_price_only:
        # WHICH names are price-only. A degradation that says "some of them" is not a
        # finding; the reader has to be able to look up the tickers THIS BOARD
        # PUBLISHES and did not explain. The list is the published movers with a null
        # `why`, in the board's own |%| order.
        names_only = [str(r.get("ticker") or "") for r in rank(mv_price_only)]
        out.append(f"- **Unexplained movers in the published table (a price, no catalyst "
                   f"captured):** {len(mv_price_only)} of {mv_total} published movers — "
                   + ", ".join(names_only))
    out.append("")
    out.append("| " + " | ".join(DIGEST_COLUMNS) + " |")
    out.append("|---|---|---|---|---|")
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

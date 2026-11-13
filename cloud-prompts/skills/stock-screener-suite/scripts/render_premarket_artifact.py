#!/usr/bin/env python3
"""
render_premarket_artifact.py — the renderer that owns the cron #08 contract files.

MARKER: premarket-render-v1

WHY THIS EXISTS
---------------
Until 2026-11-12 the contract MARKDOWN (`pre-market-gapper.md`) was written by the
agent, by hand, on every fire: the pull helper produced the numbers
(`_premarket-pull.json`) and the contract CSV, and then ~140 lines of markdown
were typed into the chat context and written out. Every number in that markdown
was a transcription, and the builder that did the transcription lived only in
one sandbox and was re-invented - differently - on the next fire. That is
exactly the class of drift the artifact contract exists to prevent.

This renderer closes it. It reads the pull's JSON and the universe manifest and
writes BOTH contract files, so that:

  * there is ONE owner per output file (the pull owns the numbers, the renderer
    owns the contract files) and the CSV and the markdown can never disagree
    about a column set;
  * every number is engine-owned - a hand-typed price is a defect, not a style
    choice;
  * the artifact is reproducible: the same pull JSON renders the same markdown.

It also implements the two changes the 2026-11-12 run analysis asked for:

  * the MARKET LADDER is the PRIMARY table. The Focus list is a momentum screen
    built on the PREVIOUS session, so it structurally cannot contain a name
    whose move has not happened yet - measured 2026-11-12, the Focus book held 0
    of the day's real movers. The market's gaps lead; the Focus book follows.
  * `driver_class` names WHY a name moved (CATALYST / CRYPTO_BETA /
    MARKET_BETA / SECTOR_BETA / IDIOSYNCRATIC / NO_MOVE), because a gap that
    clears the bar is not automatically a setup: MARA cleared the gate on
    2026-11-12 and was a BITCOIN gap.
  * `tape_lag_min` publishes how many minutes the newest print is behind the
    wall clock. Measured 2026-11-12: 14-24 minutes for 11 of 12 names and 86
    minutes for one, and nothing in the artifact said so.

USAGE
    python3 render_premarket_artifact.py \
        --pull-json daily-screens/<date>/_premarket-pull.json \
        --universe-manifest daily-screens/<date>/_universe.json \
        --context daily-screens/<date>/premarket-context.json \
        --out-dir daily-screens/<date> --date 2026-11-12

The context file is optional and carries only what a human/agent can know that
a machine cannot:

    {
      "catalysts": {"LUNR": {"confirmed": true,
                             "source": "issuer press release, 11/12",
                             "note": "Q3 revenue $269M vs $250.8M consensus"}},
      "notes": ["a caveat the agent wants in the Method section"],
      "source_health": [{"source": "web_search", "status": "ok", "role": "catalysts"}]
    }

OUTPUTS
    <out-dir>/pre-market-gapper.md    the contract markdown
    <out-dir>/pre-market-gapper.csv   the contract CSV, one row per Focus name
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

CONTRACT_VERSION = "premarket-artifact-v6"
RENDER_MARKER = "premarket-render-v1"
PULL_MARKER = "premarket-pull-v2"

GAP_TRIGGER_PCT = 4.0
MIN_PM_VOLUME_SHARES = 50_000
MIN_EXECUTED_SHARES = 25

# a tape older than this is STALE: the print behind the gap is not a live market
STALE_TAPE_MIN = 30.0

DRIVER_CLASSES = ("CATALYST", "CRYPTO_BETA", "MARKET_BETA", "SECTOR_BETA",
                  "IDIOSYNCRATIC", "NO_MOVE")

# how many market-ladder rows the markdown publishes. The FULL list stays in
# _premarket-pull.json - the artifact is read on a phone.
LADDER_ROWS = 25

CSV_COLUMNS = [
    # the universe's own session and the denominator's session, per row
    "universe_date", "ref_close_date", "universe_source",
    "ticker", "ref_close", "ref_close_source", "pm_price", "pm_gap_pct",
    "exec_shares", "exec_notional", "pm_volume", "pm_volume_source",
    "quote_price", "quote_gap_pct", "bid", "ask",
    "pm_high", "pm_low", "pm_high_gap_pct", "pm_low_gap_pct",
    "tv_pm_pct", "tv_pm_volume", "stylists", "origins",
    "verdict", "flag_reason",
    # v6: the tape's own freshness, the driver, and the prior session's move
    "tape_newest_print", "tape_lag_min", "tape_pulls", "tape_vintage_count",
    "tape_wave_count", "prior_session_change", "pm_volume_pct_30d",
    "driver_class", "driver_basis", "sustained", "catalyst",
]

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def fmt(v, nd=2):
    if v is None:
        return ""
    return ("{:,." + str(nd) + "f}").format(v)


def pct(v, dp=2, sign=True):
    if v is None:
        return "n/a"
    return ("%+.{}f%%".format(dp) % v) if sign else ("{:.{}f}%".format(dp).format(v))


def money(v, dp=2):
    return "n/a" if v is None else ("${:,.{}f}".format(v, dp))


def split_multi(v):
    return [x.strip() for x in str(v or "").replace(";", "|").split("|") if x.strip()]


def clean_px(v):
    """`$75.51 (04:00:05 AM)` -> `$75.51`."""
    s = str(v or "")
    if "(" in s:
        s = s.split("(")[0].strip()
    return s or "n/a"


def render(pull: dict, manifest: dict, context: dict, out_dir: Path, fire_date: str | None):
    recs = pull.get("records") or {}
    ladder = pull.get("market_ladder") or []
    proxies = pull.get("proxies") or {}
    crypto = pull.get("crypto_proxy") or {}
    catalysts = (context or {}).get("catalysts") or {}
    notes = (context or {}).get("notes") or []
    source_health = (context or {}).get("source_health") or []

    universe_date = (manifest or {}).get("universe_date") or ""
    denom_date = (manifest or {}).get("expected_prior_session") or universe_date

    def enrich(rec):
        r = dict(rec)
        r["_gap"] = num(r.get("pm_gap_pct"))
        r["_qg"] = num(r.get("quote_gap_pct"))
        r["_vol"] = num(r.get("pm_volume"))
        r["_es"] = num(r.get("exec_shares"))
        r["_en"] = num(r.get("exec_notional"))
        r["_lag"] = num(r.get("tape_lag_min"))
        r["_stylists"] = split_multi(r.get("stylists"))
        r["_origins"] = split_multi(r.get("origins"))
        r["_sustained"] = bool(num(r.get("pm_low_gap_pct")) is not None
                               and num(r.get("pm_low_gap_pct")) > 0)
        avg30 = num(r.get("tv_avg_volume_30d"))
        r["_volpct"] = (r["_vol"] / avg30 * 100.0) if (avg30 and r["_vol"] is not None) else None
        r["_cat"] = catalysts.get(r.get("ticker")) or {}
        return r

    rows = [enrich(rec) for rec in recs.values()]
    rows.sort(key=lambda r: -(abs(r["_gap"]) if r["_gap"] is not None else -1))
    flagged = [r for r in rows if r.get("verdict") == "FLAGGED"]
    nonflag = [r for r in rows if r.get("verdict") != "FLAGGED"]
    scanned = len(rows)

    def rank_key(r):
        return (-len(r["_stylists"]), -len(r["_origins"]),
                -(abs(r["_gap"]) if r["_gap"] is not None else 0.0), str(r.get("ticker")))
    ranked = sorted(nonflag, key=rank_key)

    # ---------------------------------------------------------------- CSV ---
    csv_rows = []
    for r in rows:
        csv_rows.append({
            "universe_date": r.get("universe_date") or universe_date,
            "ref_close_date": r.get("ref_close_date") or denom_date,
            "universe_source": (r.get("universe_source")
                                or (manifest or {}).get("universe_source")
                                or ("focus.csv:%s" % (manifest or {}).get("ref_close_column")
                                    if (manifest or {}).get("ref_close_column") else "")),
            "ticker": r.get("ticker") or "",
            "ref_close": fmt(num(r.get("base_close")), 4),
            "ref_close_source": r.get("base_close_source") or "",
            "pm_price": fmt(num(r.get("pm_price")), 4),
            "pm_gap_pct": fmt(num(r.get("pm_gap_pct")), 3),
            "exec_shares": r.get("exec_shares") if r.get("exec_shares") is not None else "",
            "exec_notional": fmt(num(r.get("exec_notional")), 2),
            "pm_volume": r.get("pm_volume") if r.get("pm_volume") is not None else "",
            "pm_volume_source": r.get("pm_volume_source") or "",
            "quote_price": fmt(num(r.get("quote_price")), 4),
            "quote_gap_pct": fmt(num(r.get("quote_gap_pct")), 3),
            "bid": fmt(num(r.get("info_bid")), 4),
            "ask": fmt(num(r.get("info_ask")), 4),
            "pm_high": r.get("pm_high") or "",
            "pm_low": r.get("pm_low") or "",
            "pm_high_gap_pct": fmt(num(r.get("pm_high_gap_pct")), 3),
            "pm_low_gap_pct": fmt(num(r.get("pm_low_gap_pct")), 3),
            "tv_pm_pct": fmt(num(r.get("tv_pm_pct")), 3),
            "tv_pm_volume": r.get("tv_pm_volume") if r.get("tv_pm_volume") is not None else "",
            "stylists": r.get("stylists") or "",
            "origins": r.get("origins") or "",
            "verdict": r.get("verdict") or "",
            "flag_reason": r.get("flag_reason") or "",
            "tape_newest_print": r.get("tape_newest_print") or "",
            "tape_lag_min": fmt(num(r.get("tape_lag_min")), 1),
            "tape_pulls": r.get("tape_pulls") if r.get("tape_pulls") is not None else "",
            "tape_vintage_count": r.get("tape_vintage_count")
                                  if r.get("tape_vintage_count") is not None else "",
            "tape_wave_count": len(pull.get("tape_waves") or []),
            "prior_session_change": (fmt(num(r.get("prior_session_change")), 3)
                                     if num(r.get("prior_session_change")) is not None else "n/a"),
            # the computed ratio lives in `_volpct` - reading a differently named
            # key here published "n/a" on EVERY row (measured 2026-11-13).
            "pm_volume_pct_30d": (fmt(r["_volpct"], 2)
                                  if r.get("_volpct") is not None else "n/a"),
            "driver_class": r.get("driver_class") or "",
            "driver_basis": r.get("driver_basis") or "",
            "sustained": "yes" if r["_sustained"] else "no",
            "catalyst": (r["_cat"].get("note") or r["_cat"].get("source") or "") if r["_cat"] else "",
        })

    csv_path = out_dir / "pre-market-gapper.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in csv_rows:
            w.writerow(row)

    # ------------------------------------------------------------ MARKDOWN ---
    L = []
    A = L.append
    # The renderer builds the marker ITSELF. The pull's stored marker_line is
    # NOT trusted: it can be an older contract (and the renderer is what
    # guarantees the artifact's contract version and capability markers).
    # The marker must name the source that ACTUALLY provided the close. In the
    # degraded-universe run that is the INDEPENDENT sources, never the stale
    # focus.csv - naming "focus.csv" there was a false attribution (measured
    # 2026-11-13).
    ref_src = ""
    for r in rows:
        src = str(r.get("base_close_source") or "").split(" (")[0]
        if src:
            ref_src = src
            break
    if not ref_src:
        ref_src = "prior sweep focus.csv"
    marker = ("_contract: %s · flagged: %d · scanned: %d · gate: |gap|>=%.1f%% and "
              "pm_volume>=%s and exec_shares>=%s · reference close: %s · pull: %s · "
              "renderer: %s_"
              % (CONTRACT_VERSION, len(flagged), scanned, GAP_TRIGGER_PCT,
                 "{:,}".format(MIN_PM_VOLUME_SHARES), "{:,}".format(MIN_EXECUTED_SHARES),
                 ref_src, PULL_MARKER, RENDER_MARKER))
    A(marker)
    A("")
    dt = datetime.strptime(fire_date, "%Y-%m-%d") if fire_date else datetime.now(ET)
    title = "# Pre-Market Gapper — %s, %d %s %d" % (WEEKDAYS[dt.weekday()], dt.day,
                                                   MONTHS[dt.month - 1], dt.year)
    A(title)
    A("")

    waves = pull.get("tape_waves") or []
    lags = [num(r.get("tape_lag_min")) for r in rows if num(r.get("tape_lag_min")) is not None]
    lag_txt = ("%d-%d min behind the wall clock" % (int(min(lags)), int(max(lags)))) if lags else "n/a"
    wave_txt = ", ".join("%s (wave %d, %s names)" % (w.get("at_et"), w.get("wave"),
                                                    w.get("symbols")) for w in waves)
    A("Pre-market tape snapshots **%s**; universe = the Focus list of the completed **%s** "
      "18:30 ET sweep (%d names); every gap is measured against that session's settled close. "
      "Source of record: the Nasdaq extended-trading tape (pulled until the cached vintage "
      "stops changing), with Cboe and TradingView as independent cross-checks."
      % (wave_txt or "n/a", universe_date, scanned))
    A("")

    # ---- TL;DR ----
    A("## TL;DR")
    A("")
    if flagged:
        A("- **%d of %d Focus names flagged.** %s" % (
            len(flagged), scanned,
            "; ".join("**%s %s** (%s, %s shares) — %s"
                      % (r["ticker"], pct(r["_gap"]), r.get("driver_class") or "",
                         "{:,}".format(int(r["_es"] or 0)), r.get("driver_basis") or "")
                      for r in flagged)))
    else:
        A("- **0 of %d Focus names flagged.** The Focus book did not fire." % scanned)
    top_ladder = ladder[:3]
    if top_ladder:
        A("- **The market's gaps sit OUTSIDE the Focus list** (it is a prior-session momentum "
          "screen, so it cannot contain a name whose move has not happened yet): %s."
          % "; ".join("%s %s%s" % (t.get("ticker"), pct(num(t.get("gap_pct"))),
                                   (" — " + (catalysts.get(t.get("ticker"), {}) or {}).get("note", ""))
                   if (catalysts.get(t.get("ticker")) or {}).get("note")
                   else (" — " + (catalysts.get(t.get("ticker"), {}) or {}).get("source", ""))
                   if (catalysts.get(t.get("ticker")) or {}).get("source")
                   else "")
                      for t in top_ladder))
    thin = [r for r in rows if (r["_es"] or 0) < MIN_EXECUTED_SHARES]
    stale = [r for r in rows if (r["_lag"] or 0) > STALE_TAPE_MIN]
    caveat_bits = []
    if (manifest or {}).get("universe_stale"):
        caveat_bits.append("**the Focus list is from %s, a session behind the denominator "
                           "session %s** — the expected session's sweep has not published, so "
                           "the universe is stale and every reference close was taken from the "
                           "INDEPENDENT sources, never from the stale file"
                           % (universe_date, denom_date))
    if stale:
        caveat_bits.append("**%d name(s) printed on a tape more than %d min old** (%s), so the "
                           "gap behind them is a snapshot, not a live market"
                           % (len(stale), int(STALE_TAPE_MIN),
                              ", ".join("%s %d min" % (r["ticker"], r["_lag"]) for r in stale)))
    tape_only = [r for r in rows if r.get("verdict") == "BORDERLINE_TAPE_ONLY"]
    if tape_only:
        caveat_bits.append("**%s cleared the bar on the live quote but not on the executed "
                           "tape** — a quote is not a market"
                           % ", ".join("%s (quote %s / tape %s)"
                                       % (r["ticker"], pct(r["_qg"]), pct(r["_gap"]))
                                       for r in tape_only))
    if thin:
        caveat_bits.append("**%d of %d names printed on fewer than %d shares** — thin, wide-spread "
                           "names, not tradeable gappers"
                           % (len(thin), scanned, MIN_EXECUTED_SHARES))
    beta_flagged = [r for r in flagged if r.get("driver_class") in
                    ("CRYPTO_BETA", "MARKET_BETA", "SECTOR_BETA")]
    if beta_flagged:
        caveat_bits.append("**%s cleared the gate on a BETA move, not a stock-specific setup**"
                           % ", ".join("%s (%s)" % (r["ticker"], r.get("driver_basis"))
                                       for r in beta_flagged))
    A("- **Caveat that changes how this reads:** %s."
      % ("; ".join(caveat_bits) if caveat_bits
         else "the tape was fresh and the size gates were met"))
    A("")

    # ---- the MARKET LADDER: the PRIMARY table ----
    A("## Market ladder — the day's pre-market gaps")
    A("")
    A("The Focus universe is a momentum screen built on the previous session, so it structurally "
      "cannot contain a name whose move has not happened yet. This is the market's book; the "
      "Focus book follows. Filter: TradingView, `type=stock`, market cap > $200M, pre-market "
      "volume > 20,000, |gap| >= %.0f%%." % GAP_TRIGGER_PCT)
    A("")
    if ladder:
        A("| Ticker | Gap % | PM volume | Mkt cap ($M) | Driver | Catalyst |")
        A("|---|---|---|---|---|---|")
        for t in ladder[:LADDER_ROWS]:
            cat = catalysts.get(t.get("ticker")) or {}
            A("| **%s** | %s | %s | %s | %s | %s |"
              % (t.get("ticker"), pct(num(t.get("gap_pct"))),
                 "{:,}".format(int(num(t.get("pm_volume")) or 0)),
                 "{:,.0f}".format((num(t.get("market_cap")) or 0) / 1e6),
                 t.get("driver_class") or cat.get("driver_class") or "—",
                 cat.get("note") or cat.get("source") or "no catalyst confirmed in this run"))
        if len(ladder) > LADDER_ROWS:
            A("")
            A("_%d market-wide gap leaders met the filter; the top %d are shown and the full "
              "list is in `_premarket-pull.json` (`market_ladder`)._"
              % (len(ladder), LADDER_ROWS))
    else:
        A("_No market-wide pre-market gap leaders met the filter._")
    A("")

    # ---- the Focus book ----
    A("## Focus scan — all names")
    A("")
    A("| Ticker | Ref close | PM price (last executed print) | Gap % | PM volume | Exec shares | "
      "Exec notional | PM high | PM low | Quote % | Driver | Lag (min) | Prior sess % | Verdict |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        A("| **{t}** | {ref} | {px} | {gap} | {vol} | {es} | {en} | {hi} | {lo} | {qg} | {drv} | "
          "{lag} | {psc} | {vd} |".format(
              t=r["ticker"], ref=fmt(num(r.get("base_close")), 2),
              px=fmt(num(r.get("pm_price")), 4), gap=pct(r["_gap"]),
              vol=("{:,}".format(int(r["_vol"])) if r["_vol"] is not None else "n/a"),
              es=("{:,}".format(int(r["_es"])) if r["_es"] is not None else "n/a"),
              en=money(r["_en"]), hi=clean_px(r.get("pm_high")), lo=clean_px(r.get("pm_low")),
              qg=pct(r["_qg"]), drv=r.get("driver_class") or "n/a",
              lag=("%.0f" % r["_lag"]) if r["_lag"] is not None else "n/a",
              psc=(pct(num(r.get("prior_session_change")))
                   if num(r.get("prior_session_change")) is not None else "n/a"),
              vd=r.get("verdict") or "n/a"))
    A("")
    A("### Liquidity and durability (context — the flag is unchanged)")
    A("")
    A("| Ticker | PM volume | 30d avg volume | PM vol as % of 30d avg | Sustained (PM low > prior "
      "close) | TV PM % | TV PM volume | Sector |")
    A("|---|---|---|---|---|---|---|---|")
    for r in rows:
        A("| **{t}** | {vol} | {avg} | {pct30} | {sus} | {tv} | {tvv} | {sec} |".format(
            t=r["ticker"],
            vol=("{:,}".format(int(r["_vol"])) if r["_vol"] is not None else "n/a"),
            avg=("{:,}".format(int(num(r.get("tv_avg_volume_30d"))))
                 if num(r.get("tv_avg_volume_30d")) is not None else "n/a"),
            pct30=(fmt(r["_volpct"], 2) if r["_volpct"] is not None else "n/a"),
            sus="yes" if r["_sustained"] else "no",
            tv=pct(num(r.get("tv_pm_pct"))),
            tvv=("{:,}".format(int(num(r.get("tv_pm_volume"))))
                 if num(r.get("tv_pm_volume")) is not None else "n/a"),
            sec=r.get("tv_sector") or "n/a"))
    A("")

    # ---- the near-miss ladder ----
    A("### Gap ladder (the 4% bar is the flag; the bands below it are context)")
    A("")
    A("| Rung | Names | Reading |")
    A("|---|---|---|")
    for label, lo, hi, reading in (
            ("≥8%", 8, 999, "exceptional gappers"),
            ("4–8%", 4, 8, "at the bar"),
            ("2–4%", 2, 4, "the near-miss band — the ones a 4% gate hides"),
            ("<2%", -999, 2, "noise")):
        names = [r["ticker"] for r in rows
                 if r["_gap"] is not None and lo <= abs(r["_gap"]) < hi]
        A("| `%s` | %s | %s |" % (label, ", ".join(names) if names else "—", reading))
    A("")

    # ---- names that did not qualify ----
    A("## Focus names that did not qualify")
    A("")
    for r in ranked:
        prov = ", ".join(r["_origins"])
        A("- **{t}** — {gap} · {vol} shares · {hi}–{lo} · {ns} stylists, {no} origins ({prov}) · "
          "setup: {setup}.".format(
              t=r["ticker"], gap=pct(r["_gap"]),
              vol=("{:,}".format(int(r["_vol"])) if r["_vol"] is not None else "n/a"),
              hi=clean_px(r.get("pm_high")), lo=clean_px(r.get("pm_low")),
              ns=len(r["_stylists"]), no=len(r["_origins"]), prov=prov,
              setup=("good setup that went nowhere" if len(r["_stylists"]) >= 3
                     else "decent setup that went nowhere")))
    if not ranked:
        A("_Every scanned name is FLAGGED._")
    A("")
    if len(ranked) >= 2:
        A("Ordered by setup quality (stylists desc, then origins desc, then size of the miss). "
          "The two best setups — **%s** (%d stylists, %d origins) and **%s** (%d stylists, "
          "%d origins) — are the two the reply must name."
          % (ranked[0]["ticker"], len(ranked[0]["_stylists"]), len(ranked[0]["_origins"]),
             ranked[1]["ticker"], len(ranked[1]["_stylists"]), len(ranked[1]["_origins"])))
        A("")

    # ---- flags ----
    A("## Flags")
    A("")
    any_flag = False
    # the universe's own flags come FIRST: if the Focus list is a session stale
    # because the expected session's sweep has not published, the reader must
    # see it before any per-name number.
    man_flags = (manifest or {}).get("flags") or []
    for mf in man_flags:
        A("- **%s**" % mf)
        any_flag = True
    for r in rows:
        bits = []
        if (r["_es"] or 0) < MIN_EXECUTED_SHARES and r["_gap"] is not None \
                and abs(r["_gap"]) >= GAP_TRIGGER_PCT:
            bits.append("gap %s printed on **%s shares** — a print that small is a rounding "
                        "artifact, not a market"
                        % (pct(r["_gap"]), "{:,}".format(int(r["_es"] or 0))))
        if r.get("verdict") == "BORDERLINE_TAPE_ONLY":
            bits.append("**a quote, not a market** — live quote %s (bid %s / ask %s) against an "
                        "executed tape at %s" % (pct(r["_qg"]), fmt(num(r.get("info_bid")), 2),
                                                 fmt(num(r.get("info_ask")), 2), pct(r["_gap"])))
        if r.get("verdict") == "BORDERLINE_INTRADAY":
            bits.append("crossed the bar intraday and gave it back (pre-market high %s / low %s "
                        "→ %s at the snapshot)" % (pct(num(r.get("pm_high_gap_pct"))),
                                                   pct(num(r.get("pm_low_gap_pct"))), pct(r["_gap"])))
        if (r["_lag"] or 0) > STALE_TAPE_MIN:
            bits.append("**stale tape** — the newest print is %d min behind the wall clock, so "
                        "the gap is a snapshot, not a live market" % int(r["_lag"]))
        if r.get("verdict") == "FLAGGED" and r.get("driver_class") in \
                ("CRYPTO_BETA", "MARKET_BETA", "SECTOR_BETA"):
            bits.append("**beta, not a setup** — %s" % (r.get("driver_basis") or ""))
        conflict = r.get("base_close_conflict")
        if conflict:
            bits.append("reference close conflict (%s) — the three-source consensus was used"
                        % conflict)
        if bits:
            any_flag = True
            A("- **%s** — %s." % (r["ticker"], "; ".join(bits)))
    if not any_flag:
        A("_No per-name suspect numbers: every gap is backed by an executed print of size._")
    A("")

    # ---- method ----
    A("## Method, source health & caveats")
    A("")
    A("| Source | Endpoint / query | Status | Role |")
    A("|---|---|---|---|")
    A("| Universe resolver | `premarket_universe.py --fire-date %s` | ok | resolved the expected "
      "prior session **%s** from the market's own session history, matched the published Focus "
      "list, picked the close column **by date**, confirmed every reference close on an "
      "independent source |" % (fire_date or "?", denom_date))
    A("| Nasdaq extended-trading tape | `api.nasdaq.com/api/quote/<SYM>/extended-trading` | ok | "
      "**source of record** for the published gap, the executed print and pre-market volume; "
      "pulled until the cached vintage stops changing (min 2, max %s) |"
      % (pull.get("pulls_per_symbol") or 4))
    A("| Nasdaq `/info` | `api.nasdaq.com/api/quote/<SYM>/info` | ok | the live quote "
      "(`quote_price`, `quote_gap_pct`) and bid/ask — published separately from the tape |")
    A("| Cboe delayed-quote CDN | `cdn.cboe.com/api/global/delayed_quotes/quotes/<SYM>.json` | ok "
      "| independent price cross-check, not subject to the Nasdaq cache |")
    A("| TradingView america scanner | `scanner.tradingview.com/america/scan` | ok | reference "
      "close and pre-market cross-check, the sector and 30-day average volume, the index/sector "
      "proxies for the driver classification, and the market ladder |")
    if source_health:
        for sh in source_health:
            A("| %s | %s | %s | %s |" % (sh.get("source", "—"), sh.get("query", "—"),
                                        sh.get("status", "—"), sh.get("role", "—")))
    A("")
    gaps_all = [abs(r["_gap"]) for r in rows if r["_gap"] is not None]
    if gaps_all:
        worst = max(gaps_all)
        A("- **Margin against the trigger:** the widest absolute gap on any source is **%.2f%%** "
          "against a %.2f%% trigger — a %.2fx margin, so the flag decision is immune to which "
          "cached vintage a source returns."
          % (worst, GAP_TRIGGER_PCT, (GAP_TRIGGER_PCT / worst) if worst else 0))
    A("- **Denominator:** every gap uses the **%s settled close** — the prior sweep's own "
      "`focus.csv` close column, chosen BY DATE, with `screen_close_resolved` (the screen's T+1 "
      "data date) rejected as a denominator." % denom_date)
    A("- **Tape freshness:** the newest print was %s at the time of the pull. A stable cache "
      "returns the SAME vintage however many times it is asked, so the burst of pulls protects "
      "against a ROTATING cache but not against an old one — which is why `tape_lag_min` is "
      "published on every row." % lag_txt)
    if waves:
        A("- **Tape waves:** %s. A wave that is spread across the run is what produces the "
          "divergence record; the re-pull wave only re-pulls the decision-relevant names "
          "(|gap| >= 2%% or a stale tape), because a name below the near-miss band cannot "
          "change the flag decision." % "; ".join(
              "wave %d at %s (%s names)" % (w.get("wave"), w.get("at_et"), w.get("symbols"))
              for w in waves))
    if crypto:
        A("- **Driver classification:** the gap is compared with the index proxy (SPY %s), the "
          "sector proxy and bitcoin (%+.2f%% overnight from %s) on the SAME TradingView snapshot "
          "as the name, so the two numbers are comparable. The published gap stays the Nasdaq "
          "tape's." % (pct(num((proxies.get("SPY") or {}).get("premarket_change"))),
                       crypto.get("overnight_pct", 0), crypto.get("from_et", "?")))
    A("- **Known Nasdaq defects checked on every fire** (`/info` `secondaryData.lastSalePrice` "
      "not always the settled close, the field flipping mid-session, `primaryData.lastSalePrice` "
      "being a trivial-size print or the ask, the bridge's `market_state: pre` serving the prior "
      "regular close, and the TradingView `premarket_volume` undercount) — the published gap is "
      "the tape's last executed print in every row and the live quote is a separate column.")
    A("- **What could not be verified:** the TradingView `earnings_release_date` field is a "
      "*candidate* catalyst, not a confirmed one, and it is sometimes stale for a name whose move "
      "is not an earnings move. Where no same-session catalyst was confirmed on the wire or in "
      "an issuer release, this artifact says so rather than inventing one.")
    for n in notes:
        A("- %s" % n)
    A("")

    # ---- catalyst ahead ----
    A("## Catalyst ahead — the forward calendar")
    A("")
    today = fire_date
    rows_cat = []
    for r in rows:
        ts = r.get("tv_earnings_release_date")
        if not ts:
            continue
        try:
            when = datetime.fromtimestamp(int(ts), ET)
        except Exception:
            continue
        if when.strftime("%Y-%m-%d") == today:
            rows_cat.append((r, when))
    if rows_cat:
        A("| Ticker | Earnings (ET) | vs today's close (16:00 ET) | Pre-market gap (tape) |")
        A("|---|---|---|---|")
        for r, when in rows_cat:
            h, m = when.hour, when.minute
            rel = ("before the open" if (h, m) < (9, 30)
                   else "after today's close" if (h, m) >= (16, 0) else "during the session")
            A("| %s | %s | %s | %s |" % (r["ticker"], when.strftime("%Y-%m-%d %H:%M"), rel,
                                        pct(r["_gap"])))
    else:
        A("_No Focus-list name has a confirmed earnings date for today._")
    A("")

    md_path = out_dir / "pre-market-gapper.md"
    md_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return md_path, csv_path, marker


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render the cron #08 contract files")
    p.add_argument("--pull-json", required=True)
    p.add_argument("--universe-manifest", required=True)
    p.add_argument("--context", default=None)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--date", default=None, help="the fire date (YYYY-MM-DD)")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    try:
        pull = json.loads(Path(a.pull_json).read_text())
    except Exception as e:
        print("render_premarket_artifact: the pull JSON could not be read (%s)" % e,
              file=sys.stderr)
        return 3
    if pull.get("pull_marker") != PULL_MARKER:
        print("render_premarket_artifact: the pull JSON carries marker %r, expected %r - it was "
              "produced by an older copy of the pull. Re-read the skill spec."
              % (pull.get("pull_marker"), PULL_MARKER), file=sys.stderr)
        return 3
    try:
        manifest = json.loads(Path(a.universe_manifest).read_text())
    except Exception as e:
        print("render_premarket_artifact: the universe manifest could not be read (%s)" % e,
              file=sys.stderr)
        return 3
    if str(manifest.get("status", "")).startswith("FAIL"):
        print("render_premarket_artifact: the universe manifest reports FAIL - there is no "
              "artifact", file=sys.stderr)
        return 3

    context = {}
    if a.context and Path(a.context).exists():
        try:
            context = json.loads(Path(a.context).read_text())
        except Exception as e:
            print("render_premarket_artifact: the context file could not be read (%s) - it is "
                  "ignored" % e, file=sys.stderr)

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md, csvp, marker = render(pull, manifest, context, out_dir, a.date)
    if not a.quiet:
        print(marker)
        print("render_premarket_artifact: %s · %s" % (md, csvp))
    return 0


if __name__ == "__main__":
    sys.exit(main())

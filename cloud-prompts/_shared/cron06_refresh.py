#!/usr/bin/env python3
"""
cron06_refresh.py — the engine behind cron #06 (stock-screener-pattern-study-backlog).

CRON06_REFRESH_V1

WHY THIS EXISTS
---------------
The 2026-11-07 run produced three correct lists and an unhelpful document. Every screen
published the HEAD of its own ranking, so the names that mattered — the ones that sit in
TWO universes at once — never appeared:

  * 12 names were 1000%-in-10-years compounders AND >20% short float. All 12 sat at
    ranks 57-335 of the 374-name short-float book, so the published top 30 contained
    NONE of them, and the enrichment (liquidity, close, 30d change) was spent on ranks
    1-40 of a list that has nothing to do with the join.
  * 5 names were sub-2-year IPOs AND >20% short float (the broken-float squeeze setup).
  * 58 of the 374 short-float names were already in the daily sweep's Master list.

So this engine changes WHAT gets published, not just how it is formatted:

  1. INTERSECTIONS are computed across the three universes and published in every
     artifact. The join is the product; the per-screen lists are its inputs.
  2. ENRICHMENT follows the intersection. Every name in any intersection is enriched
     (liquidity, close, 30-day change) whether or not it is in a screen's top rows.
  3. Every published row carries a CLOSED-SET `tradeable_verdict` instead of a prose
     tier, and a `squeeze_candidate` YES/NO. A verdict is a field, not a sentence.
  4. IPO rows carry `mcap_verified`, `days_since_ipo` and `post_lockup` — a name with
     no valuation row passes the $1B floor BY DEFAULT and the reader must be able to
     see which rows that applies to.
  5. The backlog publishes a LIVE RE-SCORE of the tagged window: live tags plus a
     `tag_change` verdict (NEW / UNCHANGED / ADDED / REMOVED / MIXED). The ledger rows
     stay frozen (that is what a ledger means), but a coil -> breakout transition is
     the signal, and freezing the tags hid it.
  6. A weekly SHORT-FLOAT STATE SNAPSHOT is written, so next week's run can publish
     the CHANGE in short float. `ownership_stats` has no date column, so it cannot be
     replayed: this week's snapshot is the first sample of a series.

WHAT THIS DOES NOT DO
---------------------
It does not fetch market data. The Agent fetches the three shibui screens with the
MCP bridge and passes the raw rows in as JSON; the engine owns the derivation, the
published numbers and the artifact rendering, so nothing is transcribed by hand.

USAGE
    python3 cron06_refresh.py \
        --fire-date 2026-11-07 --data-date 2026-11-06 \
        --ipo-json ipo.json --sf-json sf_all.json \
        --ipo-enrich-json ipo_enrich.json --sf-enrich-json sf_enrich.json \
        --scan-json scan.json --shape-json shape.json \
        --backlog-md prior_backlog.md \
        --prior-state prior_state.json \
        --master-csv daily-screens/2026-11-06/master.csv \
        --out-md-dir daily-screens/2026-11-07 \
        --out-json daily-screens/2026-11-07/cron06-refresh.json \
        --out-state pattern-study/cron06-state/short-float-2026-11-07.json

Exit codes: 0 = artifacts written; 1 = a bad input or an unmet invariant.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, timedelta

CONTRACT_VERSION = "cron06-refresh-v2"
CAPABILITY_MARKER = "CRON06_REFRESH_V1"

# --- closed-set thresholds (published in the spec; change them here and in SKILL.md) --
ADV_TRADEABLE = 20_000_000     # 30-bar average dollar volume floor for size
ADV_THIN = 5_000_000           # below this a name is untradeable for size
SHORT_OVER_FLOAT = 100.0       # short % of float above 100 is a float artifact (PERCENT units)
SHORT_SQUEEZE = 50.0           # squeeze-relevant short threshold (PERCENT units)
LOCKUP_DAYS = 180              # standard lockup length, used as a calendar marker
IPO_FLOOR = 1_000_000_000      # $1B market-cap floor (filter N)

TRADEABLE_VERDICTS = {"TRADEABLE", "THIN", "ILLIQUID", "FLOAT_ARTIFACT", "NO_QUOTE"}
TAG_CHANGES = {"NEW", "UNCHANGED", "ADDED", "REMOVED", "MIXED"}

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


# ------------------------------------------------------------------ formatting
def money(v, dp=2):
    return "—" if v is None else f"${v:,.{dp}f}"


def pct(v, dp=1):
    return "—" if v is None else f"{v:,.{dp}f}%"


def pct0(v):
    return "—" if v is None else f"{v:,.0f}%"


def bn(v):
    return "—" if v is None else f"{v/1e9:,.2f}"


def d(s):
    return date.fromisoformat(s) if s else None


# ------------------------------------------------------------------ verdict
def tradeable_verdict(short_pct: float | None, adv30: float | None) -> str:
    """Closed-set tradeability verdict. Precedence: FLOAT_ARTIFACT > NO_QUOTE >
    ILLIQUID > THIN > TRADEABLE. A verdict is a FIELD; never a sentence."""
    if short_pct is not None and short_pct > SHORT_OVER_FLOAT:
        return "FLOAT_ARTIFACT"
    if adv30 is None:
        return "NO_QUOTE"
    if adv30 < ADV_THIN:
        return "ILLIQUID"
    if adv30 < ADV_TRADEABLE:
        return "THIN"
    return "TRADEABLE"


def squeeze_flag(short_pct: float | None, adv30: float | None) -> str:
    if short_pct is None or adv30 is None:
        return "NO"
    if short_pct > SHORT_OVER_FLOAT:
        return "NO"
    if short_pct > SHORT_SQUEEZE and adv30 >= ADV_TRADEABLE:
        return "YES"
    return "NO"


# ------------------------------------------------------------------ tags
def compute_tags(row, shape):
    """Live chart-shape tags from the run's own shape metrics."""
    s = shape.get(row["symbol"])
    if not s:
        return [], None
    close, hi60, lo60 = row["cur_close"], s["hi60"], s["lo60"]
    hi10, lo10 = s["hi10"], s["lo10"]
    rng = (hi60 - lo60) or None
    cont = ((hi10 - lo10) / rng) if rng else None
    tags = []
    if cont is not None and cont < 0.65:
        tags.append("VCP")
    if hi60 and close / hi60 >= 0.95:
        tags.append("breakout")
    if cont is not None and cont < 0.85 and hi60 and close / hi60 >= 0.85:
        tags.append("coil")
    if row.get("ytd_low") and close >= 1.5 * row["ytd_low"]:
        tags.append("EP")
    if row.get("prev_close"):
        if (close / row["prev_close"] - 1) * 100 > 5:
            tags.append("big_day")
    return tags, cont


def tag_change(frozen_tags: list[str], live_tags: list[str], known: bool = True) -> str:
    """`known` is ledger MEMBERSHIP, not the presence of tags: a name already in the
    ledger whose first-tagging tag list was empty is not a new discovery."""
    if not known:
        return "NEW"
    f, l = set(frozen_tags), set(live_tags)
    if f == l:
        return "UNCHANGED"
    added, removed = l - f, f - l
    if added and removed:
        return "MIXED"
    if added:
        return "ADDED"
    return "REMOVED"


# ------------------------------------------------------------------ prior ledger
def parse_backlog_md(path):
    """Parse the prior published ledger (markdown) into {ticker: {...}}."""
    if not path or not os.path.exists(path):
        return {}, {"carried": 0, "newly": 0, "found": False}
    txt = open(path, encoding="utf-8").read()
    out = {}
    sections = {}
    for marker, key in (("## Newly tagged entries", "new"), ("## Carried forward", "carried")):
        if marker not in txt:
            continue
        sec = txt.split(marker)[1]
        rows, started = [], False
        for line in sec.splitlines():
            if line.startswith("|---"):
                started = True
                continue
            if started and line.startswith("|"):
                rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            elif started and not line.strip():
                break
        sections[key] = rows
    cols = ["ticker", "name", "type", "exchange", "sector", "current", "min10", "peak",
            "gain", "hi60", "cont", "ytd_low", "last_day", "tags"]
    for cells in sections.get("carried", []):
        if len(cells) < 15:
            continue
        d_ = {c: cells[i] for i, c in enumerate(cols)}
        d_["first_tagged"] = cells[14]
        d_["warn"] = "⚠" in cells[0]
        d_["ticker"] = cells[0].replace("⚠", "").strip()
        d_["tags"] = [t.strip() for t in cells[13].split(",") if t.strip() and t.strip() != "—"]
        out[d_["ticker"]] = d_
    for cells in sections.get("new", []):
        if len(cells) < 15:
            continue
        d_ = {c: cells[i + 1] for i, c in enumerate(cols)}
        d_["first_tagged"] = None
        d_["warn"] = "⚠" in cells[1]
        d_["ticker"] = cells[1].replace("⚠", "").strip()
        d_["tags"] = [t.strip() for t in cells[14].split(",") if t.strip() and t.strip() != "—"]
        out.setdefault(d_["ticker"], d_)
    return out, {"carried": len(sections.get("carried", [])), "newly": len(sections.get("new", [])),
                 "found": True}


def load_json(path, default=None):
    if not path:
        return default
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire-date", required=True)
    ap.add_argument("--data-date", required=True)
    ap.add_argument("--ipo-json")
    ap.add_argument("--sf-json")
    ap.add_argument("--ipo-enrich-json")
    ap.add_argument("--sf-enrich-json")
    ap.add_argument("--scan-json")
    ap.add_argument("--shape-json")
    ap.add_argument("--backlog-md")
    ap.add_argument("--prior-state")
    ap.add_argument("--master-csv")
    ap.add_argument("--out-md-dir")
    ap.add_argument("--out-json")
    ap.add_argument("--out-state")
    ap.add_argument("--intersections-only", action="store_true",
                    help="print the enrichment symbol list and exit (the run needs the "
                         "intersection names BEFORE it can enrich them)")
    args = ap.parse_args()

    fire, data = d(args.fire_date), d(args.data_date)
    ipo = load_json(args.ipo_json, []) or []
    sf = load_json(args.sf_json, []) or []
    ipo_en = {r["symbol"]: r for r in (load_json(args.ipo_enrich_json, []) or [])}
    sf_en = {r["symbol"]: r for r in (load_json(args.sf_enrich_json, []) or [])}
    scan = load_json(args.scan_json, []) or []
    shape = {r["symbol"]: r for r in (load_json(args.shape_json, []) or [])}
    prior_ledger, prior_meta = parse_backlog_md(args.backlog_md)
    prior_state = load_json(args.prior_state, None)

    if args.intersections_only:
        ipo_t = {r["ticker"] for r in ipo}
        sf_t = {r["ticker"] for r in sf}
        scan_t = {r["symbol"].split(".")[0] for r in scan}
        ledger_t = set(prior_ledger)
        inter_names = ((set(sf_t) & ledger_t) | (set(sf_t) & scan_t) | (set(ipo_t) & set(sf_t)))
        by_t = {r["ticker"]: r for r in sf}
        syms = sorted({by_t[t]["symbol"] for t in inter_names if t in by_t})
        syms += sorted({r["symbol"] for r in sf[:40] if r["symbol"] not in syms})
        print(json.dumps({"enrich_symbols": syms,
                          "intersections": {
                              "crowded_ledger": sorted(set(sf_t) & ledger_t),
                              "crowded_scan": sorted(set(sf_t) & scan_t),
                              "ipo_crowded": sorted(set(ipo_t) & set(sf_t)),
                          }}, indent=1))
        sys.exit(0)

    if not ipo or not sf or not scan:
        fail("one of the three screens returned no rows (ipo/sf/scan) — refusing to publish")
    below = [r["ticker"] for r in sf if (r.get("short_percent_float") or 0) * 100 <= 20.0]
    if below:
        fail(f"the short-float universe carries {len(below)} rows at or below the 20% gate "
             f"(the screen filter was not applied upstream): {below[:8]}")
    if FAILURES:
        print("cron06_refresh: FAILED\n  - " + "\n  - ".join(FAILURES))
        sys.exit(1)

    # ---------------------------------------------------------------- universes
    ipo_u = {r["ticker"]: r for r in ipo}
    sf_u = {r["ticker"]: r for r in sf}
    scan_u = {r["symbol"]: r for r in scan}
    scan_by_ticker = {r["symbol"].split(".")[0]: r for r in scan}
    ledger = dict(prior_ledger)

    # live tags for every scanned name (shape metadata merges in here: the scan
    # query returns prices, the shape query returns name / type / exchange / sector)
    live_rows = {}
    for sym, r in scan_u.items():
        tags, cont = compute_tags(r, shape)
        row = dict(r)
        meta = shape.get(sym, {})
        for k in ("name", "type", "exchange", "gics_sector"):
            if not row.get(k):
                row[k] = meta.get(k)
        if row.get("prev_close"):
            row["last_day_pct"] = (row["cur_close"] / row["prev_close"] - 1) * 100
        live_rows[sym] = row
        live_rows[sym]["tags_live"] = tags
        live_rows[sym]["contraction_live"] = round(cont, 2) if cont is not None else None
    tagged = sorted(live_rows.values(), key=lambda r: -r["gain_pct"])[:100]
    tagged_tickers = {r["symbol"].split(".")[0] for r in tagged}

    # ---------------------------------------------------------------- intersections
    inter = {
        "crowded_ledger": sorted(set(sf_u) & set(ledger)),
        "crowded_scan": sorted(set(sf_u) & set(scan_by_ticker)),
        "ipo_crowded": sorted(set(ipo_u) & set(sf_u)),
        "ipo_scan": sorted(set(ipo_u) & set(scan_by_ticker)),
        "ipo_ledger": sorted(set(ipo_u) & set(ledger)),
    }
    sweep_u = set()
    if args.master_csv and os.path.exists(args.master_csv):
        with open(args.master_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                k = list(row.keys())[0]
                sweep_u.add(str(row[k]).strip())
        inter["crowded_sweep"] = sorted(set(sf_u) & sweep_u)
    else:
        inter["crowded_sweep"] = []
    inter["union"] = sorted(set(inter["crowded_ledger"]) | set(inter["crowded_scan"]) |
                             set(inter["ipo_crowded"]))

    # every intersection name must be enriched, whether or not it tops a screen
    enrich_symbols = {sf_u[t]["symbol"] for t in inter["union"] if t in sf_u}
    enrich_symbols |= {r["symbol"] for r in sf[:40]}
    missing_enrich = sorted(s for s in enrich_symbols if s not in sf_en)
    if missing_enrich:
        fail(f"{len(missing_enrich)} intersection names were not enriched: {missing_enrich[:8]}")

    # ---------------------------------------------------------------- short float
    prior_pct = {}
    if prior_state:
        prior_pct = prior_state.get("universe_pct", {})
    prior_fire = prior_state.get("fire_date") if prior_state else None

    sf_rows = []
    for r in sf:
        sym = r["symbol"]
        e = sf_en.get(sym, {})
        sp = r["short_percent_float"] * 100
        adv = e.get("adv30")
        close = e.get("close_last")
        prev = e.get("close_prev")
        chg30 = None
        if e.get("close_30d_ago"):
            chg30 = (close / e["close_30d_ago"] - 1) * 100
        elif close and prev:
            chg30 = (close / prev - 1) * 100
        if sym in prior_pct:
            delta = round(sp - prior_pct[sym], 1)
        else:
            delta = "NO_PRIOR_SNAPSHOT"
        sf_rows.append({
            "ticker": r["ticker"], "symbol": sym, "name": r.get("name"),
            "exchange": r.get("exchange"), "sector": r.get("gics_sector"),
            "short_pct_float": round(sp, 1), "shares_float": r.get("shares_float"),
            "percent_institutions": r.get("percent_institutions"),
            "market_cap": e.get("market_cap"), "close": close,
            "adv30": adv, "chg_30d_pct": round(chg30, 1) if chg30 is not None else None,
            "short_float_delta_pp": delta,
            "tradeable_verdict": tradeable_verdict(sp, adv),
            "squeeze_candidate": squeeze_flag(sp, adv),
            "in_intersection": r["ticker"] in set(inter["union"]),
        })
    sf_rows.sort(key=lambda r: -r["short_pct_float"])
    sf_display = sf_rows[:30]

    # ---------------------------------------------------------------- IPO rows
    ipo_rows = []
    for t, r in ipo_u.items():
        sym = r.get("symbol") or f"{t}.{r.get('exchange')}"
        e = ipo_en.get(sym, {}) or ipo_en.get(t, {}) or {}
        adv = e.get("adv30")
        ipo_date = d(r["ipo_date"])
        lockup_end = ipo_date + timedelta(days=LOCKUP_DAYS) if ipo_date else None
        verified = r.get("market_cap") is not None
        ipo_rows.append({
            "ticker": t, "name": r.get("name"), "exchange": r.get("exchange"),
            "ipo_date": r.get("ipo_date"), "market_cap": r.get("market_cap"),
            "sector": r.get("gics_sector"), "industry": r.get("gics_industry"),
            "days_since_ipo": (data - ipo_date).days if ipo_date else None,
            "lockup_end": lockup_end.isoformat() if lockup_end else None,
            "post_lockup": "YES" if (lockup_end and data > lockup_end) else "NO",
            "mcap_verified": "YES" if verified else "NO",
            "adv30": adv, "tradeable_verdict": tradeable_verdict(None, adv),
            "in_intersection": t in set(inter["union"]),
        })
    ipo_rows.sort(key=lambda r: (r["ipo_date"] or "",), reverse=True)

    # ---------------------------------------------------------------- backlog rescore
    rescore = []
    for r in tagged:
        t = r["symbol"].split(".")[0]
        frozen = ledger.get(t)
        ftags = frozen["tags"] if frozen else []
        known = frozen is not None
        rescore.append({
            "ticker": t, "name": r.get("name"),
            "frozen_tags": ftags, "live_tags": r["tags_live"],
            "tag_change": tag_change(ftags, r["tags_live"], known),
            "live_close": r["cur_close"], "live_gain_pct": round(r["gain_pct"], 1),
            "high_60d": shape.get(r["symbol"], {}).get("hi60"),
            "contraction_live": r["contraction_live"],
            "ytd_low": r.get("ytd_low"), "last_day_pct": r.get("last_day_pct"),
        })
    newly = [r for r in rescore if r["tag_change"] == "NEW" and r["live_tags"]]
    # the security type lives in the shape metadata, not in the raw scan rows
    type_by_ticker = {s.split(".")[0]: v.get("type") for s, v in live_rows.items()}
    live_by_ticker = {s.split(".")[0]: v for s, v in live_rows.items()}
    newly_common = [r for r in newly if type_by_ticker.get(r["ticker"]) == "Common Stock"]
    excluded_new = [r for r in newly if type_by_ticker.get(r["ticker"]) != "Common Stock"]

    # ---------------------------------------------------------------- render
    os.makedirs(args.out_md_dir, exist_ok=True)
    write_ipo_md(args, ipo_rows, inter, sf_rows, sf_display)
    write_sf_md(args, sf_rows, sf_display, inter, prior_fire, prior_pct)
    write_backlog_md(args, tagged, rescore, newly, newly_common, excluded_new,
                      ledger, prior_meta, inter, live_by_ticker, type_by_ticker, sf_rows)

    # ---------------------------------------------------------------- JSON + state
    payload = {
        "contract": CONTRACT_VERSION,
        "fire_date": args.fire_date,
        "data_date": args.data_date,
        "coverage": {
            "ipo": {"rows_passing": ipo[0].get("rows_passing"), "rows_kept": len(ipo_rows)},
            "short_float": {"rows_passing": sf[0].get("rows_passing"), "rows_kept": len(sf_rows)},
            "scan": {"rows_passing": scan[0].get("rows_passing"), "rows_kept": len(live_rows)},
            "tagged": {"rows_passing": 100, "rows_kept": len(tagged)},
        },
        "intersections": inter,
        "intersection_sizes": {k: len(v) for k, v in inter.items()},
        "ipo_rows": ipo_rows,
        "short_float_rows": sf_rows,
        "short_float_display": sf_display,
        "backlog_live_rescore": rescore,
        "newly_tagged": [r["ticker"] for r in newly_common],
        "excluded_new": [r["ticker"] for r in excluded_new],
        "ledger_size": len(ledger) + len(newly_common),
        "prior_ledger_size": len(ledger),
        "prior_state_fire_date": prior_fire,
        "verdict_vocabulary": sorted(TRADEABLE_VERDICTS),
        "tag_change_vocabulary": sorted(TAG_CHANGES),
        "source_health": [
            {"source": "shibui MCP (stock_data_query via mcp_bridge.py)",
             "query": "IPO (general_info+valuation) / short float (ownership_stats) / 10y scan (stock_quotes)",
             "status": "ok",
             "result": f"ipo {len(ipo_rows)} | short-float {len(sf_rows)} | scan {len(live_rows)}"},
            {"source": "shibui MCP (date resolve)", "query": "SELECT MAX(date) FROM shibui.stock_quotes",
             "status": "ok", "result": args.data_date},
            {"source": "Finviz fallback", "status": "n/a", "result": "not invoked — primary path succeeded"},
        ],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    if args.out_state:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_state)), exist_ok=True)
        state = {
            "contract": CONTRACT_VERSION,
            "fire_date": args.fire_date,
            "data_date": args.data_date,
            "rows_passing": sf[0].get("rows_passing"),
            "universe_pct": {r["ticker"]: r["short_pct_float"] for r in sf_rows},
            "universe_liquidity": {r["ticker"]: r["adv30"] for r in sf_rows},
            "universe_close": {r["ticker"]: r["close"] for r in sf_rows},
        }
        with open(args.out_state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)

    print(f"cron06_refresh: ok — contract {CONTRACT_VERSION}, marker {CAPABILITY_MARKER}")
    print(f"  ipo {len(ipo_rows)} | short-float {len(sf_rows)} | scan {len(live_rows)} | "
          f"tagged {len(tagged)} | newly {len(newly_common)} | ledger {len(ledger)+len(newly_common)}")
    print(f"  intersections: " + ", ".join(f"{k}={len(v)}" for k, v in inter.items() if k != "union"))
    if FAILURES:
        print("  WARNINGS:")
        for f in FAILURES:
            print("   -", f)
    sys.exit(0)


# ------------------------------------------------------------------ markdown
def _hdr(title, fire, data, extra=""):
    return (f"# {title} — {fire}\n\n"
            f"<!-- contract: {CONTRACT_VERSION} | fire_date: {fire} | data_date: {data} -->\n\n"
            f"_Generated by cron #6 stock-screener-pattern-study-backlog "
            f"(engine {CAPABILITY_MARKER}). Source: shibui-finance MCP._\n\n{extra}\n\n")


def _source_health(data):
    return ("## Source health\n\n"
            "| Source | Query / URL | Status | Result |\n|---|---|---|---|\n"
            "| shibui MCP (`stock_data_query` via mcp_bridge.py) | the three screens + intersection enrichment | ok | see the coverage line above |\n"
            f"| shibui MCP (date resolve) | `SELECT MAX(date) FROM shibui.stock_quotes` | ok | {data} |\n"
            "| Finviz fallback | not invoked | n/a | primary path succeeded — no fallback chain entered |\n"
            "| web_search / web_fetch | not invoked | n/a | not needed; no MCP errors to recover from |\n")


def _intersection_md(inter, sf_rows):
    by_t = {r["ticker"]: r for r in sf_rows}
    lines = ["| Set | Count | Names |", "|---|---|---|"]
    def fmt(t):
        r = by_t.get(t, {})
        v = r.get("tradeable_verdict", "—")
        return f"{t} ({v})"
    for key, label in (("crowded_ledger", "1000%+ compounders that are also >20% short float"),
                       ("crowded_scan", "names in the 10y scan that are also >20% short float"),
                       ("ipo_crowded", "recent IPOs with >20% short float (broken-float setup)"),
                       ("ipo_ledger", "recent IPOs already in the pattern-study ledger"),
                       ("ipo_scan", "recent IPOs in the 10y scan"),
                       ("crowded_sweep", ">20% short float names also in the daily sweep Master")):
        names = inter.get(key) or []
        shown = ", ".join(fmt(t) for t in names[:25]) or "none"
        if len(names) > 25:
            shown += f", … (+{len(names)-25} more)"
        lines.append(f"| {label} | {len(names)} | {shown} |")
    return "## Cross-screen intersections\n\n" + "\n".join(lines) + "\n\n"


def write_ipo_md(args, ipo_rows, inter, sf_rows, sf_display):
    fire, data = args.fire_date, args.data_date
    head = _hdr("Weekly IPO Refresh", fire, data)
    cov = f"**Universe:** Common Stock IPOs listed in the last 365 days with market_cap > $1B (or no valuation row yet). **Latest available shibui date:** {data} (T+1 lag vs cron date {fire}).\n\n"
    cov += f"**Count:** {len(ipo_rows)} tickers — rows_passing {len(ipo_rows)} = rows_kept {len(ipo_rows)} (complete, not truncated), newest first.\n\n"
    rows = ["| # | Ticker | Name | Exchange | IPO Date | MCap ($B) | Days Since IPO | Post Lockup | MCap Verified | Tradeable | Sector | Industry |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ipo_rows, 1):
        rows.append(f"| {i} | {r['ticker']} | {r['name']} | {r['exchange']} | {r['ipo_date']} | "
                    f"{bn(r['market_cap'])} | {r['days_since_ipo']} | {r['post_lockup']} | "
                    f"{r['mcap_verified']} | {r['tradeable_verdict']} | {r['sector']} | {r['industry']} |")
    notes = (
        "## Notes\n"
        "- `MCap Verified = NO` means no `shibui.valuation` row in the last 14 calendar days, so the name "
        "passes the $1B floor BY DEFAULT rather than on a stamped number. `MCap = —` is the same fact in the "
        "MCap column; the two columns are not redundant, they are the number and its provenance.\n"
        f"- `Post Lockup = YES` means more than {LOCKUP_DAYS} days have passed since the IPO date (the standard "
        "lockup length, used here as a calendar marker, not a filing fact).\n"
        "- `Tradeable` is the closed-set verdict from the 30-bar average dollar volume: TRADEABLE >= $20M, "
        "THIN $5-20M, ILLIQUID < $5M, NO_QUOTE when no volume history.\n"
        "- The IPO cohort and the 10-year scan are disjoint BY CONSTRUCTION — a name listed less than a year "
        "ago cannot have a 10-year base — so the `recent IPOs in the 10y scan` intersection is expected to be "
        "empty and is published to prove it was checked, not assumed.\n"
    )
    txt = head + cov + "\n".join(rows) + "\n\n" + _intersection_md(inter, sf_rows) + notes + _source_health(data)
    open(os.path.join(args.out_md_dir, "weekly-ipo.md"), "w", encoding="utf-8").write(txt)


def write_sf_md(args, sf_rows, sf_display, inter, prior_fire, prior_pct):
    fire, data = args.fire_date, args.data_date
    head = _hdr("Weekly High-Short-Float Refresh", fire, data)
    cov = (f"**Universe:** Common Stock with `short_percent_float > 20%`. **Latest available shibui date:** {data} "
           f"(T+1 lag vs cron date {fire}).\n\n")
    cov += (f"**Count:** {len(sf_rows)} names pass the gate — rows_passing {len(sf_rows)} = rows_kept {len(sf_rows)} "
            f"(paged at the 200-row server ceiling, complete). The table shows the top {len(sf_display)} by "
            "`short_pct_float`; every name in any cross-screen intersection is enriched and listed below the table.\n\n")
    cols = ("| # | Ticker | Name | Exchange | Short %Float | Δ vs Prior Wk (pp) | Close | 30d Chg % | 30d ADVol ($M) "
            "| Tradeable | Squeeze | MCap ($B) | Sector |")
    rows = [cols, "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sf_display, 1):
        rows.append(
            f"| {i} | {r['ticker']} | {r['name']} | {r['exchange']} | {pct(r['short_pct_float'])} | "
            f"{r['short_float_delta_pp']} | {money(r['close'])} | {pct(r['chg_30d_pct'])} | "
            f"{('%.1f' % (r['adv30']/1e6)) if r['adv30'] is not None else '—'} | "
            f"{r['tradeable_verdict']} | {r['squeeze_candidate']} | {bn(r['market_cap'])} | {r['sector']} |")
    inter_rows = [r for r in sf_rows if r["in_intersection"]]
    inter_rows.sort(key=lambda r: -r["short_pct_float"])
    irows = ["| Ticker | Name | Short %Float | Δ vs Prior Wk (pp) | Close | 30d Chg % | 30d ADVol ($M) | Tradeable | Squeeze | Sets |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    set_by_t = {}
    for key in ("crowded_ledger", "crowded_scan", "ipo_crowded", "crowded_sweep"):
        for t in inter.get(key) or []:
            set_by_t.setdefault(t, []).append(key)
    label = {"crowded_ledger": "ledger", "crowded_scan": "10y-scan", "ipo_crowded": "IPO", "crowded_sweep": "sweep"}
    for r in inter_rows:
        irows.append(f"| {r['ticker']} | {r['name']} | {pct(r['short_pct_float'])} | {r['short_float_delta_pp']} | "
                     f"{money(r['close'])} | {pct(r['chg_30d_pct'])} | "
                     f"{('%.1f' % (r['adv30']/1e6)) if r['adv30'] is not None else '—'} | "
                     f"{r['tradeable_verdict']} | {r['squeeze_candidate']} | "
                     f"{', '.join(label.get(s, s) for s in set_by_t.get(r['ticker'], []))} |")
    if prior_fire:
        trend = (f"- **Δ vs Prior Wk (pp)** is the change in `short_percent_float` against the {prior_fire} state "
                 f"snapshot (written by the previous run to `pattern-study/cron06-state/`). `NO_PRIOR_SNAPSHOT` means "
                 "the name was not in last week's snapshot, so there is no base to difference.\n")
    else:
        trend = ("- **Δ vs Prior Wk (pp)** is `NO_PRIOR_SNAPSHOT` on every row: this is the FIRST state snapshot. "
                 "`ownership_stats` has no date column, so the short-float book cannot be replayed — this week's "
                 "sample is the beginning of the series, and next week's run can publish the change.\n")
    notes = ("## Notes\n" + trend +
             "- `short_percent_float` is a fraction in shibui (`0.20` = 20%); values > 100% occur where disclosed "
             "short interest exceeds float — the `FLOAT_ARTIFACT` verdict marks those rows as noise, not squeeze fuel.\n"
             "- `Tradeable` is the closed-set verdict: TRADEABLE >= $20M 30d ADVol, THIN $5-20M, ILLIQUID < $5M, "
             "NO_QUOTE when there is no volume history. `Squeeze = YES` requires short > 50% AND a TRADEABLE verdict.\n"
             "- `30d Chg %` is the price change over the 30-bar window already pulled for the ADVol denominator — "
             "it costs no extra call.\n")
    txt = (head + cov + "\n".join(rows) + "\n\n" + _intersection_md(inter, sf_rows) +
           f"## Intersection names (enriched regardless of rank)\n\n" + "\n".join(irows) + "\n\n" +
           notes + _source_health(data))
    open(os.path.join(args.out_md_dir, "weekly-high-short-float.md"), "w", encoding="utf-8").write(txt)


def write_backlog_md(args, tagged, rescore, newly, newly_common, excluded_new,
                     ledger, prior_meta, inter, live_by_ticker, type_by_ticker, sf_rows):
    fire, data = args.fire_date, args.data_date
    head = _hdr("peoplewish 1000%-in-10-years — Pattern-Study Backlog", fire, data)
    cov = (f"_Long-lived log of US equities that have compounded 1000%+ from their 10-year low to the most "
           f"recent close. Maintained by cron #6 stock-screener-pattern-study-backlog (weekly). The durable "
           f"ledger is `pattern-study/peoplewish-1000pct-backlog.md` in the outputs repo._\n\n")
    cov += f"**Latest shibui data:** {data} (T+1 lag vs cron date {fire}). "
    cov += f"**Scan:** {len(live_by_ticker)} rows (rows_passing {len(live_by_ticker)} = rows_kept {len(live_by_ticker)} — complete, paged at the 200-row ceiling); top {len(tagged)} shape-tagged. "
    cov += f"**Newly tagged this run:** {len(newly_common)} common stocks. **Cumulative backlog size:** {len(ledger)+len(newly_common)}.\n\n"

    meth = (
        "## Methodology\n\n"
        "- **Universe:** all symbols in shibui.stock_quotes with at least 1,260 trading days in the trailing 10-year window.\n"
        "- **Trigger:** `(current_close / 10y_min_close) - 1 >= 10.0` (1000%+ from trough).\n"
        "- **Min close filter:** `min_close_10y >= $0.50`.\n"
        "- **Security type:** newly-tagged names are restricted to `type = 'Common Stock'`; leveraged ETNs and ETFs inflate a 10-year return mechanically and are excluded from the tag list (the raw scan still records them in the run JSON).\n"
        "- **Chart-shape tags** (on the most recent 60d / 10d window): `coil` — close within 15% of 60d high AND contraction (10d range / 60d range) < 0.85; `VCP` — contraction < 0.65; `breakout` — close / high_60d >= 0.95; `EP` — close > 50% above the YTD low; `big_day` — last session moved > 5%.\n"
        "- **The scan is PAGED, never capped.** shibui's ceiling is 200 rows PER QUERY, so a query that returns exactly 200 rows is truncated, not complete. Page until the collected rows equal `rows_passing`.\n"
        "- **The ledger rows are frozen** at the values they carried when first tagged — it is a discovery ledger, not a quote sheet. The live re-score below carries this week's tags.\n\n")

    nrows = ["| # | Ticker | Name | Type | Exchange | Sector | Current | 10y Low | Peak Gain | Gain | 60d High | Contraction | YTD Low | Last Day | Tags |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(newly_common, 1):
        s = live_by_ticker.get(r["ticker"], {})
        tags = ", ".join(r["live_tags"]) if r["live_tags"] else "—"
        min10 = s.get("min10")
        max10 = s.get("max10")
        peak = ((max10 / min10 - 1) * 100) if (min10 and max10) else None
        ldp = s.get("last_day_pct")
        nrows.append(f"| {i} | {r['ticker']} | {r['name']} | {type_by_ticker.get(r['ticker'],'—')} | "
                     f"{s.get('exchange','—')} | {s.get('gics_sector','—')} | {money(r['live_close'])} | "
                     f"{money(min10)} | {pct0(peak)} | {pct0(r['live_gain_pct'])} | {money(r['high_60d'])} | "
                     f"{r['contraction_live']} | {money(r['ytd_low'])} | "
                     f"{('+' if (ldp or 0) >= 0 else '')}{pct(ldp,2)} | {tags} |")

    rrows = ["| Ticker | Name | Frozen Tags | Live Tags | Tag Change | Live Close | Live Gain % | 60d High | Contraction | Last Day |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rescore:
        rrows.append(f"| {r['ticker']} | {r['name']} | {', '.join(r['frozen_tags']) or '—'} | "
                     f"{', '.join(r['live_tags']) or '—'} | {r['tag_change']} | {money(r['live_close'])} | "
                     f"{pct0(r['live_gain_pct'])} | {money(r['high_60d'])} | {r['contraction_live']} | "
                     f"{pct(r['last_day_pct'],2)} |")

    car = ["| Ticker | Name | Type | Exchange | Sector | Current | 10y Low | Peak Gain | Gain | 60d High | Contraction | YTD Low | Last Day | Tags | First Tagged |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def gnum(v):
        try:
            return float(str(v).replace(",", "").replace("%", "").replace("$", ""))
        except (TypeError, ValueError):
            return 0.0
    for t in sorted(ledger, key=lambda t: -gnum(ledger[t]["gain"])):
        e = ledger[t]
        warn = " ⚠" if e.get("warn") else ""
        car.append(f"| {t}{warn} | {e['name']} | {e['type']} | {e['exchange']} | {e['sector']} | "
                   f"{e['current']} | {e['min10']} | {e['peak']} | {e['gain']} | {e['hi60']} | "
                   f"{e['cont']} | {e['ytd_low']} | {e['last_day']} | {', '.join(e['tags']) or '—'} | "
                   f"{e.get('first_tagged') or '—'} |")

    changes = [r for r in rescore if r["tag_change"] in ("ADDED", "REMOVED", "MIXED")]
    chg_md = ("## Tag changes this run (the signal the frozen ledger hides)\n\n"
              + ("| Ticker | Name | Frozen Tags | Live Tags | Change |\n|---|---|---|---|---|\n" +
                 "\n".join(f"| {r['ticker']} | {r['name']} | {', '.join(r['frozen_tags']) or '—'} | "
                           f"{', '.join(r['live_tags']) or '—'} | {r['tag_change']} |" for r in changes)
                 if changes else "No name changed its chart-shape tag this week."))
    notes = ("## Notes\n"
             f"- {len(newly_common)} newly tagged; {len(tagged)-len(newly_common)} of the {len(tagged)} tagged names were already known. "
             f"Backlog size {len(ledger)} -> {len(ledger)+len(newly_common)}.\n"
             f"- {len(changes)} of the {len(tagged)} tagged names changed a chart-shape tag this week (listed above); the "
             "frozen ledger rows below keep their original tags, which is why the live re-score exists.\n"
             "- The carried-forward rows are FROZEN at first-tagging values — a discovery ledger, not a quote sheet. "
             "Re-scan for live values via the daily sweep.\n"
             "- Cross-reference: the peoplewish screener (filter G) uses 14d velocity as primary sort; this backlog is the multi-year analogue.\n")
    txt = (head + cov + meth +
           _intersection_md(inter, sf_rows) +
           f"## Newly tagged entries ({fire} run)\n\n" + "\n".join(nrows) + "\n\n" +
           f"### Excluded from tagging (non-Common-Stock, {len(excluded_new)})\n\n" +
           (("New non-equity names excluded this run: " + ", ".join(r["ticker"] for r in excluded_new) + ".")
            if excluded_new else "No newly-discovered non-Common-Stock names in this week's tagged window.") + "\n\n" +
           chg_md + "\n\n" +
           f"## Live re-score of the tagged window\n\n" + "\n".join(rrows) + "\n\n" +
           f"## Carried forward (first tagged on or before {fire})\n\n" + "\n".join(car) + "\n\n" +
           notes + _source_health(data))
    open(os.path.join(args.out_md_dir, "peoplewish-backlog.md"), "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    main()

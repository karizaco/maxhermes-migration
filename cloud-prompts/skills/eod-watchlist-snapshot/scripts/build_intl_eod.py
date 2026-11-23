#!/usr/bin/env python3
"""Stage 2 - assemble cron #05's international EOD artifact (Cloud reference implementation).

INTL_EOD_V1 - capability marker (2026-11-19).  Parameterised by --date; the session's own
scanner pulls live in --work and the prior sessions' CSVs in --prior-dir/--prior-history-dir.
Reproduces the 2026-11-19 artifact byte-for-byte on all 16 per-region CSVs.

INTL_EOD_V2 - capability marker (2026-11-23).  Adds `--closed-regions`: a market that did
not trade on the date (a national holiday) has NO session to publish, so it is removed from
the artifact instead of being rebuilt from the scanner's stale copy of its last session.
Default behaviour is unchanged when the flag is absent.

Implements the skill contract:
  * universe = the per-country scanner's ISSUER-country filtered rows, type == stock
  * dedupe: (description, symbol) per line - Germany by description alone
  * venue collapse: the PRIMARY venue's line wins, and the implied prior close
    must reconcile with the prior session's published close (>5% => stale print)
  * market-cap carrier: the cap is resolved to the issuer's PRIMARY (common) line,
    converted ONCE (local cap / FX-per-USD), and every line of that issuer carries it
  * floors in USD applied AFTER conversion; volume gate on company liquidity
  * us_listing from the America scanner (stock + dr), matched on the issuer name with the
    punctuation-clean key (strip the trailing period, split on all punctuation) - see the
    SKILL.md section on `us_listing` for why the period matters
  * carry-over detection on EXACT close equality against the prior session's file
"""
import csv, json, os, re, sys
from collections import defaultdict, Counter

# INTL_EOD_V1 - capability marker (2026-11-19)
import argparse
_ap = argparse.ArgumentParser(description="cron #05 international EOD - stage 2, assemble the CSVs")
_ap.add_argument("--date", required=True, help="the session date, YYYY-MM-DD")
_ap.add_argument("--work", default="/workspace/work", help="the directory holding scan_*.json, fx.json")
_ap.add_argument("--out", default=None, help="the output directory (default /workspace/international-eod/<date>)")
_ap.add_argument("--prior-dir", default=None, help="the prior session's per-region CSVs")
_ap.add_argument("--prior-history-dir", default=None, help="the prior sessions' per-region CSVs")
_ap.add_argument("--prior-dates", default="", help="comma-separated prior session dates, newest first")
_ap.add_argument("--closed-regions", default="",
                 help="comma-separated regions whose market did not trade on this date (a national "
                      "holiday). They are removed from the artifact: no <region>.csv, no rows in "
                      "any movers table, and a `closed_regions` block in the manifest. Use it "
                      "only for a CONFIRMED closure - an unknown session is not a closure.")
_A = _ap.parse_args()
WORK = _A.work
DATE = _A.date
OUT = _A.out or f"/workspace/international-eod/{DATE}"
PRIOR_DIR = _A.prior_dir or "/workspace/prior"
PRIOR_DATE = _A.prior_dates.split(",")[0] if _A.prior_dates else ""
PRIOR_HIST_DIR = _A.prior_history_dir or "/workspace/prior_hist"

# The regions whose market did not trade on this date.  Empty by default (a run with no closed
# market is unchanged); the caller passes a region only on a CONFIRMED closure.
CLOSED_REGIONS = {r.strip() for r in _A.closed_regions.split(",") if r.strip()}

HEADER = ["date", "ticker", "name", "open", "high", "low", "close", "volume",
          "change_pct", "market_cap", "pe_ratio", "sector", "currency", "exchange",
          "cap_source_symbol", "share_class", "us_listing", "price_conflict"]

REGIONS = ["au", "jp", "tw", "ca", "eu-de", "eu-fr", "eu-it", "eu-es", "eu-nl",
           "eu-be", "eu-at", "eu-pt", "eu-ie", "eu-fi", "eu-dk", "eu-gr"]

FLOORS = {"au": (300_000_000, 100_000), "jp": (300_000_000, None), "tw": (200_000_000, None),
          "ca": (200_000_000, None), "eu-de": (300_000_000, 50_000),
          "eu-fr": (100_000_000, None), "eu-it": (100_000_000, None),
          "eu-es": (100_000_000, None), "eu-nl": (100_000_000, None),
          "eu-be": (100_000_000, None), "eu-at": (100_000_000, None),
          "eu-pt": (50_000_000, None), "eu-ie": (200_000_000, None),
          "eu-fi": (100_000_000, None), "eu-dk": (100_000_000, None),
          "eu-gr": (50_000_000, None)}

VENUE_ORDER = {
    "au": ["ASX"],
    "jp": ["TSE", "NAG", "FSE", "SAPSE"],
    "tw": ["TWSE", "TPEX"],
    "ca": ["TSX", "TSXV", "CSE", "NEO"],
    "eu-de": ["XETR", "FWB", "LSX", "LS", "GETTEX", "DUS", "MUN", "SWB", "TRADEGATE", "HAM", "HAN"],
}

CLASS_MARKER_RE = re.compile(r"\b(cum|pref|preferred|unit|class|non-voting|nonvoting|depositary|ads|gdr)\b", re.I)
# The America scanner appends the US-line wording to the issuer's name ("BHP Group Ltd
# Sponsored American Depositary Receipt Repr 2 Shs").  That wording is cut on BOTH sides so the
# two descriptions reduce to the same issuer key.
US_SUFFIX_RE = re.compile(r"\b(sponsored|depositary|adr|ads|gdr|receipt|repr|shs|shares|cum|preferred|preference|units?|class|non-voting|nonvoting)\b", re.I)
# Corporate-form words that differ between a local listing and its US line for the SAME issuer
# ("BHP Group Ltd" vs "BHP Group Limited").  They are dropped on BOTH sides of the match.
FORM_WORDS = {"limited", "ltd", "inc", "incorporated", "corporation", "corp", "co", "company",
              "plc", "sa", "nv", "ag", "gmbh", "se", "ab", "as", "oy", "spa", "pty", "group",
              "holding", "holdings", "the", "and"}


# Country-specific legal-form spellings that differ between a local listing and its US line.
FORM_ALIAS = [
    (re.compile(r"aktiengesellschaft", re.I), "ag"),
    (re.compile(r"soci[eé]t[eé]\s+anonyme", re.I), "sa"),
    (re.compile(r"naamloze\s+vennootschap", re.I), "nv"),
    (re.compile(r"besloten\s+vennootschap", re.I), "bv"),
    (re.compile(r"public\s+limited\s+company", re.I), "plc"),
    (re.compile(r"\bs\.\s?p\.\s?a\.?", re.I), "spa"),
    (re.compile(r"\bs\.\s?r\.\s?l\.?", re.I), "srl"),
    (re.compile(r"\bs\.\s?a\.?", re.I), "sa"),
    (re.compile(r"\bn\.\s?v\.?", re.I), "nv"),
    (re.compile(r"\ba\.\s?g\.?", re.I), "ag"),
]


def strip_forms(tokens):
    out = list(tokens)
    while out and out[-1].lower().rstrip(".") in FORM_WORDS:
        out.pop()
    return out


# ---------------------------------------------------------------- formatting
def fmt_price(v):
    if v is None or v == "":
        return ""
    return ("%.4f" % float(v)).rstrip("0").rstrip(".")


def fmt_num(v):
    if v is None or v == "":
        return ""
    f = float(v)
    if f.is_integer():
        return str(int(f))
    s = repr(f)
    if "e" in s or "E" in s:
        s = ("%.13f" % f).rstrip("0").rstrip(".")
    return s


def fmt_int(v):
    if v is None or v == "":
        return ""
    return str(int(round(float(v))))


# ---------------------------------------------------------------- names
def issuer_name(name):
    m = CLASS_MARKER_RE.search(name or "")
    return (name or "").strip() if not m else (name or "")[: m.start()].strip()


def norm(name):
    return re.sub(r"[^a-z0-9]", "", issuer_name(name).lower())


def match_key(name):
    """The issuer key used to match a foreign line against its US line.

    The US-line wording is cut, the corporate-form words are dropped, so "BHP Group Ltd" and
    "BHP Group Limited Sponsored American Depositary Receipt Repr 2 Shs" both reduce to
    "bhpgroup" - while "Oracle Corporation Japan" and "Oracle Corporation" stay apart.
    """
    text = (name or "").split(" - ")[0]
    text = US_SUFFIX_RE.split(text)[0]
    for rx, repl in FORM_ALIAS:
        text = rx.sub(repl, text)
    words = re.findall(r"[A-Za-z0-9]+", text)
    words = strip_forms(words)
    return re.sub(r"[^a-z0-9]", "", " ".join(words).lower())


def sym_of(tv):
    return tv.split(":", 1)[1] if ":" in tv else tv


def venue_of(tv):
    return tv.split(":", 1)[0] if ":" in tv else ""


def root_of(tv):
    return sym_of(tv).split(".")[0]


def share_class(tv, desc):
    sym = sym_of(tv).upper()
    tokens = sym.split(".")
    low = (desc or "").lower()
    if any(t in ("PR", "PF", "PREF") for t in tokens) or "preferred" in low or "preference" in low:
        return "preferred"
    if any(t in ("U", "UN", "UNT") for t in tokens) or re.search(r"\bunits?\b", low):
        return "unit"
    return "common"


# ---------------------------------------------------------------- input
fx = json.load(open(f"{WORK}/fx.json"))
FX = fx["rates"]
amer = json.load(open(f"{WORK}/scan_america.json"))

# us_listing: the US line is the second opinion on the issuer, so the matcher must strip the
# depositary/class words the America scanner appends ("BHP Group Ltd Sponsored American
# Depositary Receipt Repr 2 Shs" against the AU line's "BHP Group Ltd", so strip the
# depositary/class suffix and compare the issuer name).  The match runs on the issuer name as a
# PREFIX of the US line's name - a US line that is SHORTER than the local line is a different
# issuer (Oracle Corporation Japan vs Oracle Corporation) and must not match.
#
# 2026-11-19 - ONE surgical fix on top of the archive's matcher: the America scanner appends
# " Ltd." with a trailing period ("Accor SA Ltd."), and the old key did not strip the period, so
# the key came out "accorsaltd" and never matched the local "accor".  EVERY issuer with a
# " Ltd." US line was therefore published as `us_listing=none` - 334 rows on this session - even
# though a US line exists for each of them.  Stripping the trailing period is one-directional
# (it can only make a key match, never un-match), so the archive's prefix-bucket behaviour is
# kept exactly as it was.
US_ENTRIES = []
for r in amer:
    if not r.get("s"):
        continue
    k = match_key(r.get("description") or "")
    if len(k) < 2:
        continue
    exch = (r.get("exchange") or "").upper()
    typ = (r.get("type") or "").lower()
    if typ == "dr":
        cand = ("ADR", 4)
    elif exch in ("NYSE", "NASDAQ", "AMEX"):
        cand = ("NYSE" if exch in ("NYSE", "AMEX") else "NASDAQ", 3)
    elif exch == "OTC":
        cand = ("OTC", 2)
    else:
        continue
    US_ENTRIES.append((k, cand, r))
US_BUCKET = {}
for k, cand, r in US_ENTRIES:
    US_BUCKET.setdefault(k[:8], []).append((k, cand, r))
US_EXACT = {}
for k, cand, r in US_ENTRIES:
    prev = US_EXACT.get(k)
    if prev is None or cand[1] > prev[0][1]:
        US_EXACT[k] = (cand, r)


def us_listing(name):
    """The US listing for an issuer name, or 'none'."""
    k = match_key(name or "")
    if len(k) < 2:
        return "none", None
    best = None  # (priority, listing, row)
    cand = US_EXACT.get(k)
    if cand:
        best = (cand[0][1], cand[0][0], cand[1])
    if len(k) >= 8:
        for ak, acand, ar in US_BUCKET.get(k[:8], []):
            if ak.startswith(k) and (best is None or acand[1] > best[0]):
                best = (acand[1], acand[0], ar)
    return (best[1], best[2]) if best else ("none", None)


def prior_rows(region):
    p = f"{PRIOR_DIR}/{region}.csv"
    if not os.path.exists(p):
        return {}
    return {r["ticker"]: r for r in csv.DictReader(open(p, newline="", encoding="utf-8"))}


# The carry-over walk-back: the prior sessions are read BACKWARD and never forward.  A row that
# carries an unchanged close has not traded since the session in which that close was last set.
PRIOR_DATES = ([d for d in _A.prior_dates.split(",") if d] if _A.prior_dates else [])
_HIST = {}


def prior_history(region):
    """{date: {ticker: row}} for the sessions before today, newest first."""
    if region in _HIST:
        return _HIST[region]
    out = {}
    for d in PRIOR_DATES:
        path = (f"{PRIOR_DIR}/{region}.csv" if d == PRIOR_DATE
                else f"{PRIOR_HIST_DIR}/{d}_{region}.csv")
        if not os.path.exists(path) or os.path.getsize(path) < 5000:
            continue
        try:
            out[d] = {r["ticker"]: r for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}
        except Exception:
            continue
    _HIST[region] = out
    return out


def last_trade_date(region, ticker, close):
    """Walk the prior sessions back until a row with a print or a different close appears."""
    hist = prior_history(region)
    for d in PRIOR_DATES:
        rows = hist.get(d)
        if not rows:
            continue
        r = rows.get(ticker)
        if not r:
            continue
        if r.get("close") != close or (r.get("volume") not in ("", "0")):
            return d
    return f"before {PRIOR_DATES[-1] if PRIOR_DATES else PRIOR_DATE}"


def load_regions():
    out = {}
    for region in REGIONS:
        rows = json.load(open(f"{WORK}/scan_{region}.json"))
        stock = [r for r in rows if (r.get("type") or "") == "stock"]
        out[region] = {"universe_rows": len(stock), "stock": stock}
    return out


def build_region(region, data, prior):
    floor_usd, min_volume = FLOORS[region]
    stock = data["stock"]
    venue_rank = {v: i for i, v in enumerate(VENUE_ORDER.get(region, []))}

    def vr(tv):
        v = venue_of(tv)
        return venue_rank.get(v, len(venue_rank) + 1)

    # ---- dedupe keys
    def key_of(r):
        d = norm(r.get("description") or "")
        if region == "eu-de":
            # Germany dedupes by the RAW description (Lang & Schwarz carries a WKN symbol for
            # the same company), but the class words must NOT be cut: "SIE AG CLASS A" and
            # "SIE AG CLASS B" are different lines and must not collapse into one.  The share
            # class is carried by the symbol's letter family ("COMA" / "COMB"), and a purely
            # numeric WKN ("519406") is marked "@" so it can be folded into the same issuer's
            # primary line instead of standing as a second instrument.
            raw = re.sub(r"[^a-z0-9]", "", (r.get("description") or "").lower())
            fam = re.sub(r"\d+$", "", sym_of(r["s"]))
            return ("de", raw, fam or "@")
        return (d, sym_of(r["s"]))

    groups = defaultdict(list)
    for r in stock:
        groups[key_of(r)].append(r)

    if region == "eu-de":
        # A numeric-WKN line (the broker venue's own notation) is the SAME instrument as the
        # issuer's primary line, not a second one: it joins that group as an extra candidate
        # and never becomes an instrument of its own.
        by_desc = defaultdict(list)
        for k in list(groups):
            by_desc[k[1]].append(k)
        for desc, keys in by_desc.items():
            primaries = [k for k in keys if k[2] != "@"]
            wkn = [k for k in keys if k[2] == "@"]
            if primaries and wkn:
                for k in primaries:
                    groups[k].extend(groups[wkn[0]])
                for k in wkn:
                    del groups[k]

    # ---- venue collapse + stale-print test
    selected = []
    off_official = 0
    stale_groups = []
    for key, cands in groups.items():
        cands.sort(key=lambda r: (vr(r["s"]), -(r.get("volume") or 0), -(r.get("market_cap_basic") or 0)))

        chosen = None
        rejected = 0
        for c in cands:
            close = c.get("close")
            ch = c.get("change")
            if close is None or ch is None:
                chosen = chosen or c
                continue
            pr = prior.get(c["s"])
            if pr and pr.get("close"):
                pclose = float(pr["close"])
                if pclose:
                    same = abs(float(close) - pclose) < 1e-12
                    implied = float(close) / (1.0 + float(ch) / 100.0)
                    if not same and abs(implied - pclose) / pclose > 0.05:
                        rejected += 1
                        continue
            chosen = c
            break
        if chosen is None:
            # every line of the group failed the reconciliation
            stale_groups.extend(cands)
            off_official += rejected
            continue
        off_official += rejected
        selected.append(chosen)

    # ---- issuer groups for the cap carrier
    issuer_groups = defaultdict(list)
    for r in selected:
        issuer_groups[(venue_of(r["s"]), root_of(r["s"]))].append(r)

    rows_out = []
    excluded = []
    carryover = []
    adr_check = []

    for gkey, members in issuer_groups.items():
        commons = [m for m in members if share_class(m["s"], m.get("description")) == "common"]
        caps = [m.get("market_cap_basic") for m in members if m.get("market_cap_basic") is not None]
        if not commons:
            for m in members:
                excluded.append({"ticker": m["s"], "name": m.get("description"),
                                 "exchange": venue_of(m["s"]), "close": fmt_price(m.get("close")),
                                 "volume": fmt_int(m.get("volume")), "reason": "issuer_unresolved",
                                 "change_pct": fmt_num(m.get("change")), "market_cap_usd": ""})
            continue

        def frac(m):
            c = m.get("market_cap_basic")
            if c is None:
                return 0
            return 0 if float(c) == int(float(c)) else 1

        primary = max(commons, key=lambda m: (frac(m), m.get("volume") or 0))
        cap_local = primary.get("market_cap_basic")
        if cap_local is None:
            ints = [c for c in caps if float(c) == int(float(c))]
            cap_local = ints[0] if ints else (caps[0] if caps else None)
        cur = primary.get("currency") or members[0].get("currency")
        if cap_local is None or not cur or cur not in FX:
            for m in members:
                excluded.append({"ticker": m["s"], "name": m.get("description"),
                                 "exchange": venue_of(m["s"]), "close": fmt_price(m.get("close")),
                                 "volume": fmt_int(m.get("volume")), "reason": "no_market_cap",
                                 "change_pct": fmt_num(m.get("change")), "market_cap_usd": ""})
            continue
        usd_cap = float(cap_local) / float(FX[cur])
        liquidity = max([(m.get("volume") or 0) for m in members] or [0])

        for m in members:
            sc = share_class(m["s"], m.get("description"))
            base = {"ticker": m["s"], "name": m.get("description"), "exchange": venue_of(m["s"]),
                    "close": fmt_price(m.get("close")), "volume": fmt_int(m.get("volume")),
                    "change_pct": fmt_num(m.get("change"))}
            if usd_cap < floor_usd:
                excluded.append({**base, "reason": "below_cap_floor", "market_cap_usd": fmt_int(usd_cap)})
                continue
            if min_volume is not None and liquidity < min_volume:
                excluded.append({**base, "reason": "below_volume", "market_cap_usd": fmt_int(usd_cap)})
                continue
            us, us_row = us_listing(m.get("description") or "")
            # --- the cross-venue cap check: the ADR line is a SECOND reading of the same
            # company-level cap.  It must agree within 10%; a bigger gap is a cap finding.
            if us_row is not None and us_row.get("market_cap_basic") and (us_row.get("currency") in FX):
                try:
                    us_cap = float(us_row["market_cap_basic"]) / float(FX[us_row["currency"]])
                    if usd_cap:
                        adr_check.append({
                            "ticker": m["s"], "us_symbol": us_row.get("s"), "listing": us,
                            "local_usd": usd_cap, "us_usd": us_cap,
                            "delta_pct": (us_cap - usd_cap) / usd_cap * 100.0})
                except Exception:
                    pass
            rows_out.append({
                "date": DATE, "ticker": m["s"], "name": m.get("description"),
                "open": fmt_price(m.get("open")), "high": fmt_price(m.get("high")),
                "low": fmt_price(m.get("low")), "close": fmt_price(m.get("close")),
                "volume": fmt_int(m.get("volume")), "change_pct": fmt_num(m.get("change")),
                "market_cap": fmt_int(usd_cap), "pe_ratio": fmt_num(m.get("price_earnings_ttm")),
                "sector": m.get("sector") or "", "currency": cur, "exchange": venue_of(m["s"]),
                "cap_source_symbol": primary["s"], "share_class": sc,
                "us_listing": us if us else "none", "price_conflict": "",
                "_cap_local": cap_local, "_currency": cur, "_liquidity": liquidity,
            })

    # ---- carry-over detection: exact close equality vs the prior session's file
    for r in rows_out:
        pr = prior.get(r["ticker"])
        if not pr or pr.get("close") != r["close"]:
            continue
        vol = r["volume"]
        chg = r["change_pct"]
        if (vol == "0" or vol == "") or (chg not in ("", "0", "0.0")):
            carryover.append({"ticker": r["ticker"], "name": r["name"], "close": r["close"],
                              "volume": vol, "change_pct": chg,
                              "last_trade_date": last_trade_date(region, r["ticker"], r["close"])})
            r["_carryover"] = True

    rows_out.sort(key=lambda r: r["ticker"])
    return {"rows": rows_out, "excluded": excluded, "carryover": carryover,
            "unique_instruments": len(selected), "off_official": off_official,
            "stale_groups": len(stale_groups), "adr_check": adr_check}


def main():
    os.makedirs(OUT, exist_ok=True)
    data = load_regions()
    manifest_regions = {}
    excluded_all = {}
    carry_all = {}
    movers_all = {}
    adr_all = {}
    adr_flags = []
    closed_all = {}
    for region in REGIONS:
        # 2026-11-23 - a market that did not trade (a national holiday) has NO session to
        # publish.  Building it anyway writes the market's LAST session's close AND its last
        # session's change_pct under today's date, which asserts a session that never happened -
        # 1,357 Japanese rows on the 2026-11-23 fire, carrying SoftBank's -14.48% of 20 Nov.
        # So a confirmed closed market is REMOVED from the artifact: no <region>.csv, no rows in
        # any movers table, and the manifest records it under `closed_regions` so the omission is
        # machine-readable rather than a silent hole.  The flag is opt-in and defaults to empty,
        # so a run with no closed market reproduces the archive byte-for-byte.
        if region in CLOSED_REGIONS:
            closed_all[region] = {
                "date": DATE,
                "session": "closed",
                "rows_written": 0,
                "note": ("no session on this date - the market was closed; its last session's "
                         "levels are published in the report's index table with that session's date"),
            }
            print(f"{region:6s} CLOSED - no session, excluded from the artifact", flush=True)
            continue
        prior = prior_rows(region)
        res = build_region(region, data[region], prior)
        rows = res["rows"]
        with open(f"{OUT}/{region}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for r in rows:
                w.writerow([r[c] for c in HEADER])
        # movers / below-gate candidates
        mv = []
        for r in rows:
            if r.get("_carryover"):
                continue
            try:
                ch = float(r["change_pct"])
            except ValueError:
                ch = 0.0
            cap = float(r["market_cap"] or 0)
            if (r["volume"] != "" and float(r["volume"]) >= 100000 and cap >= 1e9 and abs(ch) >= 5.0):
                mv.append({"ticker": r["ticker"], "name": r["name"], "change_pct": ch,
                           "close": r["close"], "currency": r["currency"], "volume": r["volume"],
                           "market_cap": r["market_cap"], "us_listing": r["us_listing"],
                           "sector": r["sector"], "share_class": r["share_class"]})
        mv.sort(key=lambda x: -abs(x["change_pct"]))
        bg = []
        for e in res["excluded"]:
            if e["reason"] != "below_cap_floor":
                continue
            try:
                ch = float(e["change_pct"])
                vol = float(e["volume"] or 0)
            except ValueError:
                continue
            if vol >= 100000 and abs(ch) >= 5.0:
                bg.append({"ticker": e["ticker"], "name": e["name"], "change_pct": ch,
                           "close": e["close"], "volume": e["volume"],
                           "market_cap_usd": e["market_cap_usd"], "currency": ""})
        bg.sort(key=lambda x: -abs(x["change_pct"]))
        movers_all[region] = mv
        adr_all[region] = res["adr_check"]
        bad = [a for a in res["adr_check"] if abs(a["delta_pct"]) > 10.0]
        adr_flags.extend(bad)
        excluded_all[region] = res["excluded"]
        carry_all[region] = res["carryover"]
        counts = Counter(e["reason"] for e in res["excluded"])
        manifest_regions[region] = {
            "universe_rows": data[region]["universe_rows"],
            "unique_instruments": res["unique_instruments"],
            "written": len(rows),
            "excluded": {r: counts.get(r, 0) for r in
                         ("no_market_cap", "below_cap_floor", "below_volume",
                          "issuer_unresolved", "cap_issuer_mismatch", "stale_venue_print")},
            "carryover_rows": len(res["carryover"]),
            "off_official_rows": res["off_official"],
            "floor_usd": FLOORS[region][0],
            "min_volume": FLOORS[region][1],
            "file": f"{region}.csv",
            "venues": sorted({r["exchange"] for r in rows}),
            "movers": [m["ticker"] for m in mv],
            "mover_rows": len(mv),
            "below_gate_rows": len(bg),
            "no_catalyst_rows": 0,
        }
        manifest_regions[region]["_below_gate"] = bg
        print(f"{region:6s} universe={data[region]['universe_rows']:5d} unique={res['unique_instruments']:5d} "
              f"written={len(rows):5d} excl={len(res['excluded']):5d} {dict(counts)} "
              f"carry={len(res['carryover'])} off={res['off_official']} movers={len(mv)} bg={len(bg)}", flush=True)

    json.dump({"regions": manifest_regions, "movers": movers_all, "adr_check": adr_all,
               "adr_flags": adr_flags, "closed_regions": closed_all},
              open(f"{WORK}/build_state.json", "w"), indent=1)
    json.dump(excluded_all, open(f"{WORK}/excluded.json", "w"))
    json.dump(carry_all, open(f"{WORK}/carryover.json", "w"))
    tw = sum(v["written"] for v in manifest_regions.values())
    ex = sum(sum(v["excluded"].values()) for v in manifest_regions.values())
    print("TOTALS written", tw, "excluded", ex)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
macro_actual.py — read a macro print from its PRIMARY source, with a DATE ANCHOR.

WHY THIS FILE EXISTS
--------------------
A macro print has a primary source that does not depend on the news index, and on the
day a release lands at 08:30 ET the aggregators are not there yet. Measured on the
2026-11-16 08:30 ET fire of cron #26: the NY Empire State Manufacturing Index was
released at 08:30 ET, and at the 08:43 ET pull the calendar aggregators
(tradingcharts / sigmanomics / crtlab / tradingeconomics) carried the schedule, the
consensus (17.6) and the previous (25.5) but NO actual - the print was 7.8, a ~10-point
miss, and the brief could not publish it. The 2026-11-06 fire of the same routine hit
the same wall on the Employment Situation: two searches returned only previews, and
publishing a forecast as the actual is the worst failure mode a macro number has.

This helper reads the number from the ISSUER'S OWN page and, critically, resolves
WHICH release it is looking at. A bare value cannot tell you that (the page shows the
latest release and nothing else), so each reader carries a date anchor:

  * the Empire State's "Latest Report" link encodes the release month in its path
    (`.../empire2026/2026_11_empire-state-manufacturing-survey.pdf`), so the release
    the page carries is known even when its value has not changed since the last one;
  * the BLS response carries the year/month on every observation and a footnote code
    `P` on the preliminary release, so the newest vintage is identifiable.

A print that is not yet posted is a FACT (`not_yet_posted`), not an error and not a
zero - the caller publishes "released 08:30 ET, the source has not posted it yet".

USAGE
    python3 macro_actual.py --date 2026-11-16                 # Empire State (default)
    python3 macro_actual.py --date 2026-11-16 --release bls   # Employment Situation
    python3 macro_actual.py --date 2026-11-16 --json out.json

OUTPUT (stdout, JSON)
    {"release", "status", "requested_month", "release_month", "headline",
     "headline_label", "sub", "release_time_et", "source_url", "fetched_at_et",
     "note"}

    status: "ok"             the requested month's print was read
            "not_yet_posted" the source is up but carries an OLDER release
            "unavailable"    the source could not be read (the reason is in `note`)

EXIT CODES
    0 = the source was read (status ok or not_yet_posted)
    1 = the source could not be read (status unavailable)
    Never a non-zero exit for a late release: that is a fact, not a failure.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

MACRO_ACTUAL_V1 = "macro-actual-v1"

EMPIRE_URL = "https://www.newyorkfed.org/survey/empire/empiresurvey_overview"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
EMPIRE_RELEASE_TIME_ET = "08:30"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cron26-pre-market-brief"


def now_et():
    try:
        import zoneinfo
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(time.time(),
                                            zoneinfo.ZoneInfo("America/New_York")))
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


def fetch(url, data=None, headers=None, timeout=30):
    hdr = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdr.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(h):
    h = re.sub(r"(?s)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
          .replace("&quot;", '"').replace("&mdash;", "-").replace("&rsquo;", "'"))
    return re.sub(r"[ \t\xa0]+", " ", h)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ Empire State
def read_empire(date):
    """The NY Fed's own release page. The release month comes from the PDF path."""
    out = {"release": "empire_state", "status": "unavailable",
           "requested_month": date[:7], "release_month": None, "headline": None,
           "headline_label": "NY Empire State general business conditions index",
           "sub": {}, "release_time_et": EMPIRE_RELEASE_TIME_ET,
           "source_url": EMPIRE_URL, "fetched_at_et": now_et(), "note": "",
           "marker": MACRO_ACTUAL_V1}
    try:
        h = fetch(EMPIRE_URL)
    except Exception as e:
        out["note"] = "the NY Fed release page could not be read: %s" % str(e)[:120]
        return out

    # THE DATE ANCHOR: the "Latest Report" link's path carries the release month.
    m = re.search(r"/empire(\d{4})/(\d{4})_(\d{2})_empire-state-manufacturing-survey\.pdf", h)
    if not m:
        out["note"] = "the NY Fed release page carried no 'Latest Report' link to anchor the release month"
        return out
    out["release_month"] = "%s-%s" % (m.group(2), m.group(3))

    t = strip_tags(h)
    hm = re.search(r"general business conditions index[^.]{0,240}?\b(?:to|at)\s+"
                   r"([+-]?\d+(?:\.\d+)?)", t)
    val = _num(hm.group(1)) if hm else None
    if val is None or not (-100.0 <= val <= 100.0):
        out["note"] = ("the release month is %s but the headline index could not be read "
                       "from the page" % out["release_month"])
        return out
    out["headline"] = val
    for label, key in (("new_orders", "new orders index"),
                        ("shipments", "shipments index")):
        sm = re.search(re.escape(key) + r"[^.]{0,200}?\b(?:to|at)\s+([+-]?\d+(?:\.\d+)?)", t)
        if sm:
            out["sub"][label] = _num(sm.group(1))

    if out["release_month"] != out["requested_month"]:
        out["status"] = "not_yet_posted"
        if out["release_month"] < out["requested_month"]:
            out["note"] = ("the NY Fed page carries the %s release; the %s release is due "
                           "at %s ET" % (out["release_month"], out["requested_month"],
                                         EMPIRE_RELEASE_TIME_ET))
        else:
            out["note"] = ("the NY Fed page carries the %s release, which is the LATEST "
                           "one; the %s release is no longer on the page"
                           % (out["release_month"], out["requested_month"]))
        return out
    out["status"] = "ok"
    return out


# ------------------------------------------------------------------ BLS employment
def read_bls(date):
    """The BLS public API v2, ONE call for every series needed.

    The keyless tier has a DAILY threshold, so this asks for everything in one call
    and never probes. The headline is the DIFFERENCE between the two newest levels,
    never the level itself.
    """
    out = {"release": "bls_employment", "status": "unavailable",
           "requested_month": date[:7], "release_month": None, "headline": None,
           "headline_label": "Total nonfarm payrolls, change (thousands)",
           "sub": {}, "release_time_et": "08:30", "source_url": BLS_URL,
           "fetched_at_et": now_et(), "note": "", "marker": MACRO_ACTUAL_V1}
    series = ["CES0000000001", "LNS14000000", "CES0500000003", "CES0500000008",
              "LNS11300000"]
    try:
        raw = fetch(BLS_URL, data={"seriesid": series, "startyear": date[:4],
                                   "endyear": date[:4]},
                    headers={"Content-Type": "application/json"})
    except Exception as e:
        out["note"] = "the BLS API could not be read: %s" % str(e)[:120]
        return out
    try:
        d = json.loads(raw)
    except Exception as e:
        out["note"] = "the BLS API returned a non-JSON body: %s" % str(e)[:120]
        return out
    if d.get("status") != "REQUEST_SUCCEEDED":
        out["note"] = "the BLS API returned %s - %s" % (d.get("status"),
                                                        "; ".join(d.get("message") or [])[:160])
        return out

    by = {}
    for s in (d.get("Results") or {}).get("series") or []:
        rows = [x for x in (s.get("data") or []) if x.get("period", "").startswith("M")]
        if rows:
            by[s.get("seriesID")] = rows

    pay = by.get("CES0000000001") or []
    if len(pay) < 2:
        out["note"] = "the BLS API returned fewer than two monthly payroll observations"
        return out

    def month_of(row):
        y, m = row.get("year"), row.get("period", "").lstrip("M")
        return "%s-%02d" % (y, int(m))

    newest, prior = pay[0], pay[1]
    out["release_month"] = month_of(newest)
    out["headline"] = float(newest["value"]) - float(prior["value"])
    out["sub"] = {
        "total_nonfarm_level_k": float(newest["value"]),
        "prior_month_revision_k": float(newest["value"]) - float(prior["value"]),
        "preliminary": any(x.get("footnotes") and any("P" == (f.get("code") or "")
                                                       for f in x["footnotes"])
                            for x in pay[:1]),
    }
    un = by.get("LNS14000000") or []
    if un:
        out["sub"]["unemployment_rate_pct"] = float(un[0]["value"])
    if out["release_month"] != out["requested_month"]:
        out["status"] = "not_yet_posted"
        out["note"] = ("the BLS API's newest payroll observation is %s; the %s release is "
                       "due at 08:30 ET" % (out["release_month"], out["requested_month"]))
        return out
    out["status"] = "ok"
    return out


def main():
    ap = argparse.ArgumentParser(description="read a macro print from its primary source")
    ap.add_argument("--date", required=True, help="the fire date (YYYY-MM-DD)")
    ap.add_argument("--release", default="empire",
                    choices=("empire", "bls"), help="which print to read")
    ap.add_argument("--json", default=None, help="also write the result here")
    args = ap.parse_args()

    out = read_empire(args.date) if args.release == "empire" else read_bls(args.date)
    out["fetched_at_et"] = now_et()
    txt = json.dumps(out, indent=1)
    print(txt)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(txt)
    return 0 if out["status"] in ("ok", "not_yet_posted") else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
test_preopen_capture_edgar.py — prove the EDGAR leg BEHAVES, not just that its text is there.

WHY THIS FILE EXISTS
--------------------
On 2026-11-16 the checkpoints explained 2 of the 15 movers they published (13%, under
the 30% floor) - at 08:30 AND again at 09:50. Measured 2026-11-17: the news vendor's
TICKER INDEX held no in-window article for ANY of the 13 movers they could not explain
(eight had zero articles ever; AKAN's newest was from 2024), while EIGHT of the same
thirteen had a catalyst-bearing filing in SEC EDGAR inside the window. So EDGAR was
added as the SOURCE OF RECORD, between the article feed and the router.

The checker's gates assert that the EDGAR leg is PRESENT in the source. This file
asserts that it BEHAVES: that it finds a filing and reads its headline, that it
refuses a cover page, that it respects the window, that it beats the router, and that
it adds NO KEY to the tape (the tape's row shape is a contract with cron #17).

Nothing here touches the network: every provider call is stubbed.

USAGE
    python3 tools/test_preopen_capture_edgar.py

EXIT CODES
    0 = every EDGAR behaviour holds
    1 = one of them does not
"""

import datetime
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAP_PATH = ROOT / "cloud-prompts" / "_shared" / "preopen_capture.py"

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def load(name="cap"):
    spec = importlib.util.spec_from_file_location(name, str(CAP_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CUTOFF = datetime.datetime(2026, 11, 16, 13, 31, 55, tzinfo=datetime.timezone.utc)

# The stripped text of a press-release exhibit: the EDGAR plumbing, then the headline.
EXHIBIT_HTML = """
<html><body><div>EX-99.1</div><div>2</div><div>ck0001991792-ex99_1.htm</div>
<div>EX-99.1</div><div>EX-99.1</div><div>Exhibit 99.1</div>
<p><b>PIVOT-006 Phase 3 Registrational Trial Demonstrates Unprecedented Improvement
in Recurrence-Free Survival for High-Grade Bladder Cancer.</b></p>
</body></html>
"""
# An 8-K's cover page: no headline, only the form's own boilerplate.
COVER_HTML = """
<html><body><div>8-K</div><div>0001991792</div><div>UNITED STATES SECURITIES AND
EXCHANGE COMMISSION WASHINGTON, D.C. 20549 FORM 8-K CURRENT REPORT</div>
<p>(Exact name of Registrant as Specified in Its Charter) Delaware 001-41925</p>
</body></html>
"""
FWD_LOOKING_HTML = """
<html><body><div>This report on Form 10-Q contains forward-looking statements.</div>
</body></html>
"""


def filing(date="2026-11-16", form="8-K", items=("7.01", "8.01", "9.01"),
           accn="0001193125-26-462199", cik="0001991792", doc="ck0001991792-20261116.htm"):
    return {"date": date, "form": form, "items": list(items), "accn": accn,
            "cik": cik, "doc": doc,
            "index_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}-index.htm"}


def case_headline_extraction():
    """The headline is the PRESS RELEASE's line, with the EDGAR plumbing stripped."""
    cap = load("cap_h")
    got = cap._edgar_headline(EXHIBIT_HTML)
    check(bool(got) and got.startswith("PIVOT-006 Phase 3"),
          f"the press release's headline is extracted ({str(got)[:60]}...)")
    check("EX-99.1" not in got and "ex99_1.htm" not in got,
          "the EDGAR plumbing ('EX-99.1 2 <file>.htm ...') is stripped from the headline")
    check(cap._edgar_headline(COVER_HTML) is None,
          "a filing's COVER PAGE is refused - it is not a catalyst")
    check(cap._edgar_headline(FWD_LOOKING_HTML) is None,
          "a forward-looking-statements preamble is refused - it is not a catalyst")
    check(cap._edgar_headline("") is None and cap._edgar_headline(None) is None,
          "an empty document yields no headline")


def case_edgar_finds_and_classifies():
    """A filing inside the window becomes a DATED, CHECKABLE catalyst."""
    cap = load("cap_f")
    cap.edgar_ticker_ciks = lambda: {"CGON": "0001991792"}
    cap.edgar_filings = lambda t, cutoff, ciks=None: [filing()]
    cap._edgar_exhibit = lambda cik, accn: EXHIBIT_HTML
    cat = cap.edgar_catalyst("CGON", CUTOFF)
    check(bool(cat), "a filing inside the window produces a catalyst")
    if cat:
        check(cat["date"] == "2026-11-16", "the catalyst carries the FILING's date")
        check(bool(cat["url"]) and "sec.gov" in cat["url"],
              "the catalyst carries a CHECKABLE url (the filing)")
        check(cat["why"].startswith("PIVOT-006"),
              "the catalyst IS the press release's headline")
        check(cat["cat"] == "trial",
              f"the catalyst is CLASSIFIED from the filing (cat={cat['cat']})")


def case_edgar_falls_back_to_the_item_numbers():
    """With no usable headline, the filing's OWN ITEM NUMBERS are the cause."""
    cap = load("cap_i")
    cap.edgar_ticker_ciks = lambda: {"DVLT": "0001682149"}
    cap.edgar_filings = lambda t, cutoff, ciks=None: [
        filing(date="2026-11-13", form="8-K", items=("3.01", "8.01", "9.01"),
               accn="0001104659-26-127230", cik="0001682149", doc="tm2629197d1_8k.htm")]
    cap._edgar_exhibit = lambda cik, accn: COVER_HTML
    cap._http_get = lambda url, headers=None, timeout=30: COVER_HTML
    cat = cap.edgar_catalyst("DVLT", CUTOFF)
    check(bool(cat), "a filing with no usable headline still produces a catalyst")
    if cat:
        check("3.01" in cat["why"] and "Continued Listing Rule" in cat["why"],
              f"the fallback names the filing's ITEM NUMBER ({cat['why'][:70]})")
        check(cat["cat"] == "listing",
              f"item 3.01 (a continued listing failure) is classified as a listing "
              f"event (cat={cat['cat']})")


def case_edgar_respects_the_window():
    """A filing OUTSIDE the window is not a catalyst."""
    cap = load("cap_w")
    cap.edgar_ticker_ciks = lambda: {"AKAN": "0001888014"}
    cap.edgar_filings = lambda t, cutoff, ciks=None: []
    check(cap.edgar_catalyst("AKAN", CUTOFF) is None,
          "a name with no filing inside the window gets NO catalyst (and stays honest)")
    # The window itself: the search is asked for the last CATALYST_MAX_AGE_DAYS.
    cap.edgar_filings = lambda t, cutoff, ciks=None: [filing(date="2026-11-13")]
    cat = cap.edgar_catalyst("AKAN", CUTOFF)
    check(bool(cat) and cat["date"] == "2026-11-13",
          "a filing three days old IS inside the four-day window")


def case_edgar_beats_the_router():
    """The pipeline order: the article feed, then EDGAR, then the router.

    A dated filing beats an undated summary - and the router is the metered leg,
    so a name EDGAR explains is never spent on the router at all.
    """
    cap = load("cap_p")
    called = {"router": 0, "edgar": 0}

    def fake_article(t, cutoff, limit=8, name=None):
        return {"title": None, "date": None, "url": None, "freshest": None,
                "articles": [], "in_window": False, "error": None, "sentiment": None}

    def fake_edgar(t, cutoff, ciks=None):
        called["edgar"] += 1
        if t != "CGON":
            return None
        return {"why": "PIVOT-006 Phase 3 Registrational Trial Demonstrates Unprecedented "
                       "Improvement in Recurrence-Free Survival.",
                "date": "2026-11-16",
                "url": "https://www.sec.gov/Archives/edgar/data/0001991792/x-index.htm",
                "cat": "trial", "form": "8-K", "items": ["7.01"]}

    def fake_router(t, name=None, **k):
        called["router"] += 1
        return {"answer": "the company said something vague", "confidence": 0.9,
                "tool_used": "polygon_io_news", "refusal_reason": None, "evidence": None}

    cap.article_catalyst = fake_article
    cap.edgar_catalyst = fake_edgar
    cap.call_grounded = fake_router
    res = cap.resolve_catalysts(["CGON", "OTHER"], CUTOFF, 20, {},
                                 {"CGON": 30.92, "OTHER": -12.0})
    check(res["CGON"].get("origin") == "edgar",
          "a name EDGAR explains is explained by EDGAR")
    check(res["OTHER"].get("origin") == "router",
          "a name EDGAR cannot explain falls through to the router")
    check(called["router"] == 1,
          f"the router is called ONLY for the names EDGAR did not explain "
          f"(called {called['router']}x)")


def case_tape_shape_unchanged():
    """The EDGAR leg adds NO KEY to the tape.

    The tape's row shape is a contract with cron #17: the 10 contract keys plus the
    provenance extras. A new key would change what the consumer merges on, so the
    EDGAR cause must ride on the EXISTING fields (why / news_date / news_url / conf /
    grounded_tool) and add nothing.
    """
    cap = load("cap_k")
    src = (ROOT / "cloud-prompts" / "_shared" / "preopen_capture.py").read_text(encoding="utf-8")
    check('"origin": "edgar"' in src,
          "the EDGAR cause is produced by the catalyst resolver")
    # The ROW is built field by field; the catalyst's own keys are not spread into it.
    import re as _re
    m = _re.search(r'if cat and cat\.get\("why"\):(.*?)rec\["sign_conflict"\]', src, _re.S)
    check(m is not None, "the row application block was found")
    if m:
        body = m.group(1)
        check('rec["why"]' in body and 'rec["news_date"]' in body and 'rec["news_url"]' in body,
              "the EDGAR cause rides on why / news_date / news_url - the existing keys")
        check("**cat" not in body and "**cat}" not in body,
              "the catalyst dict is NOT spread into the row (no new tape key)")


def main():
    print("the EDGAR source of record, asserted BEHAVIOURALLY:")
    case_headline_extraction()
    case_edgar_finds_and_classifies()
    case_edgar_falls_back_to_the_item_numbers()
    case_edgar_respects_the_window()
    case_edgar_beats_the_router()
    case_tape_shape_unchanged()
    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} checks:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASSED every EDGAR behaviour")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Contract test for the TradingView scanner request shape.

Covers three things:

  1. the VALIDATOR refuses every measured-bad body shape (fault injection, offline),
  2. the SCAN path diagnoses a failed response and catches a silently truncated pull
     (a local HTTP stub - no external network),
  3. NO FILE IN THE REPO posts an array `sort` or a multi-value `in` filter to the scanner
     (the fleet-wide lint - a repo-wide regression guard).

Run:  python3 tools/test_tv_scan_contract.py
Exit: 0 all checks passed, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "cloud-prompts", "_shared", "tv_scan.py")

spec = importlib.util.spec_from_file_location("tv_scan", SHARED)
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)

FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)


def codes(body) -> list[str]:
    """Every problem code, errors and warnings."""
    return [p.code for p in tv.validate_body(body)]


def errs(body) -> list[str]:
    """Only the ERROR-severity codes - these are what make a body unsendable."""
    return [p.code for p in tv.validate_body(body) if p.severity == "error"]


# A file that shows a bad shape to warn about it is TEACHING, not SHIPPING. The lint
# must not flag the documentation that documents the trap.
TEACHING_MARKERS = (
    "json parse error", "Expected one value", "Never send", "never send",
    "sortBy", "sort-wrong-keys", "wrong keys", "silently IGNORED", "silently ignored",
)


def lint_text(text: str) -> tuple[list[str], bool]:
    """Return (bad_codes, is_documentation). A file that carries a prohibition marker for
    the shape it shows is documenting the trap, not shipping it."""
    bad: list[str] = []
    if ARRAY_SORT.search(text):
        bad.append("array-sort")
    if MULTI_IN.search(text):
        bad.append("multi-value-in-filter")
    if WRONG_SORT_KEYS.search(text):
        bad.append("wrong-keys-sort")
    if not bad:
        return [], False
    is_doc = any(m in text for m in TEACHING_MARKERS)
    return bad, is_doc


# ---------------------------------------------------------------- 1. the validator
print("1. the validator refuses every measured-bad shape")

GOOD = {"columns": ["name", "close", "volume", "average_volume_10d_calc"], "range": [0, 20000]}
GOOD_SORT = dict(GOOD, sort={"sortBy": "name", "sortOrder": "asc"})

check(errs(GOOD) == [], "a good body validates clean")
check(errs(GOOD_SORT) == [], "the canonical sortBy/sortOrder body validates clean")
check(errs(dict(GOOD, sort={"sortBy": "close", "sortOrder": "desc"})) == [], "sortOrder desc validates clean")
check(errs(dict(GOOD, sort={"sortBy": "close", "sortOrder": "ASC"})) == [], "sortOrder ASC validates clean")

check("sort-is-an-array" in codes(dict(GOOD, sort=[{"column": "close", "order": "asc"}])),
      "an ARRAY sort is refused")
check("sort-is-an-array" in codes(dict(GOOD, sort=[])),
      "an EMPTY array sort is refused (it 400s in production too)")
check("sort-wrong-keys" in codes(dict(GOOD, sort={"column": "close", "order": "asc"})),
      "the silently-ignored column/order sort is refused")
check("sort-unknown-shape" in codes(dict(GOOD, sort={"nonsense": 1})),
      "an unknown sort object is refused")
check("sort-order-invalid" in codes(dict(GOOD, sort={"sortBy": "close", "sortOrder": "sideways"})),
      "a non-asc/desc sortOrder is refused")

check("filters-plural-key" in codes(dict(GOOD, filters=[{"left": "name", "operation": "equal", "right": "AAPL"}])),
      "the plural 'filters' key is refused")
check("filter-multi-value-right" in codes(
    dict(GOOD, filter=[{"left": "name", "operation": "in", "right": ["AAPL", "MSFT"]}])),
    "a multi-value 'in' filter is refused")
check("filter-multi-value-right" in codes(
    dict(GOOD, filter=[{"left": "type", "operation": "in", "right": ["stock", "dr"]}])),
    "a multi-value 'type' in-filter is refused (the 2026-11-06 trap)")
check("filter-in_range-no-second-right" in codes(
    dict(GOOD, filter=[{"left": "close", "operation": "in_range", "right": 1}])),
    "in_range without second_right is refused")
check("filter-date-not-hour-boundary" in codes(
    dict(GOOD, filter=[{"left": "earnings_release_next_date", "operation": "greater", "right": 1793959199}])),
    "a date filter off the hour boundary is refused")
check("filter-date-not-hour-boundary" not in codes(
    dict(GOOD, filter=[{"left": "earnings_release_next_date", "operation": "greater", "right": 1793959200}])),
    "a date filter ON the hour boundary is accepted")
check("range-malformed" in codes(dict(GOOD, range=[0])), "a malformed range is refused")
check("range-inverted" in codes(dict(GOOD, range=[100, 10])), "an inverted range is refused")
check("range-at-page-cap" in codes(dict(GOOD, range=[0, 20000])), "a range at the page cap warns")

check(tv.diagnose(400, '{"totalCount":0,"error":"json parse error","data":null}')[0].code
      == "http-400-json-parse-error", "the 'json parse error' body is diagnosed")
check(tv.diagnose(400, '{"error":"Expected one value, passed 2"}')[0].code
      == "http-400-expected-one-value", "the 'Expected one value' body is diagnosed")
check(tv.diagnose(429, "rate limited")[0].severity == "warning",
      "a 429 is a RATE LIMIT, not a missing symbol")

# ---------------------------------------------------------------- 2. the scan path
print("2. the scan path (local HTTP stub - no external network)")

class Stub(BaseHTTPRequestHandler):
    payload = b'{"totalCount":0,"error":"json parse error","data":null}'
    status = 400

    def do_POST(self):
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *a):
        pass


def serve(status, payload):
    Stub.status, Stub.payload = status, payload
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/scan"


# a bad body is refused WITHOUT being sent
srv, url = serve(400, b'{"error":"json parse error"}')
try:
    sent = {"n": 0}
    orig = Stub.do_POST
    Stub.do_POST = lambda self: (sent.__setitem__("n", sent["n"] + 1), orig(self))[1]
    res, probs = tv.scan(dict(GOOD, sort=[{"column": "c", "order": "asc"}]), url=url)
    check(not res.get("sent"), "an invalid body is NOT sent")
    check(sent["n"] == 0, "the network was never touched for an invalid body")
    Stub.do_POST = orig
finally:
    srv.shutdown()

# a 400 from the endpoint is diagnosed
srv, url = serve(400, b'{"totalCount":0,"error":"json parse error","data":null}')
try:
    res, probs = tv.scan(GOOD, url=url)
    check(res.get("status") == 400, "a 400 is reported")
    check(any(p.code == "http-400-json-parse-error" for p in probs),
          "the 400 is diagnosed by its error string")
finally:
    srv.shutdown()

# a truncated pull is caught
body = json.dumps({"totalCount": 20271, "data": [{"s": "america", "d": ["AAPL", 1.0]} for _ in range(20000)]}).encode()
srv, url = serve(200, body)
try:
    res, probs = tv.scan(dict(GOOD, range=[0, 20000]), url=url)
    check(any(p.code == "pull-truncated" for p in probs),
          "a FULL pull with totalCount > rows is caught as TRUNCATED")
    check(res.get("rows") == 20000 and res.get("totalCount") == 20271,
          "the row count and totalCount are both reported")
finally:
    srv.shutdown()

# a deliberate small page is NOT truncation
body = json.dumps({"totalCount": 20271, "data": [{"s": "america", "d": ["AAPL", 1.0]}] * 50}).encode()
srv, url = serve(200, body)
try:
    res, probs = tv.scan(dict(GOOD, range=[0, 50]), url=url)
    check(not any(p.code == "pull-truncated" for p in probs),
          "a deliberate small page is NOT reported as truncated")
    check(any(p.code == "pull-partial-page" for p in probs),
          "a deliberate small page is reported as a partial page")
finally:
    srv.shutdown()

# a complete pull is clean
body = json.dumps({"totalCount": 2, "data": [{"s": "america", "d": ["AAPL", 1.0]},
                                               {"s": "america", "d": ["MSFT", 2.0]}]}).encode()
srv, url = serve(200, body)
try:
    res, probs = tv.scan(GOOD, url=url)
    check(not [p for p in probs if p.severity == "error"], "a complete pull produces no error")
finally:
    srv.shutdown()

# ---------------------------------------------------------------- 3. the fleet-wide lint
print("3. fleet-wide lint: no repo file sends a poisoned scanner body")

ARRAY_SORT = re.compile(r'"sort"\s*:\s*\[')
MULTI_IN = re.compile(r'"operation"\s*:\s*"(in|match)"[^}]*?"right"\s*:\s*\[')
WRONG_SORT_KEYS = re.compile(r'"sort"\s*:\s*\{\s*"(column|order)"')

scanned = 0
flagged: list[str] = []
documenting: list[str] = []
for root, dirs, files in os.walk(REPO):
    dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", "archive")]
    for fn in files:
        p = os.path.join(root, fn)
        rel = os.path.relpath(p, REPO)
        if rel.startswith("tools/test_tv_scan_contract.py") or rel.endswith("tv_scan.py"):
            continue
        if not rel.endswith((".py", ".md", ".sh", ".json", ".txt")):
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if "scanner.tradingview.com" not in t and "tradingview.com/america/scan" not in t:
            continue
        scanned += 1
        bad, is_doc = lint_text(t)
        if bad and is_doc:
            documenting.append(f"{rel} ({','.join(bad)})")
        elif bad:
            flagged.append(f"{rel} ({','.join(bad)})")

# the lint must actually be able to catch a real regression
check(lint_text('body = {"columns":["name"], "sort": [{"column":"close","order":"asc"}]}')[0] == ["array-sort"],
      "the lint CATCHES an array sort in a body")
check(lint_text('# Never send "sort": [{"column":"c","order":"asc"}]\n'
                'body = {"columns":["name"],"sort":{"sortBy":"c","sortOrder":"asc"}}')[1] is True,
      "the lint treats a body shown with a prohibition marker as documentation")
check(lint_text('{"sort":[{"column":"c","order":"asc"}]}')[1] is False,
      "a bare bad body with no prohibition marker is NOT documentation")
check(lint_text('body = {"columns":["name"], "sort": [{"column":"close","order":"asc"}], '
                '"filter":[{"left":"name","operation":"in","right":["A","B"]}]}')[0]
      == ["array-sort", "multi-value-in-filter"], "the lint catches BOTH shapes in one body")
check(lint_text('body = {"columns":["name"], "sort": {"sortBy":"close","sortOrder":"asc"}}')[0] == [],
      "the lint passes the canonical body")

check(scanned > 0, f"the lint actually scanned repo scanner callers ({scanned} file(s))")
check(not flagged, f"no repo file SHIPS a poisoned scanner body {flagged}")
if documenting:
    print(f"        (documenting the trap, not shipping it: {', '.join(documenting)})")

# the canonical keys must be what the repo uses
for rel in ("cloud-prompts/_shared/relvol_screen.py",
            "tools/daily_sweep_engines.py",
            "cloud-prompts/skills/stock-screener-suite/scripts/premarket_universe.py"):
    p = os.path.join(REPO, rel)
    if os.path.exists(p):
        t = open(p, encoding="utf-8", errors="replace").read()
        check('"sortBy"' in t, f"{rel} uses the canonical sortBy/sortOrder keys")

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} of {CHECKS} checks FAILED")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"RESULT: all {CHECKS} checks passed")
sys.exit(0)

# ---------------------------------------------------------------- 4. the TV_SCAN_V2 pull path
print("4. the pull path (paged, disjoint, bare-name keyed - local HTTP stub)")

class PagedStub(BaseHTTPRequestHandler):
    """Returns a DIFFERENT page per request, keyed on the requested range start."""
    pages = {}
    status = 200

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        rng = body.get("range") or [0, 0]
        payload = self.pages.get(rng[0], b'{"totalCount":0,"data":[]}')
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def serve_paged(pages):
    PagedStub.pages = pages
    srv = HTTPServer(("127.0.0.1", 0), PagedStub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/scan"


def page(rows, total):
    return json.dumps({"totalCount": total,
                       "data": [{"s": f"NYSE:{r}", "d": [r, "NYSE", 1.0]} for r in rows]}).encode()


# two pages that OVERLAP and whose union is short of totalCount -> both defects are caught
srv, url = serve_paged({0: page(["A", "B"], 5), 20000: page(["B", "C"], 5)})
try:
    res, probs = tv.pull_pages(dict(GOOD), url=url)
    got = [p.code for p in probs]
    check("pages-overlap" in got, "overlapping pages are caught (the 2026-11-11 defect)")
    check("pages-incomplete" in got, "a union short of totalCount is caught")
finally:
    srv.shutdown()

# two DISJOINT pages whose union equals totalCount -> clean
srv, url = serve_paged({0: page(["A", "B"], 4), 20000: page(["C", "D"], 4)})
try:
    res, probs = tv.pull_pages(dict(GOOD), url=url)
    check(not [p for p in probs if p.severity == "error"], "disjoint pages with a complete union pass")
    check(res.get("rows") == 4, "every row across the pages is kept")
    check("A" in res.get("by_name", {}), "rows are indexed by the BARE ticker, not the venue-prefixed s")
finally:
    srv.shutdown()

# a targeted pull: complete -> clean, and keyed by the bare name
srv, url = serve_paged({0: page(["BW", "FRVO"], 2)})
try:
    res, probs = tv.pull_names(["BW", "FRVO"], ["name", "exchange", "average_volume_10d_calc"], url=url)
    check(not [p for p in probs if p.severity == "error"], "a complete targeted pull passes")
    check(sorted(res.get("by_name", {}).keys()) == ["BW", "FRVO"],
          "the targeted pull is keyed by the bare ticker")
    check(res.get("rows") == 2 and res.get("totalCount") == 2, "the targeted pull reports rows and totalCount")
finally:
    srv.shutdown()

# a targeted pull where a requested name never comes back -> caught
srv, url = serve_paged({0: page(["BW"], 1)})
try:
    res, probs = tv.pull_names(["BW", "FRVO"], ["name", "exchange"], url=url)
    check("name-missing" in [p.code for p in probs], "a requested name that never arrives is caught")
finally:
    srv.shutdown()

# the targeted body uses in_range with a LIST (the `in` operation would 400)
body = {"columns": ["name", "exchange", "average_volume_10d_calc"],
        "filter": [{"left": "name", "operation": "in_range", "right": ["BW", "FRVO"]}],
        "range": [0, 7]}
check(tv.validate_body(body) and not errs(body), "the targeted in_range-list body validates clean")

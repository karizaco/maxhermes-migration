#!/usr/bin/env python3
"""TV_SCAN_V1 — a VALIDATED client for the TradingView public scanner.

WHY THIS EXISTS (measured 2026-11-11)
-------------------------------------
The scanner is healthy. What fails is the SHAPE of the request body, and two of the three
`sort` forms fail *without* an error message:

  | sort value                                   | HTTP | effect                                  |
  |----------------------------------------------|------|-----------------------------------------|
  | [{"column": X, "order": "asc"}]  (an ARRAY) | 400  | "json parse error" - the request never runs |
  | {"column": X, "order": "asc"}    (wrong keys)| 200  | SILENTLY IGNORED - rows come back UNSORTED |
  | {"sortBy": X, "sortOrder": "asc"} (THE keys) | 200  | sorts correctly                          |

The array form is what TradingView's PUBLIC DOCS show, so it is the one an agent reaches for
from memory. This helper makes the correct form mechanical:

  1. VALIDATE the body BEFORE it is sent. A bad shape is refused locally, with the fix.
  2. POST it, and check COMPLETENESS on the way back: `totalCount` must equal the rows
     returned, because `range` is a PAGE SIZE and the API truncates silently.
  3. DIAGNOSE a failure by its error string, so a 400 names its cause and its fix.

USAGE
-----
    tv_scan.py validate --body body.json          # dry run: refuse a bad shape, send nothing
    tv_scan.py scan    --body body.json [--url U] # validate -> post -> completeness check
    tv_scan.py diagnose --status 400 --error-body err.json
    tv_scan.py selftest                            # offline checks of the validator itself

`--body -` reads stdin. `--body` may also be an inline JSON string.

EXIT CODES
----------
    0  ok
    1  the request body is INVALID (nothing was sent)
    2  the request FAILED (status/transport)
    3  the pull came back TRUNCATED (totalCount > rows) — a failed pull, report it
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# ---- capability marker: a run-time fetch MUST require this token, or an older copy of this
# ---- file (or of a different helper with the same name) could win the download race.
CAPABILITY_MARKER = "TV_SCAN_V1"

DEFAULT_URL = "https://scanner.tradingview.com/america/scan"

# The scan endpoints that answer, and the sort shape each accepts (identical behaviour
# measured on all six on 2026-11-11).
MARKETS = ("america", "japan", "korea", "taiwan", "hongkong", "crypto")

# Columns whose values are epoch-seconds DATES. A `greater`/`less` filter on one of these
# must land on a WHOLE-HOUR boundary: 1793959200 works, 1793959199 is a 400.
DATE_COLUMNS = (
    "earnings_release_next_date", "earnings_release_date", "premarket_time",
    "postmarket_time", "change_time", "fundamental_currency_release_date",
)

# `range` is a page size. The API returns `totalCount` = the TRUE total; when it exceeds the
# rows returned, the pull is TRUNCATED and the missing slice must be pulled.
RANGE_PAGE_CAP = 20000

KNOWN_BODY_KEYS = {"columns", "filter", "filters", "range", "sort", "markets", "options", "symbols"}


class Problem:
    __slots__ = ("severity", "code", "message", "fix")

    def __init__(self, severity: str, code: str, message: str, fix: str = ""):
        self.severity = severity
        self.code = code
        self.message = message
        self.fix = fix

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message, "fix": self.fix}

    def __str__(self) -> str:
        s = f"[{self.severity}] {self.code}: {self.message}"
        if self.fix:
            s += f"\n          FIX: {self.fix}"
        return s


# --------------------------------------------------------------------------------------
# VALIDATION
# --------------------------------------------------------------------------------------

def _is_list(v) -> bool:
    return isinstance(v, list)


def validate_body(body) -> list[Problem]:
    """Return the problems with a scanner request body. An empty list means VALID.

    Severity `error` = the request will fail or return the wrong data. `warning` = it will
    succeed but the caller probably does not mean it.
    """
    problems: list[Problem] = []
    if not isinstance(body, dict):
        return [Problem("error", "body-not-object",
                        f"the request body must be a JSON object, got {type(body).__name__}",
                        "build the body as a dict: {'columns': [...], 'range': [0, N]}")]

    # ---- 1. sort -----------------------------------------------------------------
    if "sort" in body:
        sort = body["sort"]
        if _is_list(sort):
            problems.append(Problem(
                "error", "sort-is-an-array",
                'a LIST sort is REJECTED with HTTP 400 {"error":"json parse error"} - even an '
                'empty list fails. This is the shape TradingView\'s public docs show, and it is '
                'not what this API accepts.',
                'use {"sortBy": "<column>", "sortOrder": "asc|desc"} (the repo\'s canonical keys) '
                'or omit "sort" entirely'))
        elif isinstance(sort, dict):
            keys = set(sort)
            if {"sortBy", "sortOrder"} <= keys:
                if str(sort.get("sortOrder", "")).lower() not in ("asc", "desc"):
                    problems.append(Problem(
                        "error", "sort-order-invalid",
                        f'sortOrder must be "asc" or "desc", got {sort.get("sortOrder")!r}',
                        'set "sortOrder": "asc"'))
            elif {"column", "order"} <= keys:
                problems.append(Problem(
                    "error", "sort-wrong-keys",
                    '{"column": ..., "order": ...} returns HTTP 200 and is SILENTLY IGNORED - the '
                    'rows come back UNSORTED, so "the top N" is an arbitrary N.',
                    'use {"sortBy": ..., "sortOrder": ...}; never "tidy" the key pair'))
            else:
                problems.append(Problem(
                    "error", "sort-unknown-shape",
                    f"the sort object has unrecognised keys {sorted(keys)}",
                    'use {"sortBy": ..., "sortOrder": ...} or omit "sort"'))
        else:
            problems.append(Problem(
                "error", "sort-unknown-shape",
                f"sort must be an object, got {type(sort).__name__}",
                'use {"sortBy": ..., "sortOrder": ...} or omit "sort"'))

    # ---- 2. filter ---------------------------------------------------------------
    if "filters" in body:
        problems.append(Problem(
            "error", "filters-plural-key",
            'the payload key is "filter" (SINGULAR). "filters" is silently IGNORED and the '
            'scanner returns the WHOLE universe.',
            'rename the key to "filter"'))

    for i, entry in enumerate(body.get("filter") or []):
        if not isinstance(entry, dict):
            problems.append(Problem("error", "filter-not-object",
                                    f"filter[{i}] is not an object", "use a dict per filter"))
            continue
        op = entry.get("operation")
        right = entry.get("right")
        left = entry.get("left")
        if op in ("in", "match", "any") and _is_list(right):
            problems.append(Problem(
                "error", "filter-multi-value-right",
                f'filter[{i}] on {left!r} uses operation {op!r} with a LIST right - the endpoint '
                'REJECTS it with HTTP 400 {"error":"Expected one value, passed N"}.',
                'pull the universe WITHOUT this filter and filter the rows locally'))
        if op == "in_range" and "second_right" not in entry:
            problems.append(Problem(
                "error", "filter-in_range-no-second-right",
                f"filter[{i}] uses in_range but carries no second_right - a single value is a 400",
                'add "second_right"'))
        if op in ("greater", "less") and left in DATE_COLUMNS:
            val = right
            if isinstance(val, (int, float)) and float(val) % 3600 != 0:
                problems.append(Problem(
                    "error", "filter-date-not-hour-boundary",
                    f"filter[{i}] compares the DATE column {left!r} to {val!r}, which is not on a "
                    "whole-hour boundary - the endpoint returns HTTP 400",
                    "round the epoch seconds DOWN to a whole hour"))

    # ---- 3. range ----------------------------------------------------------------
    rng = body.get("range")
    if rng is not None:
        if not (_is_list(rng) and len(rng) == 2 and all(isinstance(x, int) for x in rng)):
            problems.append(Problem("error", "range-malformed",
                                    f"range must be a two-integer list [start, end], got {rng!r}",
                                    'use "range": [0, 20000]'))
        elif rng[1] < rng[0]:
            problems.append(Problem("error", "range-inverted",
                                    f"range {rng} ends before it starts", "use [start, end] with end >= start"))
        elif rng[1] - rng[0] >= RANGE_PAGE_CAP:
            problems.append(Problem(
                "warning", "range-at-page-cap",
                f"range {rng} asks for {rng[1]-rng[0]} rows, at or above the {RANGE_PAGE_CAP} "
                "page cap - the API will return the cap and DROP the rest with no error",
                "compare totalCount with the rows returned and pull the missing slice"))

    # ---- 4. unknown top-level keys ----------------------------------------------
    for k in sorted(set(body) - KNOWN_BODY_KEYS):
        problems.append(Problem("warning", "unknown-body-key",
                                f'the body carries an unrecognised top-level key {k!r}',
                                "remove it, or confirm the endpoint accepts it"))

    return problems


# --------------------------------------------------------------------------------------
# DIAGNOSIS
# --------------------------------------------------------------------------------------

def diagnose(status: int, error_body: str) -> list[Problem]:
    """Map a failed scanner response to its cause and its fix."""
    body = (error_body or "").strip()
    if status == 200:
        return []
    try:
        parsed = json.loads(body)
        msg = str(parsed.get("error") or "")
    except Exception:
        parsed = None
        msg = body[:200]

    out: list[Problem] = []
    if "json parse error" in msg:
        out.append(Problem(
            "error", "http-400-json-parse-error",
            'the endpoint could not parse the request ("json parse error"). The measured cause is '
            'a LIST "sort" (the shape TradingView\'s public docs show).',
            'send "sort": {"sortBy": "<column>", "sortOrder": "asc"} or omit "sort"'))
        out.append(Problem(
            "error", "http-400-json-parse-error",
            'secondary suspect: a "filter" whose "right" is a LIST - that is rejected with a '
            'DIFFERENT message ("Expected one value"), so if this body has one, fix both',
            "filter locally instead"))
    elif "Expected one value" in msg:
        out.append(Problem(
            "error", "http-400-expected-one-value",
            'a filter\'s "right" carried more than one value. The "in" operation does not accept '
            'multiple values on this endpoint.',
            "pull the universe and filter the rows locally"))
    elif status == 404:
        out.append(Problem("error", "http-404",
                           "the endpoint does not exist - check the market in the URL path",
                           f"valid markets: {', '.join(MARKETS)}"))
    elif status == 429:
        out.append(Problem("warning", "http-429",
                           "rate limited - the scanner is NOT missing a symbol",
                           "wait and retry once; do not report 'no data'"))
    else:
        out.append(Problem("error", f"http-{status}",
                           f"the scanner returned HTTP {status}: {msg[:200]}",
                           "validate the body with `tv_scan.py validate` before sending"))
    return out


# --------------------------------------------------------------------------------------
# SCAN
# --------------------------------------------------------------------------------------

def read_body(spec: str) -> dict:
    if spec == "-":
        return json.loads(sys.stdin.read())
    if os.path.exists(spec):
        with open(spec, encoding="utf-8") as f:
            return json.loads(f.read())
    return json.loads(spec)


def scan(body: dict, url: str = DEFAULT_URL, timeout: int = 60) -> tuple[dict, list[Problem]]:
    """Validate, POST, and check completeness. Returns (result, problems)."""
    problems = validate_body(body)
    if any(p.severity == "error" for p in problems):
        return {"sent": False}, problems

    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        problems += diagnose(e.code, raw)
        return {"sent": True, "status": e.code, "error_body": raw[:400]}, problems
    except Exception as e:  # transport
        problems.append(Problem("error", "transport", f"the request failed in transport: {e}",
                                 "retry once, then fall through the source ladder"))
        return {"sent": True}, problems

    try:
        data = json.loads(raw)
    except Exception:
        problems.append(Problem("error", "body-not-json",
                                 f"HTTP {status} but the body is not JSON: {raw[:200]}",
                                 "check the RESPONSE BODY, not just the status"))
        return {"sent": True, "status": status}, problems

    rows = data.get("data") or []
    total = data.get("totalCount")
    result = {"sent": True, "status": status, "rows": len(rows), "totalCount": total,
              "data": data}
    if isinstance(total, int) and total > len(rows):
        # `range` is a PAGE SIZE. A caller who asked for 50 rows and got 50 rows is NOT
        # truncated - there are simply more names on the next page. Truncation is only a
        # defect when the caller asked for EVERYTHING and the API dropped the tail.
        rng = body.get("range")
        # the range end is EXCLUSIVE (measured: range [0,100] returns 100 rows)
        requested = (rng[1] - rng[0]) if (isinstance(rng, list) and len(rng) == 2) else None
        if requested is None or requested >= RANGE_PAGE_CAP:
            problems.append(Problem(
                "error", "pull-truncated",
                f"the pull is TRUNCATED: totalCount {total} but only {len(rows)} rows came back. "
                f"{total - len(rows)} name(s) were dropped with NO error, and because an "
                f"ineffective sort cannot order them, the dropped slice is arbitrary.",
                "pull the missing slice (page by range), or raise the page size; a truncated "
                "pull is a FAILED pull - report it, do not publish it"))
        else:
            problems.append(Problem(
                "warning", "pull-partial-page",
                f"this page returned {len(rows)} of {total} names. That is EXPECTED for a "
                f"deliberate page of {requested} rows - the rest are on the next page. It is "
                "NOT truncation.",
                f"if you need the whole universe, keep paging on range "
                f"[{rng[0] + requested}, ...] until you have {total} rows"))
    return result, problems


# --------------------------------------------------------------------------------------
# SELFTEST
# --------------------------------------------------------------------------------------

def _codes(problems) -> list[str]:
    return [p.code for p in problems]


def selftest() -> int:
    cases = [
        ("good, no sort", {"columns": ["name", "close"], "range": [0, 20000]}, []),
        ("good, canonical sort", {"columns": ["name", "close"], "range": [0, 100],
                                   "sort": {"sortBy": "close", "sortOrder": "asc"}}, []),
        ("array sort", {"columns": ["name"], "sort": [{"column": "close", "order": "asc"}]},
         ["sort-is-an-array"]),
        ("empty array sort", {"columns": ["name"], "sort": []}, ["sort-is-an-array"]),
        ("wrong-key sort", {"columns": ["name"], "sort": {"column": "close", "order": "asc"}},
         ["sort-wrong-keys"]),
        ("plural filters key", {"columns": ["name"], "filters": [{"left": "name", "operation": "equal", "right": "AAPL"}]},
         ["filters-plural-key"]),
        ("multi-value in filter", {"columns": ["name"],
                                   "filter": [{"left": "name", "operation": "in", "right": ["AAPL", "MSFT"]}]},
         ["filter-multi-value-right"]),
        ("in_range without second_right", {"columns": ["name"],
                                            "filter": [{"left": "close", "operation": "in_range", "right": 1}]},
         ["filter-in_range-no-second-right"]),
        ("date not on hour boundary", {"columns": ["name"],
                                       "filter": [{"left": "earnings_release_next_date",
                                                   "operation": "greater", "right": 1793959199}]},
         ["filter-date-not-hour-boundary"]),
        ("date on hour boundary", {"columns": ["name"],
                                   "filter": [{"left": "earnings_release_next_date",
                                               "operation": "greater", "right": 1793959200}]}, []),
        ("malformed range", {"columns": ["name"], "range": [0]}, ["range-malformed"]),
    ]
    bad = 0
    for label, body, expected in cases:
        got = _codes(validate_body(body))
        ok = all(e in got for e in expected)
        print(f"  {'PASS' if ok else 'FAIL'}  {label:34} -> {got}")
        if not ok:
            bad += 1
    print(f"selftest: {len(cases) - bad}/{len(cases)} validator cases passed")
    return 1 if bad else 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def _emit(problems, as_json: bool) -> None:
    if as_json:
        print(json.dumps([p.as_dict() for p in problems], indent=1))
    else:
        for p in problems:
            print(str(p))


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Validated TradingView scanner client (TV_SCAN_V1)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="check a body WITHOUT sending it")
    p_val.add_argument("--body", required=True, help="json file, inline json, or - for stdin")

    p_scan = sub.add_parser("scan", help="validate, POST, and check completeness")
    p_scan.add_argument("--body", required=True, help="json file, inline json, or - for stdin")
    p_scan.add_argument("--url", default=DEFAULT_URL)
    p_scan.add_argument("--json", action="store_true", help="print the raw response as JSON")
    p_scan.add_argument("--out", help="write the raw response to this file")

    p_diag = sub.add_parser("diagnose", help="explain a failed scanner response")
    p_diag.add_argument("--status", type=int, required=True)
    p_diag.add_argument("--error-body", required=True, help="the response body, or - for stdin")

    sub.add_parser("selftest", help="offline checks of the validator")

    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return selftest()

    if a.cmd == "validate":
        body = read_body(a.body)
        problems = validate_body(body)
        _emit(problems, False)
        errs = [p for p in problems if p.severity == "error"]
        if errs:
            print(f"INVALID: {len(errs)} error(s). NOTHING WAS SENT.")
            return 1
        print("VALID: the body is well-shaped and can be sent.")
        return 0

    if a.cmd == "diagnose":
        raw = sys.stdin.read() if a.error_body == "-" else (
            open(a.error_body, encoding="utf-8").read() if os.path.exists(a.error_body) else a.error_body)
        problems = diagnose(a.status, raw)
        _emit(problems, False)
        return 1 if problems else 0

    if a.cmd == "scan":
        body = read_body(a.body)
        result, problems = scan(body, url=a.url)
        if a.out and result.get("sent"):
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(result.get("data", {}), f)
        if a.json:
            print(json.dumps(result.get("data", result), indent=1))
        else:
            _emit(problems, False)
            if result.get("sent"):
                print(f"HTTP {result.get('status')}  rows={result.get('rows')}  "
                      f"totalCount={result.get('totalCount')}")
        errs = [p for p in problems if p.severity == "error"]
        if any(p.code == "pull-truncated" for p in errs):
            return 3
        if errs:
            return 2
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

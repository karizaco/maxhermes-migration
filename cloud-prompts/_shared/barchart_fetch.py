#!/usr/bin/env python3
"""
barchart_fetch.py — read Barchart data from the cloud sandbox.

WHY THIS EXISTS
---------------
Barchart sits behind AWS WAF bot management. Plain `curl` gets an HTTP 202 challenge
response with no cookies, and the API then rejects every call with HTTP 403. This is
NOT a User-Agent problem: Chrome, Safari, mobile-Safari and bare curl all get the
identical 1997-byte challenge body.

The fix is to let a real browser engine solve the challenge. Playwright and the
chromium build are already installed in the cloud sandbox, so this script needs no
install step:

    /usr/local/lib/python3.11/dist-packages/playwright/
    /root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome

Load a Barchart page first (this clears the `aws-waf-token` challenge and sets the
session cookies), then call `core-api` FROM THE PAGE CONTEXT so the browser attaches
the cookies and the `X-XSRF-TOKEN` header itself.

USAGE
  # batch quotes for a symbol list
  barchart_fetch.py --symbols SPY,QQQ,AAPL

  # a ranked movers list (list names are discovered, not guessed — see --list)
  barchart_fetch.py --list top-gainers --limit 20

  # print the list names the page itself uses, and the full field map
  barchart_fetch.py --discover

EXIT CODES
  0 = success (stdout is JSON)
  1 = transport / API error (stdout is a JSON error object)
  2 = usage or no browser available
"""

import argparse
import glob
import json
import os
import re
import sys

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

PAGE = "https://www.barchart.com/stocks/performance/percent-change/advances"

# The movers lists the performance page actually calls. Discovered from the page's own
# network traffic on 2026-10-31 — guessing a name returns HTTP 200 with count:0, which
# looks like an empty market rather than an error.
LIST_MAP = {
    "top-gainers": "stocks.us.percent.advances.overall",
    "top-losers": "stocks.us.percent.declines.overall",
    "most-active": "stocks.us.mostActive.overall",
    "52w-high": "stocks.us.percent.fiftyTwoWeekHigh",
    "52w-low": "stocks.us.percent.fiftyTwoWeekLow",
}

QUOTE_FIELDS = "symbol,lastPrice,lastChange,lastChangePercent,volume,lastTradeTime"
MOVER_FIELDS = "symbol,symbolName,lastPrice,priceChange,percentChange,volume,exchange"


def find_chrome():
    """Locate the chromium build playwright should use."""
    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        roots.append(env)
    roots += ["/root/.cache/ms-playwright", "/workspace/.home/.cache/ms-playwright",
              os.path.expanduser("~/.cache/ms-playwright")]
    for root in roots:
        hits = sorted(glob.glob(os.path.join(root, "chromium-*/chrome-linux/chrome")))
        if hits:
            return hits[-1]
    return None


def _js_quote(symbols, fields):
    return """
async (args) => {
  const t = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
  const h = {'Accept': 'application/json'};
  if (t) h['X-XSRF-TOKEN'] = decodeURIComponent(t[1]);
  const u = '/proxies/core-api/v1/quotes/get?symbols=' + encodeURIComponent(args.symbols)
          + '&fields=' + encodeURIComponent(args.fields);
  const r = await fetch(u, {headers: h, credentials: 'include'});
  return {status: r.status, body: (await r.text()).slice(0, 4000)};
}"""


def _js_list(listname, fields, limit, order):
    return """
async (args) => {
  const t = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
  const h = {'Accept': 'application/json'};
  if (t) h['X-XSRF-TOKEN'] = decodeURIComponent(t[1]);
  const u = '/proxies/core-api/v1/quotes/get?lists=' + encodeURIComponent(args.listname)
          + '&orderDir=' + args.order
          + '&fields=' + encodeURIComponent(args.fields)
          + '&limit=' + args.limit;
  const r = await fetch(u, {headers: h, credentials: 'include'});
  return {status: r.status, body: (await r.text()).slice(0, 8000)};
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--list", dest="listname")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--order", default="desc")
    ap.add_argument("--fields")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--page", default=PAGE)
    args = ap.parse_args()

    if not (args.symbols or args.listname or args.discover):
        ap.print_help()
        return 2

    chrome = find_chrome()
    if not chrome:
        print(json.dumps({"error": "no_chromium",
                          "detail": "playwright chromium not found; set PLAYWRIGHT_BROWSERS_PATH"}))
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(json.dumps({"error": "no_playwright", "detail": str(exc)}))
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1700, "height": 1200},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};")
        page = ctx.new_page()
        seen_lists = []
        page.on("response", lambda r: seen_lists.append(r.url) if "proxies/core-api" in r.url else None)
        try:
            page.goto(args.page, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(6000)

            if args.discover:
                out = {"page": args.page, "known_lists": LIST_MAP,
                       "observed_core_api_urls": sorted(set(seen_lists))[:12]}
                for u in sorted(set(seen_lists)):
                    m = re.search(r"lists=([^&]+)", u)
                    if m:
                        out.setdefault("observed_list_names", []).append(m.group(1))
                print(json.dumps(out, indent=2))
                return 0

            if args.symbols:
                out = page.evaluate(_js_quote(
                    args.symbols, args.fields or QUOTE_FIELDS),
                    {"symbols": args.symbols, "fields": args.fields or QUOTE_FIELDS})
            else:
                lst = LIST_MAP.get(args.listname, args.listname)
                out = page.evaluate(_js_list(
                    lst, args.fields or MOVER_FIELDS, args.limit, args.order),
                    {"listname": lst, "fields": args.fields or MOVER_FIELDS,
                     "limit": args.limit, "order": args.order})
            if out.get("status") != 200:
                print(json.dumps({"error": "http_status", "status": out.get("status"),
                                  "body": str(out.get("body"))[:300]}))
                return 1
            try:
                print(json.dumps(json.loads(out["body"]), indent=2))
            except Exception:
                print(json.dumps({"error": "unparseable", "body": str(out.get("body"))[:600]}))
                return 1
        except Exception as exc:
            print(json.dumps({"error": "exception", "detail": str(exc)[:300]}))
            return 1
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())

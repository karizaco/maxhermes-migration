#!/usr/bin/env python3
"""
test_brief26_cap_basis.py — prove the cap-basis guard actually fires.

THE DEFECT (2026-11-16)
-----------------------
`brief26_pull.py` used stockanalysis.com's share count as the tiebreak with NO test:
`if sa.get(t): shares = sa[t]`. That count is the ORDINARY share count for some issuers
while the price it is multiplied by is per ADS, so the published market cap came out
inflated by the ratio - measured on that run: ADXN 63x, BLRX 327x, RADX 281x, IMOS 20x.
Two of those four names PASSED the $100M quality gate on the inflated number, and RADX
sat 0.5pp outside the top-10 losers table with a $3.30bn cap on a ~$10.6M company.

THE GUARD
---------
The site is asked a question it can answer from ONE page: is the share count it
publishes the count behind the market cap it publishes? `sharesout x the site's own
price` must reconcile with the site's own `marketcap` (within 25%). When it does not,
the count is on a different basis and is NOT used; the ADS-basis implied counts are
published instead, and the name is flagged as a basis mismatch.

WHY THIS IS A TEST AND NOT A TEXT GREP
--------------------------------------
The guard is a comparison inside a loop, and the file also contains the string
`basis_ok` in its own documentation - so a grep cannot tell a working guard from a
comment. This test drives the real `reconcile_caps()` with the network stubbed and
asserts the published cap. It also MUTATES the guard (removes the `basis_ok` test) and
asserts that the mutation produces the inflated cap - a test whose assertions cannot
fail is not a test.

USAGE
    python3 test_brief26_cap_basis.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(os.path.dirname(HERE), "cloud-prompts", "_shared")
PULL = os.path.join(SHARED, "brief26_pull.py")

RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    print("%s %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def load_module(path=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "brief26_pull_mod", path or PULL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeProc:
    """Stands in for the shibui_caps.py subprocess."""
    def __init__(self, payload):
        self.payload = payload

    def run(self, *a, **kw):
        class R:
            stdout = json.dumps(self.payload)
            stderr = ""
        return R()


def row(ticker, close, scanner_shares, nasdaq=None, shibui=None):
    r = {"ticker": ticker, "close": close,
         "market_cap_basic": close * scanner_shares,
         "description": ticker, "sector": "Test", "exchange": "NASDAQ"}
    return r


def reconcile(mod, rows, nasdaq_map, shibui_map, sa_map):
    """Run the real reconcile_caps with every network call stubbed."""
    mod.nasdaq_summary = lambda sym: (sym,) + tuple(nasdaq_map.get(sym, (None, None)))
    mod.stockanalysis_shares = lambda sym: (sym, sa_map.get(sym))
    mod.subprocess = _FakeProc({"rows": [{"ticker": t, "market_cap": mc}
                                         for t, mc in shibui_map.items()]})
    return mod.reconcile_caps(rows, "2026-11-16", {})


def main():
    if not os.path.exists(PULL):
        print("FAIL — brief26_pull.py is not at %s" % PULL)
        return 1
    mod = load_module()

    # ---------------------------------------------------------------- CASE 1
    # A COHERENT SITE: the count IS the count behind the site's own cap, so it is
    # published. This case guards against over-correcting - the median of the implied
    # counts would give a DIFFERENT (and here wrong) answer.
    close = 100.00
    rows = [row("GOOD", close, 1_000_000)]
    nasdaq = {"GOOD": (90_000_000.0, 100.0)}          # implied 900,000 -> 10% off
    shibui = {"GOOD": 80_000_000.0}                    # implied 800,000
    sa = {"GOOD": {"shares": 1_000_000, "market_cap": 100_000_000.0, "price": 100.0,
                   "implied_shares": 1_000_000.0, "status": "ok", "basis_ok": True}}
    # make it a FLAGGED row so the reconciliation runs
    nasdaq["GOOD"] = (70_000_000.0, 100.0)            # implied 700,000 -> 30% off
    meta = reconcile(mod, rows, nasdaq, shibui, sa)
    r = rows[0]
    check(r["market_cap_published"] == 100_000_000.0,
          "a coherent site publishes its own count",
          "cap=%s source=%s" % (r["market_cap_published"], r["cap_source"]))
    check(r["cap_source"] == "stockanalysis_shares x close",
          "a coherent site keeps the stockanalysis source", r["cap_source"])
    check(r.get("cap_basis_mismatch") is False and not meta.get("basis_mismatch"),
          "a coherent site is not flagged as a basis mismatch", "")

    # ---------------------------------------------------------------- CASE 2
    # A BASIS MISMATCH: the site publishes 127,410,834 shares, a market cap of
    # $7,772,317 and a price of $3.83 - its own fields disagree by 63x, so the count
    # is the ORDINARY count and must not be multiplied by a per-ADS price.
    close = 4.06
    scanner_sh, nasdaq_sh, shibui_sh = 1_204_213.0, 1_523_186.0, 954_551.0
    rows = [row("ADXN", close, scanner_sh)]
    nasdaq = {"ADXN": (nasdaq_sh * close, close)}
    shibui = {"ADXN": shibui_sh * close}
    sa = {"ADXN": {"shares": 127_410_834, "market_cap": 7_772_317.0, "price": 3.83,
                   "implied_shares": 7_772_317.0 / 3.83, "status": "mismatch",
                   "basis_ok": False}}
    # the site's count is 106x the median implied count and agrees with NONE of them
    meta = reconcile(mod, rows, nasdaq, shibui, sa)
    r = rows[0]
    expected = scanner_sh * close            # the median implied count x the close
    old = 127_410_834 * close                # what the old rule published
    check(abs(r["market_cap_published"] - expected) < 1.0,
          "a basis mismatch publishes the median implied count",
          "cap=%.0f expected=%.0f" % (r["market_cap_published"], expected))
    check(abs(r["market_cap_published"] - old) > old * 0.9,
          "the inflated count is NOT published", "cap=%.0f vs old=%.0f"
          % (r["market_cap_published"], old))
    check("rejected" in r["cap_source"],
          "the rejection is in the published cap_source", r["cap_source"])
    check(r.get("cap_basis_mismatch") is True and "ADXN" in (meta.get("basis_mismatch") or []),
          "the name is flagged in cap_meta['basis_mismatch']",
          str(meta.get("basis_mismatch")))
    check(meta.get("stockanalysis_resolved") == 1, "the stockanalysis read is counted", "")

    # ---------------------------------------------------------------- CASE 2b
    # SKHY's shape: the site's count is the ADS count (1 ADS = 1/10 common) and every
    # other source is on the ordinary basis, so the site's count is SMALLER than all of
    # them - and it is the RIGHT one. A count that sits BELOW the others can never be
    # the ordinary count (an ADS count never exceeds it), so it must be kept.
    close2 = 131.79
    sc2, nq2, sh2 = 5_003_471_537.0, 6_863_359_022.0, 7_110_755_000.0
    rows2b = [row("SKHY", close2, sc2)]
    nasdaq2b = {"SKHY": (nq2 * close2, close2)}
    shibui2b = {"SKHY": sh2 * close2}
    sa2b = {"SKHY": {"shares": 722_000_000, "market_cap": 611_381_710_878.0,
                     "price": 122.18, "implied_shares": 611_381_710_878.0 / 122.18,
                     "status": "mismatch", "basis_ok": False}}
    reconcile(mod, rows2b, nasdaq2b, shibui2b, sa2b)
    r2b = rows2b[0]
    check(abs(r2b["market_cap_published"] - 722_000_000 * close2) < 1.0,
          "a site count BELOW every other count is kept (the ADS count)",
          "cap=%.0f" % r2b["market_cap_published"])
    check(r2b.get("cap_basis_mismatch") is False,
          "the ADS-basis site count is not flagged as a mismatch", "")

    # ---------------------------------------------------------------- CASE 2c
    # WETO's shape: the site's count agrees with ONE source (Nasdaq) and disagrees
    # with the others. It has a corroborating source, so it is not a lone outlier.
    close3 = 0.6087
    sc3, nq3, sh3 = 1_077_800.0, 15_047_298.0, 220_000.0
    rows3b = [row("WETO", close3, sc3)]
    nasdaq3b = {"WETO": (nq3 * close3, close3)}
    shibui3b = {"WETO": sh3 * close3}
    sa3b = {"WETO": {"shares": 14_897_999, "market_cap": 8_424_818.0, "price": 0.5655,
                     "implied_shares": 8_424_818.0 / 0.5655, "status": "mismatch",
                     "basis_ok": False}}
    reconcile(mod, rows3b, nasdaq3b, shibui3b, sa3b)
    r3b = rows3b[0]
    check(abs(r3b["market_cap_published"] - 14_897_999 * close3) < 1.0,
          "a site count corroborated by one source is kept",
          "cap=%.0f" % r3b["market_cap_published"])

    # ---------------------------------------------------------------- CASE 3
    # The site DISAGREES with itself -> basis_ok False -> the count is rejected.
    # The site's own market cap and price are still recorded for the audit trail.
    check(rows[0].get("stockanalysis_market_cap") == 7_772_317.0
          and rows[0].get("stockanalysis_price") == 3.83,
          "the site's own cap and price are recorded", "")

    # ---------------------------------------------------------------- CASE 3b
    # A SITE THAT COULD NOT BE READ is unavailable, NOT a mismatch: "we could not ask"
    # is not "the source disagrees", and a name must not be flagged as a basis
    # mismatch for a 404.
    rows3 = [row("NOPAGE", close, scanner_sh)]
    nq3 = {"NOPAGE": (nasdaq_sh * close, close)}        # resolves, and disagrees -> flagged
    meta3 = reconcile(mod, rows3, nq3, {}, {})          # no stockanalysis page at all
    r3 = rows3[0]
    check(r3.get("cap_basis_mismatch") is False and not meta3.get("basis_mismatch"),
          "an unreadable site is not flagged as a basis mismatch", "")
    check("unavailable" in r3["cap_source"],
          "an unreadable site is named in the cap_source", r3["cap_source"])
    two_way = (scanner_sh + nasdaq_sh) / 2.0 * close   # the median of TWO counts
    check(abs(r3["market_cap_published"] - two_way) < 1.0,
          "an unreadable site falls back to the median implied count",
          "cap=%.0f expected=%.0f" % (r3["market_cap_published"], two_way))

    # ---------------------------------------------------------------- CASE 4
    # THE MUTATION: remove the basis_ok test from the guard and the same row must
    # come back inflated. If it does not, the assertions above cannot fail and this
    # test proves nothing.
    tmp = tempfile.mkdtemp(prefix="cap_basis_mutation_")
    try:
        src = open(PULL, encoding="utf-8").read()
        mutated = src.replace("            if too_big and uncorroborated:",
                               "            if False:")
        check(mutated != src, "the mutation applies to the guard", "")
        mpath = os.path.join(tmp, "brief26_pull_mutated.py")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(mutated)
        # the mutated module imports its siblings by path relative to itself, so the
        # stub has to be reinstalled on the mutated module
        mmod = load_module(mpath)
        rows2 = [row("ADXN", close, scanner_sh)]
        meta2 = reconcile(mmod, rows2, nasdaq, shibui, sa)
        inflated = rows2[0]["market_cap_published"]
        check(abs(inflated - old) < old * 0.01,
              "the mutation reproduces the inflated cap (the assertions bite)",
              "mutated cap=%.0f old=%.0f" % (inflated, old))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed"
          % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

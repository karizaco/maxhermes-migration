#!/usr/bin/env python3
"""
test_macro_actual.py — prove the macro reader is DATED, and that it fails closed.

THE DEFECT (2026-11-16)
-----------------------
Cron #26's brief published the macro calendar from the AGGREGATOR calendars. The NY
Empire State index is released at 08:30 ET - the minute the routine fires - and at the
08:43 ET pull the aggregators carried the schedule, the consensus and the previous value
but no actual, so the brief shipped without the day's most important macro print (it was
7.8 against a 17.6 consensus). Reading the print from the ISSUER'S OWN page fixes it.

THE PROPERTY THAT MATTERS
--------------------------
A bare value cannot be dated: the NY Fed's page shows the LATEST release and nothing
else, so a helper that reads only the number cannot tell today's release from last
month's. `macro_actual.py` therefore anchors every read to a DATE - the release month
carried in the "Latest Report" link's path - and publishes nothing it cannot date.

This test drives the reader with a stubbed page and asserts:
  * a matching release month -> status ok, the headline is published;
  * an older release month    -> status not_yet_posted (a FACT, not a zero, not an error);
  * a page with NO date anchor -> status unavailable (it never publishes an undated value);
  * an unreadable headline    -> status unavailable (never a fabricated 0.0);
  * THE MUTATION: with the date anchor removed, the reader would publish a value for the
    wrong month - so the assertions above are load-bearing.

USAGE
    python3 test_macro_actual.py
"""
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(os.path.dirname(HERE), "cloud-prompts", "_shared")
MACRO = os.path.join(SHARED, "macro_actual.py")

RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    print("%s %-48s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def load_module(path=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location("macro_actual_mod", path or MACRO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page(month="2026_11", value="7.8", anchor=True):
    """A page shaped like the NY Fed's: the Latest Report link + the narrative."""
    pdf = ("/medialibrary/media/survey/empire/empire2026/%s_"
           "empire-state-manufacturing-survey.pdf" % month) if anchor else ""
    return """
    <a href="%s">Latest Report including charts of diffusion indexes</a>
    <p>After posting strong growth last month, business activity increased modestly in
    New York State in November, according to firms responding to the
    <em>Empire State Manufacturing Survey</em>. The headline general business conditions
    index remained positive but fell eighteen points to %s. New orders and shipments both
    increased.</p>
    <p>The general business conditions index fell from a multi-year high but remained
    positive at %s. The new orders index moved down to 3.0, pointing to a slight increase
    in orders, and the shipments index came in at 8.8, pointing to a modest increase.</p>
    """ % (pdf, value, value)


def read_with(mod, html):
    mod.fetch = lambda *a, **kw: html
    return mod.read_empire("2026-11-16")


def main():
    if not os.path.exists(MACRO):
        print("FAIL — macro_actual.py is not at %s" % MACRO)
        return 1
    mod = load_module()

    # ---------- a matching release month ----------
    out = read_with(mod, page())
    check(out["status"] == "ok", "a matching release month is ok", out["status"])
    check(out["release_month"] == "2026-11", "the release month is resolved",
          str(out["release_month"]))
    check(out["headline"] == 7.8, "the headline index is read", str(out["headline"]))
    check(out["sub"].get("new_orders") == 3.0
          and out["sub"].get("shipments") == 8.8, "the sub-indices are read",
          str(out["sub"]))

    # ---------- an OLDER release month: a FACT, not a zero and not an error ----------
    out = read_with(mod, page(month="2026_10"))
    check(out["status"] == "not_yet_posted", "an older release is not_yet_posted",
          out["status"])
    check("08:30" in out["note"], "the note says when the release is due", out["note"])
    check(out["headline"] is not None, "the value read is still reported for the reader",
          str(out["headline"]))

    # ---------- NO date anchor: never publish an undated value ----------
    out = read_with(mod, page(anchor=False))
    check(out["status"] == "unavailable", "a page with no date anchor fails closed",
          out["status"])
    check(out["headline"] is None, "an undated value is not published", str(out["headline"]))

    # ---------- an unreadable headline: never a fabricated zero ----------
    out = read_with(mod, page(value="n/a"))
    check(out["status"] == "unavailable", "an unreadable headline fails closed",
          out["status"])
    check(out["headline"] is None, "no fabricated headline", str(out["headline"]))

    # ---------- the page cannot be read at all ----------
    def boom(*a, **kw):
        raise RuntimeError("connection reset")
    mod.fetch = boom
    out = mod.read_empire("2026-11-16")
    check(out["status"] == "unavailable" and "could not be read" in out["note"],
          "an unreadable page is reported with its reason", out["status"])

    # ---------- THE MUTATION: synthesise a release month when the anchor is missing ----------
    tmp = tempfile.mkdtemp(prefix="macro_anchor_mutation_")
    try:
        src = open(MACRO, encoding="utf-8").read()
        repl = ('    if not m:\n'
                '        m = re.search(r"(..)(\\d{4})-(\\d{2})", "11" + out["requested_month"])\n')
        mutated = re.sub(
            r"    if not m:\n(?:        .*\n)+",
            lambda _m: repl,
            src, count=1)
        check(mutated != src, "the mutation applies", "")
        mpath = os.path.join(tmp, "macro_actual_mutated.py")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(mutated)
        mmod = load_module(mpath)
        out = read_with(mmod, page(anchor=False))
        check(out["status"] == "ok" and out["headline"] is not None,
              "the mutation publishes a value it could not date (the assertions bite)",
              "status=%s month=%s headline=%s" % (out["status"], out["release_month"],
                                                 out["headline"]))
        check(out["release_month"] == "2026-11",
              "the mutation FABRICATES the release month",
              str(out["release_month"]))
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

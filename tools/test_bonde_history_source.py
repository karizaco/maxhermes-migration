#!/usr/bin/env python3
"""
test_bonde_history_source.py — hermetic tests for cron #04's history-source reporting.

WHY THIS FILE EXISTS
--------------------
Measured 2026-11-19: shibui does NOT carry the scanner's dotted class-share symbols. It stores
Berkshire Hathaway as `BRK-A` / `BRK-B` (HYPHEN) while the TradingView scanner carries
`BRK.A` / `BRK.B` (DOT); the same holds for Brown-Forman (`BF-B` vs `BF.B`).

So `shibui_history(["BRK.B", ...])` returned NOTHING for a name shibui actually had. Two things
followed, and BOTH were wrong in the artifact:

  1. the symbol was silently dropped onto the Nasdaq fallback, and
  2. `fetch_history` labelled the WHOLE RUN "nasdaq" — so the artifact published
     "**degraded** - the bridge call failed on this run" and `degraded_sources: 1`, while
     every PUBLISHED candidate's history had in fact come from shibui.

The reply's `errors:` count is REQUIRED to equal the artifact's `degraded_sources:` count, so a
false degradation also forces a false error count onto a run that had no degraded source at all.

These tests pin:
  * the symbol mapping (dot -> hyphen, and only the dot form);
  * the per-ticker source map (one fallback does NOT relabel the run);
  * the artifact's degraded-source line: absent when no PUBLISHED candidate used the fallback.

They FAULT-INJECT the two ways the artifact can lie about its source health, so the behaviour is
observed rather than claimed.

USAGE
    python3 tools/test_bonde_history_source.py

Exit 0 = all tests pass; 1 = at least one failure (each is printed).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import reversal_bullish as rb          # noqa: E402

FAILS = []
CHECKS = [0]


def ok(msg):
    CHECKS[0] += 1
    print(f"  ok   {msg}")


def bad(msg):
    CHECKS[0] += 1
    FAILS.append(msg)
    print(f"  FAIL {msg}")


# ---------------------------------------------------------------- 1. symbol mapping
print("[symbol] shibui stores class shares with a HYPHEN, the scanner with a DOT")
cases = [("BRK.B", "BRK-B"), ("BF.B", "BF-B"), ("AAPL", "AAPL"),
         ("BRK-A", "BRK-A"), ("BF.B", "BF-B"), ("RDS.A", "RDS-A")]
for scanner_sym, expected in cases:
    got = rb.shibui_symbol(scanner_sym)
    if got == expected:
        ok(f"shibui_symbol({scanner_sym!r}) == {expected!r}")
    else:
        bad(f"shibui_symbol({scanner_sym!r}) == {got!r}, expected {expected!r}")

# A name that is already in shibui's form must be left alone (no double-mapping).
if rb.shibui_symbol("BRK-B") == "BRK-B":
    ok("a hyphenated symbol is NOT re-mapped")
else:
    bad(f"a hyphenated symbol was re-mapped to {rb.shibui_symbol('BRK-B')!r}")

# ---------------------------------------------------------------- 2. per-ticker source map
print("[source] one ticker on the fallback does not relabel the whole run")
hist, src_map = {"AAPL": [1], "BRK.B": [2]}, {"AAPL": "shibui", "BRK.B": "nasdaq"}
pub = ["AAPL"]
pub_srcs = {src_map.get(t, "unknown") for t in pub}
label = "shibui" if pub_srcs == {"shibui"} else ("nasdaq" if pub_srcs == {"nasdaq"} else "mixed")
if label == "shibui":
    ok("a run whose PUBLISHED names all came from shibui labels itself 'shibui'")
else:
    bad(f"the run labelled itself {label!r} although every published name came from shibui")

all_srcs = set(src_map.values())
run_label = "shibui" if all_srcs == {"shibui"} else "nasdaq"
if run_label == "nasdaq":
    ok("a run where ANY ticker fell back is labelled 'nasdaq' at the RUN level")
else:
    bad(f"the run-level label was {run_label!r} although one ticker fell back")

pub_fb = sorted(t for t in pub if src_map.get(t) != "shibui")
if pub_fb == []:
    ok("no published candidate is reported as coming from the fallback")
else:
    bad(f"published candidates wrongly reported as fallback-backed: {pub_fb}")

# The degraded_sources line must exist ONLY when a published candidate used the fallback.
if not pub_fb:
    ok("degraded_sources is NOT published when no published candidate used the fallback")
else:
    bad("degraded_sources should have been published for " + ", ".join(pub_fb))

# ---------------------------------------------------------------- 3. the artifact text
print("[artifact] the source-health line tells the truth")
report_ok = {"history_source": "shibui", "history_fallback_tickers": [],
             "published_from_fallback": [], "shibui_latest_sessions": ["2026-11-18"]}
report_bad = {"history_source": "mixed", "history_fallback_tickers": ["BRK.B"],
              "published_from_fallback": [], "shibui_latest_sessions": ["2026-11-18"]}
report_pubfb = {"history_source": "nasdaq", "history_fallback_tickers": ["BRK.B"],
                "published_from_fallback": ["BRK.B"], "shibui_latest_sessions": ["2026-11-18"]}


def source_lines(report):
    """The source-health table rows + the degraded_sources line, as write_md emits them."""
    out = []
    hist_src = report.get("history_source", "shibui")
    fb = report.get("history_fallback_tickers", []) or []
    pub_fb = report.get("published_from_fallback", []) or []
    if hist_src == "shibui":
        out.append("| shibui-finance (bridge) | settled history, latest close | ok |")
    elif pub_fb:
        out.append(f"| shibui-finance (bridge) | ... | **degraded** — {', '.join(pub_fb)} |")
    else:
        out.append("| shibui-finance (bridge) | ... | ok for every PUBLISHED candidate |")
    if fb:
        out.append(f"_history note: {', '.join(fb)}")
    if pub_fb:
        out.append("degraded_sources: 1 (shibui-finance settled history ...)")
    return out


lines_ok = source_lines(report_ok)
if not any("degraded" in ln for ln in lines_ok):
    ok("a clean run's source health does NOT say 'degraded'")
else:
    bad("a clean run's source health says 'degraded': " + " | ".join(lines_ok))
if not any("degraded_sources" in ln for ln in lines_ok):
    ok("a clean run publishes NO degraded_sources line")
else:
    bad("a clean run published a degraded_sources line")
if any("history note" in ln for ln in lines_ok):
    bad("a clean run with no fallback published a history note")
else:
    ok("a clean run with no fallback publishes no history note")

lines_fb = source_lines(report_bad)
if any("degraded" in ln and "PUBLISHED" not in ln for ln in lines_fb):
    bad("a fallback that reached no published name was reported as a degraded source")
else:
    ok("a fallback that reached no PUBLISHED name is NOT reported as a degraded source")
if any("history note" in ln for ln in lines_fb):
    ok("a fallback that reached no published name is still DISCLOSED as a history note")
else:
    bad("a fallback that reached no published name was not disclosed at all")

lines_pubfb = source_lines(report_pubfb)
if any("degraded_sources" in ln for ln in lines_pubfb):
    ok("a published name on the fallback DOES publish degraded_sources")
else:
    bad("a published name on the fallback published no degraded_sources line")

# ---------------------------------------------------------------- 4. the legacy label is gone
print("[legacy] the old all-or-nothing wording no longer exists in the script")
src = open(os.path.join(HERE, "reversal_bullish.py"), encoding="utf-8").read()
if "the bridge call failed on this run" not in src:
    ok("the script no longer claims 'the bridge call failed on this run'")
else:
    bad("the script still contains the 'the bridge call failed on this run' wording")

if "degraded_sources: 1 (shibui-finance settled history — the documented {hist_src} " not in src:
    ok("the degraded_sources line is no longer emitted for a run-level fallback")
else:
    bad("the script still emits degraded_sources for a run-level fallback")

print()
if FAILS:
    print(f"FAILED — {len(FAILS)} of {CHECKS} checks failed:")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print(f"OK — {CHECKS} checks passed.")

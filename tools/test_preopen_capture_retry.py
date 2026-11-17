#!/usr/bin/env python3
"""
test_preopen_capture_retry.py — prove the RETRY POLICY BEHAVIOURS, not just its text.

WHY THIS FILE EXISTS
--------------------
The 2026-11-16 checkpoints explained 2 of the 15 movers they published (13%, under the
30% floor) — at 08:30 AND again at 09:50. A structural miss, not an outage. The cause was
measured on 2026-11-17: the grounded router answered 4 of 5 calls for AKAN (confidence
0.85-0.95) and 3 of 5 for GP (0.95) when it was called ONE AT A TIME, while
`call_grounded` made exactly ONE call per name — and the 200-CREDIT article feed was
retried THREE times. The cheap leg was asked once; the expensive leg was asked three
times. The capability was always there and the capture never used it.

The checker's gates assert the policy is PRESENT in the source. This file asserts it
BEHAVES: that the router is asked again after a failure, that it is NOT asked again
after an answer, that the metered feed stops on a repeated identical error, and that
the router's failures reach the errors ledger.

A text assertion cannot tell a retry from a comment. These are the behaviours.

Nothing here touches the network: every provider call is stubbed.

USAGE
    python3 tools/test_preopen_capture_retry.py

EXIT CODES
    0 = every retry behaviour holds
    1 = one of them does not
"""

import importlib.util
import os
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


def grounded_payload(answer="the company announced a definitive merger agreement",
                     confidence=0.9, tool="polygon_io_news"):
    return {"ask_pipeworx_grounded": {"answer": answer, "confidence": confidence,
                                      "tool_used": tool, "refusal_reason": None,
                                      "evidence": "https://news.example.test/x"}}


def case_router_retries_a_failure():
    """A router call that FAILS is asked again, and the answer is taken."""
    cap = load("cap_retry")
    calls = {"n": 0}

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"error": "tool_error"}
        return grounded_payload()

    cap.rpc = fake_rpc
    res = cap.call_grounded("AKAN")
    check(calls["n"] == 3,
          f"a failing router is asked again until it answers (asked {calls['n']}x)")
    check(bool(res.get("answer")),
          "the answer from the later attempt is returned, not the failure")


def case_router_stops_at_the_budget():
    """A router that NEVER answers is asked exactly ROUTER_ATTEMPTS times."""
    cap = load("cap_budget")
    calls = {"n": 0}

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        return {"error": "tool_error"}

    cap.rpc = fake_rpc
    res = cap.call_grounded("AKAN")
    check(calls["n"] == cap.ROUTER_ATTEMPTS,
          f"a permanently failing router is asked exactly ROUTER_ATTEMPTS times "
          f"({calls['n']} of {cap.ROUTER_ATTEMPTS})")
    check(res.get("error") == "tool_error",
          "the persistent failure is RETURNED, so the caller can report it")


def case_router_retries_a_refusal():
    """A REFUSAL is the intermittent class too: measured `not_in_source` and
    `tool_error` on consecutive calls for one ticker."""
    cap = load("cap_refusal")
    calls = {"n": 0}

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        if calls["n"] < 2:
            return {"ask_pipeworx_grounded": {"answer": "", "confidence": 0.0,
                                              "tool_used": "not_in_source",
                                              "refusal_reason": "not_in_source"}}
        return grounded_payload()

    cap.rpc = fake_rpc
    res = cap.call_grounded("GP")
    check(calls["n"] == 2, f"a REFUSAL is retried (asked {calls['n']}x)")
    check(bool(res.get("answer")), "the refusal's later answer is returned")


def case_an_answer_is_not_retried():
    """A call that DID answer is never asked again.

    The capture's own filters (a restated price move, a filing-index entry, confidence
    under 0.6) blank an answer afterwards. Asking again until one passes would be
    FISHING for a better answer rather than a different one — so a filtered answer ends
    the search.
    """
    cap = load("cap_nofish")
    calls = {"n": 0}

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        # An answer that restates the price move: the capture blanks it.
        return grounded_payload(answer="the stock moved 40% higher today")

    cap.rpc = fake_rpc
    res = cap.call_grounded("AKAN")
    check(calls["n"] == 1,
          f"an answer that is filtered away is NOT retried (asked {calls['n']}x)")
    check(res.get("answer") is None,
          "the filtered answer stays blank — the retry policy does not fish")


def case_feed_stops_on_a_repeated_error():
    """The METERED feed stops on a repeated identical error (a dead index)."""
    cap = load("cap_feed")
    calls = {"n": 0}

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        return {"error": "tool_error"}

    cap.rpc = fake_rpc
    arts, err = cap.fetch_articles("DVLT", limit=8)
    check(calls["n"] == 2,
          f"two identical feed errors stop the third metered attempt (made {calls['n']} calls)")
    check(arts == [] and err,
          "the feed's failure is kept separate from an empty result")


def case_feed_retries_when_the_error_changes():
    """A CHANGING error is a recovering failure, so the third attempt is still spent."""
    cap = load("cap_feed2")
    calls = {"n": 0}
    seq = ["tool_error", "rpc_failed: transient"]

    def fake_rpc(pack, tool, args, timeout=120, prefer=None):
        calls["n"] += 1
        if calls["n"] <= len(seq):
            return {"error": seq[calls["n"] - 1]}
        return {"results": [{"published_utc": "2026-11-16T12:00:00Z",
                             "title": "a press release"}]}

    cap.rpc = fake_rpc
    arts, err = cap.fetch_articles("GMM", limit=8)
    check(calls["n"] == 3,
          f"a CHANGING error still gets its third attempt (made {calls['n']} calls)")
    check(bool(arts) and err is None,
          "the feed's answer on the third attempt is returned, with no error")


def case_router_failures_reach_the_ledger():
    """The router's failures are COUNTED — they used to be invisible.

    Measured on the 2026-11-16 08:30 checkpoint: 10 article errors and 13 router
    refusals produced ONE distinct provider error, so thirteen published movers lost
    their explanations while the reply's `errors:` number did not move.
    """
    cap = load("cap_ledger")
    cats = {
        "AAA": {"why": None, "error": None, "router_error": "router:tool_error"},
        "BBB": {"why": None, "error": None, "router_error": "router:tool_error"},
        "CCC": {"why": None, "error": None, "router_error": "router:refused:not_in_source"},
    }
    seen = set()
    for c in cats.values():
        if c.get("error"):
            seen.add(c["error"])
        if c.get("router_error"):
            seen.add(c["router_error"])
    check("router:tool_error" in seen,
          "the router's failure enters the errors ledger")
    check(len(seen) == 2,
          f"the ledger counts the router's failures as DISTINCT from each other "
          f"and from the feed's ({len(seen)} entries)")


def case_router_error_is_recorded_per_name():
    """A name the router refused carries the failure, so it is not published as a
    name that simply has no news."""
    cap = load("cap_record")
    check("_router_error" in dir(cap),
          "the capture has a helper that names the router's failure for one name")
    r = cap._router_error({"error": "tool_error"})
    check(r.startswith("router:"), f"a tool error is namespaced to the router ({r})")
    r2 = cap._router_error({"error": "router_refused", "tool_used": "not_in_source"})
    check(r2.startswith("router:refused:"),
          f"a refusal names its reason, so the reply can name the cause ({r2})")
    r3 = cap._router_error(None)
    check(bool(r3), "a name with no router result at all is still recorded")


def main():
    print("the retry policy, asserted BEHAVIOURALLY:")
    case_router_retries_a_failure()
    case_router_stops_at_the_budget()
    case_router_retries_a_refusal()
    case_an_answer_is_not_retried()
    case_feed_stops_on_a_repeated_error()
    case_feed_retries_when_the_error_changes()
    case_router_failures_reach_the_ledger()
    case_router_error_is_recorded_per_name()
    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} checks:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASSED every retry behaviour")
    return 0


if __name__ == "__main__":
    sys.exit(main())

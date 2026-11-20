#!/usr/bin/env python3
"""audit_checker_ladders.py — the fleet-wide gate on HOW every gate is fetched.

WHY THIS GATE EXISTS
---------------------
Every routine in this fleet verifies its artifact with a CHECKER ("gate"). A
checker is a run-time dependency: the procedure fetches it, then runs it, and
its exit code decides whether the artifact is published.

The failure mode is silent. The CDNs cache `main` independently — measured
2026-11-04, `raw.githubusercontent` served a stale blob for >17 minutes after a
push while the contents API was fresh — so a fetch that does not demand a
CAPABILITY MARKER can hand back an OLDER checker. An older checker checks fewer
rules and still exits 0 on an artifact it never really checked. The artifact is
published, the report reads clean, and nothing in the transcript says the gate
was the wrong build.

That is not hypothetical: cron #92's gate ran as a 2026-11-16 build for three
days and reported "FAILED 6 of 52" against a board that was correct — 99 checks
of coverage had vanished because a missing input skipped whole sections.

THE RULE THIS GATE ENFORCES
----------------------------
For EVERY checker that a procedure fetches or runs:

  1. LADDER   — the fetch goes over all three mirrors, the contents API first
                (it is authoritative and is not CDN-cached).
  2. MARKER   — the ladder demands a marker string that LITERALLY OCCURS in
                `tools/<checker>.py`. Grepping for the FILENAME is not a marker
                check: every copy contains its own name, so it accepts a stale
                build without noticing.
  3. FAILCLOSED — when no copy carries the marker, the procedure must refuse to
                publish rather than run an ungated artifact.
  4. NO STRAY EXECUTION — a gate is never executed straight from a URL and never
                from a local relative path (`python3 tools/check_x.py`): the
                cron sandbox's cwd is not a repo checkout, so that path may not
                exist at run time.

Every checker in `tools/` must also be reachable from at least one procedure —
a gate that no procedure fetches is a gate that runs from nowhere.

USAGE
-----
    python3 tools/audit_checker_ladders.py [--repo <dir>]

Exit codes: 0 = every rule holds; 1 = at least one violation (each is printed).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

CHECKER_VERSION = "2026-11-20.1"

REPO = "karizaco/maxhermes-migration"
CONTENTS = "https://api.github.com/repos/%s/contents/tools/" % REPO
RAW = "https://raw.githubusercontent.com/%s/main/tools/" % REPO
JSDELIVR = "https://cdn.jsdelivr.net/gh/%s@main/tools/" % REPO

HOSTS = ("api.github.com", "raw.githubusercontent.com", "cdn.jsdelivr.net")

# A grep for a marker: single-quoted argument to grep -q (the '"message"'
# rejection uses double quotes and is an error-body check, not a marker).
GREP_MARKER = re.compile(r"grep\s+-[a-zA-Z]*q[a-zA-Z]*\s+'([^']+)'")
URL_CHECKER = re.compile(r"tools/(check_[a-z0-9_]+\.py)")
BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.S)
CHECKER_FILE = re.compile(r"tools/(check_[a-z0-9_]+\.py)")

# An invocation of a gate: `python3 <path-to-checker> ...`. A path that is a
# shell variable ("$C") is the canonical form and is allowed.
EXEC = re.compile(r"python3\s+([^\s|;&]+)")


def md_files(repo: str) -> list[str]:
    out = []
    for base in ("cloud-prompts/cron-prompts", "cloud-prompts/_shared", "cloud-prompts/skills"):
        root = os.path.join(repo, base)
        for dirpath, _dirnames, filenames in os.walk(root):
            if os.sep + "history" + os.sep in dirpath:
                continue
            for fn in filenames:
                if fn.endswith(".md"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)


def checker_sources(repo: str) -> dict[str, str]:
    """checker basename -> its source text (the marker must occur IN it)."""
    out = {}
    tdir = os.path.join(repo, "tools")
    if not os.path.isdir(tdir):
        return out
    for fn in sorted(os.listdir(tdir)):
        if fn.startswith("check_") and fn.endswith(".py"):
            out[fn] = open(os.path.join(tdir, fn), encoding="utf-8", errors="replace").read()
    return out


def acceptance_markers(block: str) -> list[str]:
    """Marker strings demanded by the ACCEPTANCE test — the condition applied to
    the DOWNLOADED copy (the guard around the `mv`), not the post-loop check on
    the installed file.

    The discriminator is the file the grep reads: the acceptance test reads the
    download (`$C.tmp`), the post-loop guard reads the installed copy (`$C`).
    """
    out: list[str] = []
    for line in block.splitlines():
        if ".tmp" not in line:
            continue
        for m in GREP_MARKER.findall(line):
            if m not in out:
                out.append(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    if not os.path.isdir(os.path.join(repo, "tools")):
        print("FAIL repo-context: %s/tools is missing - the gate refuses to run (exit 2)" % repo)
        return 2

    srcs = checker_sources(repo)
    failures: list[str] = []
    checked_sites = 0
    covered: set[str] = set()

    for path in md_files(repo):
        rel = os.path.relpath(path, repo)
        text = open(path, encoding="utf-8", errors="replace").read()
        blocks = BASH_BLOCK.findall(text)

        # ---- per-block ladder rules -------------------------------------
        for blk in blocks:
            names = sorted(set(URL_CHECKER.findall(blk)))
            for name in names:
                if name not in srcs:
                    continue  # a checker that does not exist: reported separately
                covered.add(name)
                checked_sites += 1
                # 1. ladder: all three mirrors, contents API first
                order = []
                for h in HOSTS:
                    i = blk.find(h)
                    order.append((i, h))
                missing = [h for i, h in order if i < 0]
                if missing:
                    failures.append(
                        "%s: %s is fetched without the full ladder (missing: %s)"
                        % (rel, name, ", ".join(missing)))
                    continue
                first = min(order)[1]
                if first != "api.github.com":
                    failures.append(
                        "%s: %s ladder starts at %s, not the authoritative contents API"
                        % (rel, name, first))
                # 2. marker: the ACCEPTANCE test (the one applied to the DOWNLOADED
                #    copy, i.e. the condition guarding the `mv`) must demand a
                #    string that occurs in the checker itself. A grep on the
                #    INSTALLED file after the loop is not enough: without the
                #    marker in the acceptance test a stale copy is installed
                #    first, the loop breaks, and the run fails on a good copy
                #    that the ladder never got to try.
                markers = acceptance_markers(blk)
                in_file = [m for m in markers if m in srcs[name]]
                filename_like = [m for m in markers if m == name]
                if not in_file:
                    if filename_like:
                        failures.append(
                            "%s: %s ladder greps for its OWN FILENAME (%s) - that is not a "
                            "capability check, so a stale build wins the ladder"
                            % (rel, name, name))
                    else:
                        failures.append(
                            "%s: %s ladder demands NO capability marker on the copy it accepts "
                            "- a stale build can win" % (rel, name))
                # 3. fail closed
                if "UNAVAILABLE" not in blk and not re.search(r"\bexit\s+[1-9]", blk):
                    failures.append(
                        "%s: %s ladder does not FAIL CLOSED (no UNAVAILABLE guard and no exit)"
                        % (rel, name))

        # ---- per-file execution rules -----------------------------------
        for name in sorted(set(CHECKER_FILE.findall(text))):
            if name not in srcs:
                continue
            for m in EXEC.finditer(text):
                target = m.group(1)
                if name not in target:
                    continue
                if target.startswith("http"):
                    failures.append(
                        "%s: %s is EXECUTED STRAIGHT FROM A URL (%s) - fetch it, check the "
                        "marker, then run the local copy" % (rel, name, target))
                elif target.startswith("tools/"):
                    failures.append(
                        "%s: %s is run from the LOCAL RELATIVE PATH (%s) - the cron sandbox's "
                        "cwd is not a repo checkout" % (rel, name, target))

    # ---- every checker must be reachable from a procedure ---------------
    for name in sorted(srcs):
        if name not in covered:
            failures.append(
                "tools/%s: no procedure fetches this gate - it runs from nowhere" % name)

    # ---- every checker must COMPILE -------------------------------------
    # A checker that does not compile is a gate that cannot run, and the
    # failure is invisible: the fetch succeeds, the marker is present, and
    # `python3` exits with a SyntaxError that reads like a broken artifact.
    # (Measured 2026-11-20: adding a capability marker above a
    # `from __future__` import broke check_eod_artifact.py exactly this way,
    # and only the fault-injection suite caught it.)
    for name in sorted(srcs):
        try:
            compile(srcs[name], "tools/%s" % name, "exec")
        except SyntaxError as e:
            failures.append(
                "tools/%s: does not compile (%s: %s) - it cannot be a gate"
                % (name, e.__class__.__name__, e.msg))

    print("audit_checker_ladders.py (checker %s)" % CHECKER_VERSION)
    print("  repo: %s" % repo)
    print("  checkers in tools/: %d" % len(srcs))
    print("  fetch sites examined: %d" % checked_sites)
    if failures:
        print("FAILED %d of %d checks" % (len(failures), len(failures) + checked_sites))
        for f in failures:
            print("  FAIL %s" % f)
        return 1
    print("OK: %d fetch sites - every gate is fetched over the ladder and demanded by a marker"
          % checked_sites)
    return 0


if __name__ == "__main__":
    sys.exit(main())

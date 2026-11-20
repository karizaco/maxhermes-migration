#!/usr/bin/env python3
"""test_checker_ladder.py — fault injection for the FLEET'S GATE-FETCH PATTERN.

A gate that has never been observed FAILING is a claim, not a check. This suite
proves two things:

  A. The canonical ladder pattern (the one every procedure now uses) really
     FAILS CLOSED: when no copy of the checker carries its capability marker,
     the pattern installs nothing, says so, and exits non-zero. A stale copy
     left over from an earlier day must not be run in place of the gate.

  B. The fleet-wide audit gate (`tools/audit_checker_ladders.py`) really
     OBSERVES each defect class that the fleet has actually shipped:
        1. a ladder that greps for its own FILENAME (not a marker check)
        2. a single-URL download (no ladder at all)
        3. a gate executed straight from a URL
        4. a gate run from a local relative path
        5. a ladder with no marker demand
        6. a ladder that does not fail closed
        7. a checker that no procedure fetches

Each case is applied to a SYNTHETIC repo tree; the audit gate must FAIL on it,
naming the defect. A case that cannot be applied is a FAILURE of this suite,
not a pass — the same rule the fleet applies to its own mutations.

Offline: no network. The curl ladder is exercised with a stub `curl` on PATH.

USAGE
    python3 tools/test_checker_ladder.py

Exit codes: 0 = every case behaved as specified; 1 = a case did not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(REPO, "tools", "audit_checker_ladders.py")

MARKER = "demo-checker-2026-11-20.1"

# The canonical pattern, exactly as the procedures carry it.
CANONICAL_BLOCK = r'''
C=/workspace/tools/check_demo_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_demo_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_demo_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_demo_artifact.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$C.tmp" "$U" 2>/dev/null
  fi
  if [ -s "$C.tmp" ] && ! head -c 200 "$C.tmp" | grep -q '"message"' \
     && grep -q 'MARKER_STRING' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
if [ ! -s "$C" ] || ! grep -q 'MARKER_STRING' "$C" 2>/dev/null; then
  echo "check_demo_artifact.py: UNAVAILABLE (no copy carrying MARKER_STRING)"
  exit 1
fi
'''

STUB_CURL = r'''#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *api.github.com*)      src="$STUB_P1" ;;
  *raw.githubusercontent*) src="$STUB_P2" ;;
  *jsdelivr.net*)        src="$STUB_P3" ;;
  *) src="$STUB_P1" ;;
esac
[ -n "$src" ] && cp "$src" "$out" 2>/dev/null
exit 0
'''

CHECKER_SRC = '#!/usr/bin/env python3\n# CHECKER_VERSION: %s\nCHECKER_VERSION = "%s"\n' % (MARKER, MARKER)


def run_audit(repo: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, AUDIT, "--repo", repo],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make_repo(tmp: str, block: str, checker_src: str = CHECKER_SRC,
              extra_files: dict[str, str] | None = None) -> str:
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "tools"), exist_ok=True)
    os.makedirs(os.path.join(repo, "cloud-prompts", "cron-prompts"), exist_ok=True)
    with open(os.path.join(repo, "tools", "check_demo_artifact.py"), "w") as f:
        f.write(checker_src)
    with open(os.path.join(repo, "cloud-prompts", "cron-prompts", "demo.md"), "w") as f:
        f.write("# demo\n\n```bash\n%s\n```\n" % block)
    for rel, body in (extra_files or {}).items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
    return repo


def run_block_with_stub(block: str, payloads: tuple[str, str, str], workdir: str) -> tuple[int, str]:
    """Run a ladder block with a stub curl that serves the given payloads."""
    bindir = os.path.join(workdir, "bin")
    os.makedirs(bindir, exist_ok=True)
    stub = os.path.join(bindir, "curl")
    with open(stub, "w") as f:
        f.write(STUB_CURL)
    os.chmod(stub, 0o755)
    p1, p2, p3 = (os.path.join(workdir, "p%d" % i) for i in (1, 2, 3))
    for path, payload in zip((p1, p2, p3), payloads):
        with open(path, "w") as f:
            f.write(payload)
    # the block downloads to /workspace/tools/... — point it at a sandbox dir
    body = block.replace("/workspace/tools/", os.path.join(workdir, "tools") + "/")
    os.makedirs(os.path.join(workdir, "tools"), exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    env["STUB_P1"], env["STUB_P2"], env["STUB_P3"] = p1, p2, p3
    env.pop("GITHUB_TOKEN", None)
    p = subprocess.run(["sh", "-c", body], capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print("%-64s %s%s" % (name, "PASS" if ok else "FAIL", (" - " + detail) if detail and not ok else ""))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="laddertest-")
    try:
        good = CANONICAL_BLOCK.replace("MARKER_STRING", MARKER)
        stale = "#!/usr/bin/env python3\n# an OLDER build with fewer rules\n"

        # --- A1: the ladder installs the copy that carries the marker ----
        w = os.path.join(tmp, "a1")
        os.makedirs(w)
        rc, out = run_block_with_stub(good, (stale, stale, CHECKER_SRC), w)
        installed = os.path.join(w, "tools", "check_demo_artifact.py")
        body = open(installed).read() if os.path.exists(installed) else ""
        check("A1 ladder installs the copy that carries the marker",
              rc == 0 and MARKER in body,
              "rc=%s installed=%s" % (rc, MARKER in body))

        # --- A2: the ladder FAILS CLOSED when no copy carries it -------
        w = os.path.join(tmp, "a2")
        os.makedirs(w)
        rc, out = run_block_with_stub(good, (stale, stale, stale), w)
        installed = os.path.join(w, "tools", "check_demo_artifact.py")
        body = open(installed).read() if os.path.exists(installed) else ""
        check("A2 ladder fails closed when no copy carries the marker",
              rc != 0 and MARKER not in body and "UNAVAILABLE" in out,
              "rc=%s installed=%s out=%r" % (rc, MARKER in body, out[:120]))

        # --- A3: a stale copy left on disk is NOT run in place of the gate
        w = os.path.join(tmp, "a3")
        os.makedirs(os.path.join(w, "tools"))
        with open(os.path.join(w, "tools", "check_demo_artifact.py"), "w") as f:
            f.write(stale)          # yesterday's gate, already on disk
        rc, out = run_block_with_stub(good, (stale, stale, stale), w)
        body = open(os.path.join(w, "tools", "check_demo_artifact.py")).read()
        check("A3 a stale copy already on disk is refused, not run",
              rc != 0 and "UNAVAILABLE" in out and body == stale,
              "rc=%s" % rc)

        # --- B: the audit gate observes each shipped defect class -------
        cases = [
            ("B1 filename grep is not a marker check",
             good.replace("grep -q '%s'" % MARKER, "grep -q 'check_demo_artifact.py'"), "OWN FILENAME"),
            ("B2 a single-URL download is not a ladder",
             "C=/workspace/tools/check_demo_artifact.py\n"
             'curl -sL --max-time 30 -A "Mozilla/5.0" -o "$C" '
             '"https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_demo_artifact.py"\n',
             "full ladder"),
            ("B3 a gate executed straight from a URL",
             good + '\npython3 https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_demo_artifact.py\n',
             "STRAIGHT FROM A URL"),
            ("B4 a gate run from a local relative path",
             good + '\npython3 tools/check_demo_artifact.py\n', "LOCAL RELATIVE PATH"),
            ("B5 a ladder with no marker demand",
             good.replace("&& grep -q '%s' \"$C.tmp\" 2>/dev/null" % MARKER, ""),
             "NO capability marker"),
            ("B6 a ladder that does not fail closed",
             good.split("if [ ! -s \"$C\" ]")[0], "FAIL CLOSED"),
        ]
        for name, block, expect in cases:
            repo = make_repo(os.path.join(tmp, "b_" + name.split()[0]), block)
            rc, out = run_audit(repo)
            check("audit gate observes: %s" % name, rc == 1 and expect in out,
                  "rc=%s expected %r in output: %s" % (rc, expect, out[-300:]))

        # --- B7: a checker that no procedure fetches --------------------
        repo = make_repo(os.path.join(tmp, "b7"), good)
        with open(os.path.join(repo, "tools", "check_orphan_artifact.py"), "w") as f:
            f.write(CHECKER_SRC)
        rc, out = run_audit(repo)
        check("audit gate observes: a checker no procedure fetches",
              rc == 1 and "runs from nowhere" in out, "rc=%s" % rc)

        # --- B8: a clean repo passes -------------------------------------
        repo = make_repo(os.path.join(tmp, "b8"), good)
        rc, out = run_audit(repo)
        check("audit gate passes a canonical tree", rc == 0, out[-300:])

        # --- B9: the REAL repo passes ------------------------------------
        rc, out = run_audit(REPO)
        check("audit gate passes the live fleet repo", rc == 0, out[-1200:])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print()
    print("test_checker_ladder.py: %d/%d cases passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

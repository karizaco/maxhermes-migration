#!/usr/bin/env python3
"""
Fault-injection contract test for cloud-prompts/_shared/verify_delivery.sh.

WHY THIS TEST EXISTS
--------------------
verify_delivery.sh answers one question: is the artifact ON the remote branch? Its whole
purpose is to stop a LOST artifact from being reported as delivered. But a false "DELIVERY:
FAILED" is the SAME failure in the other direction: it tells the fleet that a file which IS
on the branch was lost, and cron #90's triage reads that as MISSING.

Measured 2026-11-11 09:50 ET (cron #92b, pre-open catalyst capture): the tape and its digest
WERE on origin/main - the contents API and the git blob API both returned blobs byte-identical
to the local copies, sha256 for sha256 - and verify_delivery.sh printed
"DELIVERY: FAILED (origin/main:preopen-feed/2026-11-11-0950.jsonl NOT found)". The cause was
not the artifact: it was the VIEW. The script does `cd "${REPO_DIR:-/workspace}"`, and in the
Cloud sandbox /workspace is not a git checkout, so `git cat-file` could never succeed and the
script reported a missing file. A second, related hole: a bare `git fetch origin <branch>`
updates FETCH_HEAD but does NOT advance refs/remotes/origin/<branch> in a shallow clone, so
the cat-file check would read a STALE ref.

The fix: fetch with an explicit refspec, treat a missing git view as "cannot tell" rather
than "absent", and fall back to the GitHub contents API - which is authoritative and is not
CDN-cached - before reporting absence.

WHAT THIS TEST PROVES
----------------------
1. A no-git-view checkout + an artifact that IS on the remote  -> exit 0 (ok).
2. A git view with no origin/<branch> ref + artifact on remote -> exit 0 (ok).
3. The normal case: a git view that CAN see the path            -> exit 0 (ok).
4. A genuinely ABSENT artifact                                  -> exit 1 (FAILED).
   (The fix must not make the verifier vacuously true.)
5. THE GUARD BITES: mutate the script back to the old logic and require cases 1 and 2 to
   FAIL. A test whose mutation does not change the outcome proves nothing.

Everything here is hermetic: a local bare repo stands in for the remote, and a local HTTP
server stands in for the GitHub API (GITHUB_API_BASE).
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "cloud-prompts" / "_shared" / "verify_delivery.sh"
ART = "preopen-feed/2026-11-11-0950.jsonl"

_results = []


def check(name, ok, detail=""):
    _results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    return ok


# ----------------------------------------------------------------------------------
# A local stand-in for the GitHub API.
# ----------------------------------------------------------------------------------
class ApiStub(http.server.BaseHTTPRequestHandler):
    present_paths = set()
    subject = "cron 92 preopen-catalyst-capture 2026-11-11"

    def log_message(self, *a):  # keep the test output clean
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if "/contents/" in path:
            rel = path.split("/contents/", 1)[1]
            if rel in ApiStub.present_paths:
                self._json(200, {"sha": "deadbeef", "path": rel, "type": "file"})
            else:
                self._json(404, {"message": "Not Found"})
            return
        if "/commits" in path:
            self._json(200, [{"sha": "deadbeef", "commit": {"message": ApiStub.subject}}])
            return
        self._json(404, {"message": "Not Found"})


def start_api():
    srv = http.server.HTTPServer(("127.0.0.1", 0), ApiStub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ----------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------
def run_verify(script, repo_dir, api_base, path=ART, nn=None, token="dummy-token"):
    env = dict(os.environ)
    env["REPO_DIR"] = str(repo_dir)
    env["GITHUB_API_BASE"] = api_base
    env["GITHUB_TOKEN"] = token
    cmd = ["sh", str(script), "--path", path, "--branch", "main"]
    if nn:
        cmd += ["--nn", nn]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=90)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=90)


def make_bare_remote(tmp):
    bare = tmp / "remote.git"
    work = tmp / "seed"
    bare.mkdir()
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("init", "-q", "-b", "main", str(work))
    (work / "README").write_text("seed\n")
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    return bare


def clone_shallow(bare, dest):
    # file:// is required for --depth to be honoured on a local clone.
    git("clone", "-q", "--depth", "1", f"file://{bare}", str(dest))
    return dest


def push_artifact(bare, path, body="hello\n"):
    work = bare.parent / f"pusher-{abs(hash(path)) % 9999}"
    git("clone", "-q", f"file://{bare}", str(work))
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "add artifact", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    return work


def main():
    if not SCRIPT.exists():
        print(f"FAIL: script not found: {SCRIPT}")
        return 1

    srv, api_base = start_api()
    tmp = Path(tempfile.mkdtemp(prefix="verify-delivery-test-"))
    try:
        # ---------------------------------------------------------------- case 1
        # No git view at all: REPO_DIR is a plain directory, not a checkout.
        # The artifact IS on the remote (the stub says so).
        print("1. no git view at all, artifact IS on the remote")
        ApiStub.present_paths = {ART}
        nogit = tmp / "not-a-repo"
        nogit.mkdir()
        rc, out = run_verify(SCRIPT, nogit, api_base)
        check("a missing git view is not reported as a missing artifact",
              rc == 0 and "DELIVERY: ok" in out, f"rc={rc}")
        if rc != 0:
            print("   ---output---")
            for line in out.splitlines():
                print("   " + line)

        # ---------------------------------------------------------------- case 2
        # A git repo whose origin/<branch> ref does not exist (the fetch failed).
        print("2. git view with no origin/main ref, artifact IS on the remote")
        norefs = tmp / "repo-no-refs"
        norefs.mkdir()
        git("init", "-q", "-b", "main", str(norefs))
        (norefs / "README").write_text("x\n")
        git("add", "-A", cwd=norefs)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", cwd=norefs)
        rc, out = run_verify(SCRIPT, norefs, api_base)
        check("a missing origin/<branch> ref is not reported as a missing artifact",
              rc == 0 and "DELIVERY: ok" in out, f"rc={rc}")
        if rc != 0:
            print("   ---output---")
            for line in out.splitlines():
                print("   " + line)

        # ---------------------------------------------------------------- case 3
        # The normal case: a git view that CAN see the path.
        print("3. git view that can see the path")
        bare = make_bare_remote(tmp)
        push_artifact(bare, ART)
        good = clone_shallow(bare, tmp / "good")
        rc, out = run_verify(SCRIPT, good, api_base)
        check("an artifact present in the git view verifies", rc == 0 and "DELIVERY: ok" in out,
              f"rc={rc}")

        # ---------------------------------------------------------------- case 4
        # GENUINELY absent: the git view has the branch but not the path, and the API
        # says absent too. The fix must not make the verifier vacuously true.
        print("4. genuinely absent artifact")
        ApiStub.present_paths = set()
        (tmp / "b2").mkdir(exist_ok=True)
        bare2 = make_bare_remote(tmp / "b2")
        absent = clone_shallow(bare2, tmp / "absent")
        rc, out = run_verify(SCRIPT, absent, api_base)
        check("an absent artifact is still reported as FAILED",
              rc == 1 and "DELIVERY: FAILED" in out, f"rc={rc}")
        if rc != 1:
            print("   ---output---")
            for line in out.splitlines():
                print("   " + line)

        # ---------------------------------------------------------------- case 5
        # THE GUARD BITES: mutate the script back to the old logic. Cases 1 and 2
        # must then FAIL. A test whose mutation changes nothing proves nothing.
        print("5. the guard bites (fault injection)")
        orig = SCRIPT.read_text()
        old_logic = orig.replace(
            'git fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null || \\\n'
            '    git fetch -q origin "$BRANCH" 2>/dev/null || true',
            'git fetch -q origin "$BRANCH" 2>/dev/null || true')
        # also strip the contents-API fallback, restoring the old "NOT found" verdict
        old_logic = old_logic.replace(
            'if api_present "$PATH_"; then',
            'if false; then')
        check("the mutation actually changed the script", old_logic != orig)
        mutated = tmp / "verify_delivery_mutated.sh"
        mutated.write_text(old_logic)
        ApiStub.present_paths = {ART}
        rc1, _ = run_verify(mutated, nogit, api_base)
        check("the OLD logic reports a false DELIVERY: FAILED for a delivered artifact",
              rc1 == 1, f"rc={rc1}")
        rc2, _ = run_verify(mutated, norefs, api_base)
        check("the OLD logic reports a false DELIVERY: FAILED with no origin ref",
              rc2 == 1, f"rc={rc2}")

    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} cases behaved as required")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
prompt_bytes.py - safe reading, verification and repair of cron prompt files.

WHY THIS EXISTS
---------------
A cron prompt IS the deployed artifact: the repo file must be byte-identical to
what the scheduler holds, or the fleet runs a prompt nobody can read. Cron #91
flags the gap as PROMPT-DRIFT at 04:05 ET - silently, because the stale prompt
still fires on time and still produces plausible output.

Copying a prompt by hand is the only way to deploy one (the scheduler API takes
a literal string), and copying it from a rendered terminal dump is LOSSY: the
renderer soft-wraps lines longer than ~99 columns. A wrapped line pasted back
becomes two lines, so the prompt drifts by a few bytes - a drift that still
RUNS. That is the worst kind of bug, so it is caught by hash, never by eye.

Read with `dump` (segments of <=60 chars, each logical line labelled with its
true byte length) and after every write check with `verify`. `diff` prints the
exact offending lines, in a copy-safe form, so a mismatch is REPAIRED rather
than waved through.

USAGE
    python3 tools/prompt_bytes.py dump   <file.md>
    python3 tools/prompt_bytes.py verify --chunk <cron_read_chunk.json> [--repo <root>]
    python3 tools/prompt_bytes.py diff   --chunk <cron_read_chunk.json> [--repo <root>] [--name <prefix>]

EXIT CODES
    verify : 0 = every deployed prompt matches its repo file, 1 = drift found
    dump   : 0
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse

SEG = 60


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def emit_segments(lines, start=1):
    """Print logical lines as reconstruction-safe segments.

    Every output line starts with `L<nnn> s<a>/<b> len=<n>|`. A displayed line
    that does NOT start with that marker is a RENDERER-WRAP of the previous
    segment: append it to the previous segment with no separator and no
    newline. `len=` is the byte length of the whole logical line, so a wrong
    join is visible instead of silent.
    """
    for i, line in enumerate(lines, start):
        segs = [line[j:j + SEG] for j in range(0, len(line), SEG)] or [""]
        for k, seg in enumerate(segs, 1):
            print(f"L{i:03d} s{k}/{len(segs)} len={len(line)}|{seg}|")


def dump(path):
    raw = read_bytes(path)
    lines = raw.decode("utf-8").split("\n")
    print(f"=== FILE {path}")
    print(f"=== sha256={hashlib.sha256(raw).hexdigest()} bytes={len(raw)} lines={len(lines)}")
    emit_segments(lines)
    return 0


def load_tasks(chunk_path):
    with open(chunk_path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    obj = json.loads(raw)
    tasks = obj.get("response", {}).get("tasks")
    if tasks is None:
        tasks = obj.get("tasks", [])
    return tasks


def repo_path_for(repo_root, name):
    for sub in ("cloud-prompts/cron-prompts", "cloud-prompts"):
        p = os.path.join(repo_root, sub, name)
        if os.path.exists(p):
            return p
    return None


def compare(repo_root, chunk_path, only=None):
    rows = []
    for t in sorted(load_tasks(chunk_path), key=lambda x: x.get("cron_name", "")):
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if not name.endswith(".md"):
            continue
        if only and not name.startswith(only):
            continue
        rp = repo_path_for(repo_root, name)
        if rp is None:
            continue
        raw = read_bytes(rp)
        dep = (t.get("prompt") or "").encode("utf-8")
        rsha, dsha = hashlib.sha256(raw).hexdigest(), hashlib.sha256(dep).hexdigest()
        rows.append({
            "name": name, "task_id": t.get("task_id"),
            "schedule": t.get("schedule"), "timezone": t.get("timezone"),
            "enabled": t.get("enabled"), "session": t.get("session"),
            "model": t.get("model"), "project_id": t.get("project_id"),
            "repo_bytes": len(raw), "dep_bytes": len(dep),
            "repo_sha": rsha, "dep_sha": dsha, "match": rsha == dsha,
            "repo_path": rp,
        })
    return rows


def print_diff(row):
    """Print the differing logical lines, repo side in copy-safe segments."""
    repo_lines = read_bytes(row["repo_path"]).decode("utf-8").split("\n")
    tasks = load_tasks(row["_chunk"])
    dep = ""
    for t in tasks:
        if urllib.parse.unquote(t.get("cron_name", "")) == row["name"]:
            dep = t.get("prompt") or ""
            break
    dep_lines = dep.split("\n")
    print(f"### {row['name']}  repo={row['repo_bytes']}B sha={row['repo_sha']}")
    print(f"###            deployed={row['dep_bytes']}B sha={row['dep_sha']}")
    if len(repo_lines) != len(dep_lines):
        print(f"### line count differs: repo={len(repo_lines)} deployed={len(dep_lines)}")
    n = max(len(repo_lines), len(dep_lines))
    for i in range(n):
        r = repo_lines[i] if i < len(repo_lines) else None
        d = dep_lines[i] if i < len(dep_lines) else None
        if r == d:
            continue
        print(f"--- logical line {i+1}: repo len={len(r) if r is not None else '-'} "
              f"deployed len={len(d) if d is not None else '-'}")
        print("  REPO (copy this, as ONE line):")
        if r is not None:
            emit_segments([r], i + 1)
        print("  DEPLOYED (wrong):")
        if d is not None:
            emit_segments([d], i + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "verify", "diff"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--chunk")
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--name")
    a = ap.parse_args()

    if a.mode == "dump":
        if not a.path:
            ap.error("dump needs a file path")
        return dump(a.path)

    if not a.chunk:
        ap.error("--chunk <cron_read_chunk.json> is required for verify/diff")
    rows = compare(a.repo, a.chunk, a.name)
    if not rows:
        print("no matching prompts found in the chunk")
        return 1

    if a.mode == "verify":
        drift = 0
        for r in rows:
            if r["match"]:
                print(f"  MATCH {r['name']}  {r['repo_bytes']}B  sha={r['repo_sha']}")
            else:
                drift += 1
                print(f"  DRIFT {r['name']}  repo={r['repo_bytes']}B sha={r['repo_sha']}  "
                      f"deployed={r['dep_bytes']}B sha={r['dep_sha']}")
        print(f"\nprompt drift: {drift} of {len(rows)} deployed prompts differ from the repo")
        return 1 if drift else 0

    bad = [r for r in rows if not r["match"]]
    if not bad:
        print("no drift: every deployed prompt matches its repo file")
        return 0
    for r in bad:
        r["_chunk"] = a.chunk
        print_diff(r)
    print(f"\n{len(bad)} of {len(rows)} deployed prompts differ from the repo")
    return 1


if __name__ == "__main__":
    sys.exit(main())

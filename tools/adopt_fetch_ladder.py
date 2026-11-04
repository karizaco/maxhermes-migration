#!/usr/bin/env python3
"""
adopt_fetch_ladder.py - rewrite every dead `[ -s file ] || curl` fetch into the
ONE canonical ladder: fetch to a temp file, validate the BODY, then move it into place.

WHY
---
The fleet-wide fetch idiom was:

    for U in "$B/file.md" "https://cdn.jsdelivr.net/.../file.md"; do
      [ -s /workspace/file.md ] || curl -sL -o /workspace/file.md "$U"
    done

`[ -s file ] ||` is satisfied by the FIRST successful download, so **the second URL was dead
code** - the loop looked like it had a fallback and did not. Measured 2026-11-04: after a push,
`raw.githubusercontent.com` served a STALE blob for >17 minutes while jsDelivr was fresh, and
the GitHub **contents API** (not CDN-cached) was fresh immediately. A routine firing in that
window silently executed a stale procedure - reproduced by running the prompt's own fetch loop.

The canonical ladder (already deployed in cron #17, and the model every other block follows):

  1. the **contents API first** - it is the only source that is not CDN-cached;
  2. fetch to `"$D.tmp"`, never straight onto the target;
  3. reject on the **BODY** (`"message"` = a GitHub error JSON), not on the byte count - a 403
     body is non-empty JSON;
  4. `mv` into place and break, so the next URL is only tried when this one really failed;
  5. **say so loudly** when the file is still missing.

`mv` is safe here because the temp file lives in the same directory as the target. (`mv` across
`/tmp` -> `/workspace` fails with EXDEV - the workspace is a NAS mount.)

MATCHING
--------
Any `for U in ... done` loop whose body guards on `[ -s <file> ] || curl` is dead, whatever
shape it has (absolute first URL, `$B/...` first URL, one URL or three). The tool finds the
loop, reads the file name out of the guard, and rebuilds it. Every helper it touches lives in
`cloud-prompts/_shared/`.

BLAST RADIUS
------------
This script edits two different kinds of file, with very different consequences:

* **shared files** (`_shared/*.md`, `skills/*/SKILL.md`) are downloaded by the routines at RUN
  TIME, so a fix lands on the next fire of every routine that uses them - **no prompt redeploy,
  no byte-drift risk**;
* **prompt files** (`cron-prompts/*.md`) ARE the deployed prompt. Editing one without
  redeploying it makes cron #91's drift guard report PROMPT-DRIFT every single day, and
  redeploying means a `cron_update` paste.

So this script only touches prompt files that are **listed in `--targets`**, and the default
target list is the two routines that have NO other fetch path (`#26b` and `#90`, which do not
download `PROMPT-BLOCKS.md`). Every other routine gets the fresh helper from the shared block
first, so its own now-harmless copy of the old idiom is never reached.

**A fleet-wide rollout must deploy every prompt it touches in the same session.** Use
`--targets all` for that, then deploy with `tools/deploy_prompts.py` and verify by SHA-256.

DETERMINISM
-----------
Idempotent and byte-stable: the rewrite is a literal replacement of a fixed pattern, so running
it twice produces the same bytes, and a file that already carries the canonical ladder is left
untouched. Run `--check` to see what it WOULD change without changing anything.

USAGE
    python3 tools/adopt_fetch_ladder.py --check          # report only (default targets)
    python3 tools/adopt_fetch_ladder.py --apply          # rewrite the default targets
    python3 tools/adopt_fetch_ladder.py --check --targets all
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "cloud-prompts", "_shared")
PROMPTS = os.path.join(ROOT, "cloud-prompts", "cron-prompts")
SKILLS = os.path.join(ROOT, "cloud-prompts", "skills")

OWNER = "karizaco/maxhermes-migration"

# The routines that do NOT download _shared/PROMPT-BLOCKS.md, so their own fetch is the only
# path to the helper. Everyone else gets it from the shared block first.
PROMPT_TARGETS_DEFAULT = [
    "26b-agentic-pre-market-brief-refresh-0920.md",
    "90-delivery-auditor.md",
]

# Files that are documents (no shebang to check) rather than scripts.
DOCS = {"PROMPT-BLOCKS.md"}

FALLBACKS = {
    "push_artifact.sh": "the DELIVERY step cannot push its artifact",
    "PROMPT-BLOCKS.md": "write a stub artifact with `_source=prompt_blocks_fetch_failed`",
    "probe_mcp.py": "record `probe_unavailable` in `## Source health` - it is NOT a finding",
    "mcp_bridge.py": "fall back to web_search, then the curl ladder",
    "rvol_fetch.py": "fall back to the caller's own denominator source",
}

# A dead guard: `[ -s <target> ] || curl`. The target is either a path or a shell variable
# holding one.
DEAD_GUARD = re.compile(r'(?P<i>[ ]*)\[ -s (?P<t>[^\]\n]+)\] \|\| curl[^\n]*')

# `$BR` / `$RF` are the variable names the shared blocks use for the bridge and the
# rvol helper. Everything else is addressed by its path.
VAR_MAP = {"\"$BR\"": "mcp_bridge.py", "\"$RF\"": "rvol_fetch.py"}

# Only helpers that live in cloud-prompts/_shared/ are rewritten. Anything else is reported
# and left alone - a rewrite we cannot map to a repo path would be a guess.
KNOWN = {
    "push_artifact.sh", "verify_delivery.sh", "skip_marker.sh", "window_check.sh",
    "probe_mcp.py", "mcp_bridge.py", "rvol_fetch.py", "barchart_fetch.py",
    "preopen_feed.py", "PROMPT-BLOCKS.md", "RUNTIME-CONTRACT.md", "preopen-capture.md",
    "nyse-holidays.txt",
}


def canonical(fname, indent):
    """The canonical ladder for `cloud-prompts/_shared/<fname>`, indented like the original."""
    script = fname not in DOCS
    check = (" \\\n     && head -1 \"$D.tmp\" 2>/dev/null | grep -q '^#!'") if script else ""
    body = (
        f"D=/workspace/{fname}\n"
        "for U in \\\n"
        f'  "https://api.github.com/repos/{OWNER}/contents/cloud-prompts/_shared/{fname}?ref=main" \\\n'
        f'  "https://raw.githubusercontent.com/{OWNER}/main/cloud-prompts/_shared/{fname}" \\\n'
        f'  "https://cdn.jsdelivr.net/gh/{OWNER}@main/cloud-prompts/_shared/{fname}" ; do\n'
        '  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \\\n'
        '    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null\n'
        f'  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q \'"message"\'{check}; then\n'
        '    mv -f "$D.tmp" "$D"; break\n'
        "  fi\n"
        '  rm -f "$D.tmp"\n'
        "done\n"
        f'[ -s "$D" ] || echo "{fname} fetch FAILED - '
        f'{FALLBACKS.get(fname, "continue without it")}"'
    )
    if indent:
        body = "\n".join((indent + ln) if ln.strip() else ln for ln in body.split("\n"))
    return body


def fname_from_guard(target):
    """The helper file name out of a guard like `/workspace/x.sh` or `"$BR"`."""
    m = re.search(r"/workspace/([\w.-]+)", target)
    if m:
        return m.group(1)
    return VAR_MAP.get(target.strip())


def rewrite_file(path, rel_name):
    """Return (new_text, [notes]) for one file."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")
    notes = []
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = DEAD_GUARD.match(line)
        if not m or "| curl" not in line:
            out.append(line)
            i += 1
            continue

        fname = fname_from_guard(m.group("t"))
        if not fname or fname not in KNOWN:
            out.append(line)
            i += 1
            continue

        # Is this guard the body of a `for U in ... done` loop? The header is at most a
        # handful of lines above (the URL lines sit between). Walk back, but STOP at a
        # blank line or at a `done` - that means we left the block, and the guard is
        # standalone.
        start = None
        for s in range(i - 1, max(-1, i - 11), -1):
            if not lines[s].strip() or lines[s].strip() == "done":
                break
            if "for U in" in lines[s]:
                start = s
                break

        end = None
        if start is not None:
            for e in range(i + 1, min(len(lines), i + 21)):
                if lines[e].strip() == "done":
                    end = e
                    break

        if start is not None and start < i:
            # the old header + URL lines go with it
            out_back = out
            del out_back[len(out_back) - (i - start):]
            # and the orphan `VAR=/workspace/...` line that introduced it
            if out_back and re.match(r'[ ]*[A-Z]+=/workspace/[\w.-]+$', out_back[-1]):
                out_back.pop()
        indent = re.match(r"[ ]*", lines[start if start is not None else i]).group(0)
        notes.append(f"{rel_name}: {fname} ladder")
        out.append(canonical(fname, indent))

        # the whole loop goes: header .. guard .. done
        if end is not None:
            i = end + 1
            # drop the old loud-failure line that followed the old loop, if any
            if i < len(lines) and re.match(r'[ ]*\[ -s "?\$?[A-Za-z_]+"? \] \|\| echo', lines[i]):
                i += 1
        else:
            i += 1

    return "\n".join(out), notes


def targets(mode):
    """(path, rel_name) pairs for everything this run should consider."""
    items = []
    for name in ("PROMPT-BLOCKS.md", "preopen-capture.md"):
        items.append((os.path.join(SHARED, name), f"_shared/{name}"))
    items.append((os.path.join(SKILLS, "us-stocks-in-play", "SKILL.md"),
                  "skills/us-stocks-in-play/SKILL.md"))

    if mode == "all":
        for p in sorted(glob.glob(os.path.join(PROMPTS, "*.md"))):
            base = os.path.basename(p)
            if base in ("README.md", "ROSTER.md"):
                continue
            items.append((p, f"cron-prompts/{base}"))
    else:
        for base in PROMPT_TARGETS_DEFAULT:
            items.append((os.path.join(PROMPTS, base), f"cron-prompts/{base}"))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("--targets", default="default", choices=["default", "all"],
                    help="default = the routines with no other fetch path; "
                         "all = every prompt (MUST be deployed in the same session)")
    args = ap.parse_args()

    changed = 0
    for path, rel in targets(args.targets):
        if not os.path.exists(path):
            print(f"!! missing {rel}")
            continue
        original = open(path, encoding="utf-8").read()
        new, notes = rewrite_file(path, rel)
        if new == original:
            continue
        changed += 1
        for n in notes:
            print(f"  {n}")
        if args.apply:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
        else:
            print(f"  (dry run) would rewrite {rel}")

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"\n{verb} {changed} file(s) [{args.targets}]")
    if not args.apply and changed:
        print("re-run with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())

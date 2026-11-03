#!/usr/bin/env python3
"""
Align the repo's prompt files to the DEPLOYED copies, byte for byte.

WHY
---
Hand-pasting a 7-13 KB prompt into `cron_update` drifts: observed 3-byte
prose differences on every paste (a `view=runs` -> `view:runs` swap and one
line-wrap move), and one paste that was byte-exact-in-length but wrong in
content. The drift is always cosmetic PROSE, never executable code, but cron
#91's drift guard compares SHA-256 over the raw bytes, so any difference is
reported as drift.

The fix is to take the DEPLOYED bytes as the source of truth and align the repo
to them. That is the cheap side: re-pasting 10 KB to chase 3 cosmetic bytes
risks more drift than it removes.

SAFETY
------
Refuses to align unless the diff is confined to whitespace and to the known
prose tokens. If the diff contains anything else, the file is left alone and
reported for manual review.

USAGE
  python3 tools/align_repo_to_platform.py --chunk <path-to-chunk.txt>
"""
import argparse, json, os, re, sys, hashlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = os.path.join(REPO, "cloud-prompts", "cron-prompts")

# Tokens that are known to drift in prose only. Anything else is a real change.
SAFE_TOKENS = [
    "view=runs", "view:runs",
    "`push_artifact.sh` calls\n`verify_delivery.sh` and only reports",
    "`push_artifact.sh` calls `verify_delivery.sh`\nand only reports",
]


def extract(chunk_path):
    txt = open(chunk_path, encoding="utf-8", errors="replace").read()
    out = {}
    for m in re.finditer(r'"cron_name":\s*"([^"]+\.md)"', txt):
        name = m.group(1)
        if name in out:
            continue
        seg = txt[m.start():m.start() + 60000]
        p = seg.find('"prompt": ')
        if p < 0:
            continue
        q = p + len('"prompt": ')
        if seg[q] != '"':
            continue
        j = q + 1
        buf = []
        esc = False
        while True:
            ch = seg[j]
            if esc:
                buf.append(ch)
                esc = False
            elif ch == '\\':
                buf.append(ch)
                esc = True
            elif ch == '"':
                break
            else:
                buf.append(ch)
            j += 1
        try:
            out[name] = json.loads('"' + ''.join(buf) + '"')
        except Exception:
            continue
    return out


def is_cosmetic(repo_text, dep_text):
    """True when the two differ only in whitespace and the known prose tokens."""
    a = repo_text
    b = dep_text
    for t in SAFE_TOKENS:
        a = a.replace(t, "")
        b = b.replace(t, "")
    # collapse whitespace entirely; anything left differs materially
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    deployed = extract(a.chunk)
    if not deployed:
        print("no prompts extracted from the chunk", file=sys.stderr)
        sys.exit(2)

    changed = same = skipped = 0
    for name, dep in sorted(deployed.items()):
        path = os.path.join(PROMPTS, name)
        if not os.path.exists(path):
            print(f"  SKIP  {name}: no repo file")
            skipped += 1
            continue
        repo = open(path, encoding="utf-8").read()
        if repo == dep:
            same += 1
            continue
        if not is_cosmetic(repo, dep):
            print(f"  SKIP  {name}: NON-COSMETIC diff - needs manual review")
            skipped += 1
            continue
        print(f"  ALIGN {name}: {len(repo.encode())}B -> {len(dep.encode())}B "
              f"(cosmetic only)")
        if a.apply:
            open(path, "w", encoding="utf-8").write(dep)
        changed += 1
    print(f"\naligned={changed} already-identical={same} skipped={skipped}")
    if changed and not a.apply:
        print("re-run with --apply to write the changes")


if __name__ == "__main__":
    main()

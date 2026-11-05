#!/usr/bin/env python3
"""
check_cross_asset_artifact.py — assert the cron #12 artifact contract. Do not eyeball it.

WHY THIS EXISTS
---------------
Cron #12 (cross-asset-correlation-snapshot) has already published two classes of
defect that a reader could not see:

1. **A stale window.** On 2026-11-03 a hand-picked `--window-end` published the
   PREVIOUS day's window, so the artifact was a duplicate of the 2026-11-02 one while
   looking entirely plausible. The fix was `--window-end auto` (the window end is
   DERIVED from the fetched series) plus the front-matter flag
   `window_end_derived_from_data: true`. That flag was the only tell — so it is now a
   permanent assertion here rather than a one-off manual check.

2. **A duplicate window.** The derivation closed the stale-window class, but the
   DUPLICATE PUSH did not: publishing a second artifact for a window that is already
   in `cross-asset/` is indistinguishable from a regression at read time, and the
   recovery was a corrective second commit — meaning the wrong artifact was briefly
   the published one. This check refuses that push.

This script turns both into machine assertions, so a run that breaks the contract
FAILS instead of shipping.

IT ALSO KEEPS THE 2026-11-05 ONE-OFF VERIFICATION TASK PERMANENT
-----------------------------------------------------------------
The routine's one-off task `verify-cron12-window-roll-2026-11-05` checked
`window_end_derived_from_data`, the `n_sessions` value and the colour bands. Those
checks live here now, in the routine's own pre-push path, instead of in a task that
runs once and is then forgotten.

USAGE
    python3 check_cross_asset_artifact.py --md /workspace/cross-asset/<date>.md \
                                         [--mats /workspace/data_cross/mats.json] \
                                         [--reply /workspace/reply.txt] \
                                         [--outputs-repo karizaco/minimax-cloud-outputs] \
                                         [--ref main] [--outputs-dir <local dir>]

EXIT CODES
    0 = contract satisfied
    1 = at least one FAIL (each is printed)
    2 = bad arguments
    4 = the DUPLICATE-WINDOW check could not run (the listing could not be fetched) —
       this is NOT a pass. The caller must say so; it must not report a clean run.
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.request

CONTRACT_VERSION = "cross-asset-v4"
SHIFT_THRESHOLD = 0.20

REQUIRED_SECTIONS = [
    ("📊 Matrix", "the server-side returns matrix"),
    ("🔎 Flat heatmap", "the flat ranked heatmap"),
    ("🏆 Highlights", "the strongest and weakest pairs"),
    ("🔁 Week-over-week delta", "the week-over-week comparison"),
    ("📈 Performance", "the window's returns — the only place they appear"),
    ("🧪 Effect of the excluded partial session",
     "the proof that excluding the in-progress bar changed no conclusion"),
    ("🩺 Source health", "the source-health table"),
    ("📎 Appendix — price-level correlations", "the price-level appendix"),
]

COLOUR_BANDS = ["🟥", "🟧", "🟨", "🟩", "🟦"]

FAILURES = []
CHECKS = 0


def ok(msg):
    global CHECKS
    CHECKS += 1
    print(f"  ok   {msg}")


def bad(msg):
    global CHECKS
    CHECKS += 1
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


# ---------------------------------------------------------------- front matter
def parse_front_matter(text):
    """Return (dict, body). The artifact's front matter is `key: value` lines."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    head = text[3:end]
    body = text[end + 4:]
    fm = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, body


def window_end_of(text):
    """The window end an artifact carries — front matter first, legacy heading second.

    The 2026-10-25..2026-10-28 artifacts predate the front matter and carry it in the
    H1 ("window ending 2026-10-23"), so both shapes are read.
    """
    fm, _ = parse_front_matter(text)
    w = fm.get("window_end")
    if w and re.match(r"^\d{4}-\d{2}-\d{2}$", w):
        return w
    m = re.search(r"window ending (\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------- tables
def split_row(line):
    """Split a markdown table row on UNESCAPED pipes (the legend uses \\|corr\\|)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == "\\":
            cur += ch
            esc = True
            continue
        if ch == "|":
            cells.append(cur.strip())
            cur = ""
            continue
        cur += ch
    cells.append(cur.strip())
    return cells


def ragged_tables(body):
    """Return a list of (first_line_no, widths) for every table whose rows disagree."""
    problems = []
    block, start = [], 0
    lines = body.splitlines()
    for i, ln in enumerate(lines, 1):
        if ln.strip().startswith("|"):
            if not block:
                start = i
            block.append(ln)
            continue
        if block:
            widths = {len(split_row(r)) for r in block}
            if len(widths) > 1:
                problems.append((start, sorted(widths)))
            block = []
    if block:
        widths = {len(split_row(r)) for r in block}
        if len(widths) > 1:
            problems.append((start, sorted(widths)))
    return problems


# ---------------------------------------------------------------- outputs repo
def fetch(url, token=None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.raw")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")


def list_outputs(outputs_dir=None, outputs_repo=None, ref="main"):
    """Return {filename: window_end} for every published artifact, or raise."""
    if outputs_dir:
        out = {}
        for path in sorted(glob.glob(os.path.join(outputs_dir, "*.md"))):
            try:
                txt = open(path, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            out[os.path.basename(path)] = window_end_of(txt)
        return out
    if not outputs_repo:
        raise ValueError("no outputs dir and no outputs repo")
    token = os.environ.get("GITHUB_TOKEN", "")
    api = f"https://api.github.com/repos/{outputs_repo}/contents/cross-asset?ref={ref}"
    listing = json.loads(fetch(api, token))
    if isinstance(listing, dict):
        raise ValueError(f"the listing endpoint returned an object, not a listing: "
                         f"{str(listing)[:200]}")
    out = {}
    for item in listing:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if not name.endswith(".md"):
            continue
        url = item.get("url")
        if not url:
            continue
        try:
            raw = fetch(f"{url}?ref={ref}" if "?" not in url else f"{url}&ref={ref}", token)
        except Exception:
            continue
        out[name] = window_end_of(raw)
    return out


# ---------------------------------------------------------------- reply
def first_signal_line(reply_text):
    """The first non-empty line under the reply's `### Signal` heading."""
    lines = reply_text.splitlines()
    in_signal = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("### "):
            in_signal = s.lower().startswith("### signal")
            continue
        if in_signal and s:
            return s
    return None


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="the artifact markdown")
    ap.add_argument("--mats", help="mats.json — cross-checks the artifact's front matter")
    ap.add_argument("--reply", help="the final chat reply — asserted to lead with the signal")
    ap.add_argument("--outputs-dir", help="a local directory of published cross-asset artifacts")
    ap.add_argument("--outputs-repo", help="owner/name of the outputs repo")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--skip-duplicate-check", action="store_true",
                    help="skip the duplicate-window assertion (the caller must then say so)")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        print(f"  FAIL artifact not found: {args.md}")
        return 1
    text = open(args.md, encoding="utf-8", errors="replace").read()
    fm, body = parse_front_matter(text)
    art_name = os.path.basename(args.md)

    print(f"cross-asset artifact contract: {art_name}")

    # ---- front matter basics
    if not fm:
        bad("no front matter — the artifact must carry the `window_end` / "
            "`window_end_derived_from_data` front matter")
    else:
        ok("front matter present")

    if fm.get("contract") == CONTRACT_VERSION:
        ok(f"contract marker {CONTRACT_VERSION}")
    else:
        bad(f"contract marker is {fm.get('contract')!r}, expected {CONTRACT_VERSION!r} "
            f"— a stale renderer produced this artifact; re-fetch and re-run")

    derived = (fm.get("window_end_derived_from_data") or "").lower()
    if derived == "true":
        ok("window_end_derived_from_data: true")
    else:
        bad(f"window_end_derived_from_data is {derived!r}, expected 'true' — a hand-picked "
            f"--window-end was used and the 2026-11-03 stale-window bug is back")

    wend = fm.get("window_end")
    if wend and re.match(r"^\d{4}-\d{2}-\d{2}$", wend):
        ok(f"window_end {wend}")
    else:
        bad(f"window_end is {wend!r} — expected YYYY-MM-DD")
        wend = None

    wstart = fm.get("window_start")
    if wstart and re.match(r"^\d{4}-\d{2}-\d{2}$", wstart):
        ok(f"window_start {wstart}")
    else:
        bad(f"window_start is {wstart!r} — expected YYYY-MM-DD")

    try:
        nsess = int(fm.get("n_sessions", ""))
        if nsess > 0:
            ok(f"n_sessions {nsess}")
        else:
            bad(f"n_sessions is {nsess} — expected a positive session count")
    except Exception:
        bad(f"n_sessions is {fm.get('n_sessions')!r} — expected an integer")
        nsess = None

    # the artifact's own date must match its filename
    fdate = fm.get("date")
    m = re.search(r"(\d{4}-\d{2}-\d{2})", art_name)
    if fdate and m and fdate != m.group(1):
        bad(f"front-matter date {fdate} does not match the filename date {m.group(1)}")
    elif fdate:
        ok(f"artifact date {fdate} matches the filename")

    # ---- cross-check against mats.json (the file the renderer actually read)
    if args.mats:
        if not os.path.exists(args.mats):
            bad(f"--mats not found: {args.mats}")
        else:
            md_doc = json.load(open(args.mats))
            mwin = md_doc.get("window", {})
            for key, field in (("start", "window_start"), ("end", "window_end")):
                if mwin.get(key) and fm.get(field) and mwin[key] != fm[field]:
                    bad(f"{field} {fm[field]} does not match mats.json window.{key} "
                        f"{mwin[key]} — the artifact was hand-edited or built from another run")
            if mwin.get("n_sessions") and nsess and int(mwin["n_sessions"]) != nsess:
                bad(f"n_sessions {nsess} does not match mats.json "
                    f"window.n_sessions {mwin['n_sessions']}")
            if mwin.get("n_sessions") and nsess and int(mwin["n_sessions"]) == nsess:
                ok(f"front matter agrees with mats.json (window {mwin.get('start')} → "
                   f"{mwin.get('end')}, {nsess} sessions)")
            if md_doc.get("matrix_returns") and md_doc["matrix_returns"]:
                ok("mats.json carries a server-side matrix")

    # ---- required sections
    missing = [name for name, _ in REQUIRED_SECTIONS if name not in body]
    if missing:
        for name, why in REQUIRED_SECTIONS:
            if name in missing:
                bad(f"section missing: {name} — {why}")
    else:
        ok(f"all {len(REQUIRED_SECTIONS)} required sections present")

    # ---- colour bands
    absent = [b for b in COLOUR_BANDS if b not in body]
    if absent:
        bad(f"colour band(s) missing from the artifact: {' '.join(absent)} — all five "
            f"(🟥🟧🟨🟩🟦) must appear")
    else:
        ok("all five colour bands present")

    # ---- table shape
    probs = ragged_tables(body)
    if probs:
        for line_no, widths in probs:
            bad(f"ragged markdown table starting at line {line_no}: cell counts {widths}")
    else:
        ok("every markdown table has a consistent cell count")

    # ---- the signal line
    sig = fm.get("signal_line")
    if not sig:
        bad("front matter has no `signal_line` — the chat reply cannot be checked "
            "against it")
    else:
        ok("front matter carries a signal_line")
        try:
            mpm = float(fm.get("max_pair_move", "nan"))
        except Exception:
            mpm = None
        if mpm is not None and f"{mpm:.4f}" in sig:
            ok("signal_line carries the max_pair_move")
        elif mpm is not None:
            bad(f"signal_line does not carry max_pair_move {mpm:.4f} — the reply must "
                f"state the distance to the shift threshold")
        if f"{SHIFT_THRESHOLD:.2f}" in sig:
            ok(f"signal_line carries the {SHIFT_THRESHOLD:.2f} regime-shift threshold")
        else:
            bad(f"signal_line does not carry the {SHIFT_THRESHOLD:.2f} regime-shift "
                f"threshold")
        if re.search(r"[A-Z\^]{1,6}[–—-][A-Z\^]{1,6}", sig):
            ok("signal_line names a pair")
        else:
            bad("signal_line names no pair")
        if "hedge" in sig.lower():
            ok("signal_line carries the hedge implication")
        else:
            bad("signal_line carries no hedge implication")

    # ---- the excluded-partial-session proof must not overstate itself
    inc = (fm.get("partial_includes_in_progress") or "").lower()
    if inc == "yes":
        if "no conclusion in this report changes" in body:
            ok("partial-session section states the proof it actually has")
        else:
            bad("partial_includes_in_progress: yes but the section does not state the "
                "proof (expected 'no conclusion in this report changes')")
    elif inc == "no":
        if "NOT available for every proxy" in body:
            ok("partial-session section discloses that the bar was not included")
        else:
            bad("partial_includes_in_progress: no but the section does not disclose it — "
                "a zero-delta table must not be presented as a proof")
    else:
        bad(f"front matter has no `partial_includes_in_progress` flag (got {inc!r})")

    # ---- the reply
    if args.reply:
        if not os.path.exists(args.reply):
            bad(f"--reply not found: {args.reply}")
        else:
            rtxt = open(args.reply, encoding="utf-8", errors="replace").read()
            line = first_signal_line(rtxt)
            if not line:
                bad("the reply has no `### Signal` section, or it is empty")
            else:
                ok("the reply has a `### Signal` section")
                if sig:
                    pairs = re.findall(r"[A-Z\^]{1,6}[–—-][A-Z\^]{1,6}", sig)
                    if pairs and pairs[0] not in line:
                        bad(f"the reply's first Signal line does not name the hedge pair "
                            f"{pairs[0]} — the implication must lead")
                    elif pairs:
                        ok(f"the reply's first Signal line names {pairs[0]}")
                    try:
                        mpm = float(fm.get("max_pair_move", "nan"))
                    except Exception:
                        mpm = None
                    if mpm is not None and f"{mpm:.4f}" not in line:
                        bad(f"the reply's first Signal line does not carry the max pair "
                            f"move {mpm:.4f} — the distance to the threshold is missing")
                    elif mpm is not None:
                        ok("the reply's first Signal line carries the max pair move")
                    if f"{SHIFT_THRESHOLD:.2f}" not in line:
                        bad(f"the reply's first Signal line does not carry the "
                            f"{SHIFT_THRESHOLD:.2f} regime-shift threshold")
                    else:
                        ok("the reply's first Signal line carries the shift threshold")
                    if "hedge" not in line.lower():
                        bad("the reply's first Signal line carries no hedge implication")
                    else:
                        ok("the reply's first Signal line carries the hedge implication")

    # ---- THE DUPLICATE-WINDOW ASSERTION
    if args.skip_duplicate_check:
        print("  --   duplicate-window check SKIPPED (the caller must say so)")
    else:
        try:
            published = list_outputs(args.outputs_dir, args.outputs_repo, args.ref)
        except Exception as exc:
            print(f"  FAIL duplicate-window check could not run: {exc}")
            print(f"  FAIL this is NOT a pass — the caller must report it, not call the "
                  f"run clean")
            return 4
        if not published:
            ok("no artifact has been published yet — a duplicate window is not possible")
        else:
            clashes = [(name, w) for name, w in published.items()
                       if name != art_name and w and wend and w == wend]
            if clashes:
                for name, w in clashes:
                    bad(f"DUPLICATE WINDOW: {name} already publishes window_end {w} — "
                        f"refusing to publish a second artifact for the same window")
            else:
                ok(f"no duplicate window (checked {len(published)} published artifact(s); "
                   f"window {wend} is new)")

    print(f"cross-asset contract: {CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print(f"cross-asset contract: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("cross-asset contract: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # a checker that crashes must not look like a pass
        print(f"check_cross_asset_artifact: CRASHED: {exc}")
        sys.exit(1)

#!/usr/bin/env python3
"""
adopt_window_check.py - rewrite every prompt's inlined WINDOW CHECK block to call the
ONE shared `_shared/window_check.sh` instead.

WHY
---
20 prompts each carried their own ~2.9 KB copy of the window-check block: a holiday
`case` statement with the same ten dates re-typed by hand, plus a copy-pasted
skip_marker.sh fetch. The copies had already drifted (quoting, `case` vs `case "..."`,
one extra holiday date, one extra off-clock assertion), and the fleet's own audit
(docs/remediation/CRON-PROMPT-AUDIT.md, item D3) flagged the duplication.

This rewrites each prompt to the SAME block, parameterised only by that routine's
identity (--out / --name / --label / --nn) and its optional market-hours window.
Every prompt then fetches the shared script at RUN TIME, so a fix to the gate lands
on the next fire of every routine with no prompt redeploy.

THE REPLAY FIX
--------------
The old blocks tested the WALL CLOCK. The platform resumes a crashed cron
conversation IN PLACE, hours or days later, so on a replay the wall clock names the
wrong day: a Friday fire replayed on a Saturday was skipped (losing a real brief),
and a holiday fire replayed on a trading day published a brief for a closed market.

The shared script takes `--scheduled-at-ms` - the fire's OWN scheduled instant - and
judges every gate against that. The agent resolves it once, from the session's
`created_at` (which the platform sets when the fire is dispatched and does NOT
change on a resume), and passes it in.

DETERMINISM
-----------
This script is idempotent and byte-stable: it produces the same output for the same
input, and it refuses to touch a prompt whose facts it cannot extract. Run
`--check` to see what it WOULD change without changing anything.

USAGE
    python3 tools/adopt_window_check.py --check     # report only
    python3 tools/adopt_window_check.py --apply     # rewrite the prompt files
"""
import argparse, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(HERE, "..", "cloud-prompts", "cron-prompts")

# The block every prompt gets. {OUT} {NAME} {LABEL} {NN} {MARKET_HOURS} are substituted.
BLOCK = """## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

The gate below is the ONE shared implementation for the whole fleet - fetch it and run it.
Do not inline a holiday list here: a hand-typed copy is how 21 prompts drifted into
21 different versions of the same check.

**Resolve the fire's scheduled instant FIRST, then judge the gate against it - never against
the wall clock.** The platform resumes a crashed cron conversation IN PLACE, hours or days
later, so on a replay "now" names the resume day, not the fire day. Judging by the wall clock
both skips real briefs (a Friday fire replayed on a Saturday) and publishes briefs for a
closed market (a holiday fire replayed on a trading day).

Resolve it with ONE call, no cron_read needed:

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds). That is the instant the platform dispatched
THIS fire, and a later resume does not change it - so it identifies the original fire even
when the work happens hours later. Pass it as `--scheduled-at-ms`. The script prints
`fire-date:` - use THAT for the artifact path in `## OUTPUT`, so the gate and the artifact
can never disagree about which day they belong to.

```bash
# --- fetch the ONE shared window check (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY check below is mandatory, not decoration. An OLDER copy of this script is
# still published, and it silently IGNORES unknown flags - so without the check you would
# run a gate that never fires, and a holiday fire would publish a brief for a closed
# market. The CDNs also cache independently, so one of them can serve stale bytes for
# hours. The contents API is authoritative and is not CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \\
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \\
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \\
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script, and an older script silently
  # ignores the flags below. Require BOTH: a real script AND the capability marker.
  if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'WINDOW_CHECK_V2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'WINDOW_CHECK_V2' "$S" 2>/dev/null; then
  echo "window-check: UNAVAILABLE (no version of the shared script with the replay-aware gate)"
  echo "no artifact; no push"
  exit 1
fi

# SCHEDULED_AT_MS = session.created_at from the session_get call above (epoch ms).
sh "$S" --scheduled-at-ms "$SCHEDULED_AT_MS" \\
   --out {OUT} --name {NAME} \\
   --label "{LABEL}" \\
   --nn {NN}{MARKET_HOURS}
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - {ARTIFACT} is intentionally absent)
push: marker pushed (refs/skipped-markers/{DATE}_SKIPPED_{NAME}.md) | marker push FAILED | marker push skipped (skip_marker.sh unavailable)
errors: 0
```
"""

MARKET_HOURS = {
    # Only #07 gates on a clock window: its old block had a CLOCK ASSERTION that the
    # routine is worthless off-clock. It is evaluated against the FIRE's clock, so a
    # replay outside the window still publishes.
    "07-stock-screener-focus-rvol-09:45.md": " \\\n   --market-hours 0930-1100",
}


def extract_facts(text):
    """Pull this routine's identity out of its current inlined block."""
    m = re.search(r"## WINDOW CHECK.*?(?=\n## )", text, re.S)
    if not m:
        return None
    sec = m.group(0)
    out = re.search(r"--out\s+(\S+)", sec)
    name = re.search(r"--name\s+(\S+)", sec)
    label = re.search(r'--label\s+["\']([^"\']+)["\']', sec)
    nn = re.search(r"--nn\s+(\d+)", sec)
    # Match either the old reply line or the new one, so an already-canonical
    # prompt is recognised as such instead of being mislabelled as absent.
    # The reply line names the artifact path just before "is intentionally absent".
    # Tolerate either the old wording ("holiday skip - X.md is intentionally absent")
    # or the new one, and any dash style, so an already-canonical prompt is
    # recognised as such rather than mislabelled as absent.
    art = re.search(r"([\w./{}$-]+?\.md) is intentionally absent", sec)
    if not (out and name and label and nn and art):
        return None
    return {
        "out": out.group(1),
        "name": name.group(1),
        "label": label.group(1),
        "nn": nn.group(1),
        "artifact": art.group(1),
        "has_clock": "CLOCK ASSERTION" in sec,
    }


def render(facts, fname):
    mh = MARKET_HOURS.get(fname, "")
    if facts["has_clock"] and not mh:
        # A clock assertion we did not model - refuse rather than silently drop it.
        raise SystemExit(f"adopt_window_check.py: {fname} has a clock assertion with no "
                         f"--market-hours entry in MARKET_HOURS; add one and re-run.")
    return (BLOCK
            .replace("{OUT}", facts["out"])
            .replace("{NAME}", facts["name"])
            .replace("{LABEL}", facts["label"])
            .replace("{NN}", facts["nn"])
            .replace("{MARKET_HOURS}", mh)
            .replace("{ARTIFACT}", facts["artifact"])
            .replace("{DATE}", "$FIRE_DATE"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report what would change")
    ap.add_argument("--apply", action="store_true", help="rewrite the prompt files")
    a = ap.parse_args()
    if not (a.check or a.apply):
        ap.error("pass --check or --apply")

    changed = skipped = 0
    for path in sorted(glob.glob(os.path.join(PROMPTS, "*.md"))):
        fname = os.path.basename(path)
        text = open(path, encoding="utf-8").read()
        facts = extract_facts(text)
        if not facts:
            skipped += 1
            print(f"  skip   {fname} (no inlined window check)")
            continue
        new_sec = render(facts, fname)
        new_text, n = re.subn(r"## WINDOW CHECK.*?(?=\n## )", lambda _m: new_sec + "\n\n",
                              text, count=1, flags=re.S)
        if n != 1:
            skipped += 1
            print(f"  skip   {fname} (window check section not matched)")
            continue
        if new_text == text:
            print(f"  ok     {fname} (already canonical)")
            continue
        changed += 1
        old_len = len(text)
        print(f"  change {fname}  {old_len} -> {len(new_text)} bytes "
              f"({len(new_text)-old_len:+d})")
        if a.apply:
            open(path, "w", encoding="utf-8").write(new_text)

    print(f"\n{changed} prompt(s) {'would change' if a.check else 'changed'}, "
          f"{skipped} skipped")
    if a.apply and changed:
        print("Now verify: python3 tools/verify_prompts.py  (or the SHA-256 loop in the "
              "skill) BEFORE deploying, then deploy with tools/deploy_prompts.py.")


if __name__ == "__main__":
    main()

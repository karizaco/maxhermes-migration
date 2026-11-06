#!/usr/bin/env python3
"""
check_auditor_contract.py - the GATE on cron #90's output.

WHY A GATE
----------
Cron #90 (delivery-auditor) is the fleet's external observer: it decides which
routines delivered, which are missing, and WHY. It is also a REASONING routine,
so it can - and did - get the classification wrong in ways that look fine:

  * a routine that ran and correctly wrote nothing was reported MISSING,
    because the auditor had only three states and no way to say "ran, and
    correctly produced no artifact";
  * a gap line was published with an EMPTY reason, so the operator had to go
    and find the cause themselves;
  * a live routine that was absent from the ground truth was never checked at
    all, and the audit reported `roster_desync: 0` while it was unmonitored.

A prose rule does not prevent any of that. This checker does. It reads what
the audit actually produced - the status file AND the digest that is published
to the operator - and fails when the output breaks the contract in
`tools/auditor-contract.json`.

USAGE
-----
  python3 tools/check_auditor_contract.py --status _audit/status.json
  python3 tools/check_auditor_contract.py --status _audit/status.json \
      --reply digest.txt --tasks tasks.json --prompt 90-delivery-auditor.md

  --status        the produced _audit/status.json (required)
  --reply         the digest text that was published (the reply body)
  --tasks         the saved `cron_read view=list` JSON, to re-run the roster
                  check and prove every live-but-unrostered routine was named
  --ground-truth  default: tools/schedule-ground-truth.json
  --contract      default: tools/auditor-contract.json
  --prompt        the deployed prompt, to assert its inline fallback copy of
                  the contract still agrees with the contract file

EXIT CODES
----------
  0  the output satisfies the contract
  1  at least one contract violation - every violation is printed
  2  usage / input error
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_CONTRACT = os.path.join(HERE, "auditor-contract.json")
DEFAULT_GROUND_TRUTH = os.path.join(HERE, "schedule-ground-truth.json")

DASH = r"(?:\u2014|\u2013|--)"

RE_SUMMARY = re.compile(r"^audit:\s+(\S+)\s+due=(\d+)\s+delivered=(\d+)\s+missing=(\d+)\s*$")
RE_GAP = re.compile(r"^gap:\s+(\S+)\s+(\S+)\s+(\S+)\s+" + DASH +
                    r"\s+cause=(\S+)\s+age_h=([0-9]+(?:\.[0-9]+)?)"
                    r"(?:\s+" + DASH + r"\s+(.*))?$")
RE_GAP_BARE = re.compile(r"^gap:\s+(\S+)\s+(\S+)\s+(\S+)\s+" + DASH + r"\s*(.*)$")
RE_SKIPPED = re.compile(r"^skipped:\s+(\S+)\s+(.+?)(?:\s+" + DASH + r"\s+(\S+))?\s*$")
RE_ROSTER_GAP = re.compile(r"^roster_gap:\s+(.+?)\s+\(task\s+(\S+)\)\s+is live but not in\s+"
                           r"schedule-ground-truth\.json\s*$")
RE_STREAK = re.compile(r"^streak:\s+(\S+)\s+(\d+)\s+consecutive missed fires\s*$")
RE_PUSH = re.compile(r"^push:\s+(.+)$")
RE_ERRORS = re.compile(r"^errors:\s+(\d+)\s*$")


class Report:
    """Collects contract violations. Every one is printed; none is fatal."""

    def __init__(self):
        self.failures = []
        self.checks = 0

    def check(self, ok, cid, message):
        self.checks += 1
        if not ok:
            self.failures.append(f"FAIL {cid} {message}")
        return bool(ok)

    def fail(self, cid, message):
        self.checks += 1
        self.failures.append(f"FAIL {cid} {message}")


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("cannot parse JSON")
        return json.loads(raw[start:end])


def load_contract(path):
    doc = _read_json(path)
    for key in ("causes", "state_vocabulary", "gap_labels", "label_causes",
                "status_schema", "digest"):
        if key not in doc:
            raise ValueError(f"contract is missing '{key}'")
    return doc


def check_status(status, contract, rep):
    """Every rule the status file itself must satisfy."""
    schema = contract["status_schema"]
    for key in schema["required_top_level"]:
        rep.check(key in status, "C02",
                  f"status.json is missing the required top-level key '{key}'")
    if "audit_date_et" not in status or "audit_run_et" not in status:
        return

    gaps = status.get("gaps")
    if not rep.check(isinstance(gaps, list), "C03", "status.json 'gaps' must be a list"):
        return
    causes = set(contract["causes"])
    labels = set(contract["gap_labels"])
    label_causes = contract["label_causes"]

    missing_gaps = 0
    for i, g in enumerate(gaps):
        if not isinstance(g, dict):
            rep.fail("C03", f"gaps[{i}] is not an object")
            continue
        for field in schema["gap_fields"]:
            rep.check(field in g, "C03",
                      f"gaps[{i}] ({g.get('routine', '?')}) is missing the field '{field}'")
        label = g.get("label")
        cause = g.get("cause")
        rep.check(label in labels, "C04",
                  f"gaps[{i}] ({g.get('routine', '?')}) has the unknown label '{label}'")
        rep.check(cause in causes, "C04",
                  f"gaps[{i}] ({g.get('routine', '?')}) has the cause '{cause}', which is not in "
                  f"the controlled vocabulary {sorted(causes)}")
        if label in label_causes and cause in causes:
            rep.check(cause in label_causes[label], "C05",
                      f"gaps[{i}] ({g.get('routine', '?')}) pairs label '{label}' with cause "
                      f"'{cause}', which that label does not accept")
        age = g.get("gap_age_hours")
        rep.check(isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0,
                  "C06", f"gaps[{i}] ({g.get('routine', '?')}) has a non-numeric or negative "
                         f"gap_age_hours ({age!r})")
        streak = g.get("streak")
        rep.check(isinstance(streak, int) and not isinstance(streak, bool) and streak >= 0,
                  "C07", f"gaps[{i}] ({g.get('routine', '?')}) has a non-integer or negative "
                         f"streak ({streak!r})")
        if label == "MISSING":
            missing_gaps += 1

    # The headline count must agree with the gaps it summarises.
    rep.check(status.get("missing") == missing_gaps, "C10",
              f"status.json 'missing' is {status.get('missing')!r} but {missing_gaps} gap(s) "
              f"carry the label MISSING")
    delivered = status.get("delivered")
    due = status.get("due")
    if isinstance(due, int) and isinstance(delivered, int) and isinstance(missing_gaps, int):
        rep.check(due >= delivered + missing_gaps, "C10",
                  f"status.json due={due} is smaller than delivered={delivered} + "
                  f"missing={missing_gaps}")

    # skipped_by_design: a reason is mandatory, and it must never be a MISSING.
    skipped = status.get("skipped_by_design")
    if rep.check(isinstance(skipped, list), "C08",
                 "status.json 'skipped_by_design' must be a list"):
        missing_routines = {g.get("routine") for g in gaps
                            if isinstance(g, dict) and g.get("label") == "MISSING"}
        for i, s in enumerate(skipped):
            if not isinstance(s, dict):
                rep.fail("C08", f"skipped_by_design[{i}] is not an object")
                continue
            for field in schema["skipped_fields"]:
                rep.check(field in s, "C08",
                          f"skipped_by_design[{i}] ({s.get('routine', '?')}) is missing "
                          f"the field '{field}'")
            reason = s.get("reason")
            rep.check(isinstance(reason, str) and reason.strip() != "", "C08",
                      f"skipped_by_design[{i}] ({s.get('routine', '?')}) has no reason - a "
                      f"routine that skipped by design must say why")
            rep.check(s.get("routine") not in missing_routines, "C09",
                      f"routine '{s.get('routine')}' is both skipped_by_design and a MISSING "
                      f"gap - a deliberate skip is never a delivery failure")
        count = status.get("skipped_by_design_count")
        rep.check(count is None or count == len(skipped), "C08",
                  f"status.json 'skipped_by_design_count' is {count!r} but "
                  f"{len(skipped)} routine(s) are listed")

    # The per-routine map: every routine carries a state and a streak.
    routines = status.get("routines")
    if rep.check(isinstance(routines, dict), "C11",
                 "status.json 'routines' must be an object keyed by routine name"):
        states = set(contract["state_vocabulary"])
        for name, r in routines.items():
            if not isinstance(r, dict):
                rep.fail("C11", f"routines['{name}'] is not an object")
                continue
            for field in schema["routine_fields"]:
                rep.check(field in r, "C11",
                          f"routines['{name}'] is missing the field '{field}'")
            rep.check(r.get("state") in states, "C11",
                      f"routines['{name}'] has the unknown state '{r.get('state')}'")
            streak = r.get("streak")
            rep.check(isinstance(streak, int) and not isinstance(streak, bool) and streak >= 0,
                      "C11", f"routines['{name}'] has a non-integer or negative streak "
                             f"({streak!r})")

    # roster_gap entries
    rg = status.get("roster_gap")
    if rep.check(isinstance(rg, list), "C12", "status.json 'roster_gap' must be a list"):
        for i, g in enumerate(rg):
            if not isinstance(g, dict):
                rep.fail("C12", f"roster_gap[{i}] is not an object")
                continue
            for field in schema["roster_gap_fields"]:
                rep.check(field in g, "C12",
                          f"roster_gap[{i}] is missing the field '{field}'")

    # audit_status must agree with the findings.
    asg = status.get("audit_status")
    if asg in ("ok", "gaps_found"):
        finding_labels = {"MISSING", "present_but_empty", "roster_desync"}
        has_finding = any(isinstance(g, dict) and g.get("label") in finding_labels for g in gaps)
        has_finding = has_finding or bool(rg)
        rep.check(not (asg == "ok" and has_finding), "C13",
                  "status.json audit_status is 'ok' but the file carries findings")
        rep.check(not (asg == "gaps_found" and not has_finding), "C13",
                  "status.json audit_status is 'gaps_found' but no finding is present")


def check_reply(reply, status, contract, rep):
    """Every rule the published digest must satisfy."""
    causes = set(contract["causes"])
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]

    summaries = [ln for ln in lines if RE_SUMMARY.match(ln)]
    rep.check(len(summaries) == 1, "D01",
              f"the digest must carry exactly one 'audit: <date> due= delivered= missing=' "
              f"line; found {len(summaries)}")
    if summaries:
        m = RE_SUMMARY.match(summaries[0])
        date, due, delivered, missing = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        rep.check(date == status.get("audit_date_et"), "D01",
                  f"the digest audits {date} but the status file audits "
                  f"{status.get('audit_date_et')}")
        rep.check(due == status.get("due"), "D01",
                  f"the digest says due={due} but the status file says {status.get('due')}")
        rep.check(delivered == status.get("delivered"), "D01",
                  f"the digest says delivered={delivered} but the status file says "
                  f"{status.get('delivered')}")
        rep.check(missing == status.get("missing"), "D01",
                  f"the digest says missing={missing} but the status file says "
                  f"{status.get('missing')}")

    push_lines = [ln for ln in lines if RE_PUSH.match(ln)]
    rep.check(len(push_lines) == 1, "D02",
              f"the digest must carry exactly one 'push:' line; found {len(push_lines)}")
    errors_lines = [ln for ln in lines if RE_ERRORS.match(ln)]
    rep.check(len(errors_lines) == 1, "D03",
              f"the digest must carry exactly one 'errors:' line; found {len(errors_lines)}")
    errors = int(RE_ERRORS.match(errors_lines[0]).group(1)) if errors_lines else 0

    # Gap lines: every one carries a cause from the vocabulary and an age.
    digest_gaps = []
    bare_gap_lines = []
    for ln in lines:
        if not ln.startswith("gap:"):
            continue
        m = RE_GAP.match(ln)
        if m:
            digest_gaps.append({"routine": m.group(1), "label": m.group(2), "path": m.group(3),
                                "cause": m.group(4), "age_h": float(m.group(5)),
                                "detail": (m.group(6) or "").strip()})
        else:
            bare_gap_lines.append(ln)
    for ln in bare_gap_lines:
        rep.fail("D04", f"the gap line has no 'cause=<token>' from the controlled vocabulary: "
                        f"{ln}")
    if bare_gap_lines:
        rep.check(errors >= 1, "D07",
                  f"{len(bare_gap_lines)} gap line(s) carry no cause, so 'errors' must be at "
                  f"least 1; it is {errors}")
    for g in digest_gaps:
        rep.check(g["cause"] in causes, "D04",
                  f"the gap line for '{g['routine']}' names the cause '{g['cause']}', which is "
                  f"not in the controlled vocabulary {sorted(causes)}")
        rep.check(g["age_h"] >= 0, "D05",
                  f"the gap line for '{g['routine']}' carries a negative age_h")
    status_gaps = status.get("gaps") or []
    rep.check(len(digest_gaps) == len(status_gaps), "D06",
              f"the digest publishes {len(digest_gaps)} gap line(s) but the status file holds "
              f"{len(status_gaps)}")
    for sg in status_gaps:
        if not isinstance(sg, dict):
            continue
        match = [g for g in digest_gaps
                 if g["routine"] == sg.get("routine") and g["label"] == sg.get("label")
                 and g["path"] == sg.get("path")]
        rep.check(len(match) == 1, "D06",
                  f"the status gap '{sg.get('routine')}' / '{sg.get('label')}' / "
                  f"'{sg.get('path')}' has no matching digest gap line")
        for g in match:
            rep.check(g["cause"] == sg.get("cause"), "D06",
                      f"the digest and the status file disagree on the cause for "
                      f"'{sg.get('routine')}': {g['cause']} vs {sg.get('cause')}")

    # skipped_by_design: one line per skipped routine, with its reason, and it
    # must NOT be counted as missing.
    skipped = status.get("skipped_by_design") or []
    skipped_lines = [ln for ln in lines if ln.startswith("skipped:")]
    parsed_skipped = []
    for ln in skipped_lines:
        m = RE_SKIPPED.match(ln)
        if not m:
            rep.fail("D08", f"the skipped line does not match "
                            f"'skipped: <routine> <reason> — <marker>': {ln}")
            continue
        parsed_skipped.append((m.group(1), m.group(2).strip(), m.group(3)))
    for s in skipped:
        if not isinstance(s, dict):
            continue
        name = s.get("routine")
        matches = [p for p in parsed_skipped if p[0] == name]
        rep.check(len(matches) == 1, "D08",
                  f"the status file lists '{name}' as skipped_by_design but the digest has "
                  f"{len(matches)} 'skipped:' line(s) for it")
        for p in matches:
            rep.check(p[1] != "", "D08",
                      f"the skipped line for '{name}' carries no reason")
            marker = s.get("marker")
            if isinstance(marker, str) and marker.strip():
                rep.check(marker in (p[2] or ""), "D08",
                          f"the status file records the skip marker '{marker}' for '{name}' "
                          f"but the digest names '{p[2]}'")
        rep.check(name not in {g.get("routine") for g in digest_gaps
                               if g.get("label") == "MISSING"}, "D08",
                  f"'{name}' is skipped by design but is published as a MISSING gap")
    rep.check(len(parsed_skipped) == len(skipped), "D08",
              f"the digest publishes {len(parsed_skipped)} 'skipped:' line(s) but the status "
              f"file lists {len(skipped)}")

    # roster_gap lines must match the status file exactly.
    rg_status = status.get("roster_gap") or []
    rg_lines = []
    for ln in lines:
        if not ln.startswith("roster_gap:"):
            continue
        m = RE_ROSTER_GAP.match(ln)
        if not m:
            rep.fail("D09", f"the roster_gap line does not match the contract template: {ln}")
            continue
        rg_lines.append((m.group(1), m.group(2)))
    for g in rg_status:
        if not isinstance(g, dict):
            continue
        matches = [p for p in rg_lines if p[0] == g.get("name") and p[1] == str(g.get("task_id"))]
        rep.check(len(matches) == 1, "D09",
                  f"the status file lists the roster gap '{g.get('name')}' (task "
                  f"{g.get('task_id')}) but the digest has {len(matches)} matching line(s)")
    rep.check(len(rg_lines) == len(rg_status), "D09",
              f"the digest publishes {len(rg_lines)} roster_gap line(s) but the status file "
              f"lists {len(rg_status)}")

    # A dead routine (three missed fires in a row) must be surfaced on its own line.
    streak_lines = {}
    for ln in lines:
        if not ln.startswith("streak:"):
            continue
        m = RE_STREAK.match(ln)
        if not m:
            rep.fail("D10", f"the streak line does not match "
                            f"'streak: <routine> <n> consecutive missed fires': {ln}")
            continue
        streak_lines[m.group(1)] = int(m.group(2))
    routines = status.get("routines") or {}
    for name, r in routines.items():
        if not isinstance(r, dict):
            continue
        streak = r.get("streak")
        if isinstance(streak, int) and streak >= 3:
            rep.check(name in streak_lines, "D10",
                      f"routine '{name}' has missed {streak} consecutive fires and must be "
                      f"surfaced on its own 'streak:' line")
            if name in streak_lines:
                rep.check(streak_lines[name] == streak, "D10",
                          f"the digest says '{name}' missed {streak_lines[name]} consecutive "
                          f"fires but the status file says {streak}")


def check_roster(tasks_path, ground_truth, status, reply, rep):
    """Re-run the roster check and prove every live-but-unrostered routine was named."""
    sys.path.insert(0, HERE)
    try:
        import auditor_roster_check as arc
    except Exception as exc:                                  # noqa: BLE001
        rep.fail("R01", f"could not import auditor_roster_check: {exc}")
        return
    try:
        tasks = arc.load_tasks(tasks_path)
        gt = arc.load_ground_truth(ground_truth)
    except Exception as exc:                                  # noqa: BLE001
        rep.fail("R01", f"roster check could not run: {exc}")
        return
    report = arc.check(tasks, gt)
    live = {g["name"]: g for g in report["roster_gap"]}

    status_rg = {g.get("name") for g in (status.get("roster_gap") or []) if isinstance(g, dict)}
    rep.check(status_rg == set(live), "R01",
              f"the live-but-unrostered set is {sorted(live)} but the status file names "
              f"{sorted(status_rg)}")
    if reply:
        named = set()
        for ln in reply.splitlines():
            m = RE_ROSTER_GAP.match(ln.strip())
            if m:
                named.add(m.group(1))
        for name in live:
            rep.check(name in named, "R02",
                      f"'{name}' is live but not in the ground truth and the digest does not "
                      f"say so")
        rep.check(named == set(live), "R02",
                  f"the digest names the roster gaps {sorted(named)} but the live set is "
                  f"{sorted(live)}")


def check_prompt_parity(prompt_path, contract, rep):
    """The prompt's inline fallback copy must agree with the contract file."""
    try:
        with open(prompt_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        rep.fail("P01", f"could not read the prompt: {exc}")
        return
    for cid, marker, key in (("P01", "AUDITOR-CONTRACT-CAUSES", "causes"),
                             ("P02", "AUDITOR-CONTRACT-STATES", "state_vocabulary")):
        m = re.search(r"<!--\s*" + marker + r"\s*\n(.*?)\n-->", text, re.S)
        if not rep.check(m is not None, cid,
                         f"the prompt carries no '<!-- {marker} ... -->' block - the inline "
                         f"fallback copy of the contract is gone"):
            continue
        inline = m.group(1).split()
        expected = list(contract[key])
        rep.check(inline == expected, cid,
                  f"the prompt's inline {key} {inline} does not match the contract file "
                  f"{expected}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", required=True, help="the produced _audit/status.json")
    ap.add_argument("--reply", help="the published digest text")
    ap.add_argument("--tasks", help="saved cron_read view=list JSON")
    ap.add_argument("--ground-truth", default=DEFAULT_GROUND_TRUTH)
    ap.add_argument("--contract", default=DEFAULT_CONTRACT)
    ap.add_argument("--prompt", help="the deployed prompt, for the parity check")
    args = ap.parse_args()

    for p in (args.status, args.contract, args.ground_truth):
        if not os.path.exists(p):
            print(f"ERROR: no such file: {p}", file=sys.stderr)
            return 2
    if args.reply and not os.path.exists(args.reply):
        print(f"ERROR: no such file: {args.reply}", file=sys.stderr)
        return 2
    if args.tasks and not os.path.exists(args.tasks):
        print(f"ERROR: no such file: {args.tasks}", file=sys.stderr)
        return 2

    try:
        contract = load_contract(args.contract)
        status = _read_json(args.status)
    except Exception as exc:                                  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    rep = Report()
    check_status(status, contract, rep)

    if args.reply:
        with open(args.reply, encoding="utf-8") as fh:
            reply = fh.read()
        check_reply(reply, status, contract, rep)
        if args.tasks:
            check_roster(args.tasks, args.ground_truth, status, reply, rep)
    elif args.tasks:
        check_roster(args.tasks, args.ground_truth, status, "", rep)

    if args.prompt:
        check_prompt_parity(args.prompt, contract, rep)

    if rep.failures:
        for f in rep.failures:
            print(f)
        print(f"CONTRACT: {len(rep.failures)} violation(s) across {rep.checks} checks")
        return 1
    print(f"CONTRACT: ok ({rep.checks} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

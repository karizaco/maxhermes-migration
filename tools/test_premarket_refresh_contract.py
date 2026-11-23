#!/usr/bin/env python3
"""
test_premarket_refresh_contract.py — prove cron #26b's artifact contract is SATISFIABLE and that
every breach is CAUGHT.

The checker is only worth something if a passing artifact can be produced and a broken one
cannot slip through. This test builds a golden artifact that satisfies the contract, asserts
the checker passes it, then mutates it N ways and asserts the checker FAILS each mutation with
the expected check name.

USAGE
    python3 test_premarket_refresh_contract.py [--checker /path/to/check_premarket_refresh.py]

Exit codes: 0 = every mutation was caught; 1 = a mutation slipped through (or the golden
artifact does not satisfy the contract).
"""

import argparse
import csv
import io
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

def _row(t, name, px, gap, vol, adv, pavg, cap, sec, ex):
    """prior_close DERIVES from the published price and change, so the row reproduces itself."""
    return (t, name, px, gap, vol, adv, pavg, round(px / (1.0 + gap / 100.0), 4), cap, sec, ex)


GAINERS = [_row("GA%02d" % i, "Gain Co %d" % i, round(40.0 - i * 1.1, 4), round(20.0 - i, 2),
                500000 + i, 1000000, round((500000 + i) / 1000000 * 100, 2),
                1200000000 + i, "Technology Services", "NASDAQ") for i in range(15)]
DECLINERS = [_row("DE%02d" % i, "Dec Co %d" % i, round(30.0 - i * 1.2, 4), round(-12.0 + i, 2),
                  400000 + i, 1000000, round((400000 + i) / 1000000 * 100, 2),
                  900000000 + i, "Health Technology", "NASDAQ") for i in range(10)]
THIN = [_row("TH%02d" % i, "Thin Co %d" % i, 5.0 + i, 9.0 + i, 300000 + i, 9500000,
             round((300000 + i) / 9500000 * 100, 2), 95000000, "Process Industries",
             "NYSE") for i in range(4)] + \
        [_row("TD%02d" % i, "Thin Dec %d" % i, 4.0 - i * 0.1, -8.0 + i, 250000 + i, 9000000,
              round((250000 + i) / 9000000 * 100, 2), 90000000, "Consumer Services",
              "NYSE") for i in range(4)]
DRIVERS = ["CASH-OUT+ANCHORED"] * 15 + ["EARNINGS-CUT+ANCHORED"] * 10
ALL = GAINERS + DECLINERS


def build_md(snapshot="09:22", date="2026-11-10", cron="26-agentic-pre-market-brief-refresh",
             changes=40, up=19, down=14, complete="true", head_gain=None, head_decl=None,
             cap_override=None, disclose="both"):
    """The golden artifact.

    `head_gain` / `head_decl` are the rows published in the headline tables (default: every
    name that clears both gates) and `cap_override` changes a name's market cap in BOTH the
    markdown and the CSV - together they build a THIN tape, where fewer than 15 gainers and
    fewer than 10 decliners clear the gates and the tables carry the top 15 / top 10 OF THAT
    SET. `disclose=False` drops the "showing N of M" sentence: that is the breach the
    TOPG-SHOWS-N-OF-M assertion exists to catch.
    """
    hg = head_gain if head_gain is not None else GAINERS
    hd = head_decl if head_decl is not None else DECLINERS
    caps = cap_override or {}

    def cap_of(row):
        return caps.get(row[0], row[8])

    def clearing(rows):
        n = 0
        for r in rows:
            pv, cap = r[4], cap_of(r)
            if pv >= 100000 or (cap >= 200000000 and pv >= 10000):
                if cap >= 100000000:
                    n += 1
        return n

    L = []
    L.append("---")
    L.append("date: %s" % date)
    L.append("cron: %s" % cron)
    L.append("fire_time_et: %s 09:20" % date)
    L.append("snapshot_et: %s" % snapshot)
    L.append("source: TradingView america scanner")
    L.append("status: ok")
    L.append("changes_since_morning: %d" % changes)
    L.append("up_3pct: %d" % up)
    L.append("down_3pct: %d" % down)
    L.append("screen_complete: %s" % complete)
    L.append("---")
    L.append("")
    L.append("# Pre-market refresh — %s" % date)
    L.append("")
    L.append("## Bottom line")
    L.append("")
    L.append("1. **The one setup** — **GA00** — break above the pre-market high 40.00 is the "
             "trigger; invalidated by a trade back to/below prior close 10.00. Driver "
             "`CASH-OUT+ANCHORED` — a $0.70 special dividend.")
    L.append("2. **The one risk** — **GA01** — the leader is unwinding with no sourced catalyst; "
             "below the pre-market low 39.00 the bid is a liquidity unwind.")
    L.append("3. **The one thing to watch at the open** — **GA02** — an open below the last "
             "pre-market print 37.80 means the gap is being sold.")
    L.append("")
    L.append("## What to watch at the open")
    L.append("")
    L.append("| Name | Prior close | PM last | PM low | PM high | Trigger | Invalidation |")
    L.append("|---|---|---|---|---|---|---|")
    for t in ("GA00", "GA01", "GA02"):
        r = [x for x in GAINERS if x[0] == t][0]
        L.append("| %s | %.2f | %.2f | %.2f | %.2f | break above %.2f | back to/below prior "
                 "close %.2f |" % (t, r[7], r[2], r[2] - 0.5, r[2] + 0.5, r[2] + 0.5, r[7]))
    L.append("")
    L.append("- **Rule 1 — the open is the verdict on the gap.**")
    L.append("- **Rule 2 — the 30-minute candle is the breakout test.**")
    L.append("")
    L.append("## 1. Refreshed top-of-book")
    L.append("")
    parts = []
    if disclose in ("both", "gainers"):
        parts.append("gainers: showing %d of 15" % min(15, clearing(GAINERS)))
    if disclose in ("both", "decliners"):
        parts.append("decliners: showing %d of 10" % min(10, clearing(DECLINERS)))
    tail = (" - **" + ", ".join(parts) + "**") if parts else ""
    L.append("The +/-3%% pre-market band held **%d gainers and %d decliners** at %s. Gate A is "
             "pre-market volume of 100,000 shares, or a $200m cap with 10,000 pre-market shares; "
             "Gate B is a $100m market cap decided on the reconciled cap. **%d of the %d band "
             "gainers and %d of the %d band decliners clear both gates.** The two tables below "
             "carry the top 15 gainers and the top 10 decliners of those qualifying sets%s."
             % (up, down, snapshot, clearing(GAINERS), up, clearing(DECLINERS), down, tail))
    L.append("")
    L.append("### Top 15 gainers")
    L.append("")
    L.append("| Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector | Snapshot |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex in hg:
        L.append("| %s | %s | %.2f | %+.2f%% | %s | %.2f%% | $%.2fB | %s | %s ET |" %
                 (t, n, px, gap, "{:,}".format(vol), pavg, cap_of((t, n, px, gap, vol, adv, pavg,
                 pc_, cap, sec, ex)) / 1e9, sec, snapshot))
    L.append("")
    L.append("### Top 10 decliners")
    L.append("")
    L.append("| Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector | Snapshot |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex in hd:
        L.append("| %s | %s | %.2f | %+.2f%% | %s | %.2f%% | $%.2fB | %s | %s ET |" %
                 (t, n, px, gap, "{:,}".format(vol), pavg, cap_of((t, n, px, gap, vol, adv, pavg,
                 pc_, cap, sec, ex)) / 1e9, sec, snapshot))
    L.append("")
    L.append("### Thin tape")
    L.append("")
    n_gain = len([x for x in THIN if x[0].startswith("TH")])
    n_decl = len([x for x in THIN if x[0].startswith("TD")])
    L.append("**Thin tape** — passed the liquidity gate but below the $100M quality floor. "
             "%d gainers and %d decliners qualify; the largest are below." % (n_gain, n_decl))
    L.append("")
    L.append("| Ticker | Name | Pre-market | % | Mkt cap | Pm vol | Snapshot |")
    L.append("|---|---|---|---|---|---|---|")
    for t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex in THIN:
        L.append("| %s | %s | %.2f | %+.2f%% | $%.1fM | %s | %s ET |" %
                 (t, n, px, gap, cap / 1e6, "{:,}".format(vol), snapshot))
    L.append("")
    L.append("### Tail - refreshed")
    L.append("")
    L.append("The names the gates and the table cap left out, ranked by `|gap|`. `gate-fail` "
             "failed the liquidity or quality gate, `unranked` cleared both but did not make the "
             "headline tables.")
    L.append("")
    L.append("| Ticker | Cohort | Prior close | Pre-market last | Gap % | PM range | Key level "
             "| Invalidation |")
    L.append("|---|---|---|---|---|---|---|---|")
    for (t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex), cohort in zip(
            THIN, ["gate-fail", "gate-fail", "unranked", "gate-fail", "gate-fail", "unranked",
                   "gate-fail", "unranked"]):
        L.append("| %s | %s | %.2f | %.2f | %+.2f%% | %.2f-%.2f | prior close %.2f | %s |"
                 % (t, cohort, pc_, px, gap, px - 0.5, px + 0.5, pc_,
                    "back to/below prior close %.2f" % pc_ if gap >= 0
                    else "below PM low %.2f" % (px - 0.5)))
    L.append("")
    L.append("## 2. Gap quality — can this gap hold?")
    L.append("")
    L.append("| Ticker | Name | Gap % | PM range | Hold % | pm %ADV | Print | Driver | Key level "
             "| Invalidation |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for (t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex), drv in zip(hg + hd,
                                                                     DRIVERS[:len(hg) + len(hd)]):
        L.append("| %s | %s | %+.2f%% | %.2f–%.2f | 90 | %.2f%% | AUCTION+holding | %s | prior "
                 "close %.2f | back to/below prior close %.2f |" %
                 (t, n, gap, px - 0.5, px + 0.5, pavg, drv, pc_, pc_))
    L.append("")
    L.append("## 3. What changed since the morning brief")
    L.append("")
    L.append("The morning brief's CSV is the reference.")
    L.append("")
    L.append("## 4. Verdict")
    L.append("")
    L.append("**Broader and shallower.**")
    L.append("")
    L.append("## 5. Source health")
    L.append("")
    L.append("- **One pull.** %s ET. Both screens asserted `len(rows) == totalCount`." % snapshot)
    L.append("- **The companion CSV's `live_*` columns are empty by construction.**")
    L.append("- **The Driver is read from the morning brief's OWN sourced catalysts**, per name - "
             "`has_news = no` is `NONE`. `NONE` is a finding: %d of the %d headline names have no "
             "sourced catalyst."
             % (sum(1 for d in DRIVERS[:len(hg) + len(hd)] if d == "NONE"), len(hg) + len(hd)))
    return "\n".join(L) + "\n"


def build_csv(rows=None, cap_override=None):
    caps = cap_override or {}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["ticker", "name", "premarket_close", "premarket_change_pct", "premarket_volume",
                "avg_volume_30d", "pct_of_adv", "prior_close", "prior_session_change_pct",
                "live_close", "live_change_pct", "live_volume", "market_cap", "sector",
                "exchange", "screen_complete"])
    for t, n, px, gap, vol, adv, pavg, pc_, cap, sec, ex in (rows or (ALL + THIN)):
        w.writerow([t, n, px, gap, vol, adv, pavg, pc_, 0.5, "", "", "", caps.get(t, cap), sec,
                    ex, "true"])
    return buf.getvalue()


def run_checker(checker, md_path, csv_path):
    p = subprocess.run([sys.executable, checker, "--md", md_path, "--csv", csv_path],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", default=os.path.join(HERE, "check_premarket_refresh.py"))
    args = ap.parse_args()
    checker = args.checker
    if not os.path.exists(checker):
        print("checker not found: %s" % checker)
        return 1

    tmp = tempfile.mkdtemp(prefix="premarket-refresh-test-")
    md_path = os.path.join(tmp, "artifact.md")
    csv_path = os.path.join(tmp, "artifact.csv")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_md())
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(build_csv())

    rc, out = run_checker(checker, md_path, csv_path)
    if rc != 0:
        print("FAIL GOLDEN — the golden artifact does not satisfy the contract:")
        print(out)
        return 1
    print("PASS GOLDEN — the contract is satisfiable (%s)" % out.strip().split("\n")[-1])

    # ---- a THIN tape: the 2026-11-20 shape ----
    # Only three gainers and two decliners clear both gates, so the headline tables carry the
    # top 15 / top 10 OF THAT SET and the section publishes what it carries. The contract must
    # be satisfiable here too: a thin tape is a valid result, and the gate must not be
    # satisfiable only on a fat one.
    THIN_KEEP_G = ["GA00", "GA01", "GA02"]
    THIN_KEEP_D = ["DE00", "DE01"]

    def thin_parts():
        hg = [r for r in GAINERS if r[0] in THIN_KEEP_G]
        hd = [r for r in DECLINERS if r[0] in THIN_KEEP_D]
        caps = {}
        for r in ALL + THIN:
            if r[0] not in THIN_KEEP_G + THIN_KEEP_D:
                caps[r[0]] = 50000000      # below the $100m quality floor
        return hg, hd, caps

    def thin_md(**kw):
        hg, hd, caps = thin_parts()
        return build_md(head_gain=hg, head_decl=hd, cap_override=caps, **kw)

    def thin_csv():
        _hg, _hd, caps = thin_parts()
        return build_csv(cap_override=caps)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(thin_md())
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(thin_csv())
    rc, out = run_checker(checker, md_path, csv_path)
    if rc != 0:
        print("FAIL THIN GOLDEN — the contract is NOT satisfiable on a thin tape:")
        print(out)
        return 1
    print("PASS THIN GOLDEN — a thin tape is a valid result (%s)" % out.strip().split("\n")[-1])

    def md_mut(text, old, new, count=1):
        assert old in text, "mutation anchor not found: %r" % old[:60]
        return text.replace(old, new, count)

    def line_of(text, prefix):
        for l in text.split("\n"):
            if l.startswith(prefix):
                return l
        raise AssertionError("no line starts with %r" % prefix)

    def mutate_line(text, prefix, old, new):
        """Change ONE row only — the tables share headers, so an unqualified replace hits the
        wrong table and the test would 'pass' for the wrong reason."""
        l = line_of(text, prefix)
        assert old in l, "anchor %r not in the line %r" % (old, l[:70])
        return text.replace(l, l.replace(old, new, 1))

    def drop_line(text, prefix):
        l = line_of(text, prefix)
        return text.replace(l + "\n", "", 1)

    GQ14 = "| GA14 | Gain Co 14 | +"      # the gap-quality row
    TOP14 = "| GA14 | Gain Co 14 | 2"     # the top-of-book row
    THIN3 = "| TH03 |"                    # a thin-tape row

    mutations = [
        # The band-prose honesty rule (2026-11-23). The artifact's front matter is flipped to
        # `screen_complete: false` AND the CSV's rows are flipped with it, so the two agree and
        # the CSV-SCREEN-COMPLETE-MATCHES-FM check still passes - which leaves ONLY the new
        # band-prose rule able to catch it. The golden's prose still asserts the screens were
        # complete, so a truncated band is published as exact: the 2026-11-05 failure mode.
        ("FM-FLOOR-NOT-EXACT", lambda t, c: (
            md_mut(t, "screen_complete: true", "screen_complete: false"),
            md_mut(c, ",true\n", ",false\n", -1))),
        # The same flip, but the golden's exactness CLAIM is removed as well, so the only rule
        # left able to catch it is the disclosure rule: a truncated band that says nothing about
        # floors is as wrong as one that calls them exact.
        ("FM-FLOOR-DISCLOSED", lambda t, c: (
            md_mut(md_mut(t, "screen_complete: true", "screen_complete: false"),
                   "Both screens asserted `len(rows) == totalCount`.",
                   "Both screens were pulled."),
            md_mut(c, ",true\n", ",false\n", -1))),
        ("FM-KEYS", lambda t, c: (md_mut(t, "up_3pct: 19\n", ""), c)),
        ("FM-CRON", lambda t, c: (md_mut(t, "cron: 26-agentic-pre-market-brief-refresh",
                                         "cron: 26b-agentic-pre-market-brief-refresh"), c)),
        ("BL-THREE-LINES", lambda t, c: (md_mut(
            t, "3. **The one thing to watch at the open**", "4. **The one thing to watch at the open**"), c)),
        ("BL-L1-INVALIDATION", lambda t, c: (md_mut(t, "invalidated by a trade back to/below",
                                                    "broken by a trade back to/below"), c)),
        ("BL-L1-ANCHORED", lambda t, c: (md_mut(t, "`CASH-OUT+ANCHORED`", "`CASH-OUT`"), c)),
        ("GQ-DRIVER-VOCABULARY", lambda t, c: (mutate_line(t, GQ14, "CASH-OUT+ANCHORED",
                                                           "MADE-UP-CLASS"), c)),
        ("GQ-INVALIDATION-SIDE", lambda t, c: (mutate_line(t, GQ14, "back to/below prior close",
                                                           "at prior close"), c)),
        ("GQ-MATCHES-TOP", lambda t, c: (mutate_line(t, GQ14, "GA14", "GA13"), c)),
        ("TOPG-SORTED", lambda t, c: (mutate_line(t, TOP14, "+6.00%", "+99.00%"), c)),
        ("TOPD-ROWS", lambda t, c: (drop_line(t, "| DE09 | Dec Co 9"), c)),
        ("TOPG-ROWS", lambda t, c: (drop_line(t, TOP14), c)),
        ("GQ-ROWS", lambda t, c: (drop_line(t, GQ14), c)),
        ("TOP-CLEARING-COUNTS", lambda t, c: (md_mut(
            t, "**15 of the 19 band gainers", "**14 of the 19 band gainers"), c)),
        # the published NONE count must be the gap-quality table's own count and size
        ("GQ-NONE-COUNT", lambda t, c: (md_mut(
            t, "`NONE` is a finding: 0 of the 25 headline names",
            "`NONE` is a finding: 3 of the 25 headline names"), c)),
        ("THIN-COMPLETE", lambda t, c: (drop_line(t, THIN3), c)),
        ("SKELETON", lambda t, c: (md_mut(t, "### Tail - refreshed\n", ""), c)),
        ("TAIL-PRESENT", lambda t, c: (md_mut(
            t, "| Ticker | Cohort | Prior close | Pre-market last | Gap % | PM range | Key level "
              "| Invalidation |\n", ""), c)),
        ("TAIL-ROWS", lambda t, c: (mutate_line(t, "| TH00 | gate-fail |", "+9.00%", "+91.00%"), c)),
        ("TRACE-GAP", lambda t, c: (mutate_line(t, GQ14, "+6.00%", "+61.00%"), c)),
        ("NO-PLACEHOLDER", lambda t, c: (md_mut(t, "## 4. Verdict", "## 4. Verdict\n\nTODO: write this"), c)),
        ("PRIOR-CLOSE-RECONCILES", lambda t, c: (t, md_mut(c, ",33.3333,", ",33.3000,"))),
        # --- the three assertions added on 2026-11-19, each proven to BITE ---
        # (a) a single "?" where a published number belongs. The placeholder list held only
        #     "???", so the gate passed an artifact with a hole in it.
        ("NO-MISSING-NUMBER", lambda t, c: (md_mut(t, "Both screens asserted",
                                                   "? screens asserted"), c)),
        # (b) the GATE WINS: the artifact may not call the session not live while its own front
        #     matter says it was open at the pull.
        ("LIVE-SESSION-CONSISTENT", lambda t, c: (
            md_mut(md_mut(t, "screen_complete: true\n",
                          "screen_complete: true\nmarket_open_at_pull: true\n"),
                   "- **The companion CSV's `live_*` columns are empty by construction.**",
                   "- **These are ISOLATED field defects, not a live session.**"), c)),
        # (c) a gap-DOWN name that moved toward zero NARROWED its decline.
        ("GAP-DIRECTION", lambda t, c: (md_mut(
            t, "The morning brief's CSV is the reference.",
            "The morning brief's CSV is the reference.\n\n**Two facts behind those numbers.** DE00 - "
            "one of the morning brief's setups - extended its gap **4.00pp**, from -12.00% to "
            "-8.00%."), c)),
    ]

    # the CSV mutations need their own file handling
    csv_mutations = [
        ("CSV-HEADER", lambda c: md_mut(c, "premarket_change_pct", "pm_change")),
        ("CSV-LIVE-BLANK-PREOPEN", lambda c: md_mut(c, ",0.5,,,,", ",0.5,40.00,0.10,300000,")),
        ("CSV-SCREEN-COMPLETE-MATCHES-FM", lambda c: md_mut(c, ",true\n", ",false\n", -1)),
    ]

    # ---- the THIN tape's mutations (2026-11-20) ----
    # A short table that does not SAY it is short reads as a complete one. These two prove the
    # disclosure is required: each drops one half of the "showing N of M" sentence and the
    # matching assertion must fire.
    thin_mutations = [
        ("TOPG-SHOWS-N-OF-M", lambda: (thin_md(disclose="decliners"), thin_csv())),
        ("TOPD-SHOWS-N-OF-M", lambda: (thin_md(disclose="gainers"), thin_csv())),
    ]

    failures = []
    for name, fn in mutations:
        t, c = fn(build_md(), build_csv())
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(t)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(c)
        rc, out = run_checker(checker, md_path, csv_path)
        if rc == 0:
            failures.append("%s: the checker PASSED a broken artifact" % name)
            print("FAIL %-26s slipped through" % name)
        elif name not in out:
            failures.append("%s: the checker failed with a different check" % name)
            print("FAIL %-26s failed, but not on %s" % (name, name))
        else:
            print("PASS %-26s caught" % name)

    for name, fn in csv_mutations:
        t = build_md()
        c = fn(build_csv())
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(t)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(c)
        rc, out = run_checker(checker, md_path, csv_path)
        if rc == 0:
            failures.append("%s: the checker PASSED a broken CSV" % name)
            print("FAIL %-26s slipped through" % name)
        elif name not in out:
            failures.append("%s: the checker failed with a different check" % name)
            print("FAIL %-26s failed, but not on %s" % (name, name))
        else:
            print("PASS %-26s caught" % name)

    for name, fn in thin_mutations:
        t, c = fn()
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(t)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(c)
        rc, out = run_checker(checker, md_path, csv_path)
        if rc == 0:
            failures.append("%s: the checker PASSED a broken thin artifact" % name)
            print("FAIL %-26s slipped through" % name)
        elif name not in out:
            failures.append("%s: the checker failed with a different check" % name)
            print("FAIL %-26s failed, but not on %s" % (name, name))
        else:
            print("PASS %-26s caught" % name)

    total = len(mutations) + len(csv_mutations) + len(thin_mutations)
    print("%d mutations, %d caught, %d slipped through" %
          (total, total - len(failures), len(failures)))
    if failures:
        for f in failures:
            print("  " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

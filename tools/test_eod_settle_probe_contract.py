#!/usr/bin/env python3
"""Contract test for the settle probe loop (EOD_SETTLE_V2).

WHAT THIS PROVES
----------------
The probe loop is the only part of cron #20 that can publish a WRONG close: it decides
when the feed has stopped moving, and it exits on that verdict. The 2026-11-16 change
made the detector BATCHED (Yahoo's spark, 20 symbols per request), made the venue's poll
cadence ADAPTIVE, and replaced the ever-growing residue with a still-moving set. Each of
those changes touches the exit verdict, so each needs a test that OBSERVES it failing.

The test drives the REAL `main()` with a SYNTHETIC feed: no network, no clock, no sleep.
The feed is a table - "this symbol's bar changes at feed-round 1, this symbol's venue
changes at feed-round 2" - and the fake fetchers replay it. The assertions are about the
loop's INVARIANTS, not about its output text.

THE CLOCK. `main()` sleeps between rounds, and the sleep is the round boundary, so the
feed's round N is reached at probe round N+1 (probe round 1 reads feed-round 0, the same
feed-round pass 1 read). The timeline below is written in FEED rounds for that reason.

Run it:  python3 tools/test_eod_settle_probe_contract.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(
    REPO, "cloud-prompts", "skills", "eod-watchlist-snapshot", "scripts",
    "fetch_eod_settled.py")

if not os.path.exists(SCRIPT):
    raise SystemExit(f"the script under test is not at {SCRIPT}")

spec = importlib.util.spec_from_file_location("eod_settled", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SESSION = "2026-11-13"
TS = 1794556800  # 2026-11-13 00:00:00Z


def bar(close, vol=1000):
    """One daily bar [epoch, o, h, l, c, v]."""
    return [TS, close, close, close, close, vol]


class Feed:
    """The synthetic feed and the instrumentation the assertions read."""

    def __init__(self, spec=None):
        # ticker -> {"bar": {feed_round: close}, "venue": {feed_round: price},
        #            "no_bar": bool}
        # AAA's BAR keeps moving for five feed-rounds while its VENUE print settles
        # after one - the real shape of the problem: the vendor's daily bar is a series
        # that keeps ingesting, the venue's auction print is stamped and done.
        self.spec = spec or {
            "AAA": {"bar": {0: 10.5, 1: 10.6, 2: 10.7, 3: 10.8, 4: 10.9, 5: 11.0},
                    "venue": {0: 10.6, 1: 10.9}},
            "BBB": {"bar": {0: 5.0}, "venue": {0: 5.0}},
            "CCC": {"bar": {}, "venue": {}, "no_bar": True},
            "DDD": {"bar": {2: 20.0}, "venue": {0: 20.0}},
            "EEE": {"bar": {0: 7.0}, "venue": {0: 7.0}},
            "FFF": {"bar": {0: 8.0}, "venue": {0: 8.0}},
        }
        self.round = 0
        self.chart_calls = []
        self.spark_calls = []      # one entry per probe round: the probe set
        self.venue_calls = []
        self.probe_rounds = 0

    def close_at(self, ticker, rnd):
        s = self.spec.get(ticker)
        if s is None:
            return 100.0          # an index/ETF proxy: stable, and never probed
        if s.get("no_bar"):
            return None
        val = None
        for r, c in sorted(s["bar"].items()):
            if rnd >= r:
                val = c
        return val

    def venue_at(self, ticker, rnd):
        s = self.spec.get(ticker)
        if s is None:
            return 100.0
        val = None
        for r, c in sorted(s["venue"].items()):
            if rnd >= r:
                val = c
        return val


def run(feed, max_rounds=12, probe_size=6, spark_filter=None):
    """Drive main() with the synthetic feed. Returns (rc, stdout, history, settle_map)."""

    def fake_chart(ticker, rng, interval, throttle, timeout=25.0):
        feed.chart_calls.append((ticker, rng))
        c = feed.close_at(ticker, feed.round)
        if c is None:
            return []
        return [bar(c)]

    def fake_spark(tickers, session, throttle, batch=20, timeout=25.0):
        feed.spark_calls.append(list(tickers))
        out = {}
        for t in tickers:
            c = feed.close_at(t, feed.round)
            if c is not None:
                # Yahoo's spark ROUNDS the close - emulate that exactly
                out[t] = round(c, 2) if abs(c) >= 0.1 else round(c, 3)
        if spark_filter:
            out = spark_filter(out, tickers)
        return out

    def fake_venue(ticker):
        feed.venue_calls.append(ticker)
        return feed.venue_at(ticker, feed.round)

    mod.fetch_chart = fake_chart
    mod.fetch_spark_batch = fake_spark
    mod.fetch_venue = fake_venue

    # the sleep IS the round boundary
    orig_sleep = mod.time.sleep

    def counting_sleep(sec):
        feed.round += 1
        return orig_sleep(0)

    mod.time.sleep = counting_sleep

    tmp = tempfile.mkdtemp()
    syms = os.path.join(tmp, "symbols.csv")
    with open(syms, "w") as fh:
        fh.write("ticker\n")
        for t in feed.spec:
            fh.write(t + "\n")
    out_path = os.path.join(tmp, "history.jsonl")
    smap = os.path.join(tmp, "settle_map.json")

    argv = sys.argv
    sys.argv = ["fetch_eod_settled.py", "--symbols", syms, "--session", SESSION,
                "--out", out_path, "--settle-map", smap,
                "--probe-size", str(probe_size), "--probe-interval", "0",
                "--max-rounds", str(max_rounds)]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    finally:
        sys.argv = argv
        mod.time.sleep = orig_sleep
    return rc, buf.getvalue(), out_path, smap


FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}: {detail}")
        FAILURES.append(name)


def round_lines(out):
    return [l for l in out.splitlines() if l.startswith("  round ")]


def main() -> int:
    print("=== the settle probe contract (EOD_SETTLE_V2) ===")

    # ---- case 1: a rounded spark close is not a movement
    feed = Feed({"FFF": {"bar": {0: 350.0, 1: 356.2699890136719}, "venue": {0: 350.0}},
                 "BBB": {"bar": {0: 5.0}, "venue": {0: 5.0}},
                 "CCC": {"bar": {}, "venue": {}, "no_bar": True}})
    rc, out, hist, smap = run(feed)
    check("the run completes", rc == 0, f"rc={rc}")
    fff_moves = [l for l in round_lines(out) if "bar_moved=1" in l]
    check("the rounded value produces exactly ONE bar movement for FFF",
          len(fff_moves) == 1, f"{len(fff_moves)} rounds reported a bar move")

    # ---- case 2: a round that skipped the venue never ADVANCES the quiet streak
    feed = Feed()
    rc, out, hist, smap = run(feed)
    rl = round_lines(out)
    check("the loop ran several rounds", len(rl) >= 5, f"{len(rl)} rounds")
    parsed = []
    for l in rl:
        d = dict(kv.split("=") for kv in
                 (l.replace("  round ", "").split("  ")[0]).split() if "=" in kv)
        parsed.append(d)
    bad = []
    for i, d in enumerate(parsed):
        if i == 0:
            continue
        prev = parsed[i - 1]
        if d.get("venue_poll") == "no":
            # a skipped round must neither advance nor reset the streak
            if d.get("quiet_streak") != prev.get("quiet_streak"):
                bad.append((i, d.get("quiet_streak"), prev.get("quiet_streak")))
        else:
            want = str(int(prev.get("quiet_streak", 0)) + 1) \
                if d.get("changed") == "0" else "0"
            if d.get("quiet_streak") != want:
                bad.append((i, d.get("quiet_streak"), want))
    check("a skipped round neither advances nor resets the quiet streak",
          not bad, str(bad))

    # ---- case 3: a mover is re-measured after its LAST move
    feed = Feed()
    rc, out, hist, smap = run(feed)
    # AAA's bar changes at feed-rounds 1 and 3 -> detected at probe rounds 2 and 4.
    # It must still be in the probe set at round 5 (one round after its last move).
    sets = feed.spark_calls
    check("the probe set was measured every round", len(sets) >= 5, f"{len(sets)} rounds")
    aaa_sets = [i for i, s in enumerate(sets) if "AAA" in s]
    check("the still-moving symbol stays in the probe set after it moves",
          len(aaa_sets) >= 4, f"AAA appeared in {len(aaa_sets)} probe sets")
    check("the mover is re-measured one round after its last move",
          len(aaa_sets) >= 5 and "AAA" in sets[min(4, len(sets) - 1)],
          f"probe sets: {aaa_sets}")

    # ---- case 4: the published close is the LAST value the feed showed
    recs = {}
    with open(hist) as fh:
        for line in fh:
            r = json.loads(line)
            recs[r["ticker"]] = r
    last = None
    for b in recs.get("AAA", {}).get("bars", []):
        last = b[4]
    check("the published close is the last value the feed showed",
          last == 11.0, f"published {last}, the feed's last value was 11.0")

    # ---- case 5: the venue cadence backs off once the venue is quiet
    polllines = [l for l in round_lines(out) if "venue_poll=no" in l]
    check("the cadence backs off (at least one round skips the venue)",
          bool(polllines), "every round polled the venue")
    first_skip = next((i for i, l in enumerate(round_lines(out))
                       if "venue_poll=no" in l), None)
    check("the venue is polled EVERY round while it is still moving",
          first_skip is not None and first_skip >= 4,
          f"the first skipped venue poll was round index {first_skip}")
    moved_rounds = [i for i, l in enumerate(round_lines(out)) if "venue_moved=1" in l]
    check("the venue is polled on the round it moves",
          moved_rounds and (first_skip is None or max(moved_rounds) < first_skip),
          f"venue moved on rounds {moved_rounds}, first skip at {first_skip}")

    # ---- case 6: the detector is BATCHED - the chart is pulled only for movers
    feed = Feed()
    rc, out, hist, smap = run(feed)
    probe_pulls = [c for c in feed.chart_calls if c[1] == "5d"]
    per_round = len(feed.spark_calls)
    total_if_per_symbol = sum(len(s) for s in feed.spark_calls)
    check("the per-symbol chart is pulled only for movers, not for the whole probe set",
          len(probe_pulls) < total_if_per_symbol,
          f"{len(probe_pulls)} 5d pulls vs {total_if_per_symbol} if every symbol were pulled")
    check("the batched detector was used every round", len(feed.spark_calls) == per_round,
          f"{len(feed.spark_calls)} spark calls over {per_round} rounds")

    # ---- case 6b: the probe set SHRINKS once the names stop moving
    # The ever-changed set (the old residue) grew monotonically: on 2026-11-13 it held
    # 765 symbols by the last round, so the probe could never shrink and every round
    # re-pulled names that had been quiet for hours.
    many = {}
    for i in range(40):
        t = f"S{i:02d}"
        many[t] = {"bar": {0: 10.0 + i, 1: 11.0 + i}, "venue": {0: 10.0 + i}}
    many["QUIET"] = {"bar": {0: 1.0}, "venue": {0: 1.0}}
    many["NOBAR"] = {"bar": {}, "venue": {}, "no_bar": True}
    feed = Feed(many)
    rc, out, hist, smap = run(feed, probe_size=6, max_rounds=12)
    rl = round_lines(out)
    sizes = [int(l.split("probe=")[1].split()[0]) for l in rl]
    floor = 6 + 1          # the sample size plus the one name that never publishes a bar
    check("the probe set GROWS while the names are moving",
          max(sizes) > floor,
          f"probe sizes per round: {sizes}")
    check("the probe set shrinks back to the sample floor once the names stop moving",
          len(sizes) >= 4 and sizes[-1] <= floor,
          f"probe sizes per round: {sizes} (floor {floor})")

    # ---- case 7: the spark fallback - a symbol spark cannot resolve is still measured
    feed = Feed()

    def drop_bbb(out, tickers):
        out.pop("BBB", None)        # spark cannot resolve it
        return out

    rc, out, hist, smap = run(feed, spark_filter=drop_bbb)
    bbb_chart = [c for c in feed.chart_calls if c[0] == "BBB" and c[1] == "5d"]
    check("a symbol spark cannot resolve falls back to the per-symbol chart",
          len(bbb_chart) > 0, "BBB was never measured by the chart")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) failed: {', '.join(FAILURES)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

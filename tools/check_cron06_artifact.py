#!/usr/bin/env python3
"""
check_cron06_artifact.py — assert the cron #06 weekly-refresh artifact contract.

Do not eyeball it. The 2026-11-07 run was mechanically correct and reader-hostile:
three correct lists, no joins, no tradeability verdicts, no state, and a note that
explained the missing intersection instead of publishing it. These clauses turn the
acceptance criteria into machine assertions so a run that breaks the contract FAILS
instead of shipping.

USAGE
    python3 check_cron06_artifact.py \
        --md-dir daily-screens/<date> \
        --json daily-screens/<date>/cron06-refresh.json \
        --state pattern-study/cron06-state/short-float-<date>.json \
        [--prior-backlog pattern-study/peoplewish-1000pct-backlog.md] \
        [--reply reply.txt]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

CONTRACT_VERSION = "cron06-refresh-v2"
TRADEABLE_VERDICTS = {"TRADEABLE", "THIN", "ILLIQUID", "FLOAT_ARTIFACT", "NO_QUOTE"}
TAG_CHANGES = {"NEW", "UNCHANGED", "ADDED", "REMOVED", "MIXED"}
SI_VERDICTS = {"AGREE", "DIVERGES", "NO_DATA"}
SI_STATUSES = {"ok", "no_rows", "not_supplied"}
SI_AGREE_LO, SI_AGREE_HI = 0.67, 1.50
REQUIRED_FILES = ["weekly-ipo.md", "weekly-high-short-float.md", "peoplewish-backlog.md",
                   "peoplewish-backlog-run-full.json"]

FAILURES: list[str] = []
CHECKS = 20


def fail(clause: str, msg: str) -> None:
    FAILURES.append(f"[{clause}] {msg}")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(txt: str, header: str) -> str:
    """Return the text of a '## header' section (up to the next '## ' heading)."""
    if header not in txt:
        return ""
    rest = txt.split(header, 1)[1]
    nxt = re.search(r"^## ", rest, flags=re.M)
    return rest[: nxt.start()] if nxt else rest


def table_rows(txt: str, header: str, ncols: int | None = None):
    """Parse the markdown table inside a section into a list of cell-lists."""
    sec = section(txt, header)
    rows = []
    for line in sec.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if ncols is not None and len(cells) != ncols:
            continue
        rows.append(cells)
    return rows


def ledger_names(txt: str) -> set:
    """Tickers in a published ledger: the carried-forward table (first column) and
    the newly-tagged table (second column, after the '#' index)."""
    names = set()
    for r in table_rows(txt, "## Carried forward"):
        if r and r[0] not in ("Ticker", ""):
            names.add(r[0].replace("⚠", "").strip())
    for r in table_rows(txt, "## Newly tagged entries"):
        if r and len(r) > 1 and r[0] not in ("#", "Ticker"):
            names.add(r[1].replace("⚠", "").strip())
    return names


def num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("$", "").replace("pp", "").strip())
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md-dir", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--prior-backlog", default=None)
    ap.add_argument("--prior-state", default=None,
                    help="the PRIOR week's state snapshot — C15 recomputes the "
                         "week-over-week short-float delta from it")
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()

    # ---------------------------------------------------------------- C1 files
    paths = {f: os.path.join(args.md_dir, f) for f in REQUIRED_FILES}
    for f, p in paths.items():
        if not os.path.exists(p):
            fail("C1", f"missing artifact file: {p}")
        elif os.path.getsize(p) < 500:
            fail("C1", f"artifact file is suspiciously small: {p}")
    if not os.path.exists(args.json):
        fail("C1", f"missing machine-readable companion: {args.json}")
    if FAILURES:
        report()
        return
    docs = {f: read(p) for f, p in paths.items()
            if f.endswith(".md")}
    data = json.loads(read(args.json))

    # ---------------------------------------------------------------- C2 marker
    for f, txt in docs.items():
        if f"contract: {CONTRACT_VERSION}" not in txt:
            fail("C2", f"{f} does not carry the contract marker 'contract: {CONTRACT_VERSION}'")

    # ---------------------------------------------------------------- C3 coverage
    cov = data.get("coverage", {})
    for key in ("ipo", "short_float", "scan"):
        c = cov.get(key) or {}
        rp, rk = c.get("rows_passing"), c.get("rows_kept")
        if rp is None or rk is None:
            fail("C3", f"coverage for '{key}' does not publish rows_passing and rows_kept")
        elif rp != rk:
            fail("C3", f"coverage for '{key}' is TRUNCATED: rows_passing {rp} != rows_kept {rk}")
        else:
            owner = {"ipo": "weekly-ipo.md", "short_float": "weekly-high-short-float.md",
                     "scan": "peoplewish-backlog.md"}[key]
            if f"rows_passing {rp} = rows_kept {rk}" not in docs[owner]:
                fail("C3", f"{owner} does not publish the coverage line for '{key}' "
                           f"(rows_passing {rp} = rows_kept {rk})")
    # The coverage must also agree with the rows the artifact ITSELF carries — a
    # coverage line that is not backed by the rows is a claim, not a measurement.
    _got = {"ipo": len(data.get("ipo_rows") or []),
            "short_float": len(data.get("short_float_rows") or []),
            "scan": len((json.loads(read(os.path.join(args.md_dir, "peoplewish-backlog-run-full.json")))
                         .get("rows_full") or []))}
    for key, n_got in _got.items():
        c = cov.get(key) or {}
        if c.get("rows_kept") is not None and c["rows_kept"] != n_got:
            fail("C3", f"coverage for '{key}' claims rows_kept {c['rows_kept']} but the artifact "
                       f"carries {n_got} rows")

    # ---------------------------------------------------------------- C4 IPO fields
    ipo_rows = table_rows(docs["weekly-ipo.md"], docs["weekly-ipo.md"].splitlines()[0])
    ipo_rows = [r for r in ipo_rows if r and re.match(r"^\d+$", r[0])]
    if not ipo_rows:
        fail("C4", "the IPO table has no data rows")
    for r in ipo_rows:
        if len(r) < 12:
            fail("C4", f"IPO row {r[1] if len(r) > 1 else '?'} has {len(r)} columns, expected 12")
            continue
        days, post, verified, verdict = r[6], r[7], r[8], r[9]
        if num(days) is None:
            fail("C4", f"IPO row {r[1]}: days_since_ipo is not a number ({days!r})")
        if post not in ("YES", "NO"):
            fail("C4", f"IPO row {r[1]}: post_lockup must be YES/NO, got {post!r}")
        if verified not in ("YES", "NO"):
            fail("C4", f"IPO row {r[1]}: mcap_verified must be YES/NO, got {verified!r}")
        if verdict not in TRADEABLE_VERDICTS:
            fail("C4", f"IPO row {r[1]}: tradeable_verdict {verdict!r} is outside the closed set "
                       f"{sorted(TRADEABLE_VERDICTS)}")

    # ---------------------------------------------------------------- C5 short-float fields
    sf = data.get("short_float_rows") or []
    if not sf:
        fail("C5", "the JSON companion publishes no short_float_rows")
    for r in sf:
        v = r.get("tradeable_verdict")
        if v not in TRADEABLE_VERDICTS:
            fail("C5", f"short-float row {r.get('ticker')}: verdict {v!r} outside the closed set")
        if r.get("squeeze_candidate") not in ("YES", "NO", "CONTESTED"):
            fail("C5", f"short-float row {r.get('ticker')}: squeeze_candidate "
                       f"{r.get('squeeze_candidate')!r} is outside ['CONTESTED', 'NO', 'YES']")
        d = r.get("short_float_delta_pp")
        if d != "NO_PRIOR_SNAPSHOT" and num(d) is None:
            fail("C5", f"short-float row {r.get('ticker')}: short_float_delta_pp is neither a number "
                       f"nor NO_PRIOR_SNAPSHOT ({d!r})")
        if r.get("adv30") is not None and r.get("chg_30d_pct") is None:
            fail("C5", f"short-float row {r.get('ticker')}: has adv30 but no chg_30d_pct — the 30-bar "
                       f"window already carries it, it costs no extra call")

    # ---------------------------------------------------------------- C6 intersections
    inter = data.get("intersections") or {}
    if not inter:
        fail("C6", "the JSON companion publishes no intersections")
    for f, txt in docs.items():
        if "## Cross-screen intersections" not in txt:
            fail("C6", f"{f} does not publish the cross-screen intersections section")
    ipo_t = {r["ticker"] for r in data.get("ipo_rows") or []}
    sf_t = {r["ticker"] for r in sf}
    for key, left, right, label in (
        ("crowded_ledger", sf_t, set(inter.get("crowded_ledger") or []), "short float"),
        ("ipo_crowded", ipo_t, set(inter.get("ipo_crowded") or []), "IPO"),
    ):
        pass  # set-level consistency is checked below against the universes
    # every published intersection name must be in BOTH universes
    led = set(inter.get("crowded_ledger") or [])
    for t in led:
        if t not in sf_t:
            fail("C6", f"intersection 'crowded_ledger' names {t}, which is not in the short-float universe")
    for t in inter.get("ipo_crowded") or []:
        if t not in sf_t or t not in ipo_t:
            fail("C6", f"intersection 'ipo_crowded' names {t}, which is not in both universes")
    for t in inter.get("ipo_ledger") or []:
        if t not in ipo_t:
            fail("C6", f"intersection 'ipo_ledger' names {t}, which is not in the IPO universe")
    # the intersections must actually be COMPLETE, not a sample: recompute them
    ledger_t = set()
    if args.prior_backlog and os.path.exists(args.prior_backlog):
        ledger_t = ledger_names(read(args.prior_backlog))
    expect_ledger = sorted(sf_t & ledger_t)
    expect_ipo = sorted(ipo_t & sf_t)
    if sorted(inter.get("crowded_ledger") or []) != expect_ledger:
        fail("C6", "the 'crowded_ledger' intersection is INCOMPLETE — recomputed "
                   f"{len(expect_ledger)} names, published {len(inter.get('crowded_ledger') or [])}")
    if sorted(inter.get("ipo_crowded") or []) != expect_ipo:
        fail("C6", "the 'ipo_crowded' intersection is INCOMPLETE — recomputed "
                   f"{len(expect_ipo)} names, published {len(inter.get('ipo_crowded') or [])}")
    # the published intersection table in the short-float artifact must list them all
    sf_txt = docs["weekly-high-short-float.md"]
    if "## Intersection names" in sf_txt:
        listed = {r[0] for r in table_rows(sf_txt, "## Intersection names") if r}
        missing = set(inter.get("union") or []) - listed
        if missing:
            fail("C6", f"{len(missing)} intersection names are not listed in the enriched table: "
                       f"{sorted(missing)[:8]}")

    # ---------------------------------------------------------------- C7 backlog live re-score
    bl = docs["peoplewish-backlog.md"]
    if "## Live re-score of the tagged window" not in bl:
        fail("C7", "the backlog does not publish the live re-score section")
    else:
        rows = [r for r in table_rows(bl, "## Live re-score of the tagged window")
                if r and r[0] != "Ticker"]
        tagged = (cov.get("tagged") or {}).get("rows_kept")
        if tagged and len(rows) != tagged:
            fail("C7", f"the live re-score has {len(rows)} rows but {tagged} names were tagged")
        for r in rows:
            if len(r) < 5:
                continue
            if r[4] not in TAG_CHANGES:
                fail("C7", f"re-score row {r[0]}: tag_change {r[4]!r} is outside the closed set "
                           f"{sorted(TAG_CHANGES)}")
    nnew = len(data.get("newly_tagged") or [])
    nrows = [r for r in table_rows(bl, "## Newly tagged entries") if r and re.match(r"^\d+$", r[0])]
    if len(nrows) != nnew:
        fail("C7", f"the newly-tagged table has {len(nrows)} rows but the JSON publishes {nnew}")

    # ---------------------------------------------------------------- C8 ledger continuity
    if args.prior_backlog and os.path.exists(args.prior_backlog):
        prior_names = ledger_names(read(args.prior_backlog))
        carried = ledger_names(bl)
        dropped = prior_names - carried
        if dropped:
            fail("C8", f"{len(dropped)} names present in the prior ledger are missing from this week's "
                       f"carried-forward table (a silent ledger drop): {sorted(dropped)[:8]}")
        if (data.get("prior_ledger_size") or 0) != len(prior_names):
            fail("C8", f"the JSON claims a prior ledger of {data.get('prior_ledger_size')} names but the "
                       f"prior ledger file holds {len(prior_names)}")
        expected_size = len(prior_names) + nnew
        if data.get("ledger_size") != expected_size:
            fail("C8", f"the JSON ledger size {data.get('ledger_size')} != prior {len(prior_names)} + "
                       f"new {nnew} = {expected_size}")

    # ---------------------------------------------------------------- C9 state snapshot
    if not os.path.exists(args.state):
        fail("C9", f"missing short-float state snapshot: {args.state}")
    else:
        st = json.loads(read(args.state))
        if st.get("fire_date") != data.get("fire_date"):
            fail("C9", f"the state snapshot is for {st.get('fire_date')!r} but the artifact is "
                       f"{data.get('fire_date')!r}")
        rp = (cov.get("short_float") or {}).get("rows_passing")
        if st.get("rows_passing") != rp:
            fail("C9", f"the state snapshot holds rows_passing {st.get('rows_passing')} but the artifact "
                       f"publishes {rp}")
        if len(st.get("universe_pct") or {}) != (rp or 0):
            fail("C9", f"the state snapshot holds {len(st.get('universe_pct') or {})} names but the "
                       f"short-float universe passes {rp}")

    # ---------------------------------------------------------------- C10 verdict coherence
    for r in sf:
        v = r.get("tradeable_verdict")
        sp = r.get("short_pct_float")
        if v == "FLOAT_ARTIFACT" and sp is not None and sp <= 100:
            fail("C10", f"short-float row {r.get('ticker')}: FLOAT_ARTIFACT but short% is {sp}")
        if sp is not None and sp > 100 and v != "FLOAT_ARTIFACT":
            fail("C10", f"short-float row {r.get('ticker')}: short% {sp} exceeds float but the verdict "
                        f"is {v} — a float artifact must not be published as tradeable")
        if r.get("squeeze_candidate") == "YES":
            if not (sp is not None and sp > 50 and v == "TRADEABLE"):
                fail("C10", f"short-float row {r.get('ticker')}: squeeze_candidate=YES without "
                            f"short>50% AND a TRADEABLE verdict (short={sp}, verdict={v})")
            if r.get("xcheck_verdict") == "DIVERGES":
                fail("C10", f"short-float row {r.get('ticker')}: squeeze_candidate=YES while the "
                            f"independent source DISPUTES the short position — it must be CONTESTED")
        if r.get("squeeze_candidate") == "CONTESTED" and r.get("xcheck_verdict") != "DIVERGES":
            fail("C10", f"short-float row {r.get('ticker')}: squeeze_candidate=CONTESTED without a "
                        f"disputed cross-check (verdict={r.get('xcheck_verdict')!r})")

    # ---------------------------------------------------------------- the short-float table's columns
    # Column positions are looked up BY HEADER NAME, once, here. A fixed index is a
    # time bomb: adding a column (the cross-check's "Src %Float", 2026-11-19) moved
    # the delta and silently made C15 read the wrong cell.
    sf_display = table_rows(docs["weekly-high-short-float.md"],
                             docs["weekly-high-short-float.md"].splitlines()[0])
    _sf_hdr = next((x for x in sf_display if len(x) > 2 and x[0] == "#" and x[1] == "Ticker"), None)
    _sf_ix = {name: i for i, name in enumerate(_sf_hdr)} if _sf_hdr else {}

    # ---------------------------------------------------------------- C11 no placeholder
    for r in ipo_rows:
        if len(r) >= 10:
            for idx, name in ((6, "days_since_ipo"), (7, "post_lockup"), (8, "mcap_verified"),
                              (9, "tradeable")):
                if r[idx] == "—":
                    fail("C11", f"weekly-ipo.md: row {r[1]} carries a placeholder '—' in the required "
                                f"field {name}")
    if not _sf_hdr:
        fail("C11", "the short-float table has no header row")
    else:
        for r in [x for x in sf_display if x and re.match(r"^\d+$", x[0])]:
            for name in ("Δ vs Prior Wk (pp)", "Tradeable", "Squeeze"):
                if name in _sf_ix and _sf_ix[name] < len(r) and r[_sf_ix[name]] == "—":
                    fail("C11", f"weekly-high-short-float.md: row {r[1]} carries a placeholder '—' in "
                                f"the required field {name}")

    # ---------------------------------------------------------------- C12 dates
    for f, txt in docs.items():
        if f"data_date: {data.get('data_date')}" not in txt:
            fail("C12", f"{f} does not publish data_date {data.get('data_date')}")
        if f"fire_date: {data.get('fire_date')}" not in txt:
            fail("C12", f"{f} does not publish fire_date {data.get('fire_date')}")
        if "snapshot_pulled_at:" not in txt:
            fail("C12", f"{f} does not publish the instant the snapshot was pulled — the "
                        "short-interest numbers are a fact about that instant, not about the week")

    # ---------------------------------------------------------------- C13 source health
    for f, txt in docs.items():
        if "## Source health" not in txt:
            fail("C13", f"{f} has no '## Source health' section")
    sh = data.get("source_health") or []
    if not sh:
        fail("C13", "the JSON companion publishes no source_health entries")
    for e in sh:
        if not e.get("status") or not e.get("source"):
            fail("C13", f"a source_health entry is incomplete: {e}")

    # ---------------------------------------------------------------- C14 reply
    if args.reply and os.path.exists(args.reply):
        reply = read(args.reply)
        sig = section(reply, "### Signal")
        if not sig:
            fail("C14", "the reply has no '### Signal' section")
        for t in (data.get("newly_tagged") or []):
            if t not in reply:
                fail("C14", f"the reply does not name the newly tagged ticker {t}")
        for t in (inter.get("union") or []):
            if t not in reply:
                fail("C14", f"the reply does not name the intersection name {t}")

    # ---------------------------------------------------------------- C16 short-interest cross-check
    # shibui's short-interest ratio depends on a float definition nobody else shares, so the
    # artifact must be cross-checked against an INDEPENDENT short-interest figure (shares),
    # and the block must be published even when the source failed — a missing cross-check
    # that says nothing is a silent failure.
    xc = data.get("short_interest_crosscheck")
    if not isinstance(xc, dict):
        fail("C16", "the JSON companion publishes no short_interest_crosscheck block")
    else:
        st = xc.get("status")
        if st not in SI_STATUSES:
            fail("C16", f"short_interest_crosscheck.status {st!r} is outside {sorted(SI_STATUSES)}")
        if not xc.get("source"):
            fail("C16", "short_interest_crosscheck does not name its source")
        rows_x = xc.get("rows") or []
        for r in rows_x:
            v = r.get("verdict")
            if v not in SI_VERDICTS:
                fail("C16", f"cross-check row {r.get('ticker')}: verdict {v!r} is outside "
                            f"{sorted(SI_VERDICTS)}")
            ratio, si, nsi = r.get("ratio"), r.get("shibui_si_shares"), r.get("nasdaq_si_shares")
            if v == "AGREE":
                if num(ratio) is None:
                    fail("C16", f"cross-check row {r.get('ticker')}: AGREE without a numeric ratio")
                elif not (SI_AGREE_LO <= float(ratio) <= SI_AGREE_HI):
                    fail("C16", f"cross-check row {r.get('ticker')}: AGREE with ratio {ratio}, "
                                f"outside the {SI_AGREE_LO}-{SI_AGREE_HI} band")
            if v == "DIVERGES" and num(ratio) is not None and SI_AGREE_LO <= float(ratio) <= SI_AGREE_HI:
                fail("C16", f"cross-check row {r.get('ticker')}: DIVERGES with ratio {ratio}, "
                            f"inside the {SI_AGREE_LO}-{SI_AGREE_HI} band")
            if num(si) is not None and num(nsi):
                want = round(float(si) / float(nsi), 2)
                if num(ratio) is None or abs(float(ratio) - want) > 0.02:
                    fail("C16", f"cross-check row {r.get('ticker')}: published ratio {ratio!r} != "
                                f"recomputed {want} ({si}/{nsi})")
            sp, npct, gap = r.get("shibui_short_pct_float"), r.get("source_short_pct_float"), r.get("pct_gap_pp")
            if num(sp) is not None and num(npct) is not None:
                wgap = round(float(sp) - float(npct), 1)
                if num(gap) is None or abs(float(gap) - wgap) > 0.11:
                    fail("C16", f"cross-check row {r.get('ticker')}: published gap {gap!r} != "
                                f"recomputed {wgap} ({sp} - {npct})")
        sfm = docs["weekly-high-short-float.md"]
        if "## Short-interest cross-check" not in sfm:
            fail("C16", "weekly-high-short-float.md does not publish the short-interest "
                        "cross-check section")
        else:
            _all = table_rows(sfm, "## Short-interest cross-check")
            _hdr = next((r for r in _all if r and r[0] == "Ticker"), None)
            _vi = _hdr.index("Verdict") if _hdr and "Verdict" in _hdr else None
            if _vi is None:
                fail("C16", "the published cross-check table has no 'Verdict' column")
            mrows = {r[0]: r for r in _all if r and r[0] not in ("Ticker",)}
            if st == "ok":
                for r in rows_x:
                    m = mrows.get(r.get("ticker"))
                    if not m:
                        fail("C16", f"cross-check row {r.get('ticker')} is not in the published table")
                    elif _vi is not None and len(m) > _vi and m[_vi] != r.get("verdict"):
                        fail("C16", f"cross-check row {r.get('ticker')}: the table says {m[8]!r} "
                                    f"and the JSON says {r.get('verdict')!r}")
                if len(mrows) != len(rows_x):
                    fail("C16", f"the published cross-check table has {len(mrows)} rows and the "
                                f"JSON publishes {len(rows_x)}")

    # ---------------------------------------------------------------- C15 delta
    # The week-over-week short-float delta is the whole point of the state series.
    # It is computed against the PRIOR week's snapshot, which is keyed by TICKER.
    # A lookup keyed on the full `TICKER.EXCHANGE` symbol silently yields
    # NO_PRIOR_SNAPSHOT on every row — an artifact that looks complete and says
    # nothing.  This clause recomputes the delta from the prior snapshot.
    prior_state = None
    if args.prior_state and os.path.exists(args.prior_state):
        prior_state = json.loads(read(args.prior_state))
    prior_pct = (prior_state or {}).get("universe_pct") or {}
    by_ticker = {r.get("ticker"): r for r in sf}
    if prior_pct:
        for t, pv in prior_pct.items():
            r = by_ticker.get(t)
            if not r:
                continue  # the name left the universe this week — that is not a delta failure
            want = round((r.get("short_pct_float") or 0) - pv, 1)
            got = r.get("short_float_delta_pp")
            if num(got) is None:
                fail("C15", f"short-float row {t}: it WAS in the prior state snapshot ({pv}%) "
                            f"but the published delta is {got!r} — the delta lookup is keyed on "
                            f"the wrong key, so the week-over-week change is empty")
            elif abs(float(got) - want) > 0.15:
                fail("C15", f"short-float row {t}: published delta {got} != recomputed {want} "
                            f"({r.get('short_pct_float')} - {pv})")
        for t, r in by_ticker.items():
            if t not in prior_pct and num(r.get("short_float_delta_pp")) is not None:
                fail("C15", f"short-float row {t}: it was NOT in the prior snapshot but publishes "
                            f"a delta of {r.get('short_float_delta_pp')!r}")
    elif data.get("prior_state_fire_date"):
        if sf and all(num(r.get("short_float_delta_pp")) is None for r in sf):
            fail("C15", f"the artifact names a prior state snapshot "
                        f"({data.get('prior_state_fire_date')}) but no row carries a "
                        "week-over-week delta — the delta lookup is keyed on the wrong key")
    _di = _sf_ix.get("Δ vs Prior Wk (pp)")
    for cells in [r for r in sf_display if r and re.match(r"^\d+$", r[0])]:
        r = by_ticker.get(cells[1])
        if not r or _di is None or len(cells) <= _di:
            continue
        if cells[_di] != str(r.get("short_float_delta_pp")):
            fail("C15", f"weekly-high-short-float.md row {cells[1]}: the published delta "
                        f"{cells[_di]!r} does not match the JSON companion's "
                        f"{r.get('short_float_delta_pp')!r}")
        _si = _sf_ix.get("Src %Float")
        if _si is not None and len(cells) > _si:
            want = r.get("src_short_pct_float")
            if want is None:
                if cells[_si] != "—":
                    fail("C15", f"weekly-high-short-float.md row {cells[1]}: publishes "
                                f"{cells[_si]!r} for a name the JSON has no cross-checked "
                                f"percentage for")
            elif num(cells[_si]) is None or num(want) is None \
                    or abs(float(num(cells[_si])) - float(num(want))) > 0.11:
                fail("C15", f"weekly-high-short-float.md row {cells[1]}: the published source "
                            f"percentage {cells[_si]!r} does not match the JSON's {want!r}")

    # ---------------------------------------------------------------- C17 the 10-year claim
    # The scan's gate is 1,260 bars (~5 years), so a name can be published as a
    # "1000%-in-10-years" name while its trough is a since-IPO low. The claim is
    # earned by a published field: `ten_year_qualifier` = YES only with 2,500+ bars.
    run_full = json.loads(read(os.path.join(args.md_dir, "peoplewish-backlog-run-full.json")))
    rf_rows = run_full.get("rows_full") or []
    if not rf_rows:
        fail("C17", "the run-full scan publishes no rows")
    for r in rf_rows:
        bars = r.get("bars_10y")
        if num(bars) is None:
            fail("C17", f"scan row {r.get('symbol')}: no bars_10y — the 10-year claim cannot be checked")
            continue
        q = r.get("ten_year_qualifier")
        if q not in ("YES", "NO"):
            fail("C17", f"scan row {r.get('symbol')}: ten_year_qualifier {q!r} is outside ['NO', 'YES']")
        elif (q == "YES") != (float(bars) >= 2500):
            fail("C17", f"scan row {r.get('symbol')}: ten_year_qualifier {q} contradicts "
                        f"bars_10y {bars} (YES needs 2500+)")
        hy = r.get("history_years")
        if num(hy) is None or abs(float(hy) - float(bars) / 252.0) > 0.15:
            fail("C17", f"scan row {r.get('symbol')}: history_years {hy!r} does not match "
                        f"bars_10y {bars}")
    _bl_rows = [r for r in table_rows(docs["peoplewish-backlog.md"],
                                      "## Live re-score of the tagged window") if r and r[0] != "Ticker"]
    _rs = {r.get("ticker"): r for r in (data.get("backlog_live_rescore") or [])}
    for cells in _bl_rows:
        if len(cells) < 12:
            continue
        if cells[11] not in ("YES", "NO"):
            fail("C17", f"the live re-score row {cells[0]} carries the 10y flag {cells[11]!r}, "
                        f"which is outside ['NO', 'YES']")
        if num(cells[10]) is None:
            fail("C17", f"the live re-score row {cells[0]} carries no numeric history "
                        f"({cells[10]!r}) — the 10-year claim must be checkable per name")
        # the table and the JSON companion must agree, or one of them is a copy
        j = _rs.get(cells[0])
        if not j:
            fail("C17", f"the live re-score row {cells[0]} is not in the JSON companion")
            continue
        if j.get("ten_year_qualifier") != cells[11]:
            fail("C17", f"the live re-score row {cells[0]}: the table says {cells[11]!r} and the "
                        f"JSON says {j.get('ten_year_qualifier')!r}")
        if num(j.get("history_years")) is not None and num(cells[10]) is not None \
                and abs(float(cells[10]) - float(j["history_years"])) > 0.11:
            fail("C17", f"the live re-score row {cells[0]}: the table says {cells[10]!r} years "
                        f"and the JSON says {j.get('history_years')!r}")

    # ---------------------------------------------------------------- C18 the sweep basis
    basis = data.get("sweep_basis_data_date")
    if not basis:
        fail("C18", "the artifact publishes no sweep_basis_data_date — the daily-sweep "
                    "intersection is computed against a master.csv whose session is unknown")
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", str(basis)):
        if str(basis) > str(data.get("data_date")):
            fail("C18", f"the sweep basis date {basis} is AFTER the artifact's data date "
                        f"{data.get('data_date')} — the intersection is computed against the future")

    # ---------------------------------------------------------------- C19 the cross-check coverage
    # A cross-check that covers a handful of names is not a cross-check: proven
    # 2026-11-19, a 10-of-138 cross-check passed every other clause. The coverage is
    # a published number with a published floor.
    xc = data.get("short_interest_crosscheck") or {}
    cov_pct = xc.get("coverage_pct")
    floor = xc.get("coverage_floor_pct")
    pub_n = xc.get("published_names")
    cov_n = xc.get("crosschecked_names")
    if xc.get("status") != "ok":
        # The source did not answer: a DISCLOSED degradation, not a failed run. The
        # artifact must say so in words — an unverified screen that reads as a verified
        # one is the failure mode.
        if not data.get("crosscheck_unavailable_reason"):
            fail("C19", "the cross-check source did not answer, but the artifact publishes no "
                        "crosscheck_unavailable_reason — the reader cannot see that the "
                        "short-float numbers are UNVERIFIED")
        if "UNVERIFIED" not in docs["weekly-high-short-float.md"]:
            fail("C19", "the short-float artifact does not say that its numbers are UNVERIFIED "
                        "against a second source")
    elif cov_pct is None or floor is None:
        fail("C19", "the cross-check publishes no coverage_pct / coverage_floor_pct — a "
                    "cross-check of a few names would read as a cross-check of the universe")
    else:
        if num(cov_pct) is None or num(floor) is None:
            fail("C19", f"the cross-check coverage is not numeric (coverage={cov_pct!r}, "
                        f"floor={floor!r})")
        elif float(cov_pct) < float(floor):
            fail("C19", f"the cross-check covers {cov_pct}% of the published universe, below the "
                        f"{floor}% floor — the unverified names are not verified")
        if num(pub_n) is not None and num(cov_n) is not None and num(cov_pct) is not None:
            want = round(100.0 * float(cov_n) / float(pub_n), 1) if float(pub_n) else 0.0
            if abs(float(cov_pct) - want) > 0.11:
                fail("C19", f"the cross-check publishes coverage_pct {cov_pct} but "
                            f"{cov_n}/{pub_n} is {want}")
        rows_x = xc.get("rows") or []
        if num(cov_n) is not None and num(cov_n) != len(rows_x):
            fail("C19", f"the cross-check claims {cov_n} names cross-checked and carries {len(rows_x)}")
        missing = xc.get("not_cross_checked")
        if missing is None:
            fail("C19", "the cross-check does not name the names it did NOT cross-check")
        elif num(pub_n) is not None and num(cov_n) is not None \
                and len(missing) != int(pub_n) - int(cov_n):
            fail("C19", f"the cross-check names {len(missing)} uncross-checked names, but "
                        f"{pub_n} - {cov_n} is {int(pub_n) - int(cov_n)}")
    sfm_txt = docs["weekly-high-short-float.md"]
    if "**Coverage:**" not in sfm_txt:
        fail("C19", "the short-float artifact does not publish the cross-check coverage")

    # ---------------------------------------------------------------- C20 the ranking
    # The table says it is ranked by the independent source's figure. That is a CLAIM
    # about order, and it is checkable: the md's rows must appear in the JSON
    # companion's order.
    basis = data.get("sort_basis")
    if not basis:
        fail("C20", "the artifact publishes no sort_basis — the table's order is undeclared")
    else:
        sfm = docs["weekly-high-short-float.md"]
        if "**Ranking:**" not in sfm:
            fail("C20", "the short-float artifact does not state its ranking basis")
        md_tickers = [c[1] for c in sf_display if c and re.match(r"^\d+$", c[0])]
        json_order = [r["ticker"] for r in (data.get("short_float_rows") or [])]
        shown = [t for t in md_tickers if t in json_order]
        want = [t for t in json_order if t in set(shown)]
        if shown != want:
            fail("C20", "the published table is not in the JSON companion's order — the ranking "
                        f"basis says {basis[:60]!r} but the rows are ordered differently")

    report()


def report():
    print()
    if FAILURES:
        print(f"CONTRACT FAILED — {len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"CONTRACT OK — {CHECKS} checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
check_postmarket_brief.py — assert the cron #23 post-market brief artifact contract.

Do not eyeball it. The 2026-11-03 and 2026-11-04 artifacts were mechanically correct and
reader-hostile: the most valuable content in the brief ("Tomorrow's setup") sat at section
9 of 10 in a brief whose whole job is to set up tomorrow; the after-hours movers were
published as a percentage with no level, so a reader could not act on "ANET +9.47% AH";
the single best sentence in the brief (the 63bp cap-weight penalty, "the index was green
but the median stock was not") was buried in the second paragraph instead of being a named
metric; and the chat reply had no "tomorrow" line at all.

This script turns those four defects into machine assertions, so a run that breaks the
contract FAILS instead of shipping. The 2026-11-03 artifact looked fine and failed them.

USAGE
    python3 check_postmarket_brief.py --artifact daily-briefs/<date>-post-market.md \
                                       [--reply /workspace/reply.txt]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).

The contract lives in the routine's skill spec, which is fetched at RUN time:
    cloud-prompts/skills/agentic-post-market-brief/SKILL.md  §5
"""

import argparse
import re
import sys

CONTRACT_VERSION = "postmkt-artifact-v2"

# --------------------------------------------------------------------------------------
# The section spine (§5.3). Matched by NORMALIZED prefix so a dated or annotated heading
# ("## Tomorrow's setup — Friday, 6 November 2026") still satisfies it.
# --------------------------------------------------------------------------------------
REQUIRED_H2 = [
    "tldr",
    "tomorrowssetup",
    "daystape",
    "sectorrotation",
    "afterhoursmovers",
    "afterhoursearningsreactions",
    "openresearchqueue",
    "sourcehealth",
    "methodnotes",
]

# The H3s under "## Tomorrow's setup" (§5.3), in order.
SETUP_H3 = [
    "futuresandtheovernightsetup",
    "economiccalendar",
    "earningscalendar",
    "newstowatchforthetopmovers",
    "tomorrowsthreethingstowatch",
]

# The six participation metrics (§5.5) — these exact row labels must exist.
MARKET_READ_ROWS = [
    "advancers",
    "decliners",
    "unchanged",
    "mediannamemovepct",
    "capweightpenaltybp",
    "liquidadvdecratio",
]

# The tokens the TL;DR must name (§5.5).
TLDR_REQUIRED_TOKENS = [
    "cap_weight_penalty_bp",
    "liquid_adv_dec_ratio",
    "median_name_move_pct",
]
TLDR_REQUIRED_WORDS = ["advancers", "decliners"]

# The after-hours movers table columns (§5.7) — exact header names.
AH_COLUMNS = [
    "ticker",
    "priorclose",
    "ahlast",
    "ahhigh",
    "ahlow",
    "ahvolume",
    "gappct",
    "ahrangepct",
    "gapfilllevel",
]

# --------------------------------------------------------------------------------------
# Ticker detection for the reply rules (§5.8)
# --------------------------------------------------------------------------------------
# All-caps tokens of 1-5 letters that are NOT tickers. Without this list "ET", "AH" and
# "AMC" would read as tickers and every bullet would trip the one-ticker rule.
NON_TICKERS = set("""
A B C D E F G H I J K L M N O P Q R S T U V W X Y Z
AD AH AM AM AN AO AP AR AS AT AU AV AW AX AY AZ
BA BB BE BI BK BL BM BN BO BP BQ BR BS BT BU BV BW BX BY BZ
CA CB CC CD CE CF CG CH CI CJ CK CL CM CN CO CP CQ CR CS CT CU CV CW CX CY CZ
DA DB DC DD DE DF DG DH DI DJ DK DL DM DN DO DP DQ DR DS DT DU DV DW DX DY DZ
EA EB EC ED EE EF EG EH EI EJ EK EL EM EN EO EP EQ ER ES ET EU EV EW EX EY EZ
FA FB FC FD FE FF FG FH FI FJ FK FL FM FN FO FP FQ FR FS FT FU FV FW FX FY FZ
GA GB GC GD GE GF GG GH GI GJ GK GL GM GN GO GP GQ GR GS GT GU GV GW GX GY GZ
HA HB HC HD HE HF HG HH HI HJ HK HL HM HN HO HP HQ HR HS HT HU HV HW HX HY HZ
IA IB IC ID IE IF IG IH II IJ IK IL IM IN IO IP IQ IR IS IT IU IV IW IX IY IZ
JA JB JC JD JE JF JG JH JI JJ JK JL JM JN JO JP JQ JR JS JT JU JV JW JX JY JZ
KA KB KC KD KE KF KG KH KI KJ KK KL KM KN KO KP KQ KR KS KT KU KV KW KX KY KZ
LA LB LC LD LE LF LG LH LI LJ LK LL LM LN LO LP LQ LR LS LT LU LV LW LX LY LZ
MA MB MC MD ME MF MG MH MI MJ MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NB NC ND NE NF NG NH NI NJ NK NL NM NN NO NP NQ NR NS NT NU NV NW NX NY NZ
OA OB OC OD OE OF OG OH OI OJ OK OL OM ON OO OP OQ OR OS OT OU OV OW OX OY OZ
PA PB PC PD PE PF PG PH PI PJ PK PL PM PN PO PP PQ PR PS PT PU PV PW PX PY PZ
QA QB QC QD QE QF QG QH QI QJ QK QL QM QN QO QP QQ QR QS QT QU QV QW QX QY QZ
RA RB RC RD RE RF RG RH RI RJ RK RL RM RN RO RP RQ RR RS RT RU RV RW RX RY RZ
SA SB SC SD SE SF SG SH SI SJ SK SL SM SN SO SP SQ SR SS ST SU SV SW SX SY SZ
TA TB TC TD TE TF TG TH TI TJ TK TL TM TN TO TP TQ TR TS TT TU TV TW TX TY TZ
UA UB UC UD UE UF UG UH UI UJ UK UL UM UN UO UP UQ UR US UT UU UV UW UX UY UZ
VA VB VC VD VE VF VG VH VI VJ VK VL VM VN VO VP VQ VR VS VT VU VV VW VX VY VZ
WA WB WC WD WE WF WG WH WI WJ WK WL WM WN WO WP WQ WR WS WT WU WV WW WX WY WZ
XA XB XC XD XE XF XG XH XI XJ XK XL XM XN XO XP XQ XR XS XT XU XV XW XX XY XZ
YA YB YC YD YE YF YG YH YI YJ YK YL YM YN YO YP YQ YR YS YT YU YV YW YX YY YZ
ZA ZB ZC ZD ZE ZF ZG ZH ZI ZJ ZK ZL ZM ZN ZO ZP ZQ ZR ZS ZT ZU ZV ZW ZX ZY ZZ
AD AH AMC AM AP AR AS AT AU AV AW AX AY AZ
AI AMC AMT APR APRIL AUG BEAR BULL BPS BUY CASH CATALYST CFTC CLOSE CONS CPI
CSM DAILY DEC DEEP DECL DEF DIAM DOWN DRR DUP EAST EBITDA EPS EST ETF ETFS
EVEN EX EXP FED FOMC FRIDAY GAAP GAP GDP GMT GUID GUIDANCE HALT HIGH HOLD HOUR
IPO ISM IV JPM JUN JUL LHS LIQ LIQUID LOW MA MAY MORNING MOVE NASDAQ NASDAQ100
NFP NIKKEI NO NYSE OCT OHM OHLC OPEN OPTS OPTIONS PC PE PMI PPO POST PRE PRICE
PRIOR PT PUT PWR RANGE READ REFL REITS REV RICH RISK RUMOR SB SELL SENT SEP
SELL SHORT SIDE SOLD SPOT SPX STOP TAPE THIN THOUS TICK TICKER TIME TON TOMORROW
TUES TUE UP USD VIX VXN VOLUME WATCH YIELD YOY YTD ZONE
""".split())

TICKER_RE = re.compile(r"(?<![A-Za-z0-9$.])[A-Z]{1,5}(?![A-Za-z0-9])")
# A tradable level: a price with at least two decimals, optionally $-prefixed.
LEVEL_RE = re.compile(r"(?<![\w.])\$?\d{1,7}\.\d{2,}(?![\w])")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def norm(text: str) -> str:
    """Normalize a heading or label for matching: lowercase, alphanumerics only.

    "TL;DR" -> "tldr", "Tomorrow's setup — Friday, 6 November 2026" -> "tomorrowssetupfriday6november2026",
    "median_name_move_pct" -> "mediannamemovepct". Spaces and punctuation are dropped so a
    heading matches regardless of how it is punctuated.
    """
    return re.sub(r"[^a-z0-9]+", "", text.strip().lower())


def parse_frontmatter(md: str):
    """Return the front-matter mapping (or {} when there is none)."""
    if not md.startswith("---"):
        return {}
    lines = md.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm = {}
    for line in lines[1:end]:
        if ":" in line and not line.strip().startswith("#"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def headings(md: str, level: int):
    """[(normalized_text, raw_text, line_index)] for every heading of the given level."""
    out = []
    for i, line in enumerate(md.splitlines()):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and len(m.group(1)) == level:
            out.append((norm(m.group(2)), m.group(2).strip(), i))
    return out


def section_body(md: str, start_line: int, stop_line: int) -> str:
    return "\n".join(md.splitlines()[start_line + 1:stop_line])


def next_heading_line(md: str, after_line: int):
    """The line of the next heading of ANY level (1-3) after `after_line`, or EOF."""
    lines = md.splitlines()
    for i in range(after_line + 1, len(lines)):
        m = re.match(r"^(#{1,3})\s+", lines[i])
        if m:
            return i
    return len(lines)


def find_heading(hs, prefix):
    """The heading whose normalized text starts with `prefix` (or contains it)."""
    exact = [h for h in hs if h[0] == prefix or h[0].startswith(prefix + " ")]
    if exact:
        return exact[0]
    loose = [h for h in hs if prefix in h[0]]
    return loose[0] if loose else None


def tables(md: str):
    """Every markdown table in the text as (header_cells, [row_cells], start_line, end_line)."""
    lines = md.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            block = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append((j, lines[j]))
                j += 1
            if len(block) >= 2:
                cells = []
                for _, raw in block:
                    parts = [c.strip() for c in raw.strip().strip("|").split("|")]
                    cells.append(parts)
                if cells[1] and all(set(c) <= set("-: ") for c in cells[1]):
                    header = cells[0]
                    rows = cells[2:]
                    out.append((header, rows, block[0][0], block[-1][0]))
            i = j
        else:
            i += 1
    return out


def bullets(text: str):
    """The bullet lines of a block (markdown '-' or '*' bullets), stripped of markers."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            out.append(s[2:].strip())
    return out


def tickers_in(text: str):
    """The ticker-looking tokens of a line, with the non-ticker vocabulary removed."""
    found = []
    for m in TICKER_RE.finditer(text):
        tok = m.group(0)
        if tok in NON_TICKERS:
            continue
        found.append(tok)
    return found


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------
def check_artifact(md, fails):
    fm = parse_frontmatter(md)

    # --- §5.2 the marker -------------------------------------------------------------
    if fm.get("contract") != CONTRACT_VERSION:
        fails.append(
            "front matter: missing or wrong contract marker "
            f"(expected `contract: {CONTRACT_VERSION}`, got {fm.get('contract')!r})"
        )

    h2 = headings(md, 2)
    h3 = headings(md, 3)

    # --- §5.3 the spine --------------------------------------------------------------
    if not h2:
        fails.append("artifact: no `##` headings at all")
        return

    positions = []
    for req in REQUIRED_H2:
        hit = find_heading(h2, req)
        if hit is None:
            fails.append(f"artifact: missing required section `## {req}`")
            positions.append(None)
        else:
            positions.append(hit[2])

    known = [p for p in positions if p is not None]
    if known != sorted(known):
        order = ", ".join(
            f"## {r}" for r, p in zip(REQUIRED_H2, positions) if p is not None
        )
        fails.append(
            "artifact: the section spine is out of order — expected "
            "TL;DR -> Tomorrow's setup -> Day's tape -> Sector rotation -> "
            "After-hours movers -> After-hours earnings reactions -> "
            "Open research queue -> Source health -> Method notes "
            f"(found: {order})"
        )

    extra = [h[1] for h in h2
             if not any(h[0].startswith(r) for r in REQUIRED_H2)]
    if extra:
        fails.append(
            "artifact: unexpected `##` section(s) "
            + "; ".join(repr(e) for e in extra)
            + " — fold them into the nearest required section as an `###` subsection"
        )

    # --- §5.3 Tomorrow's setup must precede Day's tape --------------------------------
    setup = find_heading(h2, "tomorrowssetup")
    tape = find_heading(h2, "daystape")
    if setup and tape and setup[2] > tape[2]:
        fails.append(
            "artifact: `## Tomorrow's setup` must come BEFORE `## Day's tape` "
            "(this brief's product is tomorrow; the 2026-11-03 brief buried it at section 9 of 10)"
        )

    def body_of(h2_head, child_level=None):
        """The text between an H2 and the next H2 (or H1), optionally up to an H3."""
        if h2_head is None:
            return ""
        start = h2_head[2]
        end = len(md.splitlines())
        for h in h2:
            if h[2] > start:
                end = h[2]
                break
        return "\n".join(md.splitlines()[start + 1:end])

    setup_body = body_of(setup)
    tape_body = body_of(tape)

    # --- §5.3/§5.4 the setup H3s -----------------------------------------------------
    if setup is not None:
        setup_h3 = []
        for h in h3:
            if setup[2] < h[2] and (tape is None or h[2] < tape[2]):
                setup_h3.append(h)
        for req in SETUP_H3:
            if not any(h[0].startswith(req) or req in h[0] for h in setup_h3):
                fails.append(
                    f"artifact: `## Tomorrow's setup` is missing the subsection "
                    f"`### {req}`"
                )

        three = None
        for h in setup_h3:
            if h[0].startswith("tomorrowsthreethingstowatch"):
                three = h
                break
        if three is not None:
            end = next_heading_line(md, three[2])
            bl = bullets("\n".join(md.splitlines()[three[2] + 1:end]))
            if len(bl) != 3:
                fails.append(
                    "artifact: `### Tomorrow's three things to watch` must carry exactly "
                    f"3 bullets (found {len(bl)})"
                )
            for b in bl:
                tk = tickers_in(b)
                if len(tk) != 1:
                    fails.append(
                        "artifact: `### Tomorrow's three things to watch` bullet must name "
                        f"exactly ONE ticker (found {len(tk)}: {tk}) — {b[:90]!r}"
                    )
                if not LEVEL_RE.search(b):
                    fails.append(
                        "artifact: `### Tomorrow's three things to watch` bullet must carry a "
                        f"LEVEL (a price) — {b[:90]!r}"
                    )

    # --- §5.5 the market read ---------------------------------------------------------
    if tape is not None:
        mr = None
        for h in h3:
            if "marketread" in h[0] and (setup is None or h[2] > setup[2]) and \
               (tape[2] < h[2]):
                mr = h
                break
        mr_body = ""
        if mr is not None:
            end = next_heading_line(md, mr[2])
            mr_body = "\n".join(md.splitlines()[mr[2] + 1:end])
        else:
            fails.append("artifact: `## Day's tape` is missing the `### Market read` subsection")

        mr_tables = tables(mr_body)
        if not mr_tables:
            fails.append("artifact: `### Market read` has no table")
        else:
            # The metrics table is the one carrying the most named metrics — a section may
            # legitimately hold more than one table.
            def _score(t):
                labels = [norm(c[0]) for c in t[1] if c]
                return sum(1 for r in MARKET_READ_ROWS
                           if any(l == r or l.startswith(r) for l in labels))

            header, rows, _, _ = max(mr_tables, key=_score)
            labels = [norm(c[0]) for c in rows if c]
            for req in MARKET_READ_ROWS:
                if not any(l == req or l.startswith(req) for l in labels):
                    fails.append(
                        f"artifact: market-read table is missing the `{req}` row "
                        "(the participation read must be a NAMED metric, not a statistic "
                        "buried in a paragraph)"
                    )
            for c in rows:
                if not c or not c[0].strip():
                    continue
                if len(c) < 2 or not c[1].strip():
                    fails.append(
                        f"artifact: market-read row {c[0]!r} has an empty value cell"
                    )

    # --- §5.6 the cap-weight penalty history ------------------------------------------
    cw_tables = []
    for header, rows, _, _ in tables(tape_body):
        if any("capweightpenaltybp" in norm(c) for c in header):
            cw_tables.append((header, rows))
    if not cw_tables:
        fails.append(
            "artifact: no cap-weight history table — publish `cap_weight_penalty_bp` with a "
            "5-session history (header must carry `cap_weight_penalty_bp`)"
        )
    else:
        header, rows = max(cw_tables, key=lambda t: len(t[1]))
        dated = [r for r in rows if r and DATE_RE.match(r[0].strip())]
        if len(dated) < 5:
            fails.append(
                f"artifact: the cap-weight penalty history needs at least 5 dated sessions "
                f"(found {len(dated)})"
            )

    # --- §5.7 the after-hours levels --------------------------------------------------
    ah = find_heading(h2, "afterhoursmovers")
    ah_body = body_of(ah)
    ah_tables = tables(ah_body)
    # A movers table is one whose header names a ticker or an after-hours field. EVERY such
    # table must carry the full level set — a section that splits the names into a gainers
    # table and a losers table must carry the levels on BOTH.
    mover_tables = [t for t in ah_tables
                    if any("ticker" in norm(c) or "ahlast" in norm(c) for c in t[0])]
    if not mover_tables:
        fails.append("artifact: `## After-hours movers` has no movers table")
    for header, rows, _, _ in mover_tables:
        hnorm = [norm(c) for c in header]
        for col in AH_COLUMNS:
            if not any(h == col or h.startswith(col) or col in h for h in hnorm):
                fails.append(
                    f"artifact: after-hours movers table is missing the `{col}` column — "
                    "a percentage without a level is not actionable"
                )
        if not rows:
            fails.append("artifact: after-hours movers table has no rows")
        for r in rows:
            if not r or not r[0].strip():
                continue
            for idx, col in enumerate(AH_COLUMNS):
                if idx >= len(r) or not r[idx].strip():
                    fails.append(
                        f"artifact: after-hours row {r[0]!r} has an empty `{col}` cell — "
                        "publish `n/a` if the field was unavailable, never a blank"
                    )
                    break

    # --- §5.3 the open research queue --------------------------------------------------
    orq = find_heading(h2, "openresearchqueue")
    if orq is not None:
        body = body_of(orq)
        items = [l.strip() for l in body.splitlines()
                 if re.match(r"^\s*(\d+[.)]|[-*])\s+", l)]
        if len(items) < 1:
            fails.append("artifact: `## Open research queue` has no items — keep it")

    # --- §5.5 the TL;DR names the participation metrics --------------------------------
    tldr = find_heading(h2, "tldr")
    if tldr is not None:
        body = body_of(tldr)
        for tok in TLDR_REQUIRED_TOKENS:
            if tok not in body:
                fails.append(
                    f"artifact: the TL;DR must name the metric `{tok}` — the participation read "
                    "belongs in the first paragraph, not the second"
                )
        low = body.lower()
        for w in TLDR_REQUIRED_WORDS:
            if w not in low:
                fails.append(f"artifact: the TL;DR must name the metric `{w}`")


def check_reply(reply, fails):
    if "### Signal\n\n" not in reply:
        fails.append(
            "reply: `### Signal` must stand alone on its own line followed by a blank line "
            "(the emitted string must contain '### Signal\\n\\n')"
        )

    # one ticker per bullet under ### Signal
    lines = reply.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip().startswith("### Signal"))
    except StopIteration:
        start = None
    if start is not None:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].strip().startswith("### "):
                end = i
                break
        for b in bullets("\n".join(lines[start + 1:end])):
            tk = tickers_in(b)
            if len(tk) > 1:
                fails.append(
                    f"reply: a `### Signal` bullet carries {len(tk)} tickers ({', '.join(tk)}) — "
                    "ONE ticker per line"
                )

    # tomorrow's three things to watch
    m = re.search(r"(?im)^###\s+.*tomorrow'?s three things to watch.*$", reply)
    if not m:
        fails.append(
            "reply: missing the `### Tomorrow's three things to watch` section — it is what a "
            "reader opens a 22:30 brief to get"
        )
    else:
        tail = reply[m.end():]
        nxt = re.search(r"(?m)^###\s+", tail)
        block = tail[: nxt.start()] if nxt else tail
        bl = bullets(block)
        if len(bl) != 3:
            fails.append(
                f"reply: `### Tomorrow's three things to watch` must carry exactly 3 bullets "
                f"(found {len(bl)})"
            )
        for b in bl:
            tk = tickers_in(b)
            if len(tk) != 1:
                fails.append(
                    f"reply: a 'three things to watch' bullet must name exactly ONE ticker "
                    f"(found {len(tk)}: {tk}) — {b[:90]!r}"
                )
            if not LEVEL_RE.search(b):
                fails.append(
                    f"reply: a 'three things to watch' bullet must carry a LEVEL (a price) — "
                    f"{b[:90]!r}"
                )

    if not re.search(r"(?i)open research|research queue", reply):
        fails.append(
            "reply: carry the top item of the artifact's open research queue into the reply"
        )

    for head in ("### Method & caveats", "### Files", "### Push / errors"):
        if head not in reply:
            fails.append(f"reply: missing the `{head}` section of the house reply format")


def main():
    ap = argparse.ArgumentParser(description="assert the cron #23 post-market brief contract")
    ap.add_argument("--artifact", required=True, help="path to the post-market markdown artifact")
    ap.add_argument("--reply", help="path to the saved final chat reply")
    args = ap.parse_args()

    fails = []

    try:
        with open(args.artifact, encoding="utf-8") as fh:
            md = fh.read()
    except OSError as exc:
        print(f"FAIL: cannot read artifact {args.artifact}: {exc}")
        return 1

    check_artifact(md, fails)

    if args.reply:
        try:
            with open(args.reply, encoding="utf-8") as fh:
                reply = fh.read()
        except OSError as exc:
            print(f"FAIL: cannot read reply {args.reply}: {exc}")
            return 1
        check_reply(reply, fails)

    if fails:
        print(f"CONTRACT {CONTRACT_VERSION}: {len(fails)} FAIL")
        for f in fails:
            print(f"  FAIL: {f}")
        return 1

    print(f"CONTRACT {CONTRACT_VERSION}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

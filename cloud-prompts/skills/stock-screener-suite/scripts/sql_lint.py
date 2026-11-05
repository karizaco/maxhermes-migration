#!/usr/bin/env python3
"""Offline structural lint for the SQL this skill emits.

Why this exists
---------------
Five defects shipped in `scripts/screen.py` and were only found by running the
queries against the live database. Three failed loudly (syntax / binder
errors) but two were silent:

  * the Qullamägi RS screen's lookback window was shorter than the
    `LAG(close, 252)` it needs, so the entire RS book came back EMPTY with no
    error — indistinguishable from a quiet tape;
  * a `UNION ALL` takes its output column names from the FIRST branch, so the
    EP9M branch published its close-location value under the header `chg_pct`
    and the Anticipation branch published trend-intensity under `volume`.

The database is not always reachable: shibui rate-limits (HTTP 429 with a
`retry-after`), so a guard that only works live is a guard that does not
always run. This module checks the SQL's *shape* with no database and no
third-party dependency, so it can run in CI, in a cron, or on a laptop.

What it checks
--------------
  L001  CTE list separator missing (DuckDB syntax error)
  L002  UNION ALL branches have different column counts (binder error)
  L003  UNION ALL branches have different column NAMES (silent corruption)
  L004  an identifier is used that no column or alias defines (binder error)
  L005  a LAG/LEAD offset is wider than the query's own lookback window
  L006  a top-level SELECT without a LIMIT (shibui rejects >200 rows)
  L007  division by a column without NULLIF() (shibui returns inf/NaN)
  L008  date arithmetic on a bare string literal (DuckDB ambiguity error)
  L009  a CTE carries a per-branch LIMIT smaller than the outer cap (silent
        truncation: the query succeeds, the book is cut, every count still
        looks plausible)

Usage
-----
    python scripts/sql_lint.py --emitted --date 2026-10-27   # lint screen.py's own emitters
    python scripts/sql_lint.py path/to/query.sql --date 2026-10-27
    from sql_lint import lint_sql; issues = lint_sql(sql, "2026-10-27")
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# shibui schema ground truth (from the shibui schema doc).
# Used to tell a real column apart from a typo'd alias.
# --------------------------------------------------------------------------
STOCK_QUOTES_COLUMNS = {
    "symbol", "ticker", "date", "open", "high", "low", "close", "volume",
    "exchange", "currency", "country_iso",
}
TECHNICAL_INDICATOR_COLUMNS = {
    "symbol", "ticker", "date", "exchange",
    # trend
    "sma_20", "sma_50", "sma_200", "ema_9", "ema_21", "ema_50", "ema_200",
    "wma_10", "dema_30", "tema_30", "kama_30", "trima_30",
    # momentum
    "rsi_14", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d",
    "cci_20", "willr_14", "roc_10", "mom_10", "ppo", "trix_30", "ultosc",
    # strength
    "adx_14", "plus_di_14", "minus_di_14", "aroon_up_25", "aroon_down_25",
    "aroonosc_25",
    # volatility
    "atr_14", "bb_upper", "bb_middle", "bb_lower",
    # volume
    "volume_ma_20", "obv", "mfi_14", "cmf_20",
    # patterns
    "cdl_engulfing", "cdl_hammer", "cdl_doji", "cdl_harami", "cdl_morningstar",
    "cdl_eveningstar", "cdl_shootingstar", "cdl_2crows", "cdl_3blackcrows",
    "cdl_3whitesoldiers", "cdl_hangingman", "cdl_spinningtop", "cdl_marubozu",
    "cdl_invertedhammer", "cdl_dragonflydoji",
    # statistical / reversal
    "beta_5", "correl_30", "linearreg_14", "linearreg_slope_14", "stddev_5",
    "var_5", "sar",
}
VALUATION_COLUMNS = {
    "symbol", "ticker", "date", "exchange", "market_cap", "enterprise_value",
    "price_to_book",
}
GENERAL_INFO_COLUMNS = {
    "symbol", "ticker", "name", "type", "exchange", "country_iso", "country_name",
    "currency", "gics_sector", "gics_industry_group", "gics_industry",
    "gics_sub_industry", "sic_code", "sic_sector", "sic_industry",
    "description", "cik", "filer_category", "is_smaller_reporting",
    "is_emerging_growth",
    # verified live 2026-11-03 - the IPO screen reads ipo_date from here
    "ipo_date", "isin", "fiscal_year_end", "full_time_employees", "location",
    "company_website", "sec_filing_website", "phone", "logo_url",
    "reporting_currency", "has_company_details",
}
OWNERSHIP_STATS_COLUMNS = {
    "symbol", "ticker", "exchange", "percent_insiders", "percent_institutions",
    "shares_float", "short_percent_float",
}
FUNDAMENTALS_QUARTERLY_COLUMNS = {
    "symbol", "ticker", "date", "exchange", "eps_growth_yoy", "revenue_growth_yoy",
    "fcf_growth_yoy", "trailing_pe", "price_to_sales", "forward_pe", "forward_peg",
    "trailing_revenue_peg", "earnings_yield", "dividend_yield", "payout_ratio",
    "operating_pe", "free_cash_flow_yield", "price_to_cash_flow", "ev_ebit",
    "ev_ebitda", "revenue_per_share", "eps_actual", "eps_estimate",
}
BASE_COLUMNS = (
    STOCK_QUOTES_COLUMNS
    | TECHNICAL_INDICATOR_COLUMNS
    | VALUATION_COLUMNS
    | GENERAL_INFO_COLUMNS
    | OWNERSHIP_STATS_COLUMNS
    | FUNDAMENTALS_QUARTERLY_COLUMNS
)

SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "null", "is", "as", "on",
    "join", "left", "right", "inner", "outer", "full", "cross", "with",
    "recursive", "group", "by", "order", "having", "limit", "offset", "union",
    "all", "distinct", "case", "when", "then", "else", "end", "qualify",
    "window", "partition", "over", "rows", "range", "preceding", "following",
    "unbounded", "current", "row", "asc", "desc", "using", "filter", "cast",
    "interval", "date", "between", "in", "exists", "any", "some", "coalesce", "current_date",
    "true", "false", "select", "values", "insert", "update", "delete",
}
SQL_FUNCTIONS = {
    "lag", "lead", "row_number", "rank", "dense_rank", "sum", "avg", "count",
    "min", "max", "median", "stddev", "variance", "nullif", "coalesce", "current_date",
    "greatest", "least", "abs", "round", "floor", "ceil", "sqrt", "pow",
    "length", "lower", "upper", "trim", "substr", "concat", "strftime",
    "date_trunc", "extract", "year", "month", "day", "row", "unnest", "list_value",
    "first", "last", "list", "arg_max", "arg_min", "bool_and", "bool_or",
    "count_if", "any_value", "ifnull", "iif", "try_cast",
}

# US market holidays per year are not modelled; this allowance keeps the
# session estimate on the conservative side.
HOLIDAYS_PER_YEAR = 10


@dataclass
class Issue:
    severity: str
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.severity:<5} {self.code}  {self.message}"


@dataclass
class _Cte:
    name: str
    body: str
    select_items: list[str] = field(default_factory=list)
    # Character span of the CTE body in the ORIGINAL sql string. strip_comments
    # and mask_literals both preserve offsets, so the span is valid in every
    # representation of the query.
    start: int = -1
    end: int = -1


# --------------------------------------------------------------------------
# lexical helpers
# --------------------------------------------------------------------------
def strip_comments(sql: str) -> str:
    """Remove -- line comments and /* */ block comments, preserving offsets."""
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def mask_literals(sql: str) -> str:
    """Blank out string literals (keeping offsets) so regexes cannot match them."""
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in "'\"":
            quote = ch
            j = i + 1
            while j < n:
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            for k in range(i, min(j + 1, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(out)


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` at paren depth 0, ignoring separators inside strings."""
    masked = mask_literals(text)
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(masked):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _match_paren(s: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at open_idx (or -1)."""
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def alias_of(item: str) -> str | None:
    """The output column name of a select item, or None when it is positional."""
    text = item.strip()
    m = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", text, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return text
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", text):
        return text.split(".")[-1]
    return None


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def parse_ctes(sql: str) -> tuple[list[_Cte], list[Issue]]:
    """Parse the WITH list. Reports a missing separator as L001."""
    issues: list[Issue] = []
    stripped = strip_comments(sql)
    masked = mask_literals(stripped)
    m = re.search(r"\bWITH\b", masked, re.I)
    if not m:
        return [], issues
    ctes: list[_Cte] = []
    i = m.end()
    while i < len(masked):
        while i < len(masked) and masked[i] in " \t\r\n,":
            i += 1
        nm = re.match(r"[A-Za-z_][A-Za-z0-9_]*", masked[i:])
        if not nm:
            break
        name = nm.group(0)
        j = i + nm.end()
        while j < len(masked) and masked[j] in " \t\r\n":
            j += 1
        if not re.match(r"AS\b", masked[j:], re.I):
            break
        j += 2
        while j < len(masked) and masked[j] in " \t\r\n":
            j += 1
        if j >= len(masked) or masked[j] != "(":
            break
        close = _match_paren(masked, j)
        if close == -1:
            break
        body = stripped[j + 1:close]
        ctes.append(_Cte(
            name=name,
            body=body,
            select_items=select_items(body),
            start=j + 1,
            end=close,
        ))
        i = close + 1
        k = i
        while k < len(masked) and masked[k] in " \t\r\n":
            k += 1
        if k < len(masked) and masked[k] == ",":
            i = k + 1
            continue
        # A name followed by AS ( here means the CTE list is missing a comma.
        nxt = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", masked[k:], re.I)
        if nxt:
            issues.append(Issue(
                "ERROR", "L001",
                f"CTE list: missing ',' before '{nxt.group(1)} AS (' — DuckDB reports "
                f"'syntax error at or near {nxt.group(1)}'",
            ))
            i = k
            continue
        break
    return ctes, issues


def select_items(body: str) -> list[str]:
    """The select list of a CTE body (the outer SELECT)."""
    masked = mask_literals(strip_comments(body))
    m = re.search(r"\bSELECT\b", masked, re.I)
    if not m:
        return []
    i = m.end()
    depth = 0
    j = i
    while j < len(masked):
        ch = masked[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and re.match(r"\bFROM\b", masked[j:], re.I):
            break
        j += 1
    return [p for p in split_top_level(body[i:j]) if p.strip()]


def union_chains(sql: str) -> list[list[str]]:
    """Top-level `SELECT * FROM a UNION ALL SELECT * FROM b ...` chains."""
    masked = mask_literals(strip_comments(sql))
    pat = re.compile(r"SELECT\s+\*\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
    matches = list(pat.finditer(masked))
    chains: list[list[str]] = []
    cur: list = []
    for m in matches:
        if cur:
            between = masked[cur[-1].end():m.start()]
            if re.search(r"UNION\s+ALL", between, re.I):
                cur.append(m)
                continue
            chains.append([x.group(1) for x in cur])
        cur = [m]
    if cur:
        chains.append([x.group(1) for x in cur])
    return chains


def _defined_identifiers(cte: _Cte, by_name: dict[str, "_Cte"] | None = None) -> set[str]:
    """Aliases + base columns visible inside one CTE.

    A CTE sees its own output aliases, the output aliases of any CTE it reads
    FROM/JOIN, and the base columns of the tables it touches.
    """
    names: set[str] = set()
    for item in cte.select_items:
        a = alias_of(item)
        if a:
            names.add(a.lower())
    # nested CTEs declared inside this body
    nested, _ = parse_ctes(cte.body)
    for n in nested:
        for item in n.select_items:
            a = alias_of(item)
            if a:
                names.add(a.lower())
    # aliases of sibling CTEs this one reads from
    if by_name:
        body_masked = mask_literals(strip_comments(cte.body))
        for ref in re.finditer(
            r"\b(?:FROM|JOIN)\s+(?:shibui\.)?([A-Za-z_][A-Za-z0-9_]*)", body_masked, re.I
        ):
            other = by_name.get(ref.group(1).lower())
            if other is None or other is cte:
                continue
            for item in other.select_items:
                a = alias_of(item)
                if a:
                    names.add(a.lower())
    # named windows (WINDOW w AS (...)) are not columns
    for wm in re.finditer(
        r"\bWINDOW\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS", mask_literals(strip_comments(cte.body)), re.I
    ):
        names.add(wm.group(1).lower())
    names |= {c.lower() for c in BASE_COLUMNS}
    return names


def _used_identifiers(text: str) -> set[str]:
    """Bare identifiers appearing in an expression (not keywords/functions)."""
    masked = mask_literals(strip_comments(text))
    found = set()
    for tok in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", masked):
        w = tok.group(0).lower()
        if w in SQL_KEYWORDS or w in SQL_FUNCTIONS:
            continue
        found.add(w)
    return found


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def _business_days(start: _dt.date, end: _dt.date) -> int:
    """Weekdays between two dates, minus a holiday allowance."""
    if end <= start:
        return 0
    days = 0
    d = start
    while d < end:
        if d.weekday() < 5:
            days += 1
        d += _dt.timedelta(days=1)
    years = (end - start).days / 365.25
    return max(0, int(days - HOLIDAYS_PER_YEAR * years))


def _window_start(sql: str) -> tuple[_dt.date | None, str]:
    """Earliest date the query can read, and a human label for it.

    Searches the comment-stripped but UNMASKED text: the date literals are the
    very thing being looked for, so they must not be blanked out.
    """
    starts: list[tuple[_dt.date, str]] = []
    plain = strip_comments(sql)
    # DATE '2026-01-01' - INTERVAL '430 days'
    for m in re.finditer(
        r"DATE\s*'([0-9]{4}-[0-9]{2}-[0-9]{2})'\s*-\s*INTERVAL\s*'(\d+)\s+days?'",
        plain, re.I,
    ):
        base = _dt.date.fromisoformat(m.group(1))
        days = int(m.group(2))
        starts.append((base - _dt.timedelta(days=days), f"DATE '{m.group(1)}' - {days} days"))
    # q.date >= '2025-12-01'
    for m in re.finditer(
        r"\bdate\s*(?:>=|>)\s*'([0-9]{4}-[0-9]{2}-[0-9]{2})'", plain, re.I
    ):
        starts.append((_dt.date.fromisoformat(m.group(1)), f"date >= '{m.group(1)}'"))
    if not starts:
        return None, ""
    starts.sort()
    return starts[0][0], starts[0][1]


def _outer_limit(sql: str, ctes: list[_Cte]) -> int | None:
    """The cap on the QUERY's result — the LIMIT that sits outside every CTE.

    Returns None when the query carries no top-level LIMIT (the outer cap is
    then undefined and L009 has nothing to compare against).
    """
    masked = mask_literals(strip_comments(sql))
    caps = [
        int(m.group(1))
        for m in re.finditer(r"\bLIMIT\s+(\d+)", masked, re.I)
        if not _inside_any_cte(m.start(), ctes)
    ]
    return max(caps) if caps else None


def _inside_any_cte(pos: int, ctes: list[_Cte]) -> bool:
    """True when character position `pos` sits inside a CTE body."""
    return any(c.start <= pos < c.end for c in ctes)


def lint_sql(sql: str, target_date: str | None = None) -> list[Issue]:
    """Return every structural issue found in `sql`."""
    issues: list[Issue] = []
    ctes, cte_issues = parse_ctes(sql)
    issues.extend(cte_issues)
    by_name = {c.name.lower(): c for c in ctes}
    masked = mask_literals(strip_comments(sql))

    # L002 / L003 — UNION branch alignment (arity and names)
    for chain in union_chains(sql):
        if len(chain) < 2:
            continue
        shapes = []
        for name in chain:
            cte = by_name.get(name.lower())
            if cte is None:
                shapes.append(None)
                continue
            aliases = [alias_of(i) for i in cte.select_items]
            shapes.append(aliases)
        known = [s for s in shapes if s is not None]
        if not known:
            continue
        arities = {len(s) for s in known}
        if len(arities) > 1:
            detail = ", ".join(
                f"{n}={len(s) if s is not None else '?'}" for n, s in zip(chain, shapes)
            )
            issues.append(Issue(
                "ERROR", "L002",
                f"UNION ALL branches have different column counts ({detail}) — "
                f"shibui's DuckDB rejects this with 'Set operations can only apply to "
                f"expressions with the same number of result columns'",
            ))
            continue
        first = known[0]
        for name, shape in zip(chain, shapes):
            if shape is None or shape == first:
                continue
            mismatched = [
                f"{i}: {a!r} vs {b!r}"
                for i, (a, b) in enumerate(zip(first, shape))
                if (a or "").lower() != (b or "").lower()
            ]
            if mismatched:
                issues.append(Issue(
                    "ERROR", "L003",
                    f"UNION branch '{name}' publishes different column names than "
                    f"'{chain[0]}' ({'; '.join(mismatched[:4])}) — a UNION ALL takes its "
                    f"output names from the FIRST branch, so one metric is published "
                    f"under another metric's header",
                ))

    # L004 — identifiers that resolve to nothing
    for cte in ctes:
        defined = _defined_identifiers(cte, by_name)
        used = _used_identifiers(cte.body)
        # table names and their aliases are not columns
        table_aliases: set[str] = set()
        for tm in re.finditer(
            r"\b(?:FROM|JOIN)\s+(?:shibui\.)?([A-Za-z_][A-Za-z0-9_]*)"
            r"\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
            masked, re.I,
        ):
            alias = tm.group(2).lower()
            if alias in SQL_KEYWORDS:
                continue
            table_aliases.add(alias)
        table_names = {
            t.lower() for t in re.findall(
                r"\b(?:FROM|JOIN)\s+(?:shibui\.)?([A-Za-z_][A-Za-z0-9_]*)", masked, re.I
            )
        }
        unknown = sorted(
            u for u in used
            if u not in defined and u not in table_aliases and u not in table_names
        )
        for u in unknown:
            near = sorted(
                d for d in defined
                if d != u and (d.startswith(u) or u.startswith(d) or u in d or d in u)
            )
            if near:
                issues.append(Issue(
                    "ERROR", "L004",
                    f"CTE '{cte.name}': '{u}' is used but never defined — did you mean "
                    f"{near[0]!r}? (shibui's DuckDB: 'Binder Error: Referenced column "
                    f"\"{u}\" not found in FROM clause')",
                ))

    # L005 — window wide enough for the offsets it uses
    lags = [int(x) for x in re.findall(r"\bLAG\s*\([^()]*?,\s*(\d+)\s*\)", masked, re.I)]
    leads = [int(x) for x in re.findall(r"\bLEAD\s*\([^()]*?,\s*(\d+)\s*\)", masked, re.I)]
    need = max(lags + leads) if (lags or leads) else 0
    if need:
        start, label = _window_start(sql)
        end = None
        if target_date:
            try:
                end = _dt.date.fromisoformat(target_date)
            except ValueError:
                end = None
        if start and end:
            sessions = _business_days(start, end)
            if sessions < need * 1.10:
                issues.append(Issue(
                    "ERROR", "L005",
                    f"lookback window {label} gives ~{sessions} trading sessions back from "
                    f"{end.isoformat()}, but LAG/LEAD needs {need} — the query returns an "
                    f"EMPTY result with no error (needs >= {int(need * 1.10)} sessions)",
                ))

    # L006 — LIMIT on the top-level SELECT
    if not re.search(r"\bLIMIT\s+\d+", masked, re.I):
        has_aggregate = bool(re.search(
            r"\b(count|sum|avg|min|max|median)\s*\(", masked, re.I))
        row_producing_union = any(len(c) > 1 for c in union_chains(sql))
        if row_producing_union and not has_aggregate:
            issues.append(Issue(
                "ERROR", "L006",
                "no LIMIT clause on a row-producing UNION — shibui rejects any query "
                "returning more than 200 rows",
            ))
        elif not has_aggregate:
            issues.append(Issue(
                "WARN", "L006",
                "no LIMIT clause — shibui rejects any query returning more than 200 rows",
            ))

    # L007 — division without NULLIF
    for m in re.finditer(r"/\s*([A-Za-z_][A-Za-z0-9_.]*)", masked):
        denom = m.group(1).split(".")[-1].lower()
        if denom in {"nullif", "coalesce"}:
            continue
        # a NULLIF( that immediately wraps the denominator is fine
        prefix = masked[max(0, m.start() - 12):m.start()].lower()
        if prefix.rstrip().endswith("nullif("):
            continue
        issues.append(Issue(
            "WARN", "L007",
            f"division by '{m.group(1)}' without NULLIF() — a zero denominator returns "
            f"inf/NaN and breaks the JSON response",
        ))
        break  # one warning is enough

    # L008 — date arithmetic on a bare string literal
    for m in re.finditer(r"'(?:\d{4}-\d{2}-\d{2})'\s*-\s*INTERVAL", masked, re.I):
        issues.append(Issue(
            "ERROR", "L008",
            f"date arithmetic on a bare string literal — DuckDB needs DATE 'YYYY-MM-DD' "
            f"- INTERVAL '...'",
        ))

    # L009 — a per-branch LIMIT inside a CTE is a silent truncation
    #
    # The outer cap (shibui's 200-row ceiling) is the ONLY limit a query may
    # carry. A CTE that ends in its own smaller LIMIT truncates that branch
    # while the query still succeeds: the 2026-11-04 artifact published
    # `A_stockbee_4pct 50` and `B_stockbee_ep9m 50` — the caps, not
    # screen outcomes (the true passing counts that day were 233 and 236).
    # L006 checks for a MISSING limit; nothing checked for a per-branch one,
    # which is exactly the gap that let this ship twice.
    outer_cap = _outer_limit(sql, ctes)
    if outer_cap is not None:
        for cte in ctes:
            for m in re.finditer(r"\bLIMIT\s+(\d+)", masked, re.I):
                if not (cte.start <= m.start() < cte.end):
                    continue
                branch_cap = int(m.group(1))
                if branch_cap < outer_cap:
                    issues.append(Issue(
                        "ERROR", "L009",
                        f"CTE '{cte.name}' carries LIMIT {branch_cap}, smaller than the "
                        f"outer cap of {outer_cap} — this branch's book is silently "
                        f"truncated while the query still succeeds. Every branch must be "
                        f"uncapped; cap the QUERY, not the branch (and publish "
                        f"rows_passing so the truncation cannot hide).",
                    ))

    return issues


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _lint_emitters(date: str) -> list[tuple[str, list[Issue]]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import screen  # noqa: E402

    emitters = [
        ("prefilter", screen.emit_prefilter_sql),
        ("sweep_stockbee", screen.emit_sweep_sql_stockbee),
        ("sweep_qullamaggie", screen.emit_sweep_sql_qullamaggie),
        ("sweep_peoplewish", screen.emit_sweep_sql_peoplewish),
        ("breadth", screen.emit_breadth_sql),
        ("reversal_bullish", screen.emit_reversal_bullish_sql),
        ("resolve_date", screen.emit_resolve_date_sql),
        ("adr_enrichment", screen.emit_adr_enrichment_sql),
        ("weekly", screen.emit_weekly_sql),
    ]
    out = []
    for name, fn in emitters:
        try:
            sql = fn(date) if name != "adr_enrichment" else fn(["AAPL", "MSFT"])
        except Exception as exc:  # pragma: no cover - defensive
            out.append((name, [Issue("ERROR", "L000", f"emitter raised {exc!r}")]))
            continue
        out.append((name, lint_sql(sql, date)))

    # The per-branch emitters are the path the run actually takes — lint
    # them too, so a cap cannot hide in the coverage-safe fetch path.
    for branch in screen.SWEEP_BRANCHES:
        try:
            sql = screen.emit_sweep_sql_branch(date, branch)
        except Exception as exc:  # pragma: no cover - defensive
            out.append((f"branch:{branch}", [Issue("ERROR", "L000", f"emitter raised {exc!r}")]))
            continue
        out.append((f"branch:{branch}", lint_sql(sql, date)))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lint the SQL this skill emits")
    p.add_argument("path", nargs="?", help="a .sql file to lint")
    p.add_argument("--emitted", action="store_true", help="lint screen.py's own emitters")
    p.add_argument("--date", default=None, help="target date (YYYY-MM-DD) for window checks")
    args = p.parse_args(argv)

    failures = 0
    if args.emitted:
        for name, issues in _lint_emitters(args.date or "2026-10-27"):
            hard = [i for i in issues if i.severity == "ERROR"]
            status = "OK  " if not hard else "FAIL"
            print(f"  {status} {name}")
            for i in issues:
                print(f"       {i}")
            failures += len(hard)
    elif args.path:
        sql = Path(args.path).read_text(encoding="utf-8")
        for i in lint_sql(sql, args.date):
            print(f"  {i}")
            if i.severity == "ERROR":
                failures += 1
    else:
        p.print_help()
        return 2
    if failures:
        print(f"\n{failures} ERROR(s)")
        return 1
    print("\nAll lint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

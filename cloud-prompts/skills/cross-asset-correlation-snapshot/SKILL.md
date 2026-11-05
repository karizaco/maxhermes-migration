---
name: Cross-asset correlation snapshot
description: >-
  Weekly correlation matrix of the major asset proxies: SPY, QQQ, IWM, TLT,
  GLD, DXY (via UUP), VIX (when available), EEM. Used to spot regime shifts
  (risk-on/off, growth-value, commodity-Dollar coupling) that inform sector
  positioning for the week. Runs 10:00 ET on weekdays, intraday.
  the weekly brief. On Cloud the matrix is computed SERVER-SIDE by DuckDB
  `corr()` over the MCP bridge — see "Cloud adaptation" below.
---

# Cross-asset correlation — weekly snapshot

Single-purpose: produce a Pearson correlation matrix across the core asset proxies so the weekly brief can spot regime changes (stocks-bond decoupling, growth-value rotation, USD-gold rotation) and frame the week ahead.

## When
- Cron: `0 10 * * 1-5` America/New_York (weekdays, 10:00 ET — intraday, one hour after the US open)
- Manual: user asks "show me the cross-asset correlation" or "how correlated are bonds and stocks right now?"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\correlations\YYYY-Wnn-snapshot.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_)
- Compact ≤ 10-line summary in chat reply.
  _(Superseded 2026-11-05: the reply follows the fleet's standard `## DELIVERY` structure,
  and its FIRST `### Signal` line is the artifact's `signal_line` — see "Reply — lead with
  the implication, not the matrix" below. The line cap there was never the point; leading
  with the implication is.)_

## Universe (hardcoded 8 proxies)

| Proxy | Ticker | What it measures |
|---|---|---|
| S&P 500 | SPY | US large-cap equity |
| Nasdaq-100 | QQQ | US large-cap growth/tech |
| Russell 2000 | IWM | US small-cap |
| 20+ Year Treasury | TLT | Long-duration US rates |
| Gold | GLD | Precious metals / real rates |
| US Dollar | UUP | Broad USD vs basket |
| Emerging Markets | EEM | EM equity |
| VIX | ^VIX | Implied vol (skip if N/A — see step 4) |

Quarterly review for additions (e.g. XLE for energy, HYG for credit) — note in audit line if universe changes.

## Steps

1. **Compute window.** Default `period = 6mo` (6 months of daily closes). Valid options per `mcp__financekit__correlation_matrix`: `3mo`, `6mo`, `1y`, `2y`. Use `6mo` unless the user explicitly asks for a longer window.
2. **Single batched call.** `mcp__financekit__correlation_matrix(symbols="SPY,QQQ,IWM,TLT,GLD,UUP,EEM,^VIX", period="6mo")`. One call covers everything.
   **On Cloud this tool does not exist — see "Cloud adaptation" below and use the server-side
   `corr()` call there instead.** The INTENT of this step — one batched call that computes the
   whole matrix — is preserved by the Cloud path.
3. **Parse response** into a symmetric matrix (handle VIX specially — see step 4).
4. **VIX handling.** VIX often drops from correlation_matrix output (different scale, intermittent). If absent: log under Source health, drop ^VIX column from the matrix, continue.
5. **Read the matrix:**
   - Identify pairs with |corr| > 0.7 (strong relationship) — note regime signal
   - Identify pairs with |corr| < 0.2 (effectively uncorrelated) — diversification value
   - Watch for week-over-week delta (compare current snapshot file with prior week): if any pair moved >0.2 absolute, flag as `REGIME_SHIFT`
6. **Write markdown:**
   1. TL;DR (≤3 lines): regime tag (e.g. "stocks/bonds still negatively correlated, USD/Gold positively correlated — risk-off tone persists")
   2. Full correlation matrix as a markdown table
   3. Highlight pairs: top 3 strongest |corr|, top 3 weakest |corr|
   4. Week-over-week delta (if prior week exists)
   5. Source health (VIX included/dropped, any call failure)

   **On Cloud, do NOT hand-format any of these tables.** Generate the whole artifact with
   `scripts/correlation_report.py` — see "Output formatting" below. Hand-typed tables drift
   run to run, and a correlation matrix is a COMPARISON artifact whose value depends on being
   byte-comparable with last week's file.
7. **Append audit line:** `correlation-snapshot target=correlations:<iso_week> universe=<n> regime=<tag> regime_shift=<yes|no>`.

## Cloud adaptation (agent.minimax.io) — READ THIS ON CLOUD

`mcp__financekit__correlation_matrix` is **not bound in Cloud sessions**, and neither is any
`mcp__*` tool. There is no financekit MCP *server* either — the only reachable MCP servers are
`stocktwits` and `shibui` (verified 2026-10-28). So step 2's hard rule cannot be satisfied
as literally written.

**But the rule's intent can be satisfied exactly: compute the matrix SERVER-SIDE, in one call.**

`shibui.stock_data_query` runs DuckDB SQL server-side, and DuckDB's `corr()` aggregate computes
the entire matrix in a single round trip. This is the closest available equivalent of
`correlation_matrix`, and it is what the helper script does.

### Use the helper script — it is the primary path

```bash
BR=/workspace/mcp_bridge.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" ; do
  [ -s "$BR" ] || curl -sL -H "Accept: application/vnd.github.raw" -o "$BR" "$U" 2>/dev/null
done
[ -s "$BR" ] || echo "bridge fetch FAILED - fall back to web_search, then the curl ladder"

# --- fetch BOTH helper scripts, and require the CAPABILITY MARKER in each --------
# The CONTENTS API is authoritative and is NOT CDN-cached; the two CDNs cache `main`
# independently (measured 2026-11-04: raw.githubusercontent served a stale blob for >17
# minutes after a push while jsDelivr was fresh). A MARKER, not an exit code, decides
# which copy is current:
#   * an OLDER helper does not write series.json / mats_partial.json at all,
#   * an OLDER renderer silently drops three sections instead of failing.
# So a stale copy must never win the fetch.
SP=cloud-prompts/skills/cross-asset-correlation-snapshot/scripts
fetch_script() {   # $1 = filename, $2 = capability marker
  dest="/workspace/$1"; mark="$2"
  for u in \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/$SP/$1?ref=main" \
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/$SP/$1" \
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/$SP/$1" ; do
    curl -sL --max-time 45 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$dest.tmp" "$u" 2>/dev/null
    if head -1 "$dest.tmp" 2>/dev/null | grep -q '^#!' && grep -q "$mark" "$dest.tmp" 2>/dev/null; then
      mv -f "$dest.tmp" "$dest"; echo "fetched $1 (marker $mark present)"; return 0
    fi
    rm -f "$dest.tmp"
  done
  echo "FETCH FAILED: $1 — no copy carries the marker $mark"
  return 1
}
fetch_script correlation_matrix.py correlation-matrix-v2 || { echo "no artifact; no push"; exit 1; }
fetch_script correlation_report.py cross-asset-v4 || { echo "no artifact; no push"; exit 1; }

# window-end = the last COMPLETED session (see "partial session" rule below)
python3 /workspace/correlation_matrix.py \
  --symbols 'SPY,QQQ,IWM,TLT,GLD,UUP,EEM,^VIX' \
  --window-start <YYYY-MM-DD> --window-end <YYYY-MM-DD> \
  --basis adjclose --cross-check \
  --out /workspace/data_cross/mats.json
```

Add `--rolled-end <YYYY-MM-DD>` for a week-rolled comparison window.
The helper prints a JSON summary and writes `mats.json` with
`matrix_returns`, `window`, `sources`, and (with `--cross-check`) `crosscheck_shibui_raw`.

### The helper writes ALL THREE files the renderer needs

Since 2026-11-05 the helper itself emits every input the renderer reads, so **no wrapper
script is involved and the render command below works verbatim**:

| File | Written by | What it carries |
|---|---|---|
| `data_cross/mats.json` | `correlation_matrix.py` | the published server-side returns matrix + the matched-length prior-week matrix + source health |
| `data_cross/series.json` | `correlation_matrix.py` | `{symbol: [[date, adjclose, rawclose], …]}` — from ~2 weeks **before** the window start (the matrix's first return observation needs the prior close as its base) through **today** (the intraday column needs the partial bar) |
| `data_cross/mats_partial.json` | `correlation_matrix.py` | `{"matrix_returns": {…}}` for the same window **including** the in-progress session, computed through the helper's own `build_sql` + `shibui_sql` — server-side DuckDB `corr()`, never by hand |

**Before this, `series.json` and `mats_partial.json` came from an ad-hoc wrapper.** If the
wrapper was not written, three load-bearing sections silently vanished from the artifact —
`📈 Performance`, `🧪 Effect of the excluded partial session` and `📎 Appendix — price-level
correlations` — and the run still reported success. The 2026-11-04 artifact says so in its
own deviations section. That class of defect is now closed on both sides: the helper
writes the files, **and** the renderer FAILS when they are missing instead of dropping the
section.

**Price source:** Yahoo Finance Chart API `/v8/finance/chart/{sym}?range=1y&interval=1d`, short
`User-Agent: Mozilla/5.0` (a long Chrome UA is 429'd by Yahoo's edge). The aligned series are
injected into the SQL as inline VALUES and DuckDB computes the matrix server-side.
**shibui's own `stock_quotes` table is an independent cross-check, never the primary source.**

### What the helper enforces (measured constraints, not folklore)

- **shibui's tool caps result rows at 200.** An AGGREGATE query returns one row, so the matrix
  call is unaffected. Never pull raw series for 8 symbols out of it (889 rows -> tool error);
  pull per-ticker (127 rows each) or aggregate in SQL.
- **^VIX is NOT in shibui** — `general_info` has no index rows and no ticker matches `%VIX%`.
  VIX comes from Yahoo and is injected alongside the ETF series.
- **Returns must span consecutive COMMON dates.** VIX carries sessions the ETFs lack
  (2026-05-25, 2026-09-07). Compute the common date set FIRST, then take `lag()` over it.
  Otherwise VIX returns span a different interval and VIX correlations drift by ~0.002.
- **`^VIX` is not a valid SQL identifier** — the helper maps it to `VIX`.

### Adjustment basis — state it, never leave it implicit

`--basis adjclose` (default) uses Yahoo's split/dividend-adjusted closes; `--basis close` uses
raw closes. They differ materially for distributing ETFs (SPY–TLT was +0.33 on adjclose vs +0.32
on raw close over the same 6-month window), because a raw ex-dividend drop is a price move but
not a total loss. **Publish the basis in the artifact** and keep it consistent with the prior
snapshot when computing a week-over-week delta.

### Partial session rule (this cron fires intraday)

The deployed cron fires at 10:00 ET, so the current session is usually **in progress**. A
partial bar is not a close. Use the last COMPLETED session as `window-end` and report the
excluded date. If the partial bar's effect is quantified, say so.

### Fallback chain (if the bridge is unavailable)

`shibui` server-side matrix -> local Pearson on Yahoo closes -> `web_search` per symbol.
**Record which path produced the published matrix in Source health.** Do not silently ship a
locally-computed matrix while implying the server-side one was used.

## Output formatting — the renderer (Cloud)

**The artifact's tables are generated, not typed.** `scripts/correlation_report.py` reads the
`mats.json` written by `correlation_matrix.py` and emits the complete markdown report.

```bash
# The two helper scripts are fetched (with their capability markers) in the block
# above. Do NOT fetch them again here, and do NOT hand-edit them.

# 1) the matrix (server-side) AND the matched-length prior-week window, in ONE call.
#    --window-end auto DERIVES the last completed session FROM THE DATA. Never pass a
#    hand-picked window end: on 2026-11-03 a hand-picked 2026-10-30 silently published
#    the previous day's window (a duplicate of the 2026-11-02 artifact) even though
#    Yahoo's series contained the 2026-11-02 bar.
#    This one call also writes series.json and mats_partial.json — see the table above.
python3 /workspace/correlation_matrix.py --symbols 'SPY,QQQ,IWM,TLT,GLD,UUP,EEM,^VIX' \
  --window-end auto --prior-window --basis adjclose --cross-check \
  --out /workspace/data_cross/mats.json

# 2) write the two PROSE sections to files (prose is hand-written; tables are not)
cat > /workspace/tldr.txt <<'EOF'
...TL;DR prose...
EOF
cat > /workspace/deviations.txt <<'EOF'
...deviations-from-spec bullets...
EOF

# 3) render
python3 /workspace/correlation_report.py \
  --current /workspace/data_cross/mats.json \
  --partial /workspace/data_cross/mats_partial.json \
  --series  /workspace/data_cross/series.json \
  --tl-dr /workspace/tldr.txt --deviations /workspace/deviations.txt \
  --date <YYYY-MM-DD> --iso-week <YYYY-Wnn> --fire-et <HH:MM> \
  --regime "<regime tag>" --out /workspace/cross-asset/<YYYY-MM-DD>.md
```

**`--partial` and `--series` are REQUIRED, and the renderer FAILS (non-zero exit) when
either file is absent.** That is deliberate: they used to be optional, and because the
helper did not write them, a missing file silently dropped three sections while the run
reported success. If the renderer exits non-zero, **do not work around it and do not push
a hand-written replacement** — re-run `correlation_matrix.py` (check the helper's stdout
for `series:` and `partial:` paths) and render again.

### What the renderer adds (and why)

- **Semantic colour via emoji blocks.** GitHub strips `style=` from markdown and the chat
  renders GFM, so ANSI/HTML colour is impossible. The renderer uses magnitude bands instead:
  🟥 ≥ 0.70 strong · 🟧 0.60–0.70 · 🟨 0.40–0.60 · 🟩 0.20–0.40 · 🟦 < 0.20 uncorrelated.
  Sign stays in the number; colour encodes magnitude only.
- **Magnitude bars** (`███████░`, 8 steps) next to each pair, and a flat ranked heatmap list
  of all 28 pairs — easier to scan on a phone than an 8×8 grid.
- **Severity-coded flags** — ✅ no shift · ⚠️ borderline · 🔴 REGIME_SHIFT — so the
  hedge-relevant facts pop instead of hiding in prose.
- **Sign-aware delta arrows** (➕/➖) on the week-over-week table.
- **Determinism.** Every table has the same columns, the same order and the same band
  thresholds on every run, which is what makes week-over-week comparison meaningful.

### The window end is derived, never chosen

`--window-end auto` computes the last COMPLETED session from the fetched series: if the
current ET time is before today's 16:00 close, today's bar is in progress and is dropped;
otherwise today's bar is a close and is used. `^VIX` is excluded from the session calendar
(it prints overnight and can carry a bar the ETFs lack). `--prior-window` adds the
matched-length prior-week window (end − 7 days) to the same output file, so **no date
arithmetic is done by hand anywhere**.

**Never pass a hand-picked `--window-end`.** A hand-picked date on 2026-11-03 published the
window ending 2026-10-30 — the previous day's window — so the matrix and the whole
week-over-week delta were a duplicate of the 2026-11-02 artifact, and nothing in the output
looked wrong. The artifact then carried `window_end_derived_from_data: false`, which is how
you spot it.

### Rules for the renderer

1. **Never hand-write a table.** Prose (TL;DR, deviations, regime tag) may be written by hand
   into `tldr.txt` / `deviations.txt`; every table comes from the script.
2. **The renderer is not a source.** It formats `mats.json`; it never fetches data. If a
   comparison window is missing, omit that section rather than hand-filling it — but if
   `--series` or `--partial` is missing, the renderer **FAILS**, and that is the intended
   behaviour, not a bug to work around. Re-run the helper and render again.
3. **A live quote may only be used if the QUOTE ITSELF is stamped with the snapshot's date.**
   Check each quote's own `as_of` field — NOT the feed's retrieval timestamp. Before the
   open a feed returns the PREVIOUS session's close with a fresh retrieval stamp, so a
   retrieval-date check passes it and silently labels yesterday's move as "today". The
   renderer drops any quote whose `as_of` date differs from the snapshot date and falls back
   to the partial bar from the snapshot's own series, labelled with that bar's date.
   Injecting the wrong session's prices into a dated artifact is a silent date error.
4. **Check the rendered file for malformed tables before pushing.** A literal `|` inside a
   cell (e.g. `max |Δ|`) breaks the table — write `max abs diff`.
5. The level-correlation appendix is a **local Pearson** and is a supplement only. The
   published matrix is the server-side returns matrix; the artifact must say so.
6. **The performance table's window return is measured from the close BEFORE the window's
   first session** — that is the base of the matrix's first return observation. Starting the
   return at the first in-window close is one bar short of the matrix it describes.

## The artifact contract — MANDATORY pre-push check

**Do not push an artifact you have not checked.** The acceptance criteria are machine
assertions, not a reading exercise: the 2026-11-04 artifact looked fine and would have
failed several of them.

```bash
C=/workspace/tools/check_cross_asset_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_cross_asset_artifact.py?ref=main" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_cross_asset_artifact.py" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_cross_asset_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if head -1 "$C.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'check_cross_asset_artifact' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
[ -s "$C" ] || { echo "checker unavailable — do not publish an unchecked artifact"; exit 1; }

python3 "$C" \
  --md  /workspace/cross-asset/{date}.md \
  --mats /workspace/data_cross/mats.json \
  --reply /workspace/reply.txt \
  --outputs-repo karizaco/minimax-cloud-outputs --ref main
```

It asserts:

- the front matter exists and carries `contract: cross-asset-v4` (a missing marker means a
  **stale renderer** produced the file — re-fetch and re-run);
- `window_end_derived_from_data: true` — a hand-picked `--window-end` is the 2026-11-03
  stale-window bug and is refused;
- `window_start` / `window_end` / `n_sessions` agree with `mats.json` (a hand-edited
  front matter is caught);
- all eight sections are present, including `📈 Performance`, `🧪 Effect of the excluded
  partial session` and `📎 Appendix — price-level correlations`;
- all five colour bands (🟥🟧🟨🟩🟦) are present and no markdown table has a ragged cell
  count;
- the front matter carries a `signal_line` holding the max pair move, the 0.20 threshold
  and the hedge implication;
- the excluded-partial-session section does **not** overstate itself: it may only claim
  the proof when the partial matrix really included a newer session;
- the reply's first `### Signal` line names the hedge pair, the max pair move, the 0.20
  threshold and the hedge implication.

### THE DUPLICATE-WINDOW ASSERTION

The same check refuses to publish a **second artifact for a window that is already in
`cross-asset/`**. On 2026-11-03 the run published a duplicate of the 2026-11-02 artifact
because the window had not rolled; the recovery was a second corrective commit, so the
wrong artifact was briefly the published one. A duplicate window is indistinguishable
from a regression at read time, so it is refused at the source.

**If the checker exits 1 with a `DUPLICATE WINDOW` line: DO NOT PUSH.** Report it:
which file already carries that window end, and what the derived window end was. Re-push
only after you have established why the duplicate exists — a genuinely new window is the
only acceptable reason to publish.

**If the checker exits 4** (the duplicate check could not run — the listing could not be
fetched): that is **not** a pass. Re-run the fetch once; if it still fails, publish only
with `duplicate_window_check: unavailable` stated in the artifact's deviations and
reported in the reply. Never report a clean run for a check that did not run.

**Exit 1** on any other assertion means the artifact is wrong. Fix the artifact and run
the checker again. Do not report a clean run over a failing check.

## Reply — lead with the implication, not the matrix

The tables are the evidence; the reply is what gets read. The 2026-11-04 artifact's TL;DR
already carried the sentence a trader acts on, but the chat reply led with something
else — so the actionable line was a scroll away from where the reader starts.

**The first line under `### Signal` in your reply must be the artifact's `signal_line`** —
copy it verbatim from the artifact's front matter:

```
signal_line: SPY–TLT +0.31 → bonds move WITH equities, so TLT is a weak diversifier, not a hedge against a growth selloff; best equity offset in the universe is UUP–SPY -0.34 · best diversifier QQQ–TLT +0.16 · largest pair move 0.0346 vs the 0.20 regime-shift threshold (0.1654 to go)
```

It carries three facts, in this order:

1. **the hedge implication** — which instrument actually offsets which risk, in one clause;
2. **the best diversifier** in the universe, as a headline;
3. **the distance to the shift threshold** — `max_pair_move` against the 0.20
   regime-shift threshold, because that number is the routine's actual output and it says
   how much has to change for the picture to flip.

The renderer computes it from the same numbers the tables use, so the reply can never
drift from the artifact. Do not recompute a correlation by hand to write it.

The prose opener (2–4 sentences) states the same implication in sentence form — the reader
must not have to reach the `### Signal` section to learn what the snapshot means. Do not
open with the matrix, the session count or the source list.

Write the final reply to `/workspace/reply.txt` **before** running the checker, so the
`--reply` assertion can see it. The reply still follows the fleet's standard
`## DELIVERY` structure (prose opener → `### Signal` → `### Method & caveats` →
`### Files` → `### Push / errors`) — this section only fixes what the FIRST Signal line
must say.

## Hard rules
- Use only `financekit.correlation_matrix`. Do not compute correlations manually from `price_history` calls — that's redundant and slower.
  **On Cloud:** the equivalent is the server-side DuckDB `corr()` call via the MCP bridge
  (see "Cloud adaptation"). A local Pearson computed in the agent IS the manual computation the
  rule forbids — it is a fallback, and the artifact must say so.
- If the call fails, write a 1-line stub with the error and skip.
- Don't over-interpret correlation as causation. Tag it "regime context only" in the brief.
- 6-month window default. Don't switch to 1y or 2y unless the user asks.

## Out of scope
- Forward return forecasts or factor regression.
- Sector-level correlations (XLF/XLE/XLK etc.) — separate skill if needed later.
- International market correlations (EFA, EEM) — EEM only here.
# docs/ — the fleet's improvement record

One file per routine (or per cross-check), written when a routine is reviewed and
changed. They record the EVIDENCE for each change, not just what the change was —
so the next person can check the finding rather than take it on trust.

Regenerate this index with `python3 tools/gen_docs_index.py` after adding a file.

| Document | What it is |
|---|---|
| [`BUGREPORT-gui-schedule-corruption.md`](BUGREPORT-gui-schedule-corruption.md) | Bug report — web GUI save silently corrupts a scheduled task's day-of-week field — **Submit via:** the app's **Feedback** dialog (user menu → Help, or a task's top bar, or a |
| [`BUGREPORT-windows-invalid-filenames.md`](BUGREPORT-windows-invalid-filenames.md) | BUGREPORT — Windows-invalid filenames in the outputs repo — **Date:** 2026-11-08 |
| [`CROSSCHECK-cron19-earnings-reminder.md`](CROSSCHECK-cron19-earnings-reminder.md) | Cross-check — cron #19 earnings-reminder-daily — Reviewed 2026-11-01 against the deployed task and the artifacts it actually produced during the |
| [`IMPROVEMENTS-2026-11-03-holiday-guard-and-auditor-roster.md`](IMPROVEMENTS-2026-11-03-holiday-guard-and-auditor-roster.md) | Improvements — 2026-11-03: the holiday guard, and the auditor's missing routines — Two defects found while reviewing the international EOD series, plus the systemic fix that |
| [`IMPROVEMENTS-2026-11-04-fetch-ladder-and-memory-routing.md`](IMPROVEMENTS-2026-11-04-fetch-ladder-and-memory-routing.md) | Improvements — 2026-11-04: the dead fetch fallback, and where a finding goes — **Date:** 2026-11-04 · **Scope:** the fleet's fetch idiom and the routing of routine findings |
| [`IMPROVEMENTS-2026-11-06-auditor-contract-and-26b-roster.md`](IMPROVEMENTS-2026-11-06-auditor-contract-and-26b-roster.md) | Improvements — 2026-11-06: the auditor's contract, and #26b's roster — Cron #90 (delivery-auditor) is the fleet's external observer. It decides which routines |
| [`IMPROVEMENTS-2026-11-06-macro-print-source-and-mechanical-gaps.md`](IMPROVEMENTS-2026-11-06-macro-print-source-and-mechanical-gaps.md) | IMPROVEMENTS — 2026-11-06: a macro print has a primary source, and a screen gap can be a corporate action — **Date:** 2026-11-06 |
| [`IMPROVEMENTS-cron05-eod-international.md`](IMPROVEMENTS-cron05-eod-international.md) | Improvements — cron #05 `eod-international-daily` — Date: 2026-11-03. Scope: the reply format for the whole fleet (via the shared block), cron #05's |
| [`IMPROVEMENTS-cron08-pre-market-gapper.md`](IMPROVEMENTS-cron08-pre-market-gapper.md) | Improvements — cron #08 `stock-screener-pre-market-gapper` — - **Audited:** 2026-11-04 (the 08:30 ET fire, `2026-11-04`) |
| [`IMPROVEMENTS-cron09-stock-screener-suite.md`](IMPROVEMENTS-cron09-stock-screener-suite.md) | Cron #09 `stock-screener-daily-sweep-18:30` — General Improvement Audit — **Audited:** 2026-11-03. Scope: the routine as a *system* — the skill spec, its SQL, its data |
| [`IMPROVEMENTS-cron12-cross-asset-correlation-snapshot.md`](IMPROVEMENTS-cron12-cross-asset-correlation-snapshot.md) | Cron #12 — cross-asset-correlation-snapshot: improvements — The skill spec's render command references three data files: |
| [`IMPROVEMENTS-cron15-earnings-reaction-scanner.md`](IMPROVEMENTS-cron15-earnings-reaction-scanner.md) | Cron #15 — earnings-reaction-scanner: the four fixes of 2026-11-05 — Routine review of cron #15 (`earnings-reaction-scanner`), prompted by the 2026-11-03 run and |
| [`IMPROVEMENTS-cron16-unusual-options-flow.md`](IMPROVEMENTS-cron16-unusual-options-flow.md) | Cron #16 `unusual-options-flow-daily` — General Improvement Audit — **Audited:** 2026-10-31 (Sat). Scope: the routine as a *system* — cron instructions, skill spec, |
| [`IMPROVEMENTS-cron17-us-stocks-in-play.md`](IMPROVEMENTS-cron17-us-stocks-in-play.md) | IMPROVEMENTS — cron #17 `us-stocks-in-play` — Findings from the 2026-11-04 pre-close fire (settled session, 15:50 ET). |
| [`IMPROVEMENTS-cron19-earnings-reminder.md`](IMPROVEMENTS-cron19-earnings-reminder.md) | Improvements — cron #19 earnings-reminder-daily — Reviewed 2026-10-25. Evidence base: 16 recorded runs (2026-10-10 → 2026-10-25), the deployed |
| [`IMPROVEMENTS-cron20-eod-watchlist.md`](IMPROVEMENTS-cron20-eod-watchlist.md) | IMPROVEMENTS — cron #20 (eod-watchlist-csv-snapshot) — Running notes on what the routine's data path does in the Cloud runtime. Written by the |
| [`IMPROVEMENTS-cron23-post-market-brief.md`](IMPROVEMENTS-cron23-post-market-brief.md) | Improvements — cron #23 (agentic-post-market-brief): the brief is named POST-MARKET, so tomorrow's setup is the product — Four reader-hostile defects in the post-market brief, fixed in the routine's **skill spec** |
| [`IMPROVEMENTS-cron25-ntrt-gap-brief.md`](IMPROVEMENTS-cron25-ntrt-gap-brief.md) | Improvements — cron #25 ntrt-gap-brief-daily — Reviewed 2026-11-03, after the routine's own 09:00 ET fire on 2026-11-03; section 13 added |
| [`IMPROVEMENTS-cron26-agentic-pre-market-brief.md`](IMPROVEMENTS-cron26-agentic-pre-market-brief.md) | Improvements — cron #26 agentic-pre-market-brief — Reviewed 2026-11-03, after the routine's own 08:30 ET fire on 2026-11-03. Evidence base: the |
| [`IMPROVEMENTS-cron92-preopen-capture.md`](IMPROVEMENTS-cron92-preopen-capture.md) | Improvements — 2026-11-06: cron #92's pre-open capture gets a recipe, a digest, and an audit trail — Three defects in the pre-open catalyst capture (`cron #92`, checkpoints 08:30 and 09:50 ET), |

## Convention

`IMPROVEMENTS-cronNN-<routine>.md` — a review of one routine and what changed.
`CROSSCHECK-<topic>.md` — two routines checked against each other.
`BUGREPORT-<topic>.md` — a defect found outside the routine-review flow.
`remediation/` — the larger fleet-wide remediation records.

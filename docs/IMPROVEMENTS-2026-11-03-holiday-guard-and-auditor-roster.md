# Improvements — 2026-11-03: the holiday guard, and the auditor's missing routines

Two defects found while reviewing the international EOD series, plus the systemic fix that
stops the first one recurring. Both are deployed; nothing else in the fleet changed.

## 1. The Athens Exchange holiday list had SIX wrong dates

`cloud-prompts/skills/eod-watchlist-snapshot/scripts/holiday_calendar.py` lists the ATHEX's
non-trading days for 2025–2027. Six of them were wrong, all of the same class of error — a
mis-derived Orthodox date or a shifted national holiday:

| was | now | holiday |
|---|---|---|
| 2026-10-27 | **2026-10-28** | Ochi Day |
| 2027-10-26 | **2027-10-28** | Ochi Day |
| 2027-04-09 | **2027-04-30** | Good Friday (Orthodox) |
| 2027-06-07 | **2027-06-21** | Whit Monday |
| 2025-02-03, 2026-02-02, 2027-02-01, 2027-02-15 | *removed* | spurious "Clean Monday" |
| — | **+2025/26/27-03-25** | Independence Day (was missing) |
| — | **+2026-04-13** | Easter Monday (Orthodox, was missing) |
| — | **+2025/26/27-12-24** | Christmas Eve (was missing) |

**One of these was a false holiday that deleted a real trading session.** Ochi Day was listed
as 2026-10-27 instead of 10-28, and the ATHEX was open and traded on 10-27 — Yahoo's daily bars
for ALPHA.AT, EUROB.AT, TPEIR.AT, GEKTERNA.AT, MOH.AT and ETE.AT each carry a 10-27 session
whose close matches the screener to the cent. A false holiday makes the run skip a region that
traded: the session is simply absent from the archive, with no error and no artifact.

Source: Euronext Athens' own market-holiday table and Trading Calendar
(`athens.euronext.com/en/trade/trading-model/calendar`), cross-checked against the Bank of
Greece bank-holiday list, timeanddate and publicholidays.gr. Greece observes BOTH the Catholic
and the Orthodox Easter weekends, which is why four Easter dates appear.

## 2. The systemic fix: a session probe, and "unknown is never a licence to skip"

Correcting six dates does not stop the same class of error in the other fifteen tables, none
of which is machine-verified. So the calendar is now explicitly a **hint**, and the decision to
skip a region is made from evidence:

**`scripts/market_session_probe.py`** (new) answers *"did this region actually trade on this
date?"* from the exchange's own session bars:

```bash
python3 market_session_probe.py --region eu-gr --date 2026-10-27
# VERDICT region=eu-gr date=2026-10-27 traded=yes source=ALPHA.AT last_bar=2026-10-27
```

- `traded=yes` → **include the region**, and report the calendar as wrong.
- `traded=no` → the market did not trade; skip it, and say so in `## Source health`.
- `traded=unknown` → you do not know (source unreachable, date outside the fetched window, or
  after the last session). **Unknown is never a licence to skip** — treat it as a trading day and
  note the uncertainty.

A skip is a deletion from the historical record, so it needs a positive confirmation. The
skill's new section *"Holiday calendars are a HINT — verify the session before skipping a
region"* instructs the run to probe every region the calendar would skip.

Design notes: the probe uses the index where Yahoo has one and a liquid constituent where it
does not (there is no ATHEX index on Yahoo, so Greece probes `ALPHA.AT`); it fetches 2y of
daily bars so the 2025–2027 calendar window is covered; and it separates *"no session on that
date"* from *"the date is outside the fetched window"*, because a missing bar must never become
a silent holiday.

**Validation** — the probe was checked against nine known-good calendar entries it did not
change, plus the Greece regression case:

| region | date | probe | calendar |
|---|---|---|---|
| eu-gr | 2026-10-27 | traded=yes | **was a false holiday** |
| eu-gr | 2026-10-28 | traded=no | holiday ✓ |
| jp | 2026-10-12 | traded=no | holiday ✓ (Sports Day) |
| jp | 2026-10-13 | traded=yes | trading day ✓ |
| jp | 2026-11-03 | traded=no | holiday ✓ (Culture Day) |
| tw | 2026-10-26 | traded=no | holiday ✓ |
| tw | 2026-10-27 | traded=yes | trading day ✓ |
| ca | 2026-10-12 | traded=no | holiday ✓ (Thanksgiving) |
| ca | 2026-10-13 | traded=yes | trading day ✓ |
| au | 2026-04-27 | traded=yes | trading day ✓ (ANZAC on Saturday, no substitute) |

**Regression tests** — 8 new cases in `scripts/tests/test_holiday_calendar.py` cover the
corrected Greek dates, including `test_the_athex_traded_on_2026_10_27`, which asserts that
2026-10-27 is a **trading** day. The whole skill suite is **142 tests, all passing**.

## 3. Cron #90 was not auditing three live routines

The delivery auditor's roster is the contract for what every routine owes the outputs repo,
and it was written before #91 and the two #92 pre-open checkpoints existed. Three live routines
were therefore never checked for delivery: they could fail every single day and the auditor
would report the fleet healthy.

| routine | schedule | expected artifact |
|---|---|---|
| 91-schedule-drift-guard | `5 4 * * *` | none — self-check, like #90 |
| 92a-preopen-catalyst-capture | `30 8 * * 1-5` | `preopen-feed/{date}-0830.jsonl` |
| 92b-preopen-catalyst-capture | `50 9 * * 1-5` | `preopen-feed/{date}-0950.jsonl` |

The roster now carries all three, both #92 checkpoints are in the STEP 4b stale-check list, all
three are marked `not_yet_fired` before their first fire on 2026-11-03, and the prompt spells
out that **a #92 file at the wrong checkpoint time is a near-miss, not a gap** — the time is
part of the filename.

It also now says explicitly that the two rows with no artifact path (#90 and #91) must never
be checked for one: `git cat-file -e "origin/main:(no artifact …)"` reports a false `MISSING`
every single day.

**This deployment also closed a pre-existing drift.** The deployed cron #90 was 37,827 bytes
against a 39,832-byte repo file — it was missing the parallel session's "RECONSTRUCTED
ARTIFACTS" section, committed at 05:02 UTC after the last deploy at 02:58 UTC. The repo is the
source of truth, so the repo file was deployed byte-exactly and re-verified.

## 4. Deployment and verification

- Migration repo: `b513f15` (holiday guard) and `b752e4f` (auditor roster), both pushed to
  `main`, with rollback tags `pre-holiday-guard-2026-11-03` and `pre-cron5-format-2026-11-03`.
- The skill files are **fetched at run time**, so the holiday guard and the probe reach cron
  #05 and #20 with no deployment at all.
- Cron #90 was deployed with `schedule` and `timezone` sent explicitly (a prompt-only
  `cron_update` silently resets the timezone to `Etc/GMT-7` = UTC+7) and verified byte-exactly:
  deployed sha256 `5d737e80…` == repo sha256 `5d737e80…`.
- Fleet re-verified after the deployment: **25/25 routines' deployed prompts match their repo
  file byte-for-byte, all timezones `America/New_York`, zero drift.**

## 5. Still open

- **The other fifteen holiday tables are unverified.** The probe is now available for all of
  them, but only Greece was corrected. A sweep of the remaining regions against each exchange's
  published calendar is the obvious next step.
- **The 18-prompt repo → platform sync is still not approved** and was not performed. Note the
  deployed prompts currently match the repo for all 25 routines, so the sync may already be
  moot — worth re-checking before running it.
- **Four routines run without a thinking variant** (#01, #91, #92a, #92b). `cron_update` has no
  `model` field and `cron_create` takes only a `provider/model_id` string, so this cannot be
  set from here; it has to be set in the scheduling UI.
- **The `holiday_calendar.py` fix is not yet reflected in the copies under `skills-original/`**,
  which the repo keeps as the pre-migration originals. That is intentional — those are
  historical records, not live copies.

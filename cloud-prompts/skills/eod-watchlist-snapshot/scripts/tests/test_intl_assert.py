"""Tests for intl_assert.py - the build-time assertions of cron #05's international artifact.

The point of these tests is that the assertions FIRE. A checker that passes everything is
worse than no checker, so every case here breaks a contract on purpose and asserts that the
right failure is reported.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from intl_assert import (  # noqa: E402
    assert_artifact,
    issuer_name,
    normalised,
    parse_summary_tables,
    ticker_root,
)

CSV_HEADER = [
    "date", "ticker", "name", "open", "high", "low", "close", "volume", "change_pct",
    "market_cap", "pe_ratio", "sector", "currency", "exchange",
    "cap_source_symbol", "share_class", "us_listing", "price_conflict",
]

ENB_ROWS = [
    ["2026-11-04", "TSX:ENB", "Enbridge Inc.", "67.5", "68.4", "67.1", "68.02", "1200000",
     "0.5", "111132927616", "18.0", "Energy", "CAD", "TSX", "TSX:ENB", "common", "NYSE", ""],
    ["2026-11-04", "TSX:ENB.PR.B", "Enbridge Inc. Cum Red Pref Registered Shs Series B",
     "23.7", "23.78", "23.7", "23.77", "2400", "0.08", "111132927616", "9.13",
     "Industrial Services", "CAD", "TSX", "TSX:ENB", "preferred", "NYSE", ""],
    ["2026-11-04", "TSX:ENB.PF.V", "Enbridge Inc. Cum Red Pref Registered Shs Series 5",
     "25.0", "25.0", "24.95", "25.0", "10400", "-0.08", "111132927616", "13.64",
     "Industrial Services", "USD", "TSX", "TSX:ENB", "preferred", "NYSE", ""],
]

SUMMARY = """# Cron #05 eod-international-daily — Wednesday, 04 November 2026

## TL;DR
- something happened
- something else happened
- and the caveat that changes how it reads

## Market context

| Region | Index | Close | Change | Session date | Source |
|---|---|---|---|---|---|
| ca | S&P/TSX Composite | 24,356.20 | +0.75% | 2026-11-04 | TMX |

## Top movers

### ca
| Region | Ticker | Name | Change | Close | Mkt cap (USD) | US listing | Catalyst |
|---|---|---|---|---|---|---|---|
| ca | `TSX:ENB` | Enbridge Inc. | +0.50% | 68.02 CAD | $111.13B | NYSE | a sourced driver |
| ca | `TSX:ENB.PR.B` | Enbridge Inc. Cum Red Pref Registered Shs Series B | +0.08% | 23.77 CAD | $111.13B | NYSE | a sourced driver |

## Below the gate

## No catalyst

## Method, source health & caveats

| Source | Query / URL | Status | Result |
|---|---|---|---|
| TV scanner | america/scan | ok | 16/16 |
"""


def write_csv(path: Path, rows) -> None:
    import csv as _csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)


def build_artifact(tmp: Path, rows=None, excluded=None, manifest=None, summary=None) -> Path:
    directory = tmp / "2026-11-04"
    directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory / "ca.csv", rows if rows is not None else ENB_ROWS)
    (directory / "_excluded.json").write_text(
        json.dumps(excluded if excluded is not None else {"ca": [
            {"ticker": "TSX:XYZ", "name": "No Cap Co", "exchange": "TSX",
             "reason": "no_market_cap", "close": 1.0, "volume": 10},
            {"ticker": "TSX:SMALL", "name": "Small Co", "exchange": "TSX",
             "reason": "below_cap_floor", "close": 2.0, "volume": 500},
            {"ticker": "TSX:TINY", "name": "Tiny Co", "exchange": "TSX",
             "reason": "below_cap_floor", "close": 3.0, "volume": 400},
        ]}),
        encoding="utf-8",
    )
    default_manifest = {
        "date": "2026-11-04",
        "csv_columns": 18,
        "regions": {
            "ca": {
                "universe_rows": 6, "unique_instruments": 6, "written": 3,
                "excluded": {"no_market_cap": 1, "below_cap_floor": 2, "below_volume": 0,
                             "issuer_unresolved": 0, "cap_issuer_mismatch": 0,
                             "stale_venue_print": 0},
                "carryover_rows": 0, "off_official_rows": 0,
                "mover_rows": 2, "below_gate_rows": 0, "no_catalyst_rows": 0,
                "floor_usd": 200000000, "min_volume": None, "file": "ca.csv",
                "venues": ["TSX"],
            }
        },
    }
    (directory / "_manifest.json").write_text(
        json.dumps(manifest if manifest is not None else default_manifest), encoding="utf-8"
    )
    (directory / "summary.md").write_text(
        summary if summary is not None else SUMMARY, encoding="utf-8"
    )
    return directory


class TestHelpers(unittest.TestCase):

    def test_ticker_root_strips_the_class_suffix(self):
        self.assertEqual(ticker_root("TSX:ENB.PR.B"), "TSX:ENB")
        self.assertEqual(ticker_root("BME:GRF.P"), "BME:GRF")
        self.assertEqual(ticker_root("TSX:ENB"), "TSX:ENB")
        self.assertEqual(ticker_root("EURONEXT:AL2SI"), "EURONEXT:AL2SI")

    def test_issuer_name_stops_at_the_class_phrase(self):
        self.assertEqual(issuer_name("Enbridge Inc. Cum Red Pref Registered Shs Series B"),
                         "Enbridge Inc.")
        self.assertEqual(issuer_name("Indra Sistemas, S.A. Class A"), "Indra Sistemas, S.A.")
        self.assertEqual(issuer_name("BHP Group Ltd"), "BHP Group Ltd")

    def test_normalised_ignores_punctuation(self):
        self.assertEqual(normalised("Enbridge Inc."), normalised("Enbridge Inc"))


class TestSummaryParser(unittest.TestCase):

    def test_rows_are_attributed_to_their_region_subheading(self):
        tables = parse_summary_tables(SUMMARY)
        self.assertEqual(len(tables["Top movers"]), 2)
        self.assertEqual({r["region"] for r in tables["Top movers"]}, {"ca"})

    def test_a_level_two_heading_ends_the_section(self):
        tables = parse_summary_tables(SUMMARY)
        # The Method section's source-health table has no tickers, and must not leak into
        # '## No catalyst'.
        self.assertEqual(tables["No catalyst"], [])

    def test_a_region_column_is_used_when_there_is_no_subheading(self):
        summary = SUMMARY.replace("### ca\n", "")
        tables = parse_summary_tables(summary)
        self.assertEqual({r["region"] for r in tables["Top movers"]}, {"ca"})


class TestCleanArtifact(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.directory = build_artifact(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_clean_artifact_passes(self):
        findings = assert_artifact(self.directory)
        self.assertEqual([f for f in findings if f.severity == "FAIL"], [])

    def test_exit_code_is_zero(self):
        import intl_assert

        self.assertEqual(intl_assert.main(["--dir", str(self.directory)]), 0)


class TestCapProvenance(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def failures(self, directory):
        return [f for f in assert_artifact(directory) if f.severity == "FAIL"]

    def test_a_cap_carried_across_issuers_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        # Brookfield's primary line is in the file, and a preferred Enbridge line carries its cap.
        rows.append(["2026-11-04", "TSX:BN", "Brookfield Corporation", "59.0", "61.0", "58.5",
                     "60.18", "900000", "1.0", "99630700151", "32.0", "Finance", "CAD", "TSX",
                     "TSX:BN", "common", "NYSE", ""])
        rows[2][14] = "TSX:BN"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("different issuer" in f.message for f in failures), failures)

    def test_a_cap_source_that_is_not_in_the_file_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[1][14] = "TSX:ENB.MISSING"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("is not in the file" in f.message for f in failures), failures)

    def test_a_preferred_line_carrying_its_own_cap_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[1][14] = "TSX:ENB.PR.B"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("must carry the issuer's cap" in f.message for f in failures), failures)

    def test_an_empty_cap_source_symbol_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[1][14] = ""
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("empty cap_source_symbol" in f.message for f in failures), failures)

    def test_a_non_common_cap_source_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        # The cap is carried from another PREFERRED line, not from the primary.
        rows[1][14] = "TSX:ENB.PF.V"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("is not a common line" in f.message for f in failures), failures)

    def test_an_artifact_without_the_provenance_columns_is_rejected(self):
        import csv as _csv

        directory = self.tmp / "2026-11-04"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "ca.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.writer(handle)
            writer.writerow(CSV_HEADER[:14])
            writer.writerow([r[:14] for r in ENB_ROWS])
        failures = self.failures(directory)
        self.assertTrue(any("provenance column" in f.message for f in failures), failures)


class TestExclusions(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def failures(self, directory):
        return [f for f in assert_artifact(directory) if f.severity == "FAIL"]

    def test_an_excluded_row_without_a_reason_is_caught(self):
        directory = build_artifact(self.tmp, excluded={"ca": [
            {"ticker": "TSX:XYZ", "name": "No Cap Co", "exchange": "TSX",
             "reason": "", "close": 1.0, "volume": 10}
        ]})
        failures = self.failures(directory)
        self.assertTrue(any("empty reason" in f.message for f in failures), failures)

    def test_an_unknown_reason_is_caught(self):
        directory = build_artifact(self.tmp, excluded={"ca": [
            {"ticker": "TSX:XYZ", "name": "No Cap Co", "exchange": "TSX",
             "reason": "because", "close": 1.0, "volume": 10}
        ]})
        failures = self.failures(directory)
        self.assertTrue(any("is not one of" in f.message for f in failures), failures)

    def test_a_manifest_count_that_disagrees_with_the_file_is_caught(self):
        directory = build_artifact(self.tmp)
        manifest = json.loads((directory / "_manifest.json").read_text())
        manifest["regions"]["ca"]["excluded"]["no_market_cap"] = 7
        (directory / "_manifest.json").write_text(json.dumps(manifest))
        failures = self.failures(directory)
        self.assertTrue(any("_excluded.json has" in f.message for f in failures), failures)

    def test_a_broken_reconciliation_identity_is_caught(self):
        directory = build_artifact(self.tmp)
        manifest = json.loads((directory / "_manifest.json").read_text())
        manifest["regions"]["ca"]["unique_instruments"] = 99
        (directory / "_manifest.json").write_text(json.dumps(manifest))
        failures = self.failures(directory)
        self.assertTrue(any("rows were lost or double-counted" in f.message for f in failures),
                        failures)


class TestSummaryReconciliation(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def failures(self, directory):
        return [f for f in assert_artifact(directory) if f.severity == "FAIL"]

    def test_a_summary_row_absent_from_the_csv_is_caught(self):
        summary = SUMMARY.replace("`TSX:ENB`", "`TSX:GHOST`")
        directory = build_artifact(self.tmp, summary=summary)
        failures = self.failures(directory)
        self.assertTrue(any("fabricated" in f.message for f in failures), failures)

    def test_a_summary_count_that_disagrees_with_the_manifest_is_caught(self):
        summary = SUMMARY.replace(
            "| ca | `TSX:ENB` | Enbridge Inc. | +0.50% | 68.02 CAD | $111.13B | NYSE | a sourced driver |\n", "")
        directory = build_artifact(self.tmp, summary=summary)
        failures = self.failures(directory)
        self.assertTrue(any("the manifest says" in f.message for f in failures), failures)

    def test_a_malformed_price_conflict_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[0][17] = "official 139.60 but the scanner said 138.00"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("does not parse" in f.message for f in failures), failures)

    def test_a_wellformed_price_conflict_passes(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[0][17] = "official=139.60 source=wienerborse third_party=138.00 delta=1.60 (1.16%)"
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertEqual(failures, [])

    def test_a_mover_row_without_a_us_listing_is_caught(self):
        rows = [list(r) for r in ENB_ROWS]
        rows[1][16] = ""
        directory = build_artifact(self.tmp, rows=rows)
        failures = self.failures(directory)
        self.assertTrue(any("us_listing" in f.message for f in failures), failures)


if __name__ == "__main__":
    unittest.main()

"""Raw operations CSVs share SQL classification, scope, and rolling windows."""

from contextlib import redirect_stdout
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from config import ConfigurationError, load_input_config
import main_existing
from repository import InputError, load_yard_inputs
from repository.operations_repository import load_csv_shifting_summary
from repository.shifting_dates import WIB
from tests import test_main_existing as main_tests


CY = "CY 219 (Lini 2)"
HEADER = ("DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT")
ACTIVITIES = {"lifting": ("Lift On Loading",), "shifting": ("Shifting Delivery",)}
NOW = int(datetime(2026, 10, 29, 15, tzinfo=WIB).timestamp())
CUTOFF = 'shifting_cutoff = "2026-10-29T15:00:00+07:00"'


def operation(identifier="1", document="100", activity="Lift On Loading",
              timestamp="29-10-2026 14:30", branch="JKT74", equipment="SL"):
    return identifier, document, activity, timestamp, branch, equipment


def write_csv(path, rows, headers=HEADER):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


class CSVOperationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.path = root / "operations.csv"
        self.mapping = root / "mapping.toml"
        self.mapping.write_text(f'["{CY}"]\nSL = "10"\nRS = "11"\nABSENT = "9"\n', encoding="utf-8")

    def load(self, rows, *, headers=HEADER, blocks=("10", "11"), **kwargs):
        write_csv(self.path, rows, headers)
        return load_csv_shifting_summary(
            self.path, ACTIVITIES, CY, "JKT74", self.mapping, blocks,
            recorded_at=NOW, **kwargs,
        )

    def test_scope_activity_classification_zero_counts_and_diagnostics(self):
        diagnostics = {}
        summaries = self.load([
            operation(equipment=" sl ", branch=" jkt74 "),
            operation(activity="Shifting Delivery"),
            operation(activity="Lift On Delivery"),
            operation(activity="lift on loading"),
            operation(timestamp="bad", branch="OTHER"),
            operation(timestamp="bad", equipment="ABSENT"),
            operation(timestamp="bad", equipment="UNMAPPED"),
            operation(timestamp="bad", identifier=""),
            operation(timestamp="28-10-2026 14:59", activity="Excluded old activity"),
        ], diagnostics=diagnostics)
        self.assertEqual([(r.shifting_code, r.block_id, r.lifting_count, r.shifting_count)
                          for r in summaries], [("SL", "10", 1, 1), ("RS", "11", 0, 0)])
        self.assertEqual(summaries[0].shifting_percentage, 50)
        self.assertIsNone(summaries[1].shifting_percentage)
        self.assertEqual(diagnostics, {"excluded_activities": {"Lift On Delivery": 1, "lift on loading": 1}})

    def test_daily_and_weekly_start_inclusive_end_exclusive_in_wib(self):
        for granularity, start, duration in (
            ("daily", "28-10-2026 15:00", 86400),
            ("weekly", "22-10-2026 15:00", 604800),
        ):
            with self.subTest(granularity=granularity):
                rows = self.load([
                    operation(timestamp=start),
                    operation(timestamp="29-10-2026 14:59"),
                    operation(timestamp="29-10-2026 15:00"),
                    operation(timestamp="21-10-2026 15:00"),
                ], period_granularity=granularity)
                self.assertEqual(rows[0].lifting_count, 2)
                self.assertEqual({(r.period_start, r.period_end) for r in rows}, {(NOW - duration, NOW)})
                self.assertTrue(all(r.report_date is None and r.week_number is None for r in rows))

    def test_counts_operations_without_assuming_detail_ids_or_containers_are_unique(self):
        rows = self.load([operation(), operation(document="101"), operation()])
        self.assertEqual(rows[0].lifting_count, 3)

    def test_multiple_codes_can_contribute_to_one_block(self):
        self.mapping.write_text(f'["{CY}"]\nSL = "10"\nRS = "10"\n', encoding="utf-8")
        rows = self.load([operation(), operation(equipment="RS", activity="Shifting Delivery")])
        self.assertEqual({r.block_id for r in rows}, {"10"})
        self.assertEqual(main_existing.shifting_metrics(rows)["shifting_percentage"], 50)

    def test_no_rows_does_not_fall_back_to_older_operations(self):
        for records in ([], [operation(timestamp="01-01-2020 00:00")]):
            rows = self.load(records)
            self.assertEqual([(r.lifting_count, r.shifting_count) for r in rows], [(0, 0), (0, 0)])

    def test_no_loaded_blocks_ignores_invalid_activity_times(self):
        self.assertEqual(self.load([operation(timestamp="bad")], blocks=iter(())), [])

    def test_invalid_dates_report_location(self):
        for value in ("", "2026-10-29 14:30", "31-02-2026 12:00"):
            with self.subTest(value=value), self.assertRaisesRegex(InputError, "line 2.*ACTIVITY_DATE_TIME"):
                self.load([operation(timestamp=value)])

    def test_headers_allow_case_whitespace_and_extra_unique_columns(self):
        headers = tuple(" " + name.lower() + " " for name in HEADER) + ("CONTAINER_NO",)
        rows = self.load([operation() + ("SAME-CONTAINER",)], headers=headers)
        self.assertEqual(rows[0].lifting_count, 1)

    def test_missing_duplicate_headers_and_malformed_rows_fail(self):
        for headers, rows in (
            (HEADER[:-1], [operation()[:-1]]),
            (HEADER + ("doc_id",), [operation() + ("100",)]),
            (HEADER, [operation()[:-1]]),
            (HEADER, [operation() + ("extra",)]),
            ((), []),
        ):
            with self.subTest(headers=headers, rows=rows), self.assertRaises(InputError):
                self.load(rows, headers=headers)


class CSVOperationsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.set_source("shifting_summary", "csv")
        self.path = self.fixture.input_path
        self.csv_path = self.fixture.root / "operations.csv"
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace(
            "[csv]", '[csv]\nshifting_operations_file = "operations.csv"\n' + CUTOFF,
        ), encoding="utf-8")
        write_csv(self.csv_path, [operation(), operation(activity="Shifting Delivery"),
                                  operation(activity="Lift On Delivery")])

    def settings(self):
        return load_input_config(self.path, datasets=main_existing.EXISTING_YARD_DATASETS)

    def test_csv_config_and_shared_loader_need_no_sql_or_workbook(self):
        self.fixture.shifting_path.unlink()
        with patch.dict("sys.modules", {"psycopg": None}), patch.dict("os.environ", {}, clear=True):
            settings = self.settings()
            rows = load_yard_inputs(settings)["shifting_summary"]
        self.assertEqual(settings["shifting_operations_file"], self.csv_path)
        self.assertEqual(settings["shifting_csv_cutoff"], NOW)
        self.assertNotIn("shifting_workbook_file", settings)
        self.assertNotIn("shifting_period", settings)
        self.assertNotIn("connection", settings)
        self.assertEqual(sum(r.lifting_count for r in rows), 1)
        self.assertEqual(sum(r.shifting_count for r in rows), 1)
        write_csv(self.csv_path, [operation(), operation()])
        updated = load_yard_inputs(settings)["shifting_summary"]
        self.assertEqual(sum(r.lifting_count for r in updated), 2)

    def test_historical_cutoff_report_jsonl_and_presenter(self):
        with patch.object(main_existing, "time", return_value=NOW + 10 * 86400):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["recorded_at"], NOW + 10 * 86400)
        self.assertEqual((report["period_start"], report["period_end"]), (NOW - 86400, NOW))
        self.assertEqual(report["input_sources"]["shifting_summary"], "csv")
        self.assertEqual(report["shifting_source"], str(self.csv_path))
        self.assertIsNone(report["shifting_workbook_source"])
        self.assertEqual(report["operations_period_basis"], "rolling_window")
        self.assertEqual(report["operations_completeness"], "unverified")
        self.assertEqual(report["excluded_activities"], {"Lift On Delivery": 1})
        self.assertEqual(report["shifting_percentage"], 50)
        self.assertNotIn("latest_date", report)
        json.dumps(report, allow_nan=False)
        output = io.StringIO()
        with patch.object(main_existing, "_build_report_and_yard", return_value=(report, None)), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.fixture.root / "config" / "input.toml",
        ), patch.object(main_existing.YardPresenter, "outYard"), redirect_stdout(output):
            main_existing.main()
        saved = json.loads((self.fixture.root / "output" / "existing_yard_metrics.jsonl").read_text())
        self.assertEqual(saved, report)
        self.assertIn("Operations window: last 24 hours", output.getvalue())
        self.assertIn("Lift On Delivery", output.getvalue())
        self.assertIn("period_start period_end shifting_code", output.getvalue())

    def test_no_cutoff_defaults_to_recording_time_and_weekly_is_shared(self):
        text = self.path.read_text(encoding="utf-8").replace(CUTOFF, "")
        self.path.write_text(text.replace('period_granularity = "daily"', 'period_granularity = "weekly"'),
                             encoding="utf-8")
        with patch.object(main_existing, "time", return_value=NOW):
            report = main_existing.build_report(self.path)
        self.assertEqual((report["period_start"], report["period_end"]), (NOW - 604800, NOW))
        output = io.StringIO()
        with redirect_stdout(output):
            main_existing.YardPresenter().outRecordedMetrics(report)
        self.assertIn("Operations window: last 7 days", output.getvalue())

    def test_cutoff_requires_explicit_timezone_and_valid_iso_timestamp(self):
        original = self.path.read_text(encoding="utf-8")
        for value in ('"2026-10-29T15:00:00"', '"2026-10-29"', '"bad"', '123', '""'):
            with self.subTest(value=value):
                self.path.write_text(original.replace(CUTOFF, "shifting_cutoff = " + value), encoding="utf-8")
                with self.assertRaisesRegex(ConfigurationError, "shifting_cutoff.*timezone"):
                    self.settings()

    def test_missing_csv_path_and_missing_activity_lists_are_errors(self):
        original = self.path.read_text(encoding="utf-8")
        for old, new, error in (
            ('shifting_operations_file = "operations.csv"', '', 'shifting_operations_file'),
            ('shifting_operations_file = "operations.csv"', 'shifting_operations_file = ""', 'shifting_operations_file'),
        ):
            with self.subTest(old=old, new=new):
                self.path.write_text(original.replace(old, new), encoding="utf-8")
                with self.assertRaisesRegex(ConfigurationError, error):
                    self.settings()
        self.path.write_text(original, encoding="utf-8")
        document = tomllib.loads(original)
        del document["shifting"]["activities"]["lifting"]
        with patch("config.application.input_config._read_document", return_value=document):
            with self.assertRaisesRegex(ConfigurationError, "activities.lifting"):
                self.settings()

    def test_shared_activity_configuration_can_include_delivery_lifting(self):
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace('lifting = [', 'lifting = ["Lift On Delivery",'), encoding="utf-8")
        report = main_existing.build_report(self.path)
        self.assertEqual(report["lifting_count"], 2)
        self.assertEqual(report["shifting_count"], 1)
        self.assertEqual(report["excluded_activities"], {})

    def test_csv_operations_can_accompany_sql_yard_data(self):
        driver, connection, cursor = self.fixture.sql_existing()
        report = main_existing.build_report(self.path)
        self.assertEqual(report["input_sources"]["existing_containers"], "sql")
        self.assertEqual(report["input_sources"]["shifting_summary"], "csv")
        self.assertEqual(report["lifting_count"], 1)
        self.assertEqual(report["shifting_count"], 1)
        driver.connect.assert_called_once()
        cursor.execute.assert_called_once()
        self.assertTrue(connection.read_only)

    def test_empty_loaded_yard_keeps_window_without_inventing_counts(self):
        from types import SimpleNamespace

        yard = SimpleNamespace(containers={}, blocks_by_id={},
                               bad_data=SimpleNamespace(anyBadData=lambda: False))
        with patch.object(main_existing, "Yard", return_value=yard):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual((report["period_start"], report["period_end"]), (NOW - 86400, NOW))
        self.assertIsNone(report["shifting_count"])

    def test_invalid_csv_does_not_fall_back_or_write_jsonl(self):
        self.csv_path.write_text("invalid CSV", encoding="utf-8")
        with patch("repository.operations_input.load_shifting_summary") as workbook, patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.path,
        ), self.assertRaises(InputError):
            main_existing.main()
        workbook.assert_not_called()
        self.assertFalse((self.fixture.root / "output" / "existing_yard_metrics.jsonl").exists())


if __name__ == "__main__":
    unittest.main()

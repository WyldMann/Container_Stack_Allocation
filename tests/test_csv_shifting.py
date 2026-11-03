"""CSV operations use the first scoped activity window, independent of row order."""

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

from config import ConfigurationError, DEFAULT_INPUT_CONFIG_FILE, load_input_config
import main_existing
from repository import InputError, load_yard_inputs
from repository.operations_repository import load_csv_shifting_summary
from repository.shifting_dates import WIB
from tests import test_main_existing as main_tests


CY = "CY 219 (Lini 2)"
HEADER = ("DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT")
ACTIVITIES = {"lifting": ("Lift On Loading",), "shifting": ("Shifting Delivery",)}
NOW = int(datetime(2026, 10, 29, 15, tzinfo=WIB).timestamp())
START = int(datetime(2026, 10, 29, 14, 30, tzinfo=WIB).timestamp())


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
            **kwargs,
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
            operation(timestamp="30-10-2026 14:30", activity="Excluded later activity"),
        ], diagnostics=diagnostics)
        self.assertEqual([(r.shifting_code, r.block_id, r.lifting_count, r.shifting_count)
                          for r in summaries], [("SL", "10", 1, 1), ("RS", "11", 0, 0)])
        self.assertEqual(summaries[0].shifting_percentage, 50)
        self.assertIsNone(summaries[1].shifting_percentage)
        self.assertEqual(diagnostics, {"excluded_activities": {"Lift On Delivery": 1, "lift on loading": 1}})

    def test_first_daily_and_seven_day_windows_are_order_independent_and_end_exclusive(self):
        def text(timestamp):
            return datetime.fromtimestamp(timestamp, WIB).strftime("%d-%m-%Y %H:%M")

        for granularity, duration, expected in (
            ("daily", 86400, 2),
            ("weekly", 7 * 86400, 3),
        ):
            with self.subTest(granularity=granularity):
                rows = self.load([
                    operation(timestamp=text(START + duration + 3600)),
                    operation(timestamp=text(START + duration - 60)),
                    operation(timestamp=text(START + duration)),
                    operation(timestamp=text(START)),
                    operation(timestamp=text(START + 2 * 86400)),
                    operation(timestamp="01-01-2020 00:00", branch="OTHER"),
                    operation(timestamp="01-01-2020 00:00", equipment="ABSENT"),
                    operation(timestamp="01-01-2020 00:00", equipment="UNMAPPED"),
                    operation(timestamp="01-01-2020 00:00", identifier=""),
                ], period_granularity=granularity)
                self.assertEqual(rows[0].lifting_count, expected)
                self.assertEqual({(r.period_start, r.period_end) for r in rows}, {(START, START + duration)})
                self.assertTrue(all(r.report_date is None and r.week_number is None for r in rows))

    def test_all_codes_share_one_window_instead_of_starting_at_each_codes_first_activity(self):
        rows = self.load([operation(equipment="RS", timestamp="31-10-2026 14:30"), operation()])
        self.assertEqual([(r.lifting_count, r.shifting_count) for r in rows], [(1, 0), (0, 0)])
        self.assertEqual({r.period_start for r in rows}, {START})

    def test_excluded_activity_can_anchor_window_with_zero_classified_counts(self):
        diagnostics = {}
        rows = self.load([operation(activity="Lift On Delivery"),
                          operation(timestamp="30-10-2026 14:30")], diagnostics=diagnostics)
        self.assertEqual([(r.lifting_count, r.shifting_count) for r in rows], [(0, 0), (0, 0)])
        self.assertEqual(rows[0].period_start, START)
        self.assertEqual(diagnostics, {"excluded_activities": {"Lift On Delivery": 1}})

    def test_counts_operations_without_assuming_detail_ids_or_containers_are_unique(self):
        rows = self.load([operation(), operation(document="101"), operation()])
        self.assertEqual(rows[0].lifting_count, 3)

    def test_multiple_codes_can_contribute_to_one_block(self):
        self.mapping.write_text(f'["{CY}"]\nSL = "10"\nRS = "10"\n', encoding="utf-8")
        rows = self.load([operation(), operation(equipment="RS", activity="Shifting Delivery")])
        self.assertEqual({r.block_id for r in rows}, {"10"})
        self.assertEqual(main_existing.shifting_metrics(rows)["shifting_percentage"], 50)

    def test_no_scoped_rows_produces_no_window_or_observations(self):
        for records in ([], [operation(branch="OTHER")], [operation(identifier="")]):
            self.assertEqual(self.load(records), [])

    def test_historical_operations_do_not_depend_on_recording_time(self):
        rows = self.load([operation(timestamp="01-01-2020 00:00")])
        self.assertEqual(rows[0].lifting_count, 1)
        self.assertEqual(rows[0].period_start, int(datetime(2020, 1, 1, tzinfo=WIB).timestamp()))

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


class CSVOperationsConfigTests(unittest.TestCase):
    def setUp(self):
        self.document = tomllib.loads(DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8"))
        self.document["csv"]["files"]["shifting_summary"] = "../operations.csv"

    def settings(self):
        with patch("config.application.input_config._read_document", return_value=self.document):
            return load_input_config(DEFAULT_INPUT_CONFIG_FILE)

    def test_operations_path_uses_shared_csv_files_and_config_directory(self):
        settings = self.settings()
        self.assertEqual(settings["csv_files"]["shifting_summary"],
                         (DEFAULT_INPUT_CONFIG_FILE.parent / "../operations.csv").resolve())
        self.assertNotIn("shifting_operations_file", settings)

    def test_workbook_settings_are_not_read_for_csv_operations(self):
        self.document["csv"]["shifting_workbook_file"] = []
        self.document["csv"]["shifting_workbook_sheet"] = []
        settings = self.settings()
        self.assertNotIn("shifting_workbook_file", settings)
        self.assertNotIn("shifting_workbook_sheet", settings)
        self.assertIn("shifting_summary", settings["csv_files"])

    def test_csv_operations_path_is_required_and_validated(self):
        for value in ("", 123, None):
            with self.subTest(value=value):
                self.document["csv"]["files"]["shifting_summary"] = value
                with self.assertRaisesRegex(ConfigurationError, "csv.files.shifting_summary"):
                    self.settings()
        del self.document["csv"]["files"]["shifting_summary"]
        with self.assertRaisesRegex(ConfigurationError, "csv.files.*shifting_summary"):
            self.settings()

    def test_obsolete_standalone_csv_path_is_rejected(self):
        self.document["csv"]["shifting_operations_file"] = "old.csv"
        with self.assertRaisesRegex(ConfigurationError, "shifting_operations_file"):
            self.settings()

    def test_xlsx_source_does_not_require_or_load_csv_operations_path(self):
        self.document["input"]["sources"]["shifting_summary"] = "xlsx"
        del self.document["csv"]["files"]["shifting_summary"]
        self.document["csv"]["shifting_workbook_file"] = "source.xlsx"
        settings = self.settings()
        self.assertNotIn("shifting_summary", settings["csv_files"])
        self.assertEqual(settings["shifting_workbook_file"], DEFAULT_INPUT_CONFIG_FILE.parent / "source.xlsx")

    def test_only_operations_csv_with_sql_yard_needs_no_csv_mapping(self):
        self.document["input"]["sources"] = {
            name: "sql" if name != "shifting_summary" else "csv"
            for name in self.document["input"]["sources"]
        }
        self.document["csv"].pop("mapping_file", None)
        sql_mapping = tomllib.loads(DEFAULT_INPUT_CONFIG_FILE.with_name("sql_mapping.toml").read_text(encoding="utf-8"))
        with patch("config.application.input_config._read_document", side_effect=[self.document, sql_mapping]), patch.dict(
            "os.environ", {"YARD_DB_HOST": "example", "YARD_DB_NAME": "test", "YARD_DB_USER": "reader"},
        ):
            settings = load_input_config(DEFAULT_INPUT_CONFIG_FILE)
        self.assertEqual(set(settings["csv_files"]), {"shifting_summary"})
        self.assertNotIn("csv", settings["mapping_files"])

    def test_dispatch_uses_path_from_csv_files(self):
        from types import SimpleNamespace
        from repository.operations_input import load_operations

        settings = self.settings()
        branches = SimpleNamespace(cy_name=lambda: CY, records=[{"branch_code": "JKT74"}])
        with patch("repository.operations_input.load_csv_shifting_summary", return_value=[]) as loader:
            self.assertEqual(load_operations(settings, branches, {"10"}), [])
        self.assertEqual(loader.call_args.args[0], settings["csv_files"]["shifting_summary"])


class CSVOperationsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.set_source("shifting_summary", "csv")
        self.path = self.fixture.input_path
        self.csv_path = self.fixture.root / "operations.csv"
        text = self.path.read_text(encoding="utf-8")
        configured = tomllib.loads(text)["csv"]["files"].get("shifting_summary")
        if configured is not None:
            text = text.replace('shifting_summary = "' + configured + '"', '')
        self.path.write_text(text.replace(
            "[csv.files]", '[csv.files]\nshifting_summary = "operations.csv"',
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
        self.assertEqual(settings["csv_files"]["shifting_summary"], self.csv_path)
        self.assertNotIn("shifting_operations_file", settings)
        self.assertNotIn("shifting_workbook_file", settings)
        self.assertNotIn("shifting_period", settings)
        self.assertNotIn("connection", settings)
        self.assertEqual(sum(r.lifting_count for r in rows), 1)
        self.assertEqual(sum(r.shifting_count for r in rows), 1)
        write_csv(self.csv_path, [operation(), operation()])
        updated = load_yard_inputs(settings)["shifting_summary"]
        self.assertEqual(sum(r.lifting_count for r in updated), 2)

    def test_first_activity_window_report_jsonl_and_presenter(self):
        with patch.object(main_existing, "time", return_value=NOW + 10 * 86400):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["recorded_at"], NOW + 10 * 86400)
        self.assertEqual((report["period_start"], report["period_end"]), (START, START + 86400))
        self.assertEqual(report["input_sources"]["shifting_summary"], "csv")
        self.assertEqual(report["shifting_source"], str(self.csv_path))
        self.assertIsNone(report["shifting_workbook_source"])
        self.assertEqual(report["operations_period_basis"], "first_activity_window")
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
        self.assertIn("Operations window: first 24 hours", output.getvalue())
        self.assertIn("Lift On Delivery", output.getvalue())
        self.assertIn("period_start period_end shifting_code", output.getvalue())

    def test_weekly_report_uses_first_seven_days(self):
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace('period_granularity = "daily"', 'period_granularity = "weekly"'),
                             encoding="utf-8")
        with patch.object(main_existing, "time", return_value=NOW):
            report = main_existing.build_report(self.path)
        self.assertEqual((report["period_start"], report["period_end"]), (START, START + 7 * 86400))
        output = io.StringIO()
        with redirect_stdout(output):
            main_existing.YardPresenter().outRecordedMetrics(report)
        self.assertIn("Operations window: first 7 days", output.getvalue())

    def test_old_cutoff_setting_is_rejected_instead_of_silently_overriding_first_window(self):
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace('[csv]', '[csv]\nshifting_cutoff = "2026-10-29T15:00:00+07:00"'),
                             encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "shifting_cutoff"):
            self.settings()

    def test_missing_csv_path_and_missing_activity_lists_are_errors(self):
        original = self.path.read_text(encoding="utf-8")
        for old, new, error in (
            ('shifting_summary = "operations.csv"', '', 'shifting_summary'),
            ('shifting_summary = "operations.csv"', 'shifting_summary = ""', 'csv.files.shifting_summary'),
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

    def test_empty_loaded_yard_does_not_invent_a_window_or_counts(self):
        from types import SimpleNamespace

        yard = SimpleNamespace(containers={}, blocks_by_id={},
                               bad_data=SimpleNamespace(anyBadData=lambda: False))
        with patch.object(main_existing, "Yard", return_value=yard):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual((report["period_start"], report["period_end"]), (None, None))
        self.assertIsNone(report["shifting_count"])

    def test_empty_csv_report_does_not_invent_a_window(self):
        write_csv(self.csv_path, [])
        report = main_existing.build_report(self.path)
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual((report["period_start"], report["period_end"]), (None, None))
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

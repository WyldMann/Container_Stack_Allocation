"""CSV operations use the most recent scoped activity window, independent of row order."""

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
from config.application.shifting_input import shifting_settings
import main_existing
from repository import InputError, load_yard_inputs
from repository.operations_repository import load_csv_shifting_summary
from repository.shifting_dates import WIB
from tests import test_main_existing as main_tests


CY = "CY 219 (Lini 2)"
HEADER = ("DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT")
ACTIVITIES = {"lifting": ("Lift On Loading",), "shifting": ("Shifting Delivery",)}
NOW = int(datetime(2026, 10, 29, 15, tzinfo=WIB).timestamp())
LATEST = int(datetime(2026, 10, 29, 14, 30, tzinfo=WIB).timestamp())


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
        self.mapping.write_text(f'["{CY}"]\nSL = "B"\nRS = "C"\nABSENT = "9"\n', encoding="utf-8")

    def load(self, rows, *, headers=HEADER, blocks=("10", "11"), activities=ACTIVITIES, **kwargs):
        write_csv(self.path, rows, headers)
        return load_csv_shifting_summary(
            self.path, activities, CY, "JKT74", self.mapping,
            [{"block_id": block, "block_code": {"10": "B", "11": "C"}[block]} for block in blocks],
            **kwargs,
        )

    def test_same_equipment_is_paired_with_branch_for_mapping_counts_and_window(self):
        self.mapping.write_text('[JKT74]\nSL = "B"\n[OTHER]\nSL = "C"\n', encoding="utf-8")
        write_csv(self.path, [
            operation(),
            operation(branch="OTHER", activity="Shifting Delivery", timestamp="31-10-2026 14:30"),
        ])
        blocks = [{"block_id": "10", "block_code": "B"}, {"block_id": "11", "block_code": "C"}]
        results = [load_csv_shifting_summary(
            self.path, ACTIVITIES, CY, branch, self.mapping, blocks,
        )[0] for branch in (" jkt74 ", "OTHER")]
        self.assertEqual([(r.branch_code, r.shifting_code, r.block_id, r.lifting_count, r.shifting_count)
                          for r in results], [("JKT74", "SL", "10", 1, 0), ("OTHER", "SL", "11", 0, 1)])
        self.assertEqual(results[0].period_end, LATEST)
        self.assertEqual(results[1].period_end, LATEST + 2 * 86400)

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
            operation(timestamp="28-10-2026 14:30", activity="Excluded older activity"),
        ], diagnostics=diagnostics)
        self.assertEqual([(r.shifting_code, r.block_id, r.lifting_count, r.shifting_count)
                          for r in summaries], [("SL", "10", 2, 1), ("RS", "11", 0, 0)])
        self.assertAlmostEqual(summaries[0].shifting_percentage, 100 / 3)
        self.assertIsNone(summaries[1].shifting_percentage)
        self.assertEqual(diagnostics, {"excluded_activities": {"Lift On Delivery": 1}})

    def test_multiple_mapped_blocks_do_not_duplicate_equipment_counts(self):
        self.mapping.write_text('[JKT74]\nSL = ["B", "C", "B", "99"]\n', encoding="utf-8")
        rows = self.load([operation(), operation(activity="Shifting Delivery")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mapped_block_ids, ("10", "11"))
        self.assertEqual((rows[0].lifting_count, rows[0].shifting_count), (1, 1))

    def test_all_eight_requested_activity_names_are_counted_with_default_configuration(self):
        document = tomllib.loads(DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8"))
        _, activities = shifting_settings(document, activities_required=True)
        labels = (
            "Lift On Delivery", "Shifting", "Lift Off Discharge", "Lift on Relokasi",
            "Lift on Loading", "Shifting Delivery", "Lift Off Receiving", "Shifting Muat",
        )
        for transform in (str, str.lower, str.upper):
            with self.subTest(case=transform.__name__):
                diagnostics = {}
                rows = self.load([operation(activity=transform(label)) for label in labels],
                                 activities=activities, diagnostics=diagnostics)
                self.assertEqual((rows[0].lifting_count, rows[0].shifting_count), (5, 3))
                self.assertEqual(rows[0].shifting_percentage, 37.5)
                self.assertEqual(diagnostics, {"excluded_activities": {}})

    def test_latest_daily_and_seven_day_windows_ignore_row_order_and_include_latest_timestamp(self):
        def text(timestamp):
            return datetime.fromtimestamp(timestamp, WIB).strftime("%d-%m-%Y %H:%M")

        for granularity, duration, expected in (
            ("daily", 86400, 2),
            ("weekly", 7 * 86400, 3),
        ):
            with self.subTest(granularity=granularity):
                rows = self.load([
                    operation(timestamp=text(LATEST - duration - 3600)),
                    operation(timestamp=text(LATEST - duration + 60)),
                    operation(timestamp=text(LATEST - duration)),
                    operation(timestamp=text(LATEST)),
                    operation(timestamp=text(LATEST - 2 * 86400)),
                    operation(timestamp="01-01-2030 00:00", branch="OTHER"),
                    operation(timestamp="01-01-2030 00:00", equipment="ABSENT"),
                    operation(timestamp="01-01-2030 00:00", equipment="UNMAPPED"),
                    operation(timestamp="01-01-2030 00:00", identifier=""),
                ], period_granularity=granularity)
                self.assertEqual(rows[0].lifting_count, expected)
                self.assertEqual({(r.period_start, r.period_end) for r in rows}, {(LATEST - duration, LATEST)})
                self.assertTrue(all(r.report_date is None and r.week_number is None for r in rows))

    def test_all_codes_share_one_window_ending_at_the_latest_equipment_activity(self):
        rows = self.load([operation(equipment="RS", timestamp="31-10-2026 14:30"), operation()])
        self.assertEqual([(r.lifting_count, r.shifting_count) for r in rows], [(0, 0), (1, 0)])
        self.assertEqual({r.period_end for r in rows}, {LATEST + 2 * 86400})

    def test_excluded_activity_can_anchor_window_with_zero_classified_counts(self):
        diagnostics = {}
        rows = self.load([operation(timestamp="30-10-2026 14:30", activity="Lift On Delivery"),
                          operation()], diagnostics=diagnostics)
        self.assertEqual([(r.lifting_count, r.shifting_count) for r in rows], [(0, 0), (0, 0)])
        self.assertEqual(rows[0].period_end, LATEST + 86400)
        self.assertEqual(diagnostics, {"excluded_activities": {"Lift On Delivery": 1}})

    def test_counts_operations_without_assuming_detail_ids_or_containers_are_unique(self):
        rows = self.load([operation(), operation(document="101"), operation()])
        self.assertEqual(rows[0].lifting_count, 3)

    def test_multiple_codes_can_contribute_to_one_block(self):
        self.mapping.write_text(f'["{CY}"]\nSL = "B"\nRS = "B"\n', encoding="utf-8")
        rows = self.load([operation(), operation(equipment="RS", activity="Shifting Delivery")])
        self.assertEqual({r.block_id for r in rows}, {"10"})
        self.assertEqual(main_existing.shifting_metrics(rows)["shifting_percentage"], 50)

    def test_no_scoped_rows_produces_no_window_or_observations(self):
        for records in ([], [operation(branch="OTHER")], [operation(identifier="")]):
            self.assertEqual(self.load(records), [])

    def test_historical_operations_do_not_depend_on_recording_time(self):
        rows = self.load([operation(timestamp="01-01-2020 00:00")])
        self.assertEqual(rows[0].lifting_count, 1)
        self.assertEqual(rows[0].period_end, int(datetime(2020, 1, 1, tzinfo=WIB).timestamp()))

    def test_no_loaded_blocks_ignores_invalid_activity_times(self):
        self.assertEqual(self.load([operation(timestamp="bad")], blocks=iter(())), [])

    def test_invalid_dates_report_location(self):
        for value in ("2026-10-29 14:30", "31-02-2026 12:00", "31/02/2026 12:00", "10/29/2026 14:30"):
            with self.subTest(value=value), self.assertRaisesRegex(InputError, "line 2.*ACTIVITY_DATE_TIME"):
                self.load([operation(timestamp=value)])

    def test_slash_and_hyphen_dates_are_day_first_in_wib(self):
        expected = int(datetime(2026, 10, 1, 10, 33, tzinfo=WIB).timestamp())
        for value in ("1/10/2026 10:33", "01/10/2026 10:33", "1-10-2026 10:33"):
            with self.subTest(value=value):
                rows = self.load([operation(timestamp=value), operation(timestamp="01-10-2026 10:33")])
                self.assertEqual(rows[0].lifting_count, 2)
                self.assertEqual(rows[0].period_end, expected)

    def test_mixed_date_separators_preserve_latest_window_and_inclusive_end(self):
        rows = self.load([
            operation(timestamp="2/10/2026 10:33"),
            operation(timestamp="01-10-2026 10:33"),
            operation(timestamp="2/10/2026 10:32", activity="Shifting Delivery"),
        ])
        self.assertEqual((rows[0].lifting_count, rows[0].shifting_count), (1, 1))
        self.assertEqual(rows[0].period_end - rows[0].period_start, 86400)

    def test_blank_activity_times_are_skipped_when_selecting_and_counting_window(self):
        for granularity, duration in (("daily", 86400), ("weekly", 7 * 86400)):
            with self.subTest(granularity=granularity):
                diagnostics = {}
                rows = self.load([
                    operation(timestamp=""),
                    operation(),
                    operation(timestamp=" \t ", activity="Shifting Delivery"),
                    operation(activity="Shifting Delivery"),
                    operation(timestamp="", activity="Unclassified"),
                ], period_granularity=granularity, diagnostics=diagnostics)
                self.assertEqual(rows[0].lifting_count, 1)
                self.assertEqual(rows[0].shifting_count, 1)
                self.assertEqual({(r.period_start, r.period_end) for r in rows}, {(LATEST - duration, LATEST)})
                self.assertEqual(diagnostics, {"excluded_activities": {}})

    def test_only_blank_activity_times_returns_no_observations(self):
        self.assertEqual(self.load([operation(timestamp=""), operation(timestamp=" \t ")]), [])

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
            self.assertEqual(load_operations(settings, branches, [{"block_id": "10", "block_code": "B"}]), [])
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
        # Assign equipment using the selected yard block codes.
        yard_inputs = load_yard_inputs(self.settings(), include_shifting=False)
        block_codes = [row["block_code"] for row in yard_inputs["yard_blocks"]]
        self.fixture.mapping_path.write_text(
            f'["{CY}"]\nSL = "{block_codes[0]}"\nRS = "{block_codes[-1]}"\n', encoding="utf-8",
        )

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
        self.assertEqual(sum(r.lifting_count for r in rows), 2)
        self.assertEqual(sum(r.shifting_count for r in rows), 1)
        write_csv(self.csv_path, [operation(), operation()])
        updated = load_yard_inputs(settings)["shifting_summary"]
        self.assertEqual(sum(r.lifting_count for r in updated), 2)

    def test_latest_activity_window_report_jsonl_and_presenter(self):
        with patch.object(main_existing, "time", return_value=NOW + 10 * 86400):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["generated_at"], NOW + 10 * 86400)
        self.assertEqual((report["period_start"], report["period_end"]), (LATEST - 86400, LATEST))
        self.assertAlmostEqual(report["avg_shifting_percentage"], 100 / 3)
        self.assertEqual(report["latest_date"], "2026-10-29")
        self.assertEqual(list(report), [
            "cy_name", "branch_code", "generated_at", "period_start", "period_end", "latest_date", "period_granularity",
            "avg_shifting_percentage", "avg_parameter_compliance", "shifting_observations",
        ])
        json.dumps(report, allow_nan=False)
        output = io.StringIO()
        with patch.object(main_existing, "_build_reports_and_yards", return_value={"JKT74": (report, None)}), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.fixture.root / "config" / "input.toml",
        ), patch.object(main_existing.YardPresenter, "outYard"), redirect_stdout(output):
            main_existing.main()
        saved = json.loads((self.fixture.root / "output" / "existing_yard_metrics_JKT74.jsonl").read_text())
        self.assertEqual(saved, report)
        self.assertIn("latest_date is in WIB", output.getvalue())
        self.assertIn("parameter compliance use 0-100", output.getvalue())
        self.assertNotIn("Lift On Delivery", output.getvalue())
        self.assertIn("block_code assigned_equipment", output.getvalue())
        lines = output.getvalue().splitlines()
        index = lines.index("JSONL metrics row:")
        fields = lines[index + 1].split()
        values = lines[index + 2].rsplit(maxsplit=len(fields) - 1)
        displayed = dict(zip(fields, values, strict=True))
        self.assertEqual(displayed["latest_date"], saved["latest_date"])
        self.assertEqual(float(displayed["avg_parameter_compliance"]), saved["avg_parameter_compliance"])

    def test_csv_date_uses_window_end_in_wib_for_daily_and_weekly_reports(self):
        original = self.path.read_text(encoding="utf-8")
        write_csv(self.csv_path, [operation(timestamp="01-11-2026 00:15")])
        for granularity in ("daily", "weekly"):
            with self.subTest(granularity=granularity):
                self.path.write_text(original.replace(
                    'period_granularity = "daily"', f'period_granularity = "{granularity}"',
                ), encoding="utf-8")
                with patch.object(main_existing, "time", return_value=NOW):
                    report = main_existing.build_report(self.path)
                self.assertEqual(report["latest_date"], "2026-11-01")
                self.assertNotIn("report_month", report)

    def test_weekly_report_uses_latest_seven_days(self):
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace('period_granularity = "daily"', 'period_granularity = "weekly"'),
                             encoding="utf-8")
        with patch.object(main_existing, "time", return_value=NOW):
            report = main_existing.build_report(self.path)
        self.assertEqual((report["period_start"], report["period_end"]), (LATEST - 7 * 86400, LATEST))
        output = io.StringIO()
        with redirect_stdout(output):
            main_existing.YardPresenter().outRecordedMetrics(report)
        self.assertIn("weekly", output.getvalue())

    def test_old_cutoff_setting_is_rejected_instead_of_silently_overriding_latest_window(self):
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

    def test_shared_activity_configuration_matches_different_capitalization(self):
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace('"Lift On Delivery"', '"lift on delivery"'), encoding="utf-8")
        report = main_existing.build_report(self.path)
        self.assertEqual(sum(row["lifting_count"] for row in report["shifting_observations"]), 2)
        self.assertEqual(sum(row["shifting_count"] for row in report["shifting_observations"]), 1)
        self.assertAlmostEqual(report["avg_shifting_percentage"], 100 / 3)

    def test_csv_operations_can_accompany_sql_yard_data(self):
        driver, connection, cursor = self.fixture.sql_existing()
        report = main_existing.build_report(self.path)
        self.assertEqual(sum(row["lifting_count"] for row in report["shifting_observations"]), 2)
        self.assertEqual(sum(row["shifting_count"] for row in report["shifting_observations"]), 1)
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
        self.assertIsNone(report["avg_shifting_percentage"])
        self.assertIsNone(report["latest_date"])
        self.assertIsNone(report["avg_parameter_compliance"])

    def test_empty_csv_report_does_not_invent_a_window(self):
        write_csv(self.csv_path, [])
        report = main_existing.build_report(self.path)
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual((report["period_start"], report["period_end"]), (None, None))
        self.assertIsNone(report["avg_shifting_percentage"])
        self.assertIsNone(report["latest_date"])
        self.assertIsNotNone(report["avg_parameter_compliance"])

    def test_invalid_csv_does_not_fall_back_or_write_jsonl(self):
        self.csv_path.write_text("invalid CSV", encoding="utf-8")
        with patch("repository.operations_input.load_shifting_summary") as workbook, patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.path,
        ), self.assertRaises(InputError):
            main_existing.main()
        workbook.assert_not_called()
        self.assertFalse((self.fixture.root / "output" / "existing_yard_metrics_JKT74.jsonl").exists())


if __name__ == "__main__":
    unittest.main()

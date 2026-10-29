"""SQL operations use the same branch, block scope and recorded metrics as the yard."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from config import ConfigurationError, load_input_config
from config.application.shifting_input import sql_shifting_settings
import main_existing
from repository import InputError, load_yard_inputs
from repository.sql_shifting_repository import load_sql_shifting_summary, operations_count_query, sql_period_boundaries
from repository.shifting_dates import daily_boundaries
from tests import test_main_existing as main_tests


ENVIRONMENT = {
    "YARD_DB_HOST": "db.example.test", "YARD_DB_NAME": "yard_test",
    "YARD_DB_USER": "reader", "YARD_DB_PASSWORD": "test-password",
}
NOW = daily_boundaries(date(2026, 10, 29))[0] + 15 * 3600 + 16 * 60 + 17
START, END = NOW - 86400, NOW


class SQLShiftingFixture:
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.input_path
        self.fixture.set_source("shifting_summary", "sql")
        environment = patch.dict(os.environ, ENVIRONMENT)
        environment.start()
        self.addCleanup(environment.stop)

    def settings(self):
        return load_input_config(self.path, datasets=main_existing.EXISTING_YARD_DATASETS)


class SQLShiftingConfigTests(SQLShiftingFixture, unittest.TestCase):
    def test_sql_operations_alone_require_sql_settings_and_skip_csv_workbook(self):
        source = self.path.read_text(encoding="utf-8")
        self.path.write_text(source.replace(
            '[csv]', '[csv]\nshifting_workbook_file = "missing.xlsx"',
        ), encoding="utf-8")
        settings = self.settings()
        self.assertEqual(set(settings["sources"].values()), {"csv"})
        self.assertEqual(settings["shifting_source"], "sql")
        self.assertEqual(settings["shifting_granularity"], "daily")
        self.assertEqual(settings["sql_shifting"]["schema"], "REPORT")
        self.assertEqual(settings["sql_shifting"]["header_columns"]["equipment_code"], "ALAT")
        self.assertNotIn("shifting_summary_file", settings)
        self.assertNotIn("shifting_workbook_file", settings)
        self.assertEqual(settings["shifting_block_mapping_file"], self.fixture.mapping_path.resolve())
        self.assertEqual(settings["shifting_activities"]["lifting"], (
            "Lift On Loading", "Lift On Relokasi", "Lift Off Receiving", "Lift Off Discharge",
        ))
        self.assertEqual(settings["shifting_activities"]["shifting"], ("Shifting Delivery", "Shifting Muat"))
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ConfigurationError, "YARD_DB_HOST"):
            self.settings()

    def test_excluded_period_selection_and_invalid_activity_settings_fail(self):
        original = self.path.read_text(encoding="utf-8")
        replacements = (
            ('[shifting]', '[shifting]\nperiod_selection = "latest_complete_day"'),
            ('period_granularity = "daily"', 'period_granularity = "monthly"'),
            ('timezone = "Asia/Jakarta"', 'timezone = "UTC"'),
            ('"Lift On Loading",', '"Shifting Delivery",'),
            ('"Lift On Loading",', '"Lift On Loading", "Lift On Loading",'),
            ('"Shifting Delivery",\n    "Shifting Muat",', ''),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                self.path.write_text(original.replace(old, new), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    self.settings()

    def test_weekly_granularity_is_loaded_and_defaults_to_daily_when_omitted(self):
        original = self.path.read_text(encoding="utf-8")
        self.path.write_text(original.replace('period_granularity = "daily"',
                                              'period_granularity = "weekly"'), encoding="utf-8")
        self.assertEqual(self.settings()["shifting_granularity"], "weekly")
        self.path.write_text(original.replace('period_granularity = "daily"', ''), encoding="utf-8")
        self.assertEqual(self.settings()["shifting_granularity"], "daily")

    def test_sql_mapping_requires_both_relations_and_correct_equipment_field(self):
        definition = self.settings()["sql_shifting"]
        for field in ("schema", "detail_relation", "header_relation", "datetime_format"):
            invalid = deepcopy(definition)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(ConfigurationError):
                sql_shifting_settings(invalid)
        invalid = deepcopy(definition)
        invalid["header_columns"]["shifting_code"] = invalid["header_columns"].pop("equipment_code")
        with self.assertRaisesRegex(ConfigurationError, "equipment_code"):
            sql_shifting_settings(invalid)


@unittest.skipUnless(importlib.util.find_spec("psycopg"), "SQL tests require requirements-sql.txt")
class SQLShiftingLoadingTests(SQLShiftingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.loaded = self.settings()
        self.connection = MagicMock()
        self.contexts = []
        self.results = iter([200, 20, 100, 10])

        def cursor_context(**kwargs):
            context = MagicMock()
            cursor = context.__enter__.return_value
            cursor.description = [SimpleNamespace(name="operation_count")]
            cursor.__iter__.side_effect = lambda: iter([(next(self.results),)])
            self.contexts.append(context)
            return context

        self.connection.cursor.side_effect = cursor_context
        connection_patch = patch("psycopg.connect")
        self.connect = connection_patch.start()
        self.addCleanup(connection_patch.stop)
        self.connect.return_value.__enter__.return_value = self.connection

    def summaries(self, blocks=("10", "11"), *, granularity="daily", recorded_at=NOW):
        return load_sql_shifting_summary(
            self.connection, self.loaded["sql_shifting"], self.loaded["shifting_activities"],
            "CY 219 (Lini 2)", "JKT74", self.fixture.mapping_path, blocks,
            period_granularity=granularity, recorded_at=recorded_at,
        )

    def parameters(self):
        return [context.__enter__.return_value.execute.call_args.args[1] for context in self.contexts]

    def test_daily_rolling_counts_per_equipment_exclude_absent_block(self):
        with self.fixture.mapping_path.open("a", encoding="utf-8") as stream:
            stream.write('"RS TPK" = "9"\n')
        rows = self.summaries()
        self.assertEqual([(row.shifting_code, row.block_id, row.lifting_count, row.shifting_count)
                          for row in rows], [("SL", "10", 200, 20), ("RS", "11", 100, 10)])
        self.assertEqual({(row.period_start, row.period_end, row.report_date) for row in rows},
                         {(START, END, None)})
        parameters = self.parameters()
        self.assertEqual([item["equipment_code"] for item in parameters], ["SL", "SL", "RS", "RS"])
        self.assertTrue(all(item["branch_code"] == "JKT74" for item in parameters))
        self.assertTrue(all(item["period_start"] == START and item["period_end"] == END for item in parameters))
        self.assertEqual(parameters[0]["activities"], list(self.loaded["shifting_activities"]["lifting"]))
        self.assertEqual(parameters[1]["activities"], list(self.loaded["shifting_activities"]["shifting"]))
        self.assertTrue(all(item["datetime_format"] == "DD-MM-YYYY HH24:MI TZH:TZM" for item in parameters))
        self.assertTrue(all(item["utc_offset"] == " +07:00" for item in parameters))
        for context in self.contexts:
            context.__exit__.assert_called_once()
        self.connection.commit.assert_not_called()
        self.connection.close.assert_not_called()

    def test_weekly_rolling_counts_capture_one_end_time_for_all_queries(self):
        with patch("repository.sql_shifting_repository.time", side_effect=(NOW, NOW + 60)) as clock:
            rows = self.summaries(granularity="weekly", recorded_at=None)
        clock.assert_called_once()
        self.assertEqual({(row.period_start, row.period_end) for row in rows}, {(NOW - 604800, NOW)})
        self.assertTrue(all(item["period_start"] == NOW - 604800 and item["period_end"] == NOW
                            for item in self.parameters()))
        self.assertTrue(all(row.report_date is None and row.week_number is None and row.report_month is None
                            for row in rows))

    def test_rolling_boundaries_cross_years_without_midnight_or_week_alignment(self):
        now = daily_boundaries(date(2027, 1, 1))[0] + 5 * 3600 + 31
        for granularity, duration in (("daily", 86400), ("weekly", 604800)):
            with self.subTest(granularity=granularity):
                self.assertEqual(sql_period_boundaries(granularity, now), (now - duration, now))
        with self.assertRaises(ConfigurationError):
            sql_period_boundaries("monthly", now)

    def test_empty_yard_makes_no_count_queries(self):
        self.assertEqual(self.summaries(()), [])
        self.connection.cursor.assert_not_called()

    def test_zero_counts_are_recorded_without_automatic_historical_fallback(self):
        self.results = iter([0, 0, 100, 0])
        rows = self.summaries()
        self.assertEqual(rows[0].lifting_count, 0)
        self.assertEqual(rows[0].shifting_count, 0)
        self.assertIsNone(rows[0].shifting_percentage)
        self.assertEqual(rows[1].shifting_percentage, 0)
        self.assertEqual({row.period_end for row in rows}, {NOW})
        self.assertEqual(len(self.contexts), 4)

    def test_values_are_bound_and_identifiers_are_quoted(self):
        definition = deepcopy(self.loaded["sql_shifting"])
        definition["schema"] = 'report"schema'
        query = operations_count_query(definition).as_string()
        self.assertIn('"report""schema"."TBL_INSP_MAPPING_MSA_RECEIVINGDELIVERY_DTL"', query)
        self.assertIn('"b"."ALAT"', query)
        self.assertIn('WHERE EXISTS', query)
        self.assertNotIn('JOIN', query)
        self.assertIn('>= TO_TIMESTAMP(%(period_start)s::double precision)', query)
        self.assertIn('< TO_TIMESTAMP(%(period_end)s::double precision)', query)
        self.assertNotIn('BETWEEN', query)
        payload = "JKT74' OR TRUE --"
        load_sql_shifting_summary(
            self.connection, definition, self.loaded["shifting_activities"], "CY 219 (Lini 2)",
            payload, self.fixture.mapping_path, ("10",), recorded_at=NOW,
        )
        self.assertNotIn(payload, self.contexts[0].__enter__.return_value.execute.call_args.args[0].as_string())
        self.assertEqual(self.parameters()[0]["branch_code"], payload)

    def test_missing_or_invalid_aggregate_is_an_error_instead_of_zero(self):
        for value in (None, -1, True, "10"):
            with self.subTest(value=value):
                self.results = iter([value])
                with self.assertRaisesRegex(InputError, "non-negative integer"):
                    self.summaries(("10",))
        self.results = iter(())
        context = MagicMock()
        cursor = context.__enter__.return_value
        cursor.description = [SimpleNamespace(name="operation_count")]
        cursor.__iter__.return_value = iter(())
        self.connection.cursor.side_effect = None
        self.connection.cursor.return_value = context
        with self.assertRaisesRegex(InputError, "exactly one"):
            self.summaries(("10",))

    def test_sql_report_uses_one_read_only_snapshot_and_never_opens_report_csv(self):
        # Report CSV is deliberately invalid; SQL must be the only operations source.
        self.fixture.shifting_path.write_text("invalid CSV backup", encoding="utf-8")
        now = NOW
        with patch.object(main_existing, "time", return_value=now), patch(
            "repository.operations_input.load_shifting_summary", side_effect=AssertionError("CSV fallback"),
        ):
            report, yard = main_existing._build_report_and_yard(self.path)
        self.connect.assert_called_once()
        self.assertTrue(self.connection.read_only)
        import psycopg
        self.assertEqual(self.connection.isolation_level, psycopg.IsolationLevel.REPEATABLE_READ)
        self.assertEqual(report["period_start"], NOW - 86400)
        self.assertEqual(report["period_end"], report["recorded_at"])
        self.assertEqual(report["period_granularity"], "daily")
        self.assertNotIn("latest_date", report)
        self.assertNotIn("latest_week", report)
        self.assertEqual(report["lifting_count"], 300)
        self.assertEqual(report["shifting_count"], 30)
        self.assertEqual(report["total_operations"], 330)
        self.assertAlmostEqual(report["shifting_percentage"], 100 * 30 / 330)
        self.assertEqual(report["input_sources"]["shifting_summary"], "sql")
        self.assertIsNone(report["shifting_workbook_source"])
        self.assertEqual(report["operations_completeness"], "unverified")
        self.assertEqual(report["operations_period_basis"], "rolling_window")
        self.assertNotIn("period_selection", report)
        json.dumps(report, allow_nan=False)
        output = io.StringIO()
        with patch.object(main_existing, "_build_report_and_yard", return_value=(report, yard)), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.fixture.root / "config" / "input.toml",
        ), patch.object(main_existing.YardPresenter, "outYard"), redirect_stdout(output):
            main_existing.main()
        record = json.loads((self.fixture.root / "output" / "existing_yard_metrics.jsonl").read_text())
        self.assertEqual(record["lifting_count"], 300)
        self.assertEqual(record["shifting_count"], 30)
        self.assertEqual(record["period_end"], record["recorded_at"])
        self.assertEqual(record["period_end"] - record["period_start"], 86400)
        self.assertIn("Operations window: last 24 hours", output.getvalue())
        self.assertIn("period_start period_end shifting_code", output.getvalue())
        self.assertNotIn("Latest complete operations date", output.getvalue())

    def test_shared_input_loader_dispatches_sql_operations_in_its_snapshot(self):
        with patch("repository.sql_shifting_repository.time", return_value=NOW):
            inputs = load_yard_inputs(self.loaded)
        self.assertEqual(sum(row.shifting_count for row in inputs["shifting_summary"]), 30)
        self.assertEqual({row.period_end for row in inputs["shifting_summary"]}, {NOW})
        self.connect.assert_called_once()

    def test_weekly_config_propagates_to_sql_report_and_presenter(self):
        source = self.path.read_text(encoding="utf-8")
        self.path.write_text(source.replace('period_granularity = "daily"',
                                           'period_granularity = "weekly"'), encoding="utf-8")
        with patch.object(main_existing, "time", return_value=NOW):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["period_granularity"], "weekly")
        self.assertEqual(report["period_start"], NOW - 604800)
        self.assertEqual(report["period_end"], report["recorded_at"])
        self.assertNotIn("latest_week", report)
        self.assertNotIn("latest_date", report)
        self.assertTrue(all(row["period_start"] == report["period_start"]
                            and row["period_end"] == report["period_end"]
                            for row in report["shifting_observations"]))
        self.assertTrue(all(item["period_start"] == report["period_start"]
                            and item["period_end"] == report["period_end"]
                            for item in self.parameters()))
        output = io.StringIO()
        with redirect_stdout(output):
            main_existing.YardPresenter().outRecordedMetrics(report)
        self.assertIn("Operations window: last 7 days", output.getvalue())
        self.assertNotIn("operations week", output.getvalue())
        record = json.loads(json.dumps(report, allow_nan=False))
        self.assertEqual(record["period_end"] - record["period_start"], 604800)

    def test_sql_window_remains_defined_when_no_blocks_are_loaded(self):
        yard = SimpleNamespace(containers={}, blocks_by_id={}, bad_data=SimpleNamespace(anyBadData=lambda: False))
        with patch.object(main_existing, "Yard", return_value=yard), patch.object(
            main_existing, "time", return_value=NOW,
        ):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual((report["period_start"], report["period_end"]), (START, END))
        self.assertIsNone(report["shifting_count"])
        self.connection.cursor.assert_not_called()

    def test_container_sql_and_operations_sql_share_the_same_transaction(self):
        self.fixture.set_source("existing_containers", "sql")
        document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        with Path(document["csv"]["files"]["existing_containers"]).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            headers, data = next(reader), list(reader)
        data[0][headers.index("CONTNO")] = "SQL_ONLY_CONTAINER"
        context = MagicMock()
        cursor = context.__enter__.return_value
        cursor.description = [SimpleNamespace(name=name) for name in headers]
        cursor.__iter__.side_effect = lambda: iter(data)
        operations_cursor = self.connection.cursor.side_effect
        first = True

        def next_cursor(**kwargs):
            nonlocal first
            self.assertTrue(self.connection.read_only)
            if first:
                first = False
                return context
            return operations_cursor(**kwargs)

        self.connection.cursor.side_effect = next_cursor
        with patch.object(main_existing, "time", return_value=NOW):
            report, yard = main_existing._build_report_and_yard(self.path)
        self.assertIn("SQL_ONLY_CONTAINER", yard.containers)
        self.assertEqual(report["input_sources"]["existing_containers"], "sql")
        self.assertEqual(report["shifting_count"], 30)
        self.assertEqual(self.connection.cursor.call_count, 5)
        self.connect.assert_called_once()
        context.__exit__.assert_called_once()
        self.connect.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_count_failure_or_connection_failure_has_no_csv_fallback_or_jsonl_append(self):
        failure = RuntimeError("report query failed")
        self.connection.cursor.side_effect = failure
        original_open = Path.open

        def checked_open(path, *args, **kwargs):
            self.assertNotEqual(path.suffix, ".jsonl", "An unsuccessful SQL report must not append JSONL.")
            return original_open(path, *args, **kwargs)

        for connection_fails in (False, True):
            with self.subTest(connection_fails=connection_fails):
                self.connect.side_effect = failure if connection_fails else None
                with patch("repository.operations_input.load_shifting_summary") as csv_loader, patch.object(
                    main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.path,
                ), patch.object(Path, "open", checked_open), self.assertRaisesRegex(RuntimeError, "report query failed"):
                    main_existing.main()
                csv_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()

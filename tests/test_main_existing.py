"""Existing-yard metrics never load or place inbound containers."""

from contextlib import redirect_stdout
from datetime import datetime
import io
import csv
import json
import os
from pathlib import Path
import tempfile
import tomllib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from config import ConfigurationError, DEFAULT_CSV_MAPPING_FILE, DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE
from config.application.input_config import DATASETS
from config.csv_import.mapping_loader import load_mapping
from repository import CSVLoader
from repository.csvloader import BRANCH_WHITESPACE
from repository.shifting_dates import WIB
from repository.shifting_repository import ShiftingSummary
from tests.shifting_fixtures import write_report
import shifting_report_calculation


class ExistingYardMainTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.input_path = self.root / "input.toml"
        self.shifting_path = self.root / "shifting.xlsx"
        self.mapping_path = self.root / "shifting_block_mapping.toml"
        # Test-only assignments, not actual operational assignments.
        self.mapping_path.write_text('["CY 219 (Lini 2)"]\nSL = "B"\nRS = "C"\n', encoding="utf-8")
        project = DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE.parents[2]
        template = DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE.read_text(encoding="utf-8")
        template = "\n".join(
            'branch_code = "JKT74"' if line.startswith("branch_code =") else line
            for line in template.splitlines()
        ) + "\n"
        # Tests choose their own operations source, independent of the user's default.
        template = template.replace('shifting_summary = "csv"', 'shifting_summary = "xlsx"')
        template = template.replace('# shifting_workbook_file =', 'shifting_workbook_file =')
        template = template.replace('# shifting_workbook_sheet =', 'shifting_workbook_sheet =')
        configured_containers = tomllib.loads(template)["csv"]["files"]["existing_containers"]
        template = template.replace(configured_containers, "../../data_shifting_calculation/containers.csv")
        # Legacy weekly fixtures supply their own benchmark; production uses daily dates.
        template = template.replace('[input.sources]', '''[shifting_period]
benchmark_week = 40
benchmark_period_start = 1857916800

[input.sources]''').replace('shifting_workbook_sheet = "Per Alat Daily"',
                           'shifting_workbook_sheet = "Per Alat Weekly"')
        template = template.replace(
            "../../data_shifting_calculation/", (project / "data_shifting_calculation").as_posix() + "/"
        ).replace(
            'mapping_file = "csv_mapping.toml"',
            'mapping_file = "' +
            DEFAULT_CSV_MAPPING_FILE.as_posix() + '"',
        ).replace(
            'mapping_file = "sql_mapping.toml"',
            'mapping_file = "' +
            DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE.with_name("sql_mapping.toml").as_posix() + '"',
        )
        # Yard fixtures use CSV; operations use the real report workbook.
        for name in DATASETS:
            template = template.replace(f'{name} = "sql"', f'{name} = "csv"')
        # Input-loader tests may also read inbound data; never depend on a local export.
        inbound_path = self.root / "inbound.csv"
        profile = load_mapping(DEFAULT_CSV_MAPPING_FILE, source="csv")["inbound_containers"]
        with inbound_path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow([profile.columns.get(field, field) for field in profile.schema.fields])
        template = template.replace('[input.sources]', '[input.sources]\ninbound_containers = "csv"')
        template = template.replace('[csv.files]', f'[csv.files]\ninbound_containers = "{inbound_path.as_posix()}"')
        template = "\n".join(
            'shifting_workbook_file = "' + self.shifting_path.as_posix() + '"'
            if line.startswith("shifting_workbook_file =") else line
            for line in template.splitlines()
        ) + "\n"
        self.input_path.write_text(template, encoding="utf-8")
        self.write_shifting(
            "CY 219 (Lini 2),SL,100,10,2026-10,40\n"
            "CY 219 (Lini 2),SL,100,10,2026-10,40\n"
            "CY218,SL,999,99,,\n"
        )

    def write_shifting(self, rows):
        data = list(csv.reader(io.StringIO(rows)))
        for row in data:
            row[4] = row[4] or "2026-10"
            row[5] = row[5] or "40"
        write_report(self.shifting_path, data)

    def test_existing_yard_loads_without_inbound_or_sql(self):
        opened = []
        original_open = CSVLoader.open

        def guarded_open(loader):
            opened.append(loader.file_path.name)
            self.assertNotIn("inbound", loader.file_path.name.lower())
            return original_open(loader)

        with patch.object(CSVLoader, "open", guarded_open), patch.object(
            shifting_report_calculation.Yard, "assign_and_place",
            side_effect=AssertionError("Inbound placement called"),
        ), patch.dict("sys.modules", {"psycopg": None}):
            report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)

        self.assertEqual(len(opened), 8)
        self.assertGreater(len(yard.containers), 0)
        self.assertTrue(0 <= report["avg_parameter_compliance"] <= 100)
        self.assertEqual(sum(row["shifting_count"] for row in report["shifting_observations"]), 20)
        self.assertEqual(len(report["shifting_observations"]), 1)
        self.assertEqual(list(report), [
            "cy_name", "branch_code", "generated_at", "period_start", "period_end", "latest_date", "period_granularity",
            "avg_shifting_percentage", "avg_parameter_compliance", "shifting_observations",
        ])
        self.assertEqual(list(report["shifting_observations"][0]), [
            "block_code", "assigned_equipment", "lifting_count", "shifting_count",
            "shifting_percentage", "parameter_compliance",
        ])

    def set_source(self, name, source):
        text = self.input_path.read_text(encoding="utf-8")
        self.input_path.write_text(
            text.replace(f'{name} = "csv"', f'{name} = "{source}"').replace(
                f'{name} = "xlsx"', f'{name} = "{source}"'), encoding="utf-8",
        )

    def sql_existing(self):
        self.set_source("existing_containers", "sql")
        environment = patch.dict(os.environ, {
            "YARD_DB_HOST": "db.example.test", "YARD_DB_NAME": "yard_test",
            "YARD_DB_USER": "test_reader", "YARD_DB_PASSWORD": "test-password",
        })
        environment.start()
        self.addCleanup(environment.stop)
        driver = ModuleType("psycopg")
        driver.connect = MagicMock()
        driver.sql = MagicMock()
        driver.sql.SQL.return_value.join.side_effect = lambda parts: tuple(parts)
        driver.IsolationLevel = SimpleNamespace(REPEATABLE_READ="repeatable", READ_COMMITTED="committed")
        rows = ModuleType("psycopg.rows")
        rows.tuple_row = object()
        modules = patch.dict("sys.modules", {"psycopg": driver, "psycopg.rows": rows})
        modules.start()
        self.addCleanup(modules.stop)
        connection = driver.connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        document = tomllib.loads(self.input_path.read_text(encoding="utf-8"))
        source = Path(document["csv"]["files"]["existing_containers"])
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            headers, record = next(reader), next(reader)
        record[headers.index("CONTNO")] = "SQL_ONLY_CONTAINER"
        cursor.description = [SimpleNamespace(name=name) for name in headers]
        cursor.__iter__.side_effect = lambda: iter([tuple(record)])
        return driver, connection, cursor

    def test_sql_existing_containers_use_sql_mapping_and_ignore_csv_backup(self):
        driver, connection, cursor = self.sql_existing()
        text = self.input_path.read_text(encoding="utf-8")
        # An unusable CSV backup must not affect SQL loading.
        backup = tomllib.loads(text)["csv"]["files"]["existing_containers"]
        self.input_path.write_text(text.replace(
            'existing_containers = "' + backup + '"',
            'existing_containers = "missing-backup.csv"',
        ), encoding="utf-8")
        with patch.object(shifting_report_calculation.Yard, "assign_and_place", side_effect=AssertionError("Inbound")):
            report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        self.assertEqual(set(yard.containers), {"SQL_ONLY_CONTAINER"})
        driver.connect.assert_called_once()
        driver.sql.Identifier.assert_any_call("TERMINAL_APP", "TRM_TRS_TARGET_CONTAINER")
        self.assertEqual(cursor.execute.call_args.args[1], (BRANCH_WHITESPACE, ["JKT74"]))
        self.assertTrue(connection.read_only)
        self.assertEqual(connection.isolation_level, "repeatable")
        connection.cursor.return_value.__exit__.assert_called_once()
        driver.connect.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_sql_failures_do_not_open_existing_container_csv(self):
        driver, _, cursor = self.sql_existing()
        original_open = CSVLoader.open
        opened = []

        def guarded_open(loader):
            opened.append(loader.file_path.name)
            self.assertNotEqual(loader.file_path.name, "containers.csv")
            self.assertNotIn("inbound", loader.file_path.name)
            return original_open(loader)

        for failure in ("connection failed", "query failed"):
            with self.subTest(failure=failure):
                driver.connect.side_effect = RuntimeError(failure) if failure.startswith("connection") else None
                cursor.execute.side_effect = RuntimeError(failure)
                with patch.object(CSVLoader, "open", guarded_open), self.assertRaisesRegex(RuntimeError, failure):
                    shifting_report_calculation.build_report(self.input_path)
        self.assertNotIn("containers.csv", opened)

    def test_empty_sql_result_stays_empty(self):
        _, _, cursor = self.sql_existing()
        cursor.__iter__.side_effect = lambda: iter(())
        report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        self.assertEqual(len(yard.containers), 0)
        self.assertIsNone(report["avg_parameter_compliance"])
        self.assertTrue(all(row["parameter_compliance"] is None for row in report["shifting_observations"]))

    def test_sql_setup_errors_stop_loading_without_csv_fallback(self):
        driver, _, _ = self.sql_existing()
        for missing in ("host", "password", "driver"):
            environment = {
                "YARD_DB_HOST": "db.example.test", "YARD_DB_NAME": "yard_test",
                "YARD_DB_USER": "test_reader", "YARD_DB_PASSWORD": "test-password",
            }
            expected = "requirements-sql.txt"
            if missing != "driver":
                expected = "YARD_DB_" + missing.upper()
                environment.pop(expected)
            with self.subTest(missing=missing), patch.dict(os.environ, environment, clear=True), patch.dict(
                "sys.modules", {"psycopg": None if missing == "driver" else driver},
            ), self.assertRaisesRegex(ConfigurationError, expected):
                shifting_report_calculation.build_report(self.input_path)
            driver.connect.assert_not_called()

    def test_unused_inbound_sql_source_needs_no_database_settings(self):
        self.set_source("inbound_containers", "sql")
        with patch.dict(os.environ, {}, clear=True), patch.dict("sys.modules", {"psycopg": None}):
            report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        self.assertGreater(len(yard.containers), 0)

    def test_inbound_source_and_file_can_be_omitted(self):
        text = self.input_path.read_text(encoding="utf-8")
        self.input_path.write_text("\n".join(
            line for line in text.splitlines() if not line.startswith("inbound_containers =")
        ), encoding="utf-8")
        report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        self.assertGreater(len(yard.containers), 0)

    def test_available_shifts_are_summed_and_missing_observations_counted(self):
        self.write_shifting("CY 219 (Lini 2),SL,100,10,,\nCY 219 (Lini 2),SL,,,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual([row["shifting_count"] for row in report["shifting_observations"]], [10])
        self.assertIsNone(report["shifting_observations"][0]["shifting_percentage"])
        self.assertIsNone(report["avg_shifting_percentage"])

    def test_latest_week_uses_aggregate_operations_and_unix_generation_time(self):
        self.write_shifting(
            "CY 219 (Lini 2),SL,9000,9000,2026-10,43\n"
            "CY 219 (Lini 2),SL,100,100,2026-10,44\n"
            "CY 219 (Lini 2),RS,900,0,2026-10,44\n"
        )
        with patch.object(shifting_report_calculation, "time", return_value=1234567890.7):
            report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["generated_at"], 1234567890)
        self.assertNotIn("recorded_at", report)
        self.assertNotIn("recorded_at_utc", report)
        self.assertEqual(report["period_granularity"], "weekly")
        self.assertIsNotNone(report["latest_date"])
        self.assertEqual(report["period_start"], 1860336000)
        self.assertEqual(report["period_end"], 1860940800)
        self.assertEqual(sum(row["lifting_count"] for row in report["shifting_observations"]), 1000)
        self.assertEqual(sum(row["shifting_count"] for row in report["shifting_observations"]), 100)
        self.assertAlmostEqual(report["avg_shifting_percentage"], 100 * 100 / 1100)
        self.assertEqual(len(report["shifting_observations"]), 2)
        blocks = {row["block_code"]: row for row in report["shifting_observations"]}
        self.assertEqual(blocks["B"]["shifting_percentage"], 50)
        self.assertEqual(blocks["C"]["shifting_percentage"], 0)

    def test_missing_historical_counts_do_not_block_latest_week(self):
        self.write_shifting(
            "CY 219 (Lini 2),SL,100,,2026-10,43\n"
            "CY 219 (Lini 2),RS,,,2026-10,43\n"
            "CY 219 (Lini 2),SL,200,20,2026-10,44\n"
            "CY 219 (Lini 2),RS,100,10,2026-10,44\n"
        )
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(sum(row["lifting_count"] for row in report["shifting_observations"]), 300)
        self.assertEqual(sum(row["shifting_count"] for row in report["shifting_observations"]), 30)
        self.assertAlmostEqual(report["avg_shifting_percentage"], 100 * 30 / 330)
        self.assertEqual(len(report["shifting_observations"]), 2)

    def test_absent_block_invalid_counts_do_not_affect_selected_week(self):
        self.mapping_path.write_text('["CY 219 (Lini 2)"]\nSL = "B"\nRS = "99"\n', encoding="utf-8")
        self.write_shifting(
            "CY 219 (Lini 2),SL,200,20,2026-10,43\nCY 219 (Lini 2),RS,bad,-1,2026-10,43\n"
        )
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["shifting_observations"][0]["shifting_count"], 20)
        self.assertAlmostEqual(report["avg_shifting_percentage"], 100 * 20 / 220)
        self.assertNotIn("skipped_shifting_data_points", report)

    def test_incomplete_latest_week_keeps_counts_and_no_percentage(self):
        self.write_shifting(
            "CY 219 (Lini 2),SL,1000,500,2026-10,43\n"
            "CY 219 (Lini 2),SL,50,10,2026-10,44\n"
            "CY 219 (Lini 2),RS,,,2026-10,44\n"
        )
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["shifting_observations"][0]["lifting_count"], 50)
        self.assertEqual(report["shifting_observations"][0]["shifting_count"], 10)
        self.assertIsNone(report["avg_shifting_percentage"])
        self.assertIsNone(report["shifting_observations"][1]["lifting_count"])
        self.assertIsNone(report["shifting_observations"][1]["shifting_count"])

    def test_zero_total_operations_has_no_percentage(self):
        self.write_shifting("CY 219 (Lini 2),SL,0,0,2026-10,44\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["shifting_observations"][0]["lifting_count"], 0)
        self.assertEqual(report["shifting_observations"][0]["shifting_count"], 0)
        self.assertIsNone(report["avg_shifting_percentage"])
        self.assertIsNone(report["shifting_observations"][0]["shifting_percentage"])

    def test_older_block_data_is_not_joined_to_latest_week(self):
        self.write_shifting(
            "CY 219 (Lini 2),SL,50,10,2026-10,44\nCY 219 (Lini 2),RS,100,30,2026-10,43\n"
        )
        report = shifting_report_calculation.build_report(self.input_path)
        rows = report["shifting_observations"]
        self.assertEqual(rows[0]["block_code"], "B")
        self.assertTrue(all(row["shifting_count"] is None for row in rows if row["block_code"] == "C"))

    def test_all_missing_observations_do_not_become_zero(self):
        self.write_shifting("CY 219 (Lini 2),SL,,,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertIsNone(report["shifting_observations"][0]["shifting_count"])
        self.assertIsNone(report["avg_shifting_percentage"])

    def test_explicit_zero_remains_zero(self):
        self.write_shifting("CY 219 (Lini 2),SL,100,0,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["shifting_observations"][0]["shifting_count"], 0)
        self.assertEqual(report["avg_shifting_percentage"], 0)

    def test_compliance_is_container_weighted(self):
        first = Mock()
        first.getBranch.return_value = "2"
        first.getCode.return_value = "B"
        first.getId.return_value = "10"
        first.parameterCompliance.return_value = 1.0
        second = Mock()
        second.getBranch.return_value = "2"
        second.getCode.return_value = "C"
        second.getId.return_value = "11"
        second.parameterCompliance.return_value = 0.0
        containers = {}
        for index, block in enumerate(("B", "C", "C", "C")):
            container = Mock()
            container.getCoordsStr.return_value = ("2", block, "1", "1", "1")
            containers[str(index)] = container
        yard = SimpleNamespace(
            containers=containers,
            blocks_by_id={"10": first, "11": second},
            bad_data=SimpleNamespace(anyBadData=lambda: True),
        )
        with patch.object(shifting_report_calculation, "Yard", return_value=yard):
            report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["avg_parameter_compliance"], 25)
        self.assertEqual(report["shifting_observations"][0]["parameter_compliance"], 100)

    def test_empty_yard_omits_all_observations_and_has_no_compliance(self):
        yard = SimpleNamespace(
            containers={}, blocks_by_id={},
            bad_data=SimpleNamespace(anyBadData=lambda: False),
        )
        with patch.object(shifting_report_calculation, "Yard", return_value=yard):
            report = shifting_report_calculation.build_report(self.input_path)
        self.assertIsNone(report["avg_parameter_compliance"])
        self.assertEqual(report["shifting_observations"], [])
        self.assertIsNone(report["period_start"])
        self.assertIsNone(report["latest_date"])
        self.assertIsNone(report["avg_shifting_percentage"])
        self.assertNotIn("skipped_shifting_data_points", report)

    def test_absent_block_counts_are_excluded_from_yard_and_block_totals(self):
        self.mapping_path.write_text('["CY 219 (Lini 2)"]\nSL = "B"\nRS = "99"\n', encoding="utf-8")
        self.write_shifting("CY 219 (Lini 2),SL,100,10,,\nCY 219 (Lini 2),RS,100,30,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(report["shifting_observations"][0]["shifting_count"], 10)
        self.assertEqual(len(report["shifting_observations"]), 1)
        self.assertNotIn("skipped_shifting_data_points", report)
        self.assertNotIn("skipped_shifting_observations", report)
        self.assertEqual(
            report["shifting_observations"][0]["block_code"], "B",
        )

    def test_shifting_counts_are_joined_to_blocks(self):
        self.write_shifting(
            "CY 219 (Lini 2),SL,100,10,,\nCY 219 (Lini 2),RS,100,30,,\nCY 219 (Lini 2),SL,100,20,,\n"
        )
        report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        rows = report["shifting_observations"]
        self.assertEqual(sum(row["shifting_count"] for row in rows if row["block_code"] == "B"), 30)
        self.assertEqual(sum(row["shifting_count"] for row in rows
                             if row["block_code"] == "C" and row["shifting_count"] is not None), 30)
        self.assertEqual(report["shifting_observations"][0]["assigned_equipment"], ["SL"])
        block = next(block for block in yard.blocks_by_id.values() if block.getCode() == "B")
        self.assertAlmostEqual(rows[0]["parameter_compliance"], block.parameterCompliance() * 100)
        self.assertNotIn("equipment_group", report["shifting_observations"][0])

    def test_equipment_mapped_to_the_same_block_is_combined(self):
        self.mapping_path.write_text('["CY 219 (Lini 2)"]\nSL = "B"\nRS = "B"\n', encoding="utf-8")
        self.write_shifting(
            "CY 219 (Lini 2),SL,100,100,2026-10,44\n"
            "CY 219 (Lini 2),RS,900,0,2026-10,44\n"
            "CY 219 (Lini 2),SL,9999,9999,2026-10,43\n"
        )
        report, yard = shifting_report_calculation._build_report_and_yard(self.input_path)
        self.assertEqual(len(report["shifting_observations"]), 1)
        row = report["shifting_observations"][0]
        self.assertEqual((row["block_code"], row["assigned_equipment"]), ("B", ["RS", "SL"]))
        self.assertEqual((row["lifting_count"], row["shifting_count"]), (1000, 100))
        self.assertAlmostEqual(row["shifting_percentage"], 100 * 100 / 1100)
        self.assertEqual(row["shifting_percentage"], report["avg_shifting_percentage"])
        block = next(block for block in yard.blocks_by_id.values() if block.getCode() == "B")
        self.assertAlmostEqual(row["parameter_compliance"], block.parameterCompliance() * 100)

    def test_block_without_observations_is_not_reported_as_zero(self):
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertNotIn("C", [row["block_code"] for row in report["shifting_observations"]])

    def test_workbook_equipment_can_merge_multiple_blocks(self):
        self.mapping_path.write_text(
            '["CY 219 (Lini 2)"]\nSL = ["B", "C"]\nRS = "C"\n', encoding="utf-8",
        )
        self.write_shifting("CY 219 (Lini 2),SL,100,10,,\nCY 219 (Lini 2),RS,200,20,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        self.assertEqual(len(report["shifting_observations"]), 1)
        row = report["shifting_observations"][0]
        self.assertEqual(row["block_code"], "B, C")
        self.assertEqual((row["lifting_count"], row["shifting_count"]), (300, 30))
        self.assertAlmostEqual(row["parameter_compliance"], report["avg_parameter_compliance"])

    def test_shifting_path_is_required(self):
        text = self.input_path.read_text(encoding="utf-8")
        self.input_path.write_text(
            text.replace("\nshifting_workbook_file =", "\n# shifting_workbook_file ="),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigurationError, "shifting_workbook_file"):
            shifting_report_calculation.build_report(self.input_path)

    def test_main_appends_one_json_record_per_run(self):
        self.write_shifting("CY 219 (Lini 2),SL,100,10,,\nCY 219 (Lini 2),SL,,,,\n")
        report = shifting_report_calculation.build_report(self.input_path)
        captured = io.StringIO()
        with patch.object(
            shifting_report_calculation, "_build_reports_and_yards", return_value={"JKT74": (report, Mock())},
        ), patch.object(shifting_report_calculation.YardPresenter, "outYard"), patch.object(
            shifting_report_calculation, "OUTPUT_DIR", self.root / "output",
        ), redirect_stdout(captured):
            shifting_report_calculation.main()
            shifting_report_calculation.main()
        output = self.root / "output" / "existing_yard_metrics_JKT74.jsonl"
        records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records, [report, report])
        self.assertIn("parameter compliance use 0-100", captured.getvalue())
        self.assertIn('"generated_at": ', output.read_text(encoding="utf-8"))
        self.assertIn(', "period_start": ', output.read_text(encoding="utf-8"))
        lines = captured.getvalue().splitlines()
        index = lines.index("JSONL metrics row:")
        fields = lines[index + 1].split()
        values = lines[index + 2].rsplit(maxsplit=len(fields) - 1)
        displayed = dict(zip(fields, values, strict=True))
        for field, value in displayed.items():
            self.assertEqual(value, "null" if records[0][field] is None else str(records[0][field]))
        self.assertEqual(displayed["avg_shifting_percentage"], "null")
        self.assertNotIn("Known shifting count:", captured.getvalue())
        self.assertNotIn("Skipped shifting observations:", captured.getvalue())


class RecordedMetricsTests(unittest.TestCase):
    def setUp(self):
        self.now = int(datetime(2026, 11, 1, 0, 15, tzinfo=WIB).timestamp())
        self.inputs = {name: [] for name in shifting_report_calculation.EXISTING_YARD_DATASETS}
        self.inputs["terminal_branches"] = [{
            "branch_id": "2", "terminal_id": "1", "branch_code": "JKT74",
            "branch_name": "CY 219 (Lini 2)",
        }]
        blocks = {}
        for block_id, code, score in (("29", "B", 1.0), ("30", "C", 0.0), ("31", "D", None)):
            block = Mock()
            block.getId.return_value = block_id
            block.getBranch.return_value = "2"
            block.getCode.return_value = code
            block.parameterCompliance.return_value = score
            blocks[block_id] = block
        containers = {}
        for index, code in enumerate(("B", "C", "C", "C")):
            container = Mock()
            container.getCoordsStr.return_value = ("2", code, "1", "1", "1")
            containers[str(index)] = container
        self.yard = SimpleNamespace(containers=containers, blocks_by_id=blocks)

    def report(self, source="csv", granularity="daily", empty=False, observations=None):
        start = self.now - (86400 if granularity == "daily" else 7 * 86400)
        report_date = "2026-10-31" if source == "xlsx" and granularity == "daily" else None
        rows = [] if empty else [
            ShiftingSummary("CY 219 (Lini 2)", equipment, lifting, shifting,
                            block_id=block_id, period_start=start, period_end=self.now,
                            report_date=report_date)
            for equipment, block_id, lifting, shifting in (
                ("SL", "29", 100, 100), ("RS", "30", 900, 0),
                ("EXTRA", "29", 0, 0), ("EMPTY", "31", 0, 0),
            )
        ]
        if observations is not None:
            rows = observations
        settings = {"shifting_source": source, "shifting_granularity": granularity,
                    "shifting_workbook_sheet": "Per Alat " + granularity.title(),
                    "shifting_period": {}}
        with patch.object(shifting_report_calculation, "Yard", return_value=self.yard), patch.object(
            shifting_report_calculation, "load_operations", return_value=rows,
        ), patch.object(shifting_report_calculation, "time", return_value=self.now):
            report, _ = shifting_report_calculation._build_loaded_report(settings, self.inputs, None)
        return report

    def test_shared_block_totals_and_missing_counts_for_all_sources(self):
        for source in ("csv", "sql", "xlsx"):
            for missing in (False, True):
                with self.subTest(source=source, missing=missing):
                    rows = [
                        ShiftingSummary("CY", code, lifting, shifting, block_id=block,
                                        branch_code="JKT74", period_start=self.now - 86400,
                                        period_end=self.now)
                        for code, block, lifting, shifting in (
                            ("RTG05", "29", 100, 100),
                            ("RTG03", "29", None if missing else 900, None if missing else 0),
                            ("OTHER", "30", 0, 0),
                        )
                    ]
                    report = self.report(source, observations=rows)
                    self.assertEqual(len(report["shifting_observations"]), 2)
                    combined, other = report["shifting_observations"]
                    self.assertEqual(combined["assigned_equipment"], ["RTG03", "RTG05"])
                    self.assertEqual(combined["lifting_count"], 100 if missing else 1000)
                    self.assertEqual(combined["shifting_count"], 100)
                    self.assertEqual(combined["parameter_compliance"], 100)
                    self.assertEqual(report["avg_parameter_compliance"], 25)
                    self.assertEqual(other["assigned_equipment"], ["OTHER"])
                    self.assertEqual((other["lifting_count"], other["shifting_count"]), (0, 0))
                    self.assertIsNone(other["shifting_percentage"])
                    if missing:
                        self.assertIsNone(combined["shifting_percentage"])
                        self.assertIsNone(report["avg_shifting_percentage"])
                    else:
                        self.assertAlmostEqual(combined["shifting_percentage"], 100 * 100 / 1100)
                        self.assertEqual(combined["shifting_percentage"], report["avg_shifting_percentage"])

    def test_assigned_equipment_keeps_unique_names_with_spaces(self):
        rows = [
            ShiftingSummary("CY", code, 100, 10, block_id="29", branch_code="JKT74",
                            period_start=self.now - 86400, period_end=self.now)
            for code in ("RTG05", "RS MDL", "RS MDL")
        ]
        for source in ("csv", "sql", "xlsx"):
            with self.subTest(source=source):
                report = self.report(source, observations=rows)
                row = report["shifting_observations"][0]
                self.assertEqual(row["assigned_equipment"], ["RS MDL", "RTG05"])
                self.assertNotIn("shifting_code", row)
                self.assertEqual((row["lifting_count"], row["shifting_count"]), (300, 30))

    def test_connected_blocks_merge_transitively_with_weighted_compliance(self):
        for source in ("csv", "sql", "xlsx"):
            with self.subTest(source=source):
                rows = [
                    ShiftingSummary("CY", code, lifting, shifting, block_id=ids[0], block_ids=ids,
                                    branch_code="JKT64", period_start=self.now - 86400,
                                    period_end=self.now)
                    for code, ids, lifting, shifting in (
                        ("OTHER", ("31",), 20, 0),
                        ("RTG04", ("29", "30"), 100, 100),
                        ("RTG05", ("30", "31"), 900, 0),
                    )
                ]
                report = self.report(source, observations=rows)
                self.assertEqual(len(report["shifting_observations"]), 1)
                row = report["shifting_observations"][0]
                self.assertEqual(row["block_code"], "B, C, D")
                self.assertEqual(row["assigned_equipment"], ["OTHER", "RTG04", "RTG05"])
                self.assertEqual((row["lifting_count"], row["shifting_count"]), (1020, 100))
                self.assertAlmostEqual(row["shifting_percentage"], 100 * 100 / 1120)
                self.assertEqual(row["parameter_compliance"], 25)
                self.assertEqual(row["shifting_percentage"], report["avg_shifting_percentage"])

    def test_merge_keeps_branches_separate_and_empty_compliance_missing(self):
        rows = [ShiftingSummary("CY", "RTG04", lifting, 1, block_ids=("29", "30"), branch_code=branch)
                for branch, lifting in (("JKT74", 10), ("JKT64", 20))]
        result = shifting_report_calculation.block_shifting_observations(
            rows, self.yard, {"29": None, "30": None}, {"29": 0, "30": 0},
        )
        self.assertEqual(len(result), 2)
        self.assertEqual([row["lifting_count"] for row in result], [10, 20])
        self.assertTrue(all(row["parameter_compliance"] is None for row in result))

    def test_all_sources_share_ordered_schema_and_weighted_percentages(self):
        for source in ("csv", "sql", "xlsx"):
            for granularity in ("daily", "weekly"):
                with self.subTest(source=source, granularity=granularity):
                    report = self.report(source, granularity)
                    self.assertEqual(report["cy_name"], "CY 219 (Lini 2)")
                    self.assertEqual(report["branch_code"], "JKT74")
                    self.assertEqual(list(report), [
                        "cy_name", "branch_code", "generated_at", "period_start", "period_end", "latest_date", "period_granularity",
                        "avg_shifting_percentage", "avg_parameter_compliance", "shifting_observations",
                    ])
                    self.assertEqual(report["period_granularity"], granularity)
                    self.assertEqual(report["latest_date"], "2026-10-31" if source == "xlsx" and
                                     granularity == "daily" else "2026-11-01")
                    self.assertAlmostEqual(report["avg_shifting_percentage"], 100 * 100 / 1100)
                    self.assertEqual(report["avg_parameter_compliance"], 25)
                    self.assertEqual([row["parameter_compliance"] for row in report["shifting_observations"]],
                                     [100, 0, None])
                    for row in report["shifting_observations"]:
                        self.assertEqual(list(row), [
                            "block_code", "assigned_equipment", "lifting_count", "shifting_count",
                            "shifting_percentage", "parameter_compliance",
                        ])
                    json.dumps(report, allow_nan=False)

    def test_empty_observations_keep_compliance_and_source_window_behavior(self):
        for source in ("csv", "sql", "xlsx"):
            with self.subTest(source=source):
                report = self.report(source, empty=True)
                self.assertEqual(report["cy_name"], "CY 219 (Lini 2)")
                self.assertEqual(report["branch_code"], "JKT74")
                self.assertEqual(report["shifting_observations"], [])
                self.assertEqual(report["avg_parameter_compliance"], 25)
                self.assertIsNone(report["avg_shifting_percentage"])
                self.assertEqual(report["latest_date"], "2026-11-01" if source == "sql" else None)

    def test_weekly_xlsx_date_uses_last_included_day_at_midnight(self):
        self.now = int(datetime(2026, 11, 1, tzinfo=WIB).timestamp())
        self.assertEqual(self.report("xlsx", "weekly")["latest_date"], "2026-10-31")


if __name__ == "__main__":
    unittest.main()

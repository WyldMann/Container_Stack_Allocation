"""Batch reports keep yard identity, source windows, and JSONL history separate."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from config import ConfigurationError, load_input_config
from repository import InputError
from tests import test_input_filters as filter_tests
import main
import shifting_report_calculation


class MultipleBranchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = filter_tests.InputFilterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        self.root = self.fixture.root
        self.fixture.set_filters('branch_code = ["JKT74", "JKT64"]')
        self.fixture.data["terminal_branches"][1].update(
            branch_code="JKT64", branch_name="CY 218 (Lini 2)",
        )
        for dataset in ("existing_containers", "equipment_history"):
            for row in self.fixture.data[dataset]:
                if row["branch_id"] == "JKT75":
                    row["branch_id"] = "JKT64"
        for name in ("terminal_branches", "existing_containers", "equipment_history"):
            self.fixture.write_records(name, self.fixture.data[name])
        # Both yards use the same equipment label and block code.
        self.fixture.fixture.mapping_path.write_text(
            '[JKT74]\nSL = "B"\n[JKT64]\nSL = "B"\n', encoding="utf-8",
        )
        # Only the first yard's containers match their parameter.
        self.fixture.write_records("parameters", [
            dict(parameter_id="P", parameter_name="Twenty-foot", container_size="20",
                 container_size_score="1", terminal_id="1", branch_id="2"),
            dict(parameter_id="P", parameter_name="Forty-foot", container_size="40",
                 container_size_score="1", terminal_id="1", branch_id="3"),
        ])
        self.fixture.write_records("yard_planning", [
            dict(parameter_id="P", block_id=block, row_no="1", slot_no="1",
                 terminal_id="1", branch_id="3" if block == "12" else "2")
            for block in ("10", "11", "12")
        ])
        self.fixture.fixture.set_source("shifting_summary", "csv")
        self.activities = self.root / "operations.csv"
        self.activities.write_text(
            "DTL_ID,DOC_ID,ACTIVITY,ACTIVITY_DATE_TIME,KODE_CABANG,ALAT\n"
            "1,D,Lift on Loading,30-10-2026 12:00,JKT74,SL\n"
            "2,D,Lift on Loading,30-10-2026 11:00,JKT74,SL\n"
            "3,D,Shifting,30-10-2026 11:00,JKT74,SL\n"
            "4,D,Lift on Loading,29-10-2026 09:00,JKT64,SL\n"
            "5,D,Shifting,29-10-2026 09:00,JKT64,SL\n"
            "6,D,Shifting,29-10-2026 08:00,JKT64,SL\n"
            "7,D,Shifting,29-10-2026 08:00,JKT64,SL\n"
            "8,D,Shifting,invalid date,JKT76,SL\n", encoding="utf-8",
        )
        document = load_input_config(self.path)
        source = document["csv_files"]["shifting_summary"].as_posix()
        self.path.write_text(self.path.read_text(encoding="utf-8").replace(
            source, self.activities.as_posix(),
        ).replace('block_mapping_file = "shifting_block_mapping.toml"',
                  f'block_mapping_file = "{self.fixture.fixture.mapping_path.as_posix()}"'), encoding="utf-8")

    def assert_reports(self, reports):
        self.assertEqual(list(reports), ["JKT74", "JKT64"])
        for code, name, lifting, shifting, compliance in (
            ("JKT74", "CY 219 (Lini 2)", 2, 1, 100),
            ("JKT64", "CY 218 (Lini 2)", 1, 3, 0),
        ):
            with self.subTest(code=code):
                report = reports[code]
                self.assertEqual(report["avg_parameter_compliance"], compliance)
                self.assertAlmostEqual(report["avg_shifting_percentage"], 100 * shifting / (lifting + shifting))
                self.assertEqual(len(report["shifting_observations"]), 1)
                row = report["shifting_observations"][0]
                self.assertEqual((report["branch_code"], report["cy_name"], row["block_code"], row["assigned_equipment"]),
                                 (code, name, "B", ["SL"]))
                self.assertNotIn("cy_name", row)
                self.assertNotIn("branch_code", row)
                self.assertEqual((row["lifting_count"], row["shifting_count"]), (lifting, shifting))
                self.assertEqual(row["parameter_compliance"], compliance)

    def test_shared_csv_keeps_names_counts_compliance_and_latest_dates_separate(self):
        reports = shifting_report_calculation.build_reports(self.path)
        self.assert_reports(reports)
        self.assertEqual(reports["JKT74"]["latest_date"], "2026-10-30")
        self.assertEqual(reports["JKT64"]["latest_date"], "2026-10-29")
        self.assertNotEqual(reports["JKT74"]["period_end"], reports["JKT64"]["period_end"])
        self.assertEqual(reports["JKT74"]["generated_at"], reports["JKT64"]["generated_at"])
        for code in reports:
            selected = shifting_report_calculation.build_report(self.path, branch_code=code.lower())
            self.assertEqual(selected["shifting_observations"], reports[code]["shifting_observations"])
        with self.assertRaisesRegex(ConfigurationError, "build_reports"):
            shifting_report_calculation.build_report(self.path)
        with self.assertRaises(ConfigurationError):
            shifting_report_calculation.build_report(self.path, branch_code="MISSING")

    def test_each_run_appends_only_to_the_matching_branch_file(self):
        output = self.root / "output"
        with patch.object(shifting_report_calculation, "DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE", self.path), patch.object(
            shifting_report_calculation, "OUTPUT_DIR", output,
        ), patch.object(
            shifting_report_calculation.YardPresenter, "outYard",
        ), redirect_stdout(io.StringIO()):
            shifting_report_calculation.main()
            shifting_report_calculation.main()
        self.assertEqual({path.name for path in output.glob("*.jsonl")}, {
            "existing_yard_metrics_JKT74.jsonl", "existing_yard_metrics_JKT64.jsonl",
        })
        reports = {}
        for code in ("JKT74", "JKT64"):
            lines = (output / f"existing_yard_metrics_{code}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            records = [json.loads(line) for line in lines]
            self.assertEqual(records[0]["shifting_observations"], records[1]["shifting_observations"])
            reports[code] = records[0]
        self.assert_reports(reports)

    def test_empty_operations_still_get_their_own_branch_file(self):
        self.activities.write_text(self.activities.read_text().splitlines()[0] + "\n", encoding="utf-8")
        results = shifting_report_calculation._build_reports_and_yards(self.path)
        self.assertEqual(list(results), ["JKT74", "JKT64"])
        for code, (report, _) in results.items():
            self.assertEqual(report["shifting_observations"], [])
            self.assertEqual(report["branch_code"], code)
            self.assertEqual(report["cy_name"], "CY 219 (Lini 2)" if code == "JKT74" else "CY 218 (Lini 2)")
        with patch.object(shifting_report_calculation, "_build_reports_and_yards", return_value=results), patch.object(
            shifting_report_calculation, "OUTPUT_DIR", self.root / "output",
        ), patch.object(shifting_report_calculation, "YardPresenter"), redirect_stdout(io.StringIO()):
            shifting_report_calculation.main()
        self.assertEqual(len(list((self.root / "output").glob("*.jsonl"))), 2)

    def test_missing_second_branch_does_not_append_partial_batch(self):
        self.fixture.set_filters('branch_code = ["JKT74", "MISSING"]')
        with patch.object(shifting_report_calculation, "DEFAULT_SHIFTING_REPORT_INPUT_CONFIG_FILE", self.path), patch.object(
            shifting_report_calculation, "OUTPUT_DIR", self.root / "output",
        ), self.assertRaises(InputError):
            shifting_report_calculation.main()
        self.assertFalse(list(self.root.rglob("*.jsonl")))

    def test_display_names_are_taken_verbatim_from_each_branch_record(self):
        self.fixture.data["terminal_branches"][1]["branch_name"] = "  New yard name\t"
        self.fixture.write_records("terminal_branches", self.fixture.data["terminal_branches"])
        reports = shifting_report_calculation.build_reports(self.path)
        self.assertEqual(reports["JKT64"]["cy_name"], "  New yard name\t")

    def test_xlsx_selects_the_corresponding_branch_name(self):
        self.fixture.fixture.set_source("shifting_summary", "xlsx")
        self.fixture.fixture.write_shifting(
            "CY 219 (Lini 2),SL,2,1,2026-10,40\n"
            "CY 218 (Lini 2),SL,1,3,2026-10,40\n"
        )
        self.assert_reports(shifting_report_calculation.build_reports(self.path))

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "SQL tests require requirements-sql.txt")
    def test_sql_operations_bind_each_branch_in_one_shared_snapshot(self):
        self.fixture.fixture.set_source("shifting_summary", "sql")
        connection = MagicMock()
        contexts = []
        counts = iter((2, 1, 1, 3))

        def cursor_context(**kwargs):
            context = MagicMock()
            cursor = context.__enter__.return_value
            cursor.description = [SimpleNamespace(name="operation_count")]
            cursor.__iter__.side_effect = lambda: iter([(next(counts),)])
            contexts.append(context)
            return context

        connection.cursor.side_effect = cursor_context
        with patch.dict(os.environ, {
            "YARD_DB_HOST": "db.test", "YARD_DB_NAME": "yard", "YARD_DB_USER": "reader",
            "YARD_DB_PASSWORD": "test-password",
        }), patch("psycopg.connect") as connect, patch.object(shifting_report_calculation, "time", return_value=1793300000):
            connect.return_value.__enter__.return_value = connection
            reports = shifting_report_calculation.build_reports(self.path)
        connect.assert_called_once()
        self.assertTrue(connection.read_only)
        self.assert_reports(reports)
        self.assertEqual([context.__enter__.return_value.execute.call_args.args[1]["branch_code"]
                          for context in contexts], ["JKT74", "JKT74", "JKT64", "JKT64"])

    def test_placement_entrypoint_runs_each_branch_without_overwriting_outputs(self):
        self.activities.unlink()
        with patch.object(main, "DEFAULT_STACKING_INPUT_CONFIG_FILE", self.path), patch.object(
            main, "YardPresenter",
        ), patch.object(main, "BadDataPresenter"), patch.object(
            main.ContainerFileWriter, "writeCSV", autospec=True,
        ) as write_csv, redirect_stdout(io.StringIO()):
            main.main()
        self.assertEqual(write_csv.call_count, 2)
        self.assertEqual([call.args[0].file_path.name for call in write_csv.call_args_list],
                         ["result_JKT74.csv", "result_JKT64.csv"])
        yards = [call.args[1] for call in write_csv.call_args_list]
        self.assertEqual([set(yard.blocks_by_id) for yard in yards], [{"10", "11"}, {"12"}])


if __name__ == "__main__":
    unittest.main()

"""Existing-yard metrics never load or place inbound containers."""

from contextlib import redirect_stdout
import io
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from config import ConfigurationError, DEFAULT_INPUT_CONFIG_FILE
from repository import CSVLoader
import main_existing


class ExistingYardMainTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.input_path = self.root / "input.toml"
        self.shifting_path = self.root / "shifting.csv"
        self.mapping_path = self.root / "shifting_block_mapping.toml"
        # Test-only assignments, not actual operational assignments.
        self.mapping_path.write_text('[CY219]\nSL = "10"\nRS = "11"\n', encoding="utf-8")
        project = DEFAULT_INPUT_CONFIG_FILE.parent.parent
        template = DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8")
        template = template.replace(
            "../data_CY219/", (project / "data_CY219").as_posix() + "/"
        ).replace(
            'mapping_file = "csv_mapping.toml"',
            'mapping_file = "' +
            DEFAULT_INPUT_CONFIG_FILE.with_name("csv_mapping.toml").as_posix() + '"',
        )
        # Keep operational SQL selectors to verify this entrypoint is CSV-only.
        template = "\n".join(
            'shifting_summary_file = "' + self.shifting_path.as_posix() + '"'
            if line.lstrip("# ").startswith("shifting_summary_file =") else line
            for line in template.splitlines()
        ) + "\n"
        self.input_path.write_text(template, encoding="utf-8")
        self.write_shifting(
            "CY219,SL,100,10,2026-10,40\n"
            "CY219,SL,100,10,2026-10,40\n"
            "CY218,SL,999,99,,\n"
        )

    def write_shifting(self, rows):
        data = list(csv.reader(io.StringIO(rows)))
        for row in data:
            row[4] = row[4] or "2026-10"
            row[5] = row[5] or "40"
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerows(data)
        self.shifting_path.write_text(
            "cy_name,equipment_group,lifting_count,shifting_count,"
            "report_month,week_number\n" + buffer.getvalue(),
            encoding="utf-8",
        )

    def test_existing_yard_loads_without_inbound_or_sql(self):
        opened = []
        original_open = CSVLoader.open

        def guarded_open(loader):
            opened.append(loader.file_path.name)
            self.assertNotIn("inbound", loader.file_path.name.lower())
            return original_open(loader)

        with patch.object(CSVLoader, "open", guarded_open), patch.object(
            main_existing.Yard, "assign_and_place",
            side_effect=AssertionError("Inbound placement called"),
        ), patch.dict("sys.modules", {"psycopg": None}):
            report = main_existing.build_report(self.input_path)

        self.assertEqual(len(opened), 8)
        self.assertGreater(report["loaded_containers"], 0)
        self.assertEqual(
            report["loaded_containers"],
            sum(block["container_count"] for block in report["blocks"]),
        )
        self.assertTrue(0 <= report["parameter_compliance"] <= 1)
        self.assertEqual(report["shifting_count"], 20)
        self.assertEqual(report["shifting_data_points"], 2)
        self.assertEqual(report["shifting_observations"][0]["report_month"], "2026-10")

    def test_available_shifts_are_summed_and_missing_observations_counted(self):
        self.write_shifting("CY219,SL,100,10,,\nCY219,SL,,,,\n")
        report = main_existing.build_report(self.input_path)
        self.assertEqual(report["shifting_count"], 10)
        self.assertEqual(report["missing_shifting_observations"], 1)
        self.assertNotIn("known_shifting_count", report)

    def test_latest_week_uses_aggregate_operations_and_unix_recording_time(self):
        self.write_shifting(
            "CY219,SL,9000,9000,2026-10,43\n"
            "CY219,SL,100,100,2026-10,44\n"
            "CY219,RS,900,0,2026-10,44\n"
        )
        with patch.object(main_existing, "time", return_value=1234567890.7):
            report = main_existing.build_report(self.input_path)
        self.assertEqual(report["recorded_at"], 1234567890)
        self.assertNotIn("recorded_at_utc", report)
        self.assertEqual(report["latest_week"], 44)
        self.assertEqual(report["period_start"], 1860336000)
        self.assertEqual(report["period_end"], 1860940800)
        self.assertEqual(report["lifting_count"], 1000)
        self.assertEqual(report["shifting_count"], 100)
        self.assertEqual(report["total_operations"], 1100)
        self.assertAlmostEqual(report["shifting_percentage"], 100 * 100 / 1100)
        self.assertEqual(report["shifting_data_points"], 2)
        self.assertEqual(report["loaded_shifting_data_points"], 2)
        self.assertEqual(len(report["shifting_observations"]), 2)
        self.assertEqual(report["parameter_compliance_basis"], "current_yard_snapshot")
        blocks = {block["block_id"]: block for block in report["blocks"]}
        self.assertEqual(blocks["10"]["shifting_percentage"], 50)
        self.assertEqual(blocks["11"]["shifting_percentage"], 0)

    def test_missing_historical_counts_do_not_block_latest_week(self):
        self.write_shifting(
            "CY219,SL,100,,2026-10,43\n"
            "CY219,RS,,,2026-10,43\n"
            "CY219,UNKNOWN,bad,count,2026-10,42\n"
            "CY219,SL,200,20,2026-10,44\n"
            "CY219,RS,100,10,2026-10,44\n"
        )
        report = main_existing.build_report(self.input_path)
        self.assertEqual(report["latest_week"], 44)
        self.assertEqual(report["lifting_count"], 300)
        self.assertEqual(report["shifting_count"], 30)
        self.assertAlmostEqual(report["shifting_percentage"], 100 * 30 / 330)
        self.assertEqual(report["missing_lifting_observations"], 0)
        self.assertEqual(report["missing_shifting_observations"], 0)
        self.assertEqual(len(report["shifting_observations"]), 2)

    def test_latest_week_with_absent_blocks_does_not_fall_back_to_older_week(self):
        self.mapping_path.write_text('[CY219]\nSL = "10"\nRS = "99"\n', encoding="utf-8")
        self.write_shifting(
            "CY219,SL,200,20,2026-10,43\nCY219,RS,100,10,2026-10,44\n"
        )
        with self.assertWarnsRegex(UserWarning, "RS -> 99"):
            report = main_existing.build_report(self.input_path)
        self.assertIsNone(report["shifting_count"])
        self.assertIsNone(report["shifting_percentage"])
        self.assertEqual(report["shifting_observations"], [])
        self.assertEqual(report["skipped_shifting_data_points"], 1)

    def test_incomplete_latest_week_keeps_counts_and_no_percentage(self):
        self.write_shifting(
            "CY219,SL,1000,500,2026-10,43\n"
            "CY219,SL,50,10,2026-10,44\n"
            "CY219,RS,,,2026-10,44\n"
        )
        report = main_existing.build_report(self.input_path)
        self.assertEqual(report["latest_week"], 44)
        self.assertEqual(report["lifting_count"], 50)
        self.assertEqual(report["shifting_count"], 10)
        self.assertIsNone(report["shifting_percentage"])
        self.assertEqual(report["missing_lifting_observations"], 1)
        self.assertEqual(report["missing_shifting_observations"], 1)

    def test_zero_total_operations_has_no_percentage(self):
        self.write_shifting("CY219,SL,0,0,2026-10,44\n")
        report = main_existing.build_report(self.input_path)
        self.assertEqual(report["total_operations"], 0)
        self.assertIsNone(report["shifting_percentage"])

    def test_older_block_data_is_not_joined_to_latest_week(self):
        self.write_shifting(
            "CY219,SL,50,10,2026-10,44\nCY219,RS,100,30,2026-10,43\n"
        )
        report = main_existing.build_report(self.input_path)
        block = next(b for b in report["blocks"] if b["block_id"] == "11")
        self.assertIsNone(block["lifting_count"])
        self.assertIsNone(block["shifting_count"])
        self.assertIsNone(block["shifting_percentage"])

    def test_all_missing_observations_do_not_become_zero(self):
        self.write_shifting("CY219,SL,,,,\n")
        report = main_existing.build_report(self.input_path)
        self.assertIsNone(report["shifting_count"])
        self.assertEqual(report["missing_shifting_observations"], 1)

    def test_explicit_zero_remains_zero(self):
        self.write_shifting("CY219,SL,100,0,,\n")
        report = main_existing.build_report(self.input_path)
        self.assertEqual(report["shifting_count"], 0)
        self.assertEqual(report["shifting_percentage"], 0)
        self.assertEqual(report["missing_shifting_observations"], 0)

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
        with patch.object(main_existing, "Yard", return_value=yard):
            report = main_existing.build_report(self.input_path)
        self.assertEqual(report["parameter_compliance"], 0.25)
        self.assertTrue(report["has_bad_data"])

    def test_empty_yard_records_skipped_observations_and_no_compliance(self):
        yard = SimpleNamespace(
            containers={}, blocks_by_id={},
            bad_data=SimpleNamespace(anyBadData=lambda: False),
        )
        with patch.object(main_existing, "Yard", return_value=yard), self.assertWarns(UserWarning):
            report = main_existing.build_report(self.input_path)
        self.assertEqual(report["loaded_containers"], 0)
        self.assertIsNone(report["parameter_compliance"])
        self.assertIsNone(report["shifting_count"])
        self.assertEqual(report["shifting_data_points"], 0)
        self.assertIsNone(report["period_start"])
        self.assertIsNone(report["lifting_count"])
        self.assertIsNone(report["shifting_percentage"])
        self.assertEqual(report["skipped_shifting_data_points"], 2)

    def test_absent_block_counts_are_excluded_from_yard_and_block_totals(self):
        self.mapping_path.write_text('[CY219]\nSL = "10"\nRS = "99"\n', encoding="utf-8")
        self.write_shifting("CY219,SL,100,10,,\nCY219,RS,100,30,,\n")
        with self.assertWarnsRegex(UserWarning, "RS -> 99"):
            report = main_existing.build_report(self.input_path)
        self.assertEqual(report["shifting_count"], 10)
        self.assertEqual(report["shifting_data_points"], 1)
        self.assertEqual(report["skipped_shifting_data_points"], 1)
        self.assertEqual(report["skipped_shifting_observations"][0]["shifting_count"], 30)
        self.assertEqual(
            next(b for b in report["blocks"] if b["block_id"] == "10")["shifting_count"], 10,
        )

    def test_shifting_counts_are_joined_to_blocks(self):
        self.write_shifting(
            "CY219,SL,100,10,,\nCY219,RS,100,30,,\nCY219,SL,100,20,,\n"
        )
        report = main_existing.build_report(self.input_path)
        blocks = {block["block_id"]: block for block in report["blocks"]}
        self.assertEqual(blocks["10"]["shifting_count"], 30)
        self.assertEqual(blocks["10"]["shifting_data_points"], 2)
        self.assertEqual(blocks["11"]["shifting_count"], 30)
        self.assertEqual(report["shifting_count"], 60)
        self.assertEqual(report["shifting_observations"][0]["shifting_code"], "SL")
        self.assertEqual(report["shifting_observations"][0]["block_id"], "10")
        self.assertNotIn("equipment_group", report["shifting_observations"][0])

    def test_block_without_observations_is_not_reported_as_zero(self):
        report = main_existing.build_report(self.input_path)
        block = next(block for block in report["blocks"] if block["block_id"] == "11")
        self.assertEqual(block["shifting_data_points"], 0)
        self.assertIsNone(block["shifting_count"])
        self.assertEqual(block["missing_shifting_observations"], 0)
        self.assertNotIn("known_shifting_count", block)

    def test_shifting_path_is_required(self):
        text = self.input_path.read_text(encoding="utf-8")
        self.input_path.write_text(
            text.replace("\nshifting_summary_file =", "\n# shifting_summary_file ="),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigurationError, "shifting_summary_file"):
            main_existing.build_report(self.input_path)

    def test_main_appends_one_json_record_per_run(self):
        self.write_shifting("CY219,SL,100,10,,\nCY219,SL,,,,\n")
        report = main_existing.build_report(self.input_path)
        captured = io.StringIO()
        with patch.object(main_existing, "build_report", return_value=report), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE",
            self.root / "config" / "input.toml",
        ), redirect_stdout(captured):
            main_existing.main()
            main_existing.main()
        output = self.root / "output" / "existing_yard_metrics.jsonl"
        records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records, [report, report])
        self.assertIn("Shifting count: 10", captured.getvalue())
        self.assertIn("Lifting count: 100", captured.getvalue())
        self.assertIn("Shifting percentage: N/A", captured.getvalue())
        self.assertIn("Missing shifting observations: 1", captured.getvalue())
        self.assertNotIn("Known shifting count:", captured.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Week benchmarks provide explicit Unix boundaries without calendar inference."""

import copy
import unittest
from dataclasses import replace

from config import ConfigurationError
from config.application.shifting_period import (
    ShiftingPeriodSettings, parse_shifting_period,
)
from repository import InputError
from repository.shifting_repository import (
    ShiftingSummary, assign_shifting_periods,
)
from tests import test_shifting_repository as shifting_tests


class ShiftingPeriodTests(unittest.TestCase):
    def setUp(self):
        self.settings = ShiftingPeriodSettings(40, 1857916800)
        self.row = ShiftingSummary("CY 219 (Lini 2)", "SL", 100, 10,
                                   report_month="2026-10", week_number="44", block_id="10")

    def test_benchmark_forward_and_backward_offsets(self):
        self.assertEqual(self.settings.boundaries(40), (1857916800, 1858521600))
        self.assertEqual(self.settings.boundaries(44), (1860336000, 1860940800))
        self.assertEqual(self.settings.boundaries(39), (1857312000, 1857916800))

    def test_invalid_benchmarks_and_report_weeks(self):
        for week in (None, 0, 54, True, "40", 40.0):
            with self.subTest(week=week), self.assertRaises(ConfigurationError):
                ShiftingPeriodSettings(week, 1857916800)
        for stamp in (None, -1, True, "1857916800", 1857916800.0):
            with self.subTest(stamp=stamp), self.assertRaises(ConfigurationError):
                ShiftingPeriodSettings(40, stamp)
        for week in (0, 54, True, "44"):
            with self.subTest(week=week), self.assertRaises(ConfigurationError):
                self.settings.boundaries(week)
        with self.assertRaises(ConfigurationError):
            ShiftingPeriodSettings(40, 0).boundaries(39)

    def test_configuration_requires_complete_known_settings(self):
        self.assertIsNone(parse_shifting_period({}))
        with self.assertRaisesRegex(ConfigurationError, "Configure"):
            parse_shifting_period({}, required=True)
        for section in ({}, {"benchmark_week": 40},
                        {"benchmark_week": 40, "benchmark_period_start": 1, "other": 1}, []):
            with self.subTest(section=section), self.assertRaises(ConfigurationError):
                parse_shifting_period({"shifting_period": section})
        actual = parse_shifting_period({"shifting_period": {
            "benchmark_week": 40, "benchmark_period_start": 1857916800,
        }})
        self.assertEqual(actual, self.settings)

    def test_boundaries_attached_without_changing_source_record(self):
        row = assign_shifting_periods([self.row], self.settings)[0]
        self.assertEqual(row.period_start, 1860336000)
        self.assertEqual(row.period_end, 1860940800)
        self.assertIsNone(self.row.period_start)

    def test_missing_and_invalid_week_labels_are_reported(self):
        for week in (None, "", "unknown", "0", "54"):
            with self.subTest(week=week), self.assertRaises(InputError):
                assign_shifting_periods([replace(self.row, week_number=week)], self.settings)

    def test_report_year_reset_requires_another_benchmark(self):
        rows = [self.row, replace(self.row, report_month="2027-01", week_number="1")]
        with self.assertRaisesRegex(InputError, "one report year"):
            assign_shifting_periods(rows, self.settings)

    def test_shifting_ratio_is_share_of_all_operations(self):
        self.assertAlmostEqual(self.row.shifting_ratio, 10 / 110)
        self.assertAlmostEqual(self.row.shifting_percentage, 100 * 10 / 110)
        self.assertEqual(replace(self.row, lifting_count=0).shifting_percentage, 100)
        self.assertIsNone(replace(self.row, lifting_count=0, shifting_count=0).shifting_percentage)
        self.assertIsNone(replace(self.row, lifting_count=None).shifting_percentage)


class ShiftingPeriodInputTests(unittest.TestCase):
    setUp = shifting_tests.ShiftingInputTests.setUp
    settings = shifting_tests.ShiftingInputTests.settings

    def test_benchmark_available_to_shared_input_loader(self):
        import tempfile
        from pathlib import Path
        from repository import load_yard_inputs

        document = copy.deepcopy(self.document)
        document["shifting_period"] = {
            "benchmark_week": 40, "benchmark_period_start": 1857916800,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shifting.csv"
            mapping = Path(directory) / "mapping.toml"
            path.write_text(
                "cy_name,shifting_code,lifting_count,shifting_count,report_month,week_number\n"
                "CY 219 (Lini 2),SL,100,10,2026-10,44\n", encoding="utf-8",
            )
            mapping.write_text('["CY 219 (Lini 2)"]\nSL = "10"\n', encoding="utf-8")
            document["csv"]["shifting_summary_file"] = path.as_posix()
            document["csv"]["shifting_block_mapping_file"] = mapping.as_posix()
            settings = self.settings(document)
            self.assertEqual(settings["shifting_period"], ShiftingPeriodSettings(40, 1857916800))
            rows = load_yard_inputs(settings)["shifting_summary"]
        self.assertEqual(rows[0].period_start, 1860336000)
        self.assertEqual(rows[0].period_end, 1860940800)


if __name__ == "__main__":
    unittest.main()

"""Keep block series identifiable across old and new JSONL schemas."""

import math
import unittest

from visualize_metrics import equipment_codes, plot_metrics


class EquipmentCodesTests(unittest.TestCase):
    def test_arrays_and_legacy_strings_preserve_equipment_names(self):
        expected = ("RS MDL", "RTG05")
        self.assertEqual(equipment_codes({"assigned_equipment": ["RTG05", "RS MDL", "RTG05"]}), expected)
        self.assertEqual(equipment_codes({"shifting_code": "RS MDL, RTG05"}), expected)
        self.assertEqual(equipment_codes({"assigned_equipment": ["SL"]}), ("SL",))
        self.assertEqual(equipment_codes({}), ())

    def test_invalid_equipment_arrays_are_rejected(self):
        for value in ("RTG03, RTG05", None, [None], [""]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "assigned_equipment"):
                equipment_codes({"assigned_equipment": value})


class MetricsIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import matplotlib
        except ImportError:
            raise unittest.SkipTest("matplotlib is optional")
        matplotlib.use("Agg")

    def test_mixed_history_keeps_series_continuous_and_branches_separate(self):
        import matplotlib.pyplot as plt

        observation = {
            "block_code": "B",
            "shifting_percentage": 10, "parameter_compliance": 40,
        }
        records = [
            {"period_end": 1000, "shifting_observations": [
                {**observation, "cy_name": "First yard", "branch_code": "JKT74",
                 "shifting_code": "RS MDL, RTG05"},
            ]},
            {"period_end": 2000, "cy_name": "First yard", "branch_code": "JKT74",
             "shifting_observations": [{**observation, "shifting_percentage": 20,
                                        "assigned_equipment": ["RTG05", "RS MDL"]}]},
            {"period_end": 3000, "cy_name": "Second yard", "branch_code": "JKT64",
             "shifting_observations": [{**observation, "shifting_percentage": 30,
                                        "assigned_equipment": ["SL"]}]},
        ]
        figure = plot_metrics(records)
        self.addCleanup(plt.close, figure)
        self.assertEqual([axis.get_title() for axis in figure.axes], [
            "Overall averages", "First yard / JKT74 / Block B", "Second yard / JKT64 / Block B",
        ])
        first = figure.axes[1].lines[0].get_ydata()
        second = figure.axes[2].lines[0].get_ydata()
        self.assertEqual(list(first[:2]), [10, 20])
        self.assertEqual(figure.axes[1].lines[0].get_label(), "Shifting (RS MDL, RTG05)")
        self.assertEqual(second[2], 30)
        self.assertTrue(math.isnan(first[2]))
        self.assertTrue(all(math.isnan(value) for value in second[:2]))


if __name__ == "__main__":
    unittest.main()

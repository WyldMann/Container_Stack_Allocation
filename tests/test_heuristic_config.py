import math
import tempfile
import unittest
from dataclasses import fields, FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from config import (
    ApplicationSettings, ConfigurationError, FeasibilitySettings,
    HeuristicSettings, load_config, load_feasibility_settings,
)
from entities.block import Block
from entities.heuristic_model import HeuristicModel
from entities.yard import Yard


class HeuristicConfigTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text(text, encoding='utf-8')
            return load_config(path)

    def test_missing_sections_preserve_defaults(self):
        self.assertEqual(self.load_text(''), ApplicationSettings())

    def test_both_sections_are_loaded_with_partial_defaults(self):
        result = self.load_text(
            '[feasibility]\nloader_access = false\n'
            '[heuristic]\nw_delta_weight = 20\nsize_cluster_radius = 0\n'
        )
        self.assertEqual(result.feasibility, FeasibilitySettings(loader_access=False))
        self.assertEqual(result.heuristic.w_delta_weight, 20)
        self.assertEqual(result.heuristic.size_cluster_radius, 0)
        self.assertEqual(result.heuristic.hl_delta_weight, 5000)

    def test_default_file_matches_default_settings(self):
        path = Path(__file__).resolve().parents[1] / 'config.toml'
        self.assertEqual(load_config(path), ApplicationSettings())

    def test_unknown_options_and_wrong_section_type_are_rejected(self):
        for text in ('[heuristic]\nunknown = 1\n', 'heuristic = false\n'):
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_invalid_numeric_values_are_rejected(self):
        for field in fields(HeuristicSettings):
            values = ('true', '"1"', '[]', '-1')
            if field.name == 'size_cluster_radius':
                values += ('1.5',)
            else:
                values += ('nan', 'inf', '-inf')
                if field.name != 'size_cluster_bias':
                    values += ('0',)
            for value in values:
                with self.subTest(field=field.name, value=value):
                    with self.assertRaises(ConfigurationError):
                        self.load_text(f'[heuristic]\n{field.name} = {value}\n')

    def test_direct_settings_validation_and_immutability(self):
        for value in (True, '1', math.inf, math.nan, -1, 0, 10 ** 1000):
            with self.subTest(value=str(value)[:20]):
                with self.assertRaises((TypeError, ValueError)):
                    HeuristicSettings(hl_delta_weight=value)
        settings = HeuristicSettings()
        with self.assertRaises(FrozenInstanceError):
            settings.w_delta_weight = 20

    def test_legacy_feasibility_loader_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text(
                '[feasibility]\nloader_access = false\n'
                '[heuristic]\nw_delta_weight = 20\n', encoding='utf-8',
            )
            self.assertEqual(
                load_feasibility_settings(path),
                FeasibilitySettings(loader_access=False),
            )


class ConfiguredHeuristicModelTests(unittest.TestCase):
    def test_default_scores_preserve_previous_formula(self):
        model = HeuristicModel()
        for weight, distance in ((0, 0), (5000, 5), (None, 0), (-1, 0), (0, math.inf)):
            with self.subTest(weight=weight, distance=distance):
                weight_score = (
                    0.1 if weight is None else
                    0.001 if weight < 0 else
                    10 * math.exp(-math.log(2) / 5000 * weight)
                )
                distance_score = (
                    0.001 if distance == math.inf else
                    10 * math.exp(-math.log(2) / 5 * distance)
                )
                self.assertEqual(model.evaluate(weight, distance), weight_score * distance_score)

    def test_custom_weights_and_half_lives(self):
        model = HeuristicModel(HeuristicSettings(
            w_delta_weight=20, hl_delta_weight=1000,
            w_equipment_distance=8, hl_equipment_distance=10,
            min_value=0.02, no_delta_weight_value=0.4,
        ))
        self.assertAlmostEqual(model.deltaWeight(1000), 10)
        self.assertAlmostEqual(model.equipmentDistance(10), 4)
        self.assertAlmostEqual(model.evaluate(1000, 10), 40)
        self.assertEqual(model.deltaWeight(None), 0.4)
        self.assertEqual(model.deltaWeight(-1), 0.02)
        self.assertEqual(model.equipmentDistance(math.inf), 0.02)

    def test_custom_clustering_constants_and_zero_controls(self):
        block = Block(
            BRANCH_ID='B', BLOCK_ID='A', BLOCK_CODE='A', SLOT_COUNT='4',
            ROW_COUNT='3', MAX_TIER='3', POS_X='0', POS_Y='0',
        )
        container = SimpleNamespace(getContSize=lambda: '20')
        block.getStack(1, 1).addContainer(container, 0)
        coord = ('A', 1, 2, 0)
        model = HeuristicModel(HeuristicSettings(
            size_cluster_radius=1, hl_size_cluster_distance=1,
            size_cluster_prior=4, size_cluster_bias=2,
        ))
        self.assertAlmostEqual(model.sizeCluster(container, block, coord), 2 ** (2 * 0.5 / 4.5))
        for settings in (HeuristicSettings(size_cluster_radius=0), HeuristicSettings(size_cluster_bias=0)):
            with self.subTest(settings=settings):
                self.assertEqual(HeuristicModel(settings).sizeCluster(container, block, coord), 1)

    def test_yards_have_independent_configured_models(self):
        first = Yard([], heuristic_settings=HeuristicSettings(w_delta_weight=20))
        second = Yard([])
        self.assertIsNot(first.model, second.model)
        self.assertEqual(first.model.evaluate(0, 0), 200)
        self.assertEqual(second.model.evaluate(0, 0), 100)
        first.model.W_DELTA_WEIGHT = 30
        self.assertEqual(second.model.evaluate(0, 0), 100)

    def test_file_settings_reach_yard_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('[heuristic]\nw_delta_weight = 25\n', encoding='utf-8')
            settings = load_config(path)
        yard = Yard([], feasibility_settings=settings.feasibility, heuristic_settings=settings.heuristic)
        self.assertEqual(yard.model.evaluate(0, 0), 250)


if __name__ == '__main__':
    unittest.main()

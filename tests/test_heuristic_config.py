import math
import tempfile
import unittest
from dataclasses import fields, FrozenInstanceError
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from config import (
    ApplicationSettings, ConfigurationError, FeasibilitySettings,
    HeuristicSettings, load_config, load_feasibility_settings,
    load_heuristic_settings,
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
        path = Path(__file__).resolve().parents[1] / 'config' / 'config.toml'
        self.assertEqual(load_config(path), ApplicationSettings())

    def test_unknown_options_and_wrong_section_type_are_rejected(self):
        for text in ('[heuristic]\nunknown = 1\n', 'heuristic = false\n'):
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_invalid_numeric_values_are_rejected(self):
        for field in fields(HeuristicSettings):
            if field.type is bool:
                continue
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

    def test_factor_switches_accept_booleans_and_preserve_other_defaults(self):
        for name in ('enable_delta_weight', 'enable_equipment_distance', 'enable_size_cluster'):
            for enabled in (True, False):
                with self.subTest(name=name, enabled=enabled):
                    result = self.load_text(f'[heuristic]\n{name} = {str(enabled).lower()}\n')
                    self.assertEqual(result.heuristic, HeuristicSettings(**{name: enabled}))

    def test_factor_switches_reject_non_booleans(self):
        for name in ('enable_delta_weight', 'enable_equipment_distance', 'enable_size_cluster'):
            for value in ('0', '1', '1.0', '"false"', '[]', 'nan', 'inf'):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ConfigurationError):
                        self.load_text(f'[heuristic]\n{name} = {value}\n')
            for value in (0, 1, 1.0, 'false', None):
                with self.subTest(name=name, direct_value=value):
                    with self.assertRaises(TypeError):
                        HeuristicSettings(**{name: value})

    def test_disabled_factors_still_validate_numeric_settings(self):
        with self.assertRaises(ConfigurationError):
            self.load_text(
                '[heuristic]\nenable_delta_weight = false\nhl_delta_weight = 0\n'
            )

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

    def test_heuristic_only_loader_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('', encoding='utf-8')
            self.assertEqual(load_heuristic_settings(path), HeuristicSettings())

    def test_heuristic_only_loader_reads_partial_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text(
                'feasibility = false\n'
                '[heuristic]\nw_delta_weight = 20\n', encoding='utf-8',
            )
            # Like the feasibility-only loader, it validates its own section.
            self.assertEqual(
                load_heuristic_settings(path), HeuristicSettings(w_delta_weight=20),
            )

    def test_heuristic_only_loader_rejects_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            for text in (
                '[heuristic]\nunknown = 1\n',
                '[heuristic]\nhl_delta_weight = 0\n',
                'heuristic = false\n',
                '[heuristic\n',
            ):
                with self.subTest(text=text):
                    path.write_text(text, encoding='utf-8')
                    with self.assertRaises(ConfigurationError):
                        load_heuristic_settings(path)
            with self.assertRaises(ConfigurationError):
                load_heuristic_settings(Path(directory) / 'missing.toml')


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

    def test_factor_switch_combinations(self):
        for weight_enabled, distance_enabled, cluster_enabled in product((True, False), repeat=3):
            with self.subTest(weight=weight_enabled, distance=distance_enabled, cluster=cluster_enabled):
                model = HeuristicModel(HeuristicSettings(
                    enable_delta_weight=weight_enabled,
                    enable_equipment_distance=distance_enabled,
                    enable_size_cluster=cluster_enabled,
                ))
                expected = (
                    (5 if weight_enabled else 1)
                    * (5 if distance_enabled else 1)
                    * (1.5 if cluster_enabled else 1)
                )
                self.assertAlmostEqual(model.evaluate(5000, 5, 1.5), expected)

    def test_disabled_weight_and_distance_skip_scoring_and_fallbacks(self):
        model = HeuristicModel(HeuristicSettings(
            enable_delta_weight=False, enable_equipment_distance=False,
        ))
        model.decayFormula = Mock(side_effect=AssertionError('Decay should be skipped.'))
        for weight in (None, -1, 0, 5000):
            with self.subTest(weight=weight):
                self.assertEqual(model.deltaWeight(weight), 1.0)
        for distance in (0, 5, math.inf):
            with self.subTest(distance=distance):
                self.assertEqual(model.equipmentDistance(distance), 1.0)
        model.decayFormula.assert_not_called()

    def test_disabled_clustering_skips_neighborhood_scan(self):
        model = HeuristicModel(HeuristicSettings(enable_size_cluster=False))
        container, block = Mock(), Mock()
        self.assertEqual(model.sizeCluster(container, block, ('A', 1, 2, 0)), 1.0)
        block.getSlots.assert_not_called()
        container.getContSize.assert_not_called()

    def test_all_factors_disabled_ignore_fallbacks_and_supplied_multiplier(self):
        model = HeuristicModel(HeuristicSettings(
            enable_delta_weight=False,
            enable_equipment_distance=False,
            enable_size_cluster=False,
        ))
        for weight, distance in ((0, 0), (None, math.inf), (-1, 5)):
            with self.subTest(weight=weight, distance=distance):
                self.assertEqual(model.evaluate(weight, distance, 0.25), 1.0)

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
            branch_id='B', block_id='A', block_code='A', slot_count='4',
            row_count='3', max_tier='3', pos_x='0', pos_y='0',
        )
        container = SimpleNamespace(getContSize=lambda: '20')
        block.getStack(1, 1).addContainer(container, 0)
        coordinate = ('A', 1, 2, 0)
        model = HeuristicModel(HeuristicSettings(
            size_cluster_radius=1, hl_size_cluster_distance=1,
            size_cluster_prior=4, size_cluster_bias=2,
        ))
        self.assertAlmostEqual(model.sizeCluster(container, block, coordinate), 2 ** (2 * 0.5 / 4.5))
        for settings in (HeuristicSettings(size_cluster_radius=0), HeuristicSettings(size_cluster_bias=0)):
            with self.subTest(settings=settings):
                self.assertEqual(HeuristicModel(settings).sizeCluster(container, block, coordinate), 1)

    def test_yards_have_independent_configured_models(self):
        first = Yard([], heuristic_settings=HeuristicSettings(w_delta_weight=20))
        second = Yard([])
        self.assertIsNot(first.model, second.model)
        self.assertEqual(first.model.evaluate(0, 0), 200)
        self.assertEqual(second.model.evaluate(0, 0), 100)
        first.model.w_delta_weight = 30
        self.assertEqual(second.model.evaluate(0, 0), 100)

    def test_file_settings_reach_yard_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('[heuristic]\nw_delta_weight = 25\n', encoding='utf-8')
            settings = load_config(path)
        yard = Yard([], feasibility_settings=settings.feasibility, heuristic_settings=settings.heuristic)
        self.assertEqual(yard.model.evaluate(0, 0), 250)

    def test_file_factor_switches_reach_yard_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text(
                '[heuristic]\nenable_delta_weight = false\n'
                'enable_equipment_distance = false\nenable_size_cluster = false\n',
                encoding='utf-8',
            )
            settings = load_config(path)
        yard = Yard([], heuristic_settings=settings.heuristic)
        self.assertFalse(yard.model.enable_delta_weight)
        self.assertFalse(yard.model.enable_equipment_distance)
        self.assertFalse(yard.model.enable_size_cluster)
        self.assertEqual(yard.model.evaluate(0, 0, 2), 1.0)


if __name__ == '__main__':
    unittest.main()

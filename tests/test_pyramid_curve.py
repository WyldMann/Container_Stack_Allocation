import unittest
from types import SimpleNamespace

from config import ConfigurationError, FeasibilitySettings, HeuristicSettings
from config.application.config_loader import parse_config
from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.heuristic_model import HeuristicModel
from entities.yard import Yard


class PyramidCurveTests(unittest.TestCase):
    def test_curve_has_full_score_linear_decline_and_endpoint(self):
        model = HeuristicModel(HeuristicSettings(stacking_safety_limit_multiplier=0.25))
        for difference, expected in ((0, 1), (1, 1), (2, 0.75), (3, 0.5), (4, 0.25), (5, 0.25)):
            with self.subTest(difference=difference):
                self.assertAlmostEqual(model.stackingSafetyMultiplier(difference, 1, 4), expected)
        for floor in (0, 1):
            model = HeuristicModel(HeuristicSettings(stacking_safety_limit_multiplier=floor))
            self.assertEqual(model.stackingSafetyMultiplier(1, 1, 4), 1)
            self.assertEqual(model.stackingSafetyMultiplier(4, 1, 4), floor)

    def test_configuration_round_trip_and_validation(self):
        parsed = parse_config({
            "feasibility": {"stacking_safety_mode": "combined", "stacking_safety_penalty_start": 1, "stacking_safety_maxima": 4},
            "heuristic": {"stacking_safety_limit_multiplier": 0.25},
        })
        self.assertEqual(parse_config(parsed.to_document()).to_document(), parsed.to_document())
        self.assertEqual(parse_config({}).feasibility.stacking_safety_penalty_start, 0)
        self.assertEqual(FeasibilitySettings(stacking_safety_maxima=1).stacking_safety_penalty_start, 0)
        self.assertEqual(HeuristicSettings(unsafe_stacking_multiplier=0.4).stacking_safety_limit_multiplier, 0.4)
        self.assertEqual(HeuristicSettings(unsafe_stacking_multiplier=0.4, stacking_safety_limit_multiplier=0.2).stacking_safety_limit_multiplier, 0.2)
        for invalid in (-1, 2, 3, True, 0.5, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                parse_config({"feasibility": {"stacking_safety_penalty_start": invalid}})
        for invalid in (-0.1, 1.1, True, "0.25", float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                parse_config({"heuristic": {"stacking_safety_limit_multiplier": invalid}})
        with self.assertRaises(ConfigurationError):
            parse_config({"feasibility": {"loader_access_mode": "combined"}})

    def yard(self, size, mode):
        return Yard(
            yard_blocks_input=[dict(branch_id="B", block_id="A", block_code="A", row_count="3",
                                    slot_count="4", max_tier="6", pos_x="0", pos_y="0")],
            feasibility_settings=FeasibilitySettings(loader_access=False, stacking_safety_mode=mode,
                                                     stacking_safety_penalty_start=1, stacking_safety_maxima=4),
            heuristic_settings=HeuristicSettings(enable_delta_container_mass=False, enable_equipment_distance=False,
                                                 enable_size_cluster=False, stacking_safety_limit_multiplier=0.25),
        )

    def incoming(self, size):
        return Container(container_id="NEW", principal="", container_condition="", container_fill="",
                         container_size=size, container_grade="", pol="", pod="", vessel="", voyage="",
                         weight="", move_time="", branch_id="", block_code="", row_no="", slot_no="", tier_no="")

    def fill(self, block, row, slot, size, height):
        for tier in range(height):
            block.getStack(row, slot).addContainer(SimpleNamespace(getContSize=lambda: size, getWeight=lambda: None), tier)

    def test_all_modes_score_and_enforce_boundaries_for_both_sizes(self):
        for size in ("20", "40"):
            for mode in ("off", "heuristic", "feasibility", "combined"):
                for difference, multiplier in ((1, 1), (2, 0.75), (3, 0.5), (4, 0.25), (5, 0.25)):
                    with self.subTest(size=size, mode=mode, difference=difference):
                        yard = self.yard(size, mode)
                        block = yard.getBlockByID("A")
                        for slot in ((0, 1) if size == "40" else (1,)):
                            self.fill(block, 1, slot, size, difference - 1)
                        incoming = self.incoming(size)
                        coordinate = ("A", 1, 1, difference - 1)
                        result = yard.feasibility.evaluate(incoming, block, 1, 1)
                        if mode in ("combined", "feasibility") and difference > 4:
                            self.assertFalse(result.feasible)
                            with self.assertRaises(PlacementRejected):
                                yard.addContainerByCoords(incoming, coordinate)
                        else:
                            self.assertEqual(result.coordinates, coordinate)
                            candidate = yard.bestCoordCandidate(incoming, [coordinate])[0]
                            self.assertAlmostEqual(candidate.stacking_safety_multiplier,
                                                   multiplier if mode in ("combined", "heuristic") else 1)
                            yard.addContainerByCoords(incoming, coordinate)

    def test_empty_forty_foot_footprint_uses_both_neighbor_cells(self):
        yard = self.yard("40", "combined")
        block = yard.getBlockByID("A")
        self.fill(block, 0, 0, "20", 3)
        self.assertEqual(block.pyramidHeightDifference(1, 1, container_size="40"), 0)
        self.assertEqual(block.pyramidHeightDifference(1, 1, container_size="20"), 1)
        incoming = self.incoming("40")
        candidate = yard.bestCoordCandidate(incoming, [("A", 1, 1, 0)])[0]
        self.assertEqual(candidate.stacking_safety_multiplier, 1)


if __name__ == "__main__":
    unittest.main()

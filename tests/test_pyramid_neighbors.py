import unittest
from itertools import product
from types import SimpleNamespace

from config import ConfigurationError, FeasibilitySettings, HeuristicSettings
from config.application.config_loader import parse_config
from entities import Container
from entities.block import Block
from entities.feasibility.placement_feasibility import PlacementFeasibility, RejectionReason
from entities.yard import Yard


DIRECTIONS = ("up", "down", "left", "right")


class PyramidNeighborTests(unittest.TestCase):
    def make_block(self, size):
        block = Block(
            branch_id="B", block_id="A", block_code="A", slot_count="6",
            row_count="3", max_tier="5", pos_x="0", pos_y="0",
        )
        for slot in ((2, 3) if size == "40" else (3,)):
            self.fill(block, 1, slot, size, 2)
        return block

    def fill(self, block, row, slot, size, height):
        for tier in range(height):
            block.getStack(row, slot).addContainer(
                SimpleNamespace(getContSize=lambda: size, getWeight=lambda: None), tier,
            )

    def test_defaults_select_up_and_down_and_round_trip_all_combinations(self):
        self.assertEqual(FeasibilitySettings().stacking_safety_neighbors, ("up", "down"))
        for enabled in product((False, True), repeat=4):
            with self.subTest(enabled=enabled):
                options = {"stacking_safety_neighbor_" + side: flag for side, flag in zip(DIRECTIONS, enabled)}
                parsed = parse_config({"feasibility": options})
                expected = tuple(side for side, flag in zip(DIRECTIONS, enabled) if flag)
                self.assertEqual(parsed.feasibility.stacking_safety_neighbors, expected)
                document = parsed.to_document()
                for key, value in options.items():
                    self.assertIs(document["feasibility"][key], value)
                self.assertEqual(parse_config(document).to_document(), document)

    def test_neighbor_options_require_booleans(self):
        for direction in DIRECTIONS:
            key = "stacking_safety_neighbor_" + direction
            for value in ("true", 0, 1, None, []):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ConfigurationError, key):
                        parse_config({"feasibility": {key: value}})

    def test_only_enabled_sides_provide_support_for_twenty_and_forty_foot_stacks(self):
        for size in ("20", "40"):
            footprint = (2, 3) if size == "40" else (3,)
            sides = {
                "up": [(0, slot) for slot in footprint],
                "down": [(2, slot) for slot in footprint],
                "left": [(1, footprint[0] - 1)],
                "right": [(1, 4)],
            }
            for support_side, positions in sides.items():
                for row, slot in positions:
                    block = self.make_block(size)
                    self.fill(block, row, slot, "20", 1)
                    self.assertEqual(block.safeMaxima(1, 3), support_side in ("up", "down"))
                    for enabled in product((False, True), repeat=4):
                        with self.subTest(size=size, support=(support_side, row, slot), enabled=enabled):
                            options = {"stacking_safety_neighbor_" + side: flag for side, flag in zip(DIRECTIONS, enabled)}
                            settings = FeasibilitySettings(loader_access=False, **options)
                            result = PlacementFeasibility(settings).evaluate(
                                SimpleNamespace(getContSize=lambda: size), block, 1, 3,
                            )
                            expected = options["stacking_safety_neighbor_" + support_side]
                            self.assertEqual(result.feasible, expected)
                            if not expected:
                                self.assertEqual(result.rejection_reason, RejectionReason.UNSAFE_STACKING)

    def test_no_enabled_sides_still_allows_the_isolated_stack_height(self):
        for size in ("20", "40"):
            block = self.make_block(size)
            for slot in ((2, 3) if size == "40" else (3,)):
                stack = block.getStack(1, slot)
                stack.removeContainer(1)
            self.assertTrue(block.safeMaxima(1, 3, neighbors=()))
            for slot in ((2, 3) if size == "40" else (3,)):
                block.getStack(1, slot).addContainer(SimpleNamespace(getContSize=lambda: size), 1)
            self.assertFalse(block.safeMaxima(1, 3, neighbors=()))

    def test_directions_apply_to_both_feasibility_and_heuristic_scoring(self):
        for size in ("20", "40"):
            for mode in ("feasibility", "heuristic", "off"):
                for right_enabled in (False, True):
                    with self.subTest(size=size, mode=mode, right_enabled=right_enabled):
                        yard = Yard(
                            yard_blocks_input=[dict(
                                branch_id="B", block_id="A", block_code="A", row_count="1",
                                slot_count="6", max_tier="5", pos_x="0", pos_y="0",
                            )],
                            feasibility_settings=FeasibilitySettings(
                                loader_access=False, stacking_safety_mode=mode,
                                stacking_safety_neighbor_right=right_enabled,
                            ),
                            heuristic_settings=HeuristicSettings(
                                enable_delta_container_mass=False, enable_equipment_distance=False,
                                enable_size_cluster=False, unsafe_stacking_multiplier=0.2,
                            ),
                        )
                        block = yard.getBlockByID("A")
                        for slot in ((2, 3) if size == "40" else (3,)):
                            self.fill(block, 0, slot, size, 2)
                        self.fill(block, 0, 4, "20", 1)
                        incoming = Container(
                            container_id="NEW", principal="", container_condition="", container_fill="",
                            container_size=size, container_grade="", pol="", pod="", vessel="", voyage="",
                            weight="", move_time="", branch_id="", block_code="", row_no="", slot_no="", tier_no="",
                        )
                        coordinate = ("A", 0, 3, 2)
                        result = yard.assignContainer(incoming)
                        scores = {candidate.coordinates: candidate for candidate in result.sorted_candidate_evaluations}
                        if mode == "feasibility" and not right_enabled:
                            self.assertNotIn(coordinate, scores)
                        else:
                            expected = 0.2 if mode == "heuristic" else 1.0
                            self.assertEqual(scores[coordinate].stacking_safety_multiplier, expected)


if __name__ == "__main__":
    unittest.main()

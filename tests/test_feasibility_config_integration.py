import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from config import FeasibilitySettings, load_feasibility_settings
from entities.block import Block
from entities.feasibility.placement_feasibility import (
    PlacementFeasibility,
    RejectionReason,
)
from entities.yard import Yard


class FeasibilityConfigIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.block_input = {
            "BRANCH_ID": "B", "BLOCK_ID": "A", "BLOCK_CODE": "A",
            "SLOT_COUNT": "4", "ROW_COUNT": "3", "MAX_TIER": "3",
            "POS_X": "0", "POS_Y": "0",
        }
        self.block = Block(**self.block_input)
        self.container = SimpleNamespace(getContSize=lambda: "20")

    def fill(self, row, slot, size, count):
        container = SimpleNamespace(getContSize=lambda: size)
        for tier in range(count):
            self.block.getStack(row, slot).addContainer(container, tier)

    def prepare_inaccessible_destination(self):
        for row in range(3):
            for slot in range(4):
                if (row, slot) != (1, 1):
                    self.fill(row, slot, "20", 3)

    def test_defaults_preserve_loader_access_check(self):
        self.prepare_inaccessible_destination()
        result = PlacementFeasibility().evaluate(
            self.container, self.block, 1, 1
        )
        self.assertEqual(
            result.rejection_reason,
            RejectionReason.LOADER_DESTINATION_INACCESSIBLE,
        )

    def test_disabling_loader_access_preserves_stacking_check(self):
        self.fill(0, 1, "20", 2)
        evaluator = PlacementFeasibility(FeasibilitySettings(loader_access=False))
        result = evaluator.evaluate(self.container, self.block, 0, 1)
        self.assertEqual(result.rejection_reason, RejectionReason.UNSAFE_STACKING)

    def test_disabling_stacking_preserves_loader_access_check(self):
        self.prepare_inaccessible_destination()
        evaluator = PlacementFeasibility(FeasibilitySettings(stacking_safety=False))
        result = evaluator.evaluate(self.container, self.block, 1, 1)
        self.assertEqual(
            result.rejection_reason,
            RejectionReason.LOADER_DESTINATION_INACCESSIBLE,
        )

    def test_disabling_both_allows_unsafe_height_candidate(self):
        self.fill(0, 1, "20", 2)
        evaluator = PlacementFeasibility(FeasibilitySettings(False, False))
        result = evaluator.evaluate(self.container, self.block, 0, 1)
        self.assertEqual(result.coordinates, ("A", 0, 1, 2))

    def test_disabled_policies_do_not_disable_size_compatibility(self):
        self.fill(0, 0, "40", 1)
        self.fill(0, 1, "40", 1)
        evaluator = PlacementFeasibility(FeasibilitySettings(False, False))
        result = evaluator.evaluate(self.container, self.block, 0, 1)
        self.assertEqual(result.rejection_reason, RejectionReason.SIZE_CONFLICT)

    def test_disabled_policies_do_not_disable_pairing(self):
        self.fill(0, 0, "40", 1)
        evaluator = PlacementFeasibility(FeasibilitySettings(False, False))
        container = SimpleNamespace(getContSize=lambda: "40")
        result = evaluator.evaluate(container, self.block, 0, 1)
        self.assertEqual(
            result.rejection_reason, RejectionReason.PARTNER_TIER_MISMATCH,
        )

    def test_file_settings_reach_yard_evaluator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                "[feasibility]\nstacking_safety = true\nloader_access = false\n",
                encoding="utf-8",
            )
            settings = load_feasibility_settings(path)

        yard = Yard(
            yard_block_input=[self.block_input],
            feasibility_settings=settings,
        )
        block = yard.getBlockByID("A")
        for row in range(3):
            for slot in range(4):
                if (row, slot) == (1, 1):
                    continue
                for tier in range(3):
                    block.getStack(row, slot).addContainer(self.container, tier)

        result = yard.feasibility.evaluate(self.container, block, 1, 1)
        self.assertEqual(result.coordinates, ("A", 1, 1, 0))


if __name__ == "__main__":
    unittest.main()

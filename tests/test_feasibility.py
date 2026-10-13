import unittest
from types import SimpleNamespace

from entities.block import Block
from entities.equipment import RTG
from entities.feasibility.placement_feasibility import (
    FeasibilityResult, PlacementFeasibility, RejectionReason,
)


class FeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.feasibility = PlacementFeasibility()
        self.block = Block(
            branch_id='B', block_id='A', block_code='A', slot_count='4',
            row_count='3', max_tier='5', pos_x='0', pos_y='0',
        )
        # These tests isolate size, pairing, and stacking safety from loader access.
        self.block.setRTG(RTG('RTG-1', ('A', 0, 0)))

    def fill(self, row_index, slot_index, container_size, count):
        container = SimpleNamespace(getContSize=lambda: container_size)
        for tier_index in range(count):
            self.block.getStack(row_index, slot_index).addContainer(container, tier_index)

    def evaluate(self, container_size, row_index=0, slot_index=1):
        return self.feasibility.evaluate(
            SimpleNamespace(getContSize=lambda: container_size), self.block, row_index, slot_index,
        )

    def check(self, container_size, row_index=0, slot_index=1):
        return self.evaluate(container_size, row_index, slot_index).coordinates

    def assert_rejected(self, container_size, reason, row_index=0, slot_index=1):
        result = self.evaluate(container_size, row_index, slot_index)
        self.assertFalse(result.feasible)
        self.assertIsNone(result.coordinates)
        self.assertEqual(result.rejection_reason, reason)

    def test_unsupported_sizes_are_rejected(self):
        for container_size in ('45', '', 'invalid'):
            with self.subTest(container_size=container_size):
                self.assert_rejected(container_size, RejectionReason.UNSUPPORTED_SIZE)

    def test_empty_pair_accepts_forty_foot(self):
        self.assertEqual(self.check('40'), ('A', 0, 1, 0))

    def test_empty_stack_accepts_twenty_foot(self):
        self.assertEqual(self.check('20', row_index=1, slot_index=2), ('A', 1, 2, 0))

    def test_compatible_pair_accepts_forty_foot(self):
        self.fill(0, 0, '40', 1)
        self.fill(0, 1, '40', 1)
        self.assertEqual(self.check('40'), ('A', 0, 1, 1))

    def test_equal_height_twenty_foot_partner_is_rejected(self):
        self.fill(0, 0, '20', 1)
        self.fill(0, 1, '40', 1)
        self.assert_rejected('40', RejectionReason.PARTNER_SIZE_CONFLICT)

    def test_removed_partner_is_rejected(self):
        self.block.getStack(0, 0).makeVoid()
        self.assert_rejected('40', RejectionReason.PARTNER_SIZE_CONFLICT)

    def test_unequal_height_partner_is_rejected(self):
        self.fill(0, 0, '40', 1)
        self.assert_rejected('40', RejectionReason.PARTNER_TIER_MISMATCH)

    def test_even_anchor_is_rejected(self):
        for slot_index in (0, 2):
            with self.subTest(slot_index=slot_index):
                self.assert_rejected(
                    '40', RejectionReason.INVALID_FORTY_FOOT_ANCHOR, slot_index=slot_index,
                )

    def test_evaluation_does_not_modify_stacks(self):
        self.fill(0, 0, '40', 1)
        self.fill(0, 1, '40', 1)
        self.block.getStack(2, 3).makeVoid()

        def snapshot():
            return [
                (stack.getMode(), stack.getMaxTier(), tuple(stack.getContainers()))
                for slots in self.block.getSlots()
                for stack in slots
            ]

        before = snapshot()
        self.assertEqual(self.check('40'), ('A', 0, 1, 1))
        self.assertEqual(snapshot(), before)
        self.assert_rejected('20', RejectionReason.SIZE_CONFLICT)
        self.assertEqual(snapshot(), before)

    def test_opposite_row_does_not_make_boundary_safe(self):
        self.fill(0, 1, '20', 2)
        self.assert_rejected('20', RejectionReason.UNSAFE_STACKING)
        self.fill(2, 1, '20', 2)
        self.assert_rejected('20', RejectionReason.UNSAFE_STACKING)

    def test_opposite_slot_does_not_make_boundary_safe(self):
        self.fill(1, 0, '20', 2)
        self.assert_rejected('20', RejectionReason.UNSAFE_STACKING, row_index=1, slot_index=0)
        self.fill(1, 3, '20', 2)
        self.assert_rejected('20', RejectionReason.UNSAFE_STACKING, row_index=1, slot_index=0)

    def test_actual_neighbor_can_make_placement_safe(self):
        self.fill(0, 1, '20', 2)
        self.fill(1, 1, '20', 1)
        self.assertEqual(self.check('20'), ('A', 0, 1, 2))

    def test_invalid_locations_are_rejected(self):
        for row_index, slot_index in ((-1, 1), (3, 1), (0, -1), (0, 4)):
            with self.subTest(row_index=row_index, slot_index=slot_index):
                self.assert_rejected(
                    '20', RejectionReason.INVALID_LOCATION, row_index=row_index, slot_index=slot_index,
                )

    def test_full_anchor_is_rejected(self):
        self.fill(0, 1, '20', 5)
        self.assert_rejected('20', RejectionReason.STACK_UNAVAILABLE)

    def test_removed_anchor_is_rejected(self):
        self.block.getStack(0, 1).makeVoid()
        self.assert_rejected('20', RejectionReason.STACK_UNAVAILABLE)

    def test_forty_foot_container_on_twenty_foot_stack_is_rejected(self):
        self.fill(0, 1, '20', 1)
        self.assert_rejected('40', RejectionReason.SIZE_CONFLICT)

    def test_twenty_foot_container_on_forty_foot_stack_is_rejected(self):
        self.fill(0, 0, '40', 1)
        self.fill(0, 1, '40', 1)
        self.assert_rejected('20', RejectionReason.SIZE_CONFLICT)

    def test_unsafe_forty_foot_pair_is_rejected(self):
        self.fill(0, 0, '40', 2)
        self.fill(0, 1, '40', 2)
        self.assert_rejected('40', RejectionReason.UNSAFE_STACKING)

    def test_neighbor_can_make_forty_foot_pair_safe(self):
        self.fill(0, 0, '40', 2)
        self.fill(0, 1, '40', 2)
        self.fill(1, 0, '40', 1)
        self.fill(1, 1, '40', 1)
        result = self.evaluate('40')
        self.assertTrue(result.feasible)
        self.assertEqual(result.coordinates, ('A', 0, 1, 2))
        self.assertIsNone(result.rejection_reason)


class FeasibilityResultTests(unittest.TestCase):
    def test_neither_outcome_is_invalid(self):
        with self.assertRaises(ValueError):
            FeasibilityResult()

    def test_both_outcomes_are_invalid(self):
        with self.assertRaises(ValueError):
            FeasibilityResult(
                coordinates=('A', 0, 1, 0),
                rejection_reason=RejectionReason.SIZE_CONFLICT,
            )


if __name__ == '__main__':
    unittest.main()

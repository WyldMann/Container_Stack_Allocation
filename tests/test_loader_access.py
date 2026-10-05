import unittest
from types import SimpleNamespace

from entities.block import Block
from entities.feasibility.loader_access import (
    LoaderBorderAccessPolicy, LoaderAccessRule, ReceivingLocation,
)
from entities.feasibility.placement_proposal import PlacementProposal


class LoaderAccessTests(unittest.TestCase):
    def setUp(self):
        self.block = Block(
            BRANCH_ID='B', BLOCK_ID='A', BLOCK_CODE='A',
            SLOT_COUNT='4', ROW_COUNT='5', MAX_TIER='3',
            POS_X='0', POS_Y='0',
        )
        self.rule = LoaderAccessRule()
        self.policy = LoaderBorderAccessPolicy()
        # Full stacks form obstacles without receiving capacity.
        for row in range(5):
            for slot in range(4):
                self.set_stack(row, slot, count=3)

    def set_stack(self, row, slot, size='20', count=0):
        stack = self.block.getStack(row, slot)
        stack.containers = [None] * stack.getMaxTier()
        stack.setMode('0')
        container = SimpleNamespace(getContSize=lambda: size)
        for tier in range(count):
            stack.addContainer(container, tier)

    def proposal(self, row, slot, tier=0, size='20'):
        return PlacementProposal('A', row, slot, tier, size)

    def evaluate(self, proposal, policy=None):
        return self.rule.evaluate(
            self.block, proposal, self.policy if policy is None else policy,
        )

    def can_serve(self, row, slot, size='20', policy=None):
        policy = self.policy if policy is None else policy
        reachable = self.rule._reachable_ground(self.block, policy)
        return self.rule._can_serve(
            self.block, ReceivingLocation(row, slot, size), reachable, policy,
        )

    def test_closing_final_row_approach_rejects_placement(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        result = self.evaluate(self.proposal(0, 1))
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.isolated_locations, (ReceivingLocation(1, 1, '20'),),
        )

    def test_alternate_row_approach_preserves_access(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        for row in (2, 3, 4):
            self.block.getStack(row, 1).makeVoid()
        self.assertTrue(self.evaluate(self.proposal(0, 1)).allowed)

    def test_slot_side_ground_does_not_provide_service(self):
        self.set_stack(2, 1, count=1)
        self.block.getStack(2, 0).makeVoid()
        self.assertFalse(self.can_serve(2, 1))

    def test_forty_foot_requires_two_positions_on_same_side(self):
        self.set_stack(1, 0, '40', 1)
        self.set_stack(1, 1, '40', 1)
        self.set_stack(0, 0)
        self.set_stack(0, 1)
        self.assertTrue(self.can_serve(1, 1, '40'))
        result = self.evaluate(self.proposal(0, 1, size='40'))
        self.assertEqual(
            result.isolated_locations, (ReceivingLocation(1, 1, '40'),),
        )

    def test_one_working_position_is_insufficient_for_forty_foot(self):
        self.set_stack(1, 0, '40', 1)
        self.set_stack(1, 1, '40', 1)
        self.block.getStack(0, 0).makeVoid()
        self.assertFalse(self.can_serve(1, 1, '40'))

    def test_split_working_positions_are_insufficient_for_forty_foot(self):
        self.set_stack(2, 0, '40', 1)
        self.set_stack(2, 1, '40', 1)
        for position in ((0, 0), (1, 0), (3, 1), (4, 1)):
            self.block.getStack(*position).makeVoid()
        self.assertFalse(self.can_serve(2, 1, '40'))

    def test_removed_ground_connects_interior_working_area(self):
        for position in ((0, 0), (1, 0), (1, 1)):
            self.block.getStack(*position).makeVoid()
        self.set_stack(2, 1, count=1)
        self.assertTrue(self.can_serve(2, 1))
        locations = self.rule._receiving_locations(self.block)
        self.assertNotIn(ReceivingLocation(1, 1, '20'), locations)

    def test_corridor_closure_isolates_multiple_distant_locations(self):
        self.set_stack(0, 1)
        for position in ((1, 1), (2, 1), (2, 2)):
            self.block.getStack(*position).makeVoid()
        self.set_stack(3, 1, count=1)
        self.set_stack(3, 2, count=1)
        result = self.evaluate(self.proposal(0, 1))
        self.assertEqual(
            result.isolated_locations,
            (ReceivingLocation(3, 1, '20'), ReceivingLocation(3, 2, '20')),
        )

    def test_already_isolated_location_does_not_reject_placement(self):
        self.set_stack(2, 2, count=1)
        self.set_stack(0, 0)
        self.assertFalse(self.can_serve(2, 2))
        self.assertTrue(self.evaluate(self.proposal(0, 0)).allowed)

    def test_placement_above_ground_does_not_change_routes(self):
        self.set_stack(0, 1, count=1)
        self.set_stack(1, 1, count=1)
        result = self.evaluate(self.proposal(0, 1, tier=1))
        self.assertTrue(result.destination_accessible)
        self.assertTrue(result.allowed)

    def test_inaccessible_destination_rejects_without_new_isolation(self):
        self.set_stack(2, 1)
        result = self.evaluate(self.proposal(2, 1))
        self.assertFalse(result.destination_accessible)
        self.assertEqual(result.isolated_locations, ())
        self.assertFalse(result.allowed)

    def test_destination_with_remaining_capacity_can_be_isolated(self):
        # An empty interior destination is initially its neighbour's
        # working position. Filling it removes that reciprocal access.
        self.block.getStack(2, 0).makeVoid()
        self.set_stack(2, 1)
        self.set_stack(3, 1)
        result = self.evaluate(self.proposal(2, 1))
        self.assertIn(ReceivingLocation(2, 1, '20'), result.isolated_locations)

    def test_full_destination_is_excluded_from_remaining_capacity(self):
        self.set_stack(0, 1, count=2)
        proposal = self.proposal(0, 1, tier=2)
        self.assertNotIn(
            ReceivingLocation(0, 1, '20'),
            self.rule._receiving_locations(self.block, proposal),
        )
        self.assertTrue(self.evaluate(proposal).allowed)

    def test_exterior_row_borders_provide_service(self):
        self.assertTrue(self.can_serve(0, 1))
        self.assertTrue(self.can_serve(4, 1, '40'))
        self.assertFalse(self.can_serve(
            0, 1, policy=LoaderBorderAccessPolicy(above=False),
        ))

    def test_closed_entry_border_does_not_seed_reachability(self):
        self.block.getStack(2, 0).makeVoid()
        self.block.getStack(2, 1).makeVoid()
        self.set_stack(3, 1, count=1)
        self.assertTrue(self.can_serve(3, 1))
        self.assertFalse(self.can_serve(
            3, 1, policy=LoaderBorderAccessPolicy(left=False),
        ))

    def test_unreachable_empty_area_does_not_provide_service(self):
        self.set_stack(2, 1)
        self.set_stack(3, 1, count=1)
        self.assertFalse(self.can_serve(3, 1))

    def test_invalid_proposals_raise_value_error(self):
        self.set_stack(0, 1)
        for proposal in (
            PlacementProposal('B', 0, 1, 0, '20'),
            self.proposal(5, 1),
            self.proposal(0, 4),
            self.proposal(0, 1, tier=1),
            self.proposal(0, 3, size='40'),
        ):
            with self.subTest(proposal=proposal):
                with self.assertRaises(ValueError):
                    self.evaluate(proposal)

    def test_removed_destination_is_rejected(self):
        self.block.getStack(0, 1).makeVoid()
        with self.assertRaises(ValueError):
            self.evaluate(self.proposal(0, 1))

    def test_evaluation_leaves_block_unchanged(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)

        def snapshot():
            return [
                (stack.getMode(), stack.getMaxTier(), tuple(stack.getContainers()))
                for slots in self.block.getSlots()
                for stack in slots
            ]

        before = snapshot()
        self.evaluate(self.proposal(0, 1))
        self.assertEqual(snapshot(), before)


if __name__ == '__main__':
    unittest.main()

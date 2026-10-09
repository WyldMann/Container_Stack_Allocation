import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from entities.equipment import RTG
from entities.feasibility.loader_access import LoaderBorderAccessPolicy
from entities.feasibility.placement_feasibility import RejectionReason
from entities.yard import Yard


class LoaderAccessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard(
            yard_block_input=[
                {
                    'BRANCH_ID': 'B', 'BLOCK_ID': 'A', 'BLOCK_CODE': 'A',
                    'SLOT_COUNT': '4', 'ROW_COUNT': '3', 'MAX_TIER': '3',
                    'POS_X': '0', 'POS_Y': '0',
                }
            ]
        )
        self.block = self.yard.getBlockByID('A')
        self.container = SimpleNamespace(getContSize=lambda: '20')
        for row in range(3):
            for slot in range(4):
                self.set_stack(row, slot, count=3)

    def set_stack(self, row, slot, size='20', count=0):
        stack = self.block.getStack(row, slot)
        stack.containers = [None] * stack.getMaxTier()
        stack.setMode('0')
        container = SimpleNamespace(getContSize=lambda: size)
        for tier in range(count):
            stack.addContainer(container, tier)

    def test_inaccessible_destination_is_rejected(self):
        self.set_stack(1, 1)
        result = self.yard.feasibility.evaluate(self.container, self.block, 1, 1)
        self.assertEqual(
            result.rejection_reason,
            RejectionReason.LOADER_DESTINATION_INACCESSIBLE,
        )

    def test_placement_isolating_neighbour_is_rejected(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        result = self.yard.feasibility.evaluate(self.container, self.block, 0, 1)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_ACCESS_BLOCKED)

    def test_alternate_approach_allows_placement(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        self.block.getStack(2, 1).makeVoid()
        result = self.yard.feasibility.evaluate(self.container, self.block, 0, 1)
        self.assertEqual(result.coordinates, ('A', 0, 1, 0))

    def test_rtg_exempts_inaccessible_destination(self):
        self.set_stack(1, 1)
        self.block.setRTG(RTG('RTG-1', ('A', 0, 0)))
        result = self.yard.feasibility.evaluate(self.container, self.block, 1, 1)
        self.assertEqual(result.coordinates, ('A', 1, 1, 0))

    def test_rtg_exempts_isolation_and_closed_borders(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        self.block.setRTG(RTG('RTG-1', ('A', 0, 0)))
        result = self.yard.feasibility.evaluate(
            self.container, self.block, 0, 1,
            loader_policy=LoaderBorderAccessPolicy(False, False, False, False),
        )
        self.assertEqual(result.coordinates, ('A', 0, 1, 0))

    def test_forty_foot_requires_complete_working_area(self):
        self.set_stack(1, 0)
        self.set_stack(1, 1)
        self.block.getStack(0, 0).makeVoid()
        container = SimpleNamespace(getContSize=lambda: '40')
        result = self.yard.feasibility.evaluate(container, self.block, 1, 1)
        self.assertEqual(
            result.rejection_reason,
            RejectionReason.LOADER_DESTINATION_INACCESSIBLE,
        )
        self.block.getStack(0, 1).makeVoid()
        result = self.yard.feasibility.evaluate(container, self.block, 1, 1)
        self.assertEqual(result.coordinates, ('A', 1, 1, 0))

    def test_candidate_selection_uses_block_border_policy(self):
        self.set_stack(0, 1)
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        self.yard.params['P'] = parameter
        self.block.getStack(0, 1).addParameter(parameter)
        _, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(coordinates, [('A', 0, 1, 0)])
        self.yard.loader_access_policies['A'] = LoaderBorderAccessPolicy(
            above=False, below=False, left=False, right=False,
        )
        _, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(coordinates, [])

    def test_candidate_selection_excludes_isolating_placement(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        self.yard.params['P'] = parameter
        self.block.getStack(0, 1).addParameter(parameter)
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        # Reject the positive-scoring placement that would isolate its neighbour,
        # but retain that neighbour as a feasible, unplanned fallback.
        self.assertNotIn(('A', 0, 1, 0), coordinates)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 1, 1, 1)])


if __name__ == '__main__':
    unittest.main()

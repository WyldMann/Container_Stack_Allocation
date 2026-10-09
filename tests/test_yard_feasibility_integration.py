import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from entities.yard import Yard


class YardFeasibilityIntegrationTests(unittest.TestCase):
    def test_candidate_selection_applies_feasibility(self):
        yard = Yard(
            yard_block_input=[
                {
                    'BRANCH_ID': 'B',
                    'BLOCK_ID': 'A',
                    'BLOCK_CODE': 'A',
                    'SLOT_COUNT': '2',
                    'ROW_COUNT': '1',
                    'MAX_TIER': '5',
                    'POS_X': '0',
                    'POS_Y': '0',
                }
            ]
        )

        # A positive parameter score lets feasible stacks become candidates.
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        yard.params['P'] = parameter

        for stack in yard.getBlockByID('A').getSlots()[0]:
            stack.addParameter(parameter)

        container = SimpleNamespace(getContSize=lambda: '40')
        score, _, coordinates = yard.findCoordsCandidates(container)

        # Slot 0 is an invalid anchor; slot 1 is a valid empty pair.
        self.assertEqual(score, 1.0)
        self.assertEqual(coordinates, [('A', 0, 1, 0)])

        # Removing the partner makes the remaining anchor infeasible.
        yard.getStack('A', 0, 0).makeVoid()
        score, _, coordinates = yard.findCoordsCandidates(container)

        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [])


class UnplannedStackSelectionTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([dict(
            BRANCH_ID='B', BLOCK_ID='A', BLOCK_CODE='A',
            SLOT_COUNT='3', ROW_COUNT='1', MAX_TIER='1',
            POS_X='0', POS_Y='0',
        )])
        self.container = SimpleNamespace(getContSize=lambda: '20')

    def add_parameter(self, slot, score):
        parameter = Mock()
        parameter.evaluate.return_value = score
        self.yard.params[str(parameter)] = parameter
        self.yard.getStack('A', 0, slot).addParameter(parameter)

    def test_unplanned_stacks_are_candidates_with_zero_score(self):
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 0, slot, 0) for slot in range(3)])

    def test_zero_scoring_parameterized_stacks_are_excluded(self):
        self.add_parameter(1, 0)
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 0, 0, 0), ('A', 0, 2, 0)])

    def test_positive_feasible_score_supersedes_unplanned_stacks_in_either_order(self):
        self.add_parameter(1, 2)
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(score, 2)
        # Unplanned slots before and after the positive candidate are excluded.
        self.assertEqual(coordinates, [('A', 0, 1, 0)])

    def test_infeasible_positive_match_does_not_prevent_zero_score_fallback(self):
        self.add_parameter(1, 2)
        self.yard.getStack('A', 0, 1).addContainer(self.container, 0)
        self.yard.getStack('A', 0, 2).makeVoid()
        score, parameter_scores, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(max(parameter_scores.values()), 2)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 0, 0, 0)])


if __name__ == '__main__':
    unittest.main()

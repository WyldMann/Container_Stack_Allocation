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


if __name__ == '__main__':
    unittest.main()

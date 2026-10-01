import unittest
from types import SimpleNamespace

from entities.block import Block
from entities.yard import Yard


class FeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.block = Block(
            BRANCH_ID='B', BLOCK_ID='A', BLOCK_CODE='A', SLOT_COUNT='4',
            ROW_COUNT='3', MAX_TIER='5', POS_X='0', POS_Y='0',
        )

    def fill(self, row, slot, size, count):
        container = SimpleNamespace(getContSize=lambda: size)
        for tier in range(count):
            self.block.getStack(row, slot).addContainer(container, tier)

    def check(self, size, row=0, slot=1):
        return Yard.feasibilityCheck(
            SimpleNamespace(getContSize=lambda: size), self.block,
            self.block.slots[row], self.block.getStack(row, slot), row, slot,
        )

    def test_unsupported_sizes_are_rejected(self):
        for size in ('45', '', 'invalid'):
            with self.subTest(size=size):
                self.assertIsNone(self.check(size))

    def test_empty_pair_accepts_forty_foot(self):
        self.assertEqual(self.check('40'), ('A', 0, 1, 0))

    def test_compatible_pair_accepts_forty_foot(self):
        self.fill(0, 0, '40', 1)
        self.fill(0, 1, '40', 1)
        self.assertEqual(self.check('40'), ('A', 0, 1, 1))

    def test_equal_height_twenty_foot_partner_is_rejected(self):
        self.fill(0, 0, '20', 1)
        self.fill(0, 1, '40', 1)
        self.assertIsNone(self.check('40'))

    def test_removed_partner_is_rejected(self):
        self.block.getStack(0, 0).makeVoid()
        self.assertIsNone(self.check('40'))

    def test_unequal_height_partner_is_rejected(self):
        self.fill(0, 0, '40', 1)
        self.assertIsNone(self.check('40'))

    def test_even_anchor_is_rejected(self):
        self.assertIsNone(self.check('40', slot=0))

    def test_opposite_row_does_not_make_boundary_safe(self):
        self.fill(0, 1, '20', 2)
        self.assertIsNone(self.check('20'))
        self.fill(2, 1, '20', 2)
        self.assertIsNone(self.check('20'))

    def test_opposite_slot_does_not_make_boundary_safe(self):
        self.fill(1, 0, '20', 2)
        self.assertIsNone(self.check('20', row=1, slot=0))
        self.fill(1, 3, '20', 2)
        self.assertIsNone(self.check('20', row=1, slot=0))

    def test_actual_neighbor_can_make_placement_safe(self):
        self.fill(0, 1, '20', 2)
        self.fill(1, 1, '20', 1)
        self.assertEqual(self.check('20'), ('A', 0, 1, 2))


if __name__ == '__main__':
    unittest.main()

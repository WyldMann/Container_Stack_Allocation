import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from entities import Container, Yard
from entities.bad_yard_data import PlacementRejected
from entities.equipment import Loader, RTG
from entities.feasibility.loader_access import LoaderBorderAccessPolicy, ReceivingLocation
from entities.feasibility.placement_feasibility import RejectionReason
from tests.loader_access_reference import ReferencePlacementFeasibility


class ReachStackerAccessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([
            dict(branch_id='BR', block_id=block_id, block_code=block_id,
                 slot_count='4', row_count='3', max_tier='3', pos_x=str(index * 10), pos_y='0')
            for index, block_id in enumerate(('A', 'B'))
        ])
        self.block = self.yard.getBlockByID('A')
        self.yard.feasibility.settings = replace(
            self.yard.feasibility.settings, preserve_future_loader_access=False,
            ignore_full_stacks_for_loader_access=True,
        )
        for block in self.yard.blocks_by_id.values():
            for row, stacks in enumerate(block.getSlots()):
                for slot in range(len(stacks)):
                    self.set_stack(block, row, slot, 3)
        self.block.getStack(1, 0).makeVoid()
        self.set_stack(self.block, 1, 1, 0)
        self.incoming = Container(
            container_id='NEW', principal='', container_condition='', container_fill='',
            container_size='20', container_grade='', pol='', pod='', vessel='',
            voyage='', weight='', move_time='',
        )

    @staticmethod
    def set_stack(block, row, slot, count):
        stack = block.getStack(row, slot)
        stack.containers = [None] * stack.getMaxTier()
        stack.setMode('0')
        for tier in range(count):
            stack.addContainer(SimpleNamespace(getContSize=lambda: '20'), tier)

    def register(self, code, equipment_type, block_id='A', row=0, slot=3):
        self.yard.inputEquipment(
            [dict(equipment_code=code, equipment_type=equipment_type)],
            {code: ('BR', block_id, row, slot)},
        )
        return self.yard.master_loaders[-1]

    def test_import_retains_rs_capability_without_granting_it_to_sl_or_legacy_loaders(self):
        rs = self.register('RS1', ' rs ')
        sl = self.register('SL1', 'SL')
        self.assertEqual(rs.equipment_type, 'RS')
        self.assertTrue(rs.twenty_foot_side_access)
        self.assertFalse(sl.twenty_foot_side_access)
        self.assertFalse(Loader('LEGACY', ('A', 0, 0)).twenty_foot_side_access)

    def test_side_only_destination_rejects_sl_and_accepts_rs_at_commit(self):
        sl = self.register('SL1', 'SL', row=1, slot=1)
        rs = self.register('RS1', 'RS')
        coordinate = ('A', 1, 1, 0)
        with self.assertRaisesRegex(PlacementRejected, 'loader_destination_inaccessible'):
            self.yard.placeContainer(self.incoming, coordinate, sl)
        self.assertEqual(sl.getCoords(), ('A', 1, 1))
        self.assertNotIn('NEW', self.yard.containers)
        self.yard.placeContainer(self.incoming, coordinate, rs)
        self.assertIs(self.block.getStack(1, 1).getContainer(0), self.incoming)
        self.assertEqual(rs.getCoords(), ('A', 1, 1))

    def test_assignment_selects_remote_rs_instead_of_nearer_local_sl(self):
        sl = self.register('SL1', 'SL', row=1, slot=1)
        rs = self.register('RS1', 'RS', block_id='B')
        result = self.yard.assign_and_place(self.incoming)
        self.assertEqual(result.getBestCoordinate(), ('A', 1, 1, 0))
        self.assertIs(result.getBestEquipment(), rs)
        self.assertTrue(result.getBestCandidate().loader_access.destination_accessible)
        self.assertEqual(result.getBestCandidate().distance, float('inf'))
        self.assertEqual(sl.getCoords(), ('A', 1, 1))
        self.assertEqual(rs.getCoords(), ('A', 1, 1))
        self.assertNotIn(rs, self.yard.getBlockByID('B').getLoaders())
        self.assertIn(rs, self.block.getLoaders())

    def test_rs_selection_honors_destination_modes(self):
        sl = self.register('SL1', 'SL', row=1, slot=1)
        rs = self.register('RS1', 'RS', block_id='B')
        for mode, expected in (('feasibility', rs), ('heuristic', rs), ('off', sl)):
            with self.subTest(mode=mode):
                self.yard.feasibility.settings = replace(
                    self.yard.feasibility.settings, loader_destination_access_mode=mode,
                )
                result = self.yard.assignContainer(self.incoming)
                self.assertIs(result.getBestEquipment(), expected)

    def test_rs_access_obeys_closed_borders_during_search_and_commit(self):
        rs = self.register('RS1', 'RS')
        self.yard.loader_access_policies['A'] = LoaderBorderAccessPolicy(left=False)
        self.assertIsNone(self.yard.assignContainer(self.incoming))
        with self.assertRaisesRegex(PlacementRejected, 'loader_destination_inaccessible'):
            self.yard.placeContainer(self.incoming, ('A', 1, 1, 0), rs)

    def test_explicit_rs_and_sl_are_checked_even_when_block_has_rtg(self):
        sl = self.register('SL1', 'SL')
        rs = self.register('RS1', 'RS')
        rtg = RTG('RTG1', ('A', 0, 0))
        self.block.setRTG(rtg)
        self.assertIs(self.yard.assignContainer(self.incoming).getBestEquipment(), rtg)
        with self.assertRaisesRegex(PlacementRejected, 'loader_destination_inaccessible'):
            self.yard.placeContainer(self.incoming, ('A', 1, 1, 0), sl)
        self.yard.placeContainer(self.incoming, ('A', 1, 1, 0), rs)

    def test_removing_rs_refreshes_access_and_invalidates_assignment(self):
        self.register('SL1', 'SL')
        rs = self.register('RS1', 'RS', block_id='B')
        result = self.yard.assignContainer(self.incoming)
        self.assertIs(result.getBestEquipment(), rs)
        self.yard.master_loaders.remove(rs)
        self.yard.getBlockByID('B').removeLoader(rs)
        self.assertIsNone(self.yard.assignContainer(self.incoming))
        with self.assertRaises(PlacementRejected):
            self.yard.placeContainerWithAssignResult(result)
        self.assertNotIn('NEW', self.yard.containers)

    def test_rs_fleet_protects_sole_lateral_approach_during_sl_placement(self):
        sl = self.register('SL1', 'SL')
        self.register('RS1', 'RS', block_id='B')
        self.block.getStack(0, 1).makeVoid()
        self.set_stack(self.block, 1, 2, 1)
        result = self.yard.feasibility.evaluate(
            self.incoming, self.block, 1, 1, loader=sl, twenty_foot_side_access=True,
        )
        self.assertTrue(result.loader_access.destination_accessible)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_OCCUPIED_ACCESS_BLOCKED)
        self.assertIn(ReceivingLocation(1, 2, '20'), result.loader_access.isolated_occupied_locations)
        with self.assertRaisesRegex(PlacementRejected, 'loader_occupied_access_blocked'):
            self.yard.placeContainer(self.incoming, ('A', 1, 1, 0), sl)

    def test_rs_access_heuristics_count_lateral_losses(self):
        self.register('RS1', 'RS')
        self.block.getStack(0, 1).makeVoid()
        self.set_stack(self.block, 1, 2, 1)
        self.yard.feasibility.settings = replace(
            self.yard.feasibility.settings, loader_access_mode='heuristic',
            preserve_future_loader_access=True,
        )
        candidate, = self.yard.bestCoordCandidate(self.incoming, [('A', 1, 1, 0)])
        self.assertIn(ReceivingLocation(1, 2, '20'), candidate.loader_access.isolated_occupied_locations)
        self.assertIn(ReceivingLocation(1, 2, '20'), candidate.loader_access.isolated_locations)
        self.assertLess(candidate.loader_access_multiplier, 1.0)
        self.assertLess(candidate.future_loader_access_multiplier, 1.0)

    def test_mixed_fleet_search_matches_independent_reference_and_reuses_contexts(self):
        self.register('SL1', 'SL')
        self.register('RS1', 'RS', block_id='B')
        optimized = self.yard.feasibility
        # The reference protects full stacks, so use the same policy on both sides.
        optimized.settings = replace(optimized.settings, ignore_full_stacks_for_loader_access=False)
        actual_rejections = {}
        with patch.object(optimized.loader_access, 'prepare_context', wraps=optimized.loader_access.prepare_context) as prepare:
            actual = self.yard.findCoordsCandidates(self.incoming, rejection_counts=actual_rejections)
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(all(call.kwargs['twenty_foot_side_access'] for call in prepare.call_args_list))
        self.yard.feasibility = ReferencePlacementFeasibility(optimized.settings)
        expected_rejections = {}
        expected = self.yard.findCoordsCandidates(self.incoming, rejection_counts=expected_rejections)
        self.assertEqual(actual, expected)
        self.assertEqual(actual_rejections, expected_rejections)


if __name__ == '__main__':
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from config import FeasibilitySettings
from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.yard import Yard


class YardFeasibilityIntegrationTests(unittest.TestCase):
    def test_candidate_selection_applies_feasibility(self):
        yard = Yard(
            yard_blocks_input=[
                {
                    'branch_id': 'B',
                    'block_id': 'A',
                    'block_code': 'A',
                    'slot_count': '2',
                    'row_count': '1',
                    'max_tier': '5',
                    'pos_x': '0',
                    'pos_y': '0',
                }
            ]
        )

        # A positive parameter score lets feasible stacks become candidates.
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        yard.parameters['P'] = parameter

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
            branch_id='B', block_id='A', block_code='A',
            slot_count='3', row_count='1', max_tier='1',
            pos_x='0', pos_y='0',
        )])
        self.container = SimpleNamespace(getContSize=lambda: '20')

    def add_parameter(self, slot_index, score):
        parameter = Mock()
        parameter.evaluate.return_value = score
        self.yard.parameters[str(parameter)] = parameter
        self.yard.getStack('A', 0, slot_index).addParameter(parameter)

    def test_unplanned_stacks_are_candidates_with_zero_score(self):
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 0, slot_index, 0) for slot_index in range(3)])

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


class AnomalousStackSelectionTests(unittest.TestCase):
    def make_yard(self, container_size='20', *, slots=4, tiers=3, floating=True, settings=None):
        record = dict(
            container_id='FLOATING', principal='', container_condition='',
            container_fill='', container_size=container_size, container_grade='',
            pol='', pod='', vessel='', voyage='', weight='', move_time='',
            branch_id='BR', block_code='A', row_no='1',
            slot_no='2' if container_size == '40' else '1', tier_no='3',
        )
        yard = Yard(
            yard_blocks_input=[dict(
                branch_id='BR', block_id='A', block_code='A',
                row_count='1', slot_count=str(slots), max_tier=str(tiers),
                pos_x='0', pos_y='0',
            )],
            containers_input=[record] if floating else [],
            equipment_input=[dict(equipment_code='L', equipment_type='SL')],
            equipment_locations_input={'L': ('BR', 'A', 0, 0)},
            feasibility_settings=settings,
        )
        incoming = Container(**(record | {
            'container_id': 'NEW', 'branch_id': '', 'block_code': '',
            'row_no': '', 'slot_no': '', 'tier_no': '',
        }))
        return yard, incoming, record

    @staticmethod
    def snapshot(yard):
        return (
            dict(yard.containers),
            tuple((container, container.getCoordsStrTuple())
                  for container in yard.containers.values()),
            tuple((stack.getMode(), tuple(stack.getContainers()),
                   tuple(stack.getParameters()))
                  for block in yard.blocks_by_id.values()
                  for row in block.getSlots() for stack in row),
            tuple((loader, loader.getCoords()) for loader in yard.master_loaders),
            tuple(yard.bad_data.getAnomalousStacks()),
            tuple(yard.bad_data.stacks_with_dummy_containers),
            yard.bad_data.getImportErrors(),
        )

    def test_assignment_uses_valid_alternative_when_repaired_footprint_is_full(self):
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                yard, incoming, _ = self.make_yard(container_size)
                yard.fillDummyContainer()
                yard.anomalyCheck()
                before = self.snapshot(yard)
                floating = yard.containers['FLOATING']
                floating_coords = floating.getCoordsStrTuple()
                self.assertEqual(yard.bad_data.getTotalAnomalousStacks(), 0)

                result = yard.assignContainer(incoming)

                self.assertIsNotNone(result)
                slot_index = 3 if container_size == '40' else 1
                self.assertEqual(result.getBestCoordinate(), ('A', 0, slot_index, 0))
                self.assertEqual(self.snapshot(yard), before)
                yard.placeContainerWithAssignResult(result)
                self.assertIs(yard.containers['NEW'], incoming)
                self.assertEqual(floating.getCoordsStrTuple(), floating_coords)
                for slot in ((0, 1) if container_size == '40' else (0,)):
                    self.assertIs(yard.getStack('A', 0, slot).getContainer(2), floating)

    def test_anomaly_rescan_refreshes_the_report(self):
        yard, _, record = self.make_yard('40', floating=False)
        yard.addContainerInput(Container(**record))
        yard.anomalyCheck()
        initial = yard.bad_data.getAnomalousStacks().copy()
        self.assertEqual(len(initial), 2)

        yard.anomalyCheck()
        self.assertEqual(yard.bad_data.getAnomalousStacks(), initial)

        for tier in ('1', '2'):
            yard.addContainerInput(Container(**(record | {
                'container_id': f'SUPPORT-{tier}', 'tier_no': tier,
            })))
        yard.anomalyCheck()
        self.assertEqual(yard.bad_data.getAnomalousStacks(), [])

    def test_full_repaired_high_scoring_stack_does_not_exclude_valid_lower_score(self):
        yard, incoming, _ = self.make_yard()
        yard.fillDummyContainer()
        for slot_index, score in ((0, 10), (1, 1)):
            parameter = Mock()
            parameter.getId.return_value = f'P{slot_index}'
            parameter.evaluate.return_value = score
            yard.parameters[parameter.getId()] = parameter
            yard.getStack('A', 0, slot_index).addParameter(parameter)

        result = yard.assign_and_place(incoming)

        self.assertIsNotNone(result)
        self.assertEqual(result.max_parameter_score, 1)
        self.assertEqual(result.getBestCoordinate(), ('A', 0, 1, 0))
        self.assertIs(yard.containers['NEW'], incoming)

    def test_full_repaired_yard_returns_no_assignment_without_mutation(self):
        for container_size, slots in (('20', 1), ('40', 2)):
            with self.subTest(container_size=container_size):
                yard, incoming, _ = self.make_yard(container_size, slots=slots)
                yard.fillDummyContainer()
                before = self.snapshot(yard)

                self.assertIsNone(yard.assign_and_place(incoming))

                self.assertEqual(self.snapshot(yard), before)
                self.assertEqual(yard.bad_data.getIncompleteInboundContainers(), [])

    def test_direct_placement_rejects_unrepaired_anomalies_with_optional_rules_disabled(self):
        settings = FeasibilitySettings(stacking_safety=False, loader_access=False)
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                yard, incoming, record = self.make_yard(container_size, floating=False, settings=settings)
                yard.addContainerInput(Container(**record))
                coordinates = ('A', 0, 1 if container_size == '40' else 0, 0)
                before = self.snapshot(yard)
                incoming_coords = incoming.getCoordsStrTuple()
                for action in (
                    lambda: yard.addContainerByCoords(incoming, coordinates),
                    lambda: yard.placeContainer(incoming, coordinates, yard.master_loaders[0]),
                ):
                    with self.assertRaisesRegex(PlacementRejected, 'anomalous_stack'):
                        action()
                    self.assertEqual(self.snapshot(yard), before)
                    self.assertEqual(incoming.getCoordsStrTuple(), incoming_coords)

    def test_commit_rechecks_new_anomaly_even_when_next_available_tier_is_unchanged(self):
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                yard, incoming, record = self.make_yard(container_size, floating=False)
                result = yard.assignContainer(incoming)
                self.assertIsNotNone(result)
                self.assertEqual(result.getBestCoordinate()[3], 0)
                yard.addContainerInput(Container(**record))
                self.assertEqual(yard.getStack(*result.getBestCoordinate()[:3]).availableTierInt(), 0)
                before = self.snapshot(yard)

                with self.assertRaisesRegex(PlacementRejected, 'anomalous_stack'):
                    yard.placeContainerWithAssignResult(result)

                self.assertEqual(self.snapshot(yard), before)

    def test_assignment_above_repaired_tiers_preserves_dummies(self):
        settings = FeasibilitySettings(stacking_safety=False, loader_access_mode='feasibility')
        for size, slot_count in (('20', 1), ('40', 2)):
            with self.subTest(size=size):
                yard, incoming, _ = self.make_yard(size, slots=slot_count, tiers=4, settings=settings)
                yard.fillDummyContainer()
                block = yard.getBlockByID('A')
                stacks = block.getSlots()[0]
                dummy = stacks[0].getContainer(0)
                for stack in stacks:
                    self.assertIs(stack.getContainer(0), dummy)
                    self.assertEqual(stack.getDummyTiers(), [0, 1])
                    self.assertEqual(stack.getMode(), size)
                    self.assertEqual(stack.occupancy(), 3)
                context = yard.feasibility.prepare_loader_context(block)
                self.assertIn((0, slot_count - 1, size), {
                    (location.row_index, location.slot_index, location.container_size)
                    for location in context.accessible_occupied_locations
                })
                before = self.snapshot(yard)
                yard.fillDummyContainer()
                self.assertEqual(self.snapshot(yard), before)

                dummy_coords = ('A', 0, slot_count - 1, 0)
                with self.assertRaises(PlacementRejected):
                    yard.addContainerByCoords(incoming, dummy_coords)
                with self.assertRaises(PlacementRejected):
                    yard.placeContainer(incoming, dummy_coords, yard.master_loaders[0])
                self.assertEqual(self.snapshot(yard), before)

                result = yard.assign_and_place(incoming)
                self.assertEqual(result.getBestCoordinate(), ('A', 0, slot_count - 1, 3))
                self.assertEqual(set(yard.containers), {'FLOATING', 'NEW'})
                for stack in stacks:
                    self.assertIs(stack.getContainer(3), incoming)
                    self.assertIs(stack.getContainer(0), dummy)
                    self.assertEqual(stack.getDummyTiers(), [0, 1])

    def test_existing_data_correction_replaces_dummy_in_both_slots(self):
        yard, _, record = self.make_yard('40', slots=2)
        yard.fillDummyContainer()
        stacks = yard.getBlockByID('A').getSlots()[0]
        before = self.snapshot(yard)
        yard.addContainerInput(Container(**(record | {
            'container_id': 'WRONG-SIZE', 'container_size': '20', 'tier_no': '1',
        })))
        self.assertEqual(self.snapshot(yard)[:-1], before[:-1])
        self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 1)

        for tier in ('1', '2'):
            real = Container(**(record | {'container_id': f'FOUND-{tier}', 'tier_no': tier}))
            yard.addContainerInput(real)
            for stack in stacks:
                self.assertIs(stack.getContainer(int(tier) - 1), real)
            self.assertIs(yard.containers[real.getId()], real)
            expected = stacks if tier == '1' else []
            self.assertEqual(yard.bad_data.stacks_with_dummy_containers, expected)
        self.assertEqual(yard.bad_data.getTotalOverlapping(), 0)

    def test_repair_fills_an_internal_gap_and_leaves_open_tiers_above_it(self):
        yard, _, record = self.make_yard(slots=1, tiers=4, floating=False)
        base = Container(**(record | {'container_id': 'BASE', 'tier_no': '1'}))
        top = Container(**record)
        yard.addContainerInput(base)
        yard.addContainerInput(top)
        stack = yard.getStack('A', 0, 0)

        yard.fillDummyContainer()
        self.assertIsNone(stack.getContainer(1))

        yard.anomalyCheck()
        self.assertEqual(yard.bad_data.getAnomalousStacks(), [stack])
        self.assertIsNone(stack.getContainer(1))

        yard.fillDummyContainer()
        self.assertEqual(stack.getDummyTiers(), [1])
        self.assertIs(stack.getContainer(0), base)
        self.assertIs(stack.getContainer(2), top)
        self.assertEqual(stack.availableTierInt(), 3)
        self.assertEqual(yard.bad_data.getAnomalousStacks(), [stack])

        yard.anomalyCheck()
        self.assertEqual(yard.bad_data.getAnomalousStacks(), [])
        self.assertEqual(yard.bad_data.stacks_with_dummy_containers, [stack])

    def test_repair_leaves_an_inconsistent_forty_foot_footprint_unrepaired(self):
        yard, _, record = self.make_yard('40', slots=2, floating=False)
        yard.addContainerInput(Container(**record))
        yard.getStack('A', 0, 0).removeContainer(2)
        yard.anomalyCheck()
        before = self.snapshot(yard)

        yard.fillDummyContainer()

        self.assertEqual(self.snapshot(yard), before)
        self.assertEqual(yard.bad_data.getTotalAnomalousStacks(), 1)

    def test_every_returned_candidate_passes_the_same_placement_validation(self):
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                yard, incoming, _ = self.make_yard(container_size)
                result = yard.assignContainer(incoming)
                self.assertIsNotNone(result)
                before = self.snapshot(yard)
                for candidate in result.sorted_candidate_evaluations:
                    validated = yard.bad_data.validateInboundPlacement(
                        incoming, candidate.coordinates, candidate.equipment,
                        blocks_by_id=yard.blocks_by_id,
                        registered_containers=yard.containers,
                        master_loaders=yard.master_loaders,
                        feasibility=yard.feasibility,
                        loader_policies=yard.loader_access_policies,
                    )
                    self.assertEqual(validated.proposal.coordinates, candidate.coordinates)
                self.assertEqual(self.snapshot(yard), before)


if __name__ == '__main__':
    unittest.main()

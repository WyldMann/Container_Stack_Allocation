import itertools
import random
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import FeasibilitySettings
from entities.block import Block
from entities.equipment import RTG
from entities.feasibility.loader_access import LoaderAccessRule, LoaderBorderAccessPolicy
from entities.feasibility.placement_proposal import PlacementProposal
from entities.yard import Yard
from tests.loader_access_reference import (
    LoaderAccessRule as ReferenceAccessRule,
    ReferencePlacementFeasibility,
)


def block_input(rows=3, slots=4, tiers=3, block_id='A'):
    return dict(
        BRANCH_ID='B', BLOCK_ID=block_id, BLOCK_CODE=block_id,
        SLOT_COUNT=str(slots), ROW_COUNT=str(rows), MAX_TIER=str(tiers),
        POS_X='0', POS_Y='0',
    )


def fill(block, row, slot, size='20', count=1):
    container = SimpleNamespace(getContSize=lambda: size)
    for tier in range(count):
        block.getStack(row, slot).addContainer(container, tier)


def locations(values):
    return {(location.row, location.slot, location.size) for location in values}


def result_signature(result):
    return (
        result.destination_accessible,
        tuple((loc.row, loc.slot, loc.size) for loc in result.isolated_locations),
    )


class LoaderAccessContextTests(unittest.TestCase):
    def setUp(self):
        self.rule = LoaderAccessRule()
        self.policy = LoaderBorderAccessPolicy()
        self.block = Block(**block_input())

    def test_snapshot_is_immutable_and_does_not_mutate_block(self):
        fill(self.block, 1, 1)
        before = [
            (stack.getMode(), tuple(stack.getContainers()))
            for row in self.block.getSlots() for stack in row
        ]
        context = self.rule.prepare_context(self.block, self.policy)
        with self.assertRaises(FrozenInstanceError):
            context.policy = LoaderBorderAccessPolicy(False, False, False, False)
        for values in (context.ground, context.reachable_ground,
                       context.receiving_locations, context.accessible_locations):
            self.assertIsInstance(values, frozenset)
        self.rule.evaluate(
            self.block, PlacementProposal('A', 0, 1, 0, '40'),
            self.policy, context=context,
        )
        after = [
            (stack.getMode(), tuple(stack.getContainers()))
            for row in self.block.getSlots() for stack in row
        ]
        self.assertEqual(before, after)

    def test_context_requires_same_block_object_and_policy(self):
        context = self.rule.prepare_context(self.block, self.policy)
        proposal = PlacementProposal('A', 0, 0, 0, '20')
        for block, policy in (
            (Block(**block_input()), self.policy),
            (self.block, LoaderBorderAccessPolicy(above=False)),
        ):
            with self.subTest(block=block, policy=policy), self.assertRaises(ValueError):
                self.rule.evaluate(block, proposal, policy, context=context)

    def test_supplied_context_does_not_bypass_proposal_validation(self):
        context = self.rule.prepare_context(self.block, self.policy)
        for proposal in (
            PlacementProposal('OTHER', 0, 0, 0, '20'),
            PlacementProposal('A', 3, 0, 0, '20'),
            PlacementProposal('A', 0, 0, 1, '20'),
        ):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                self.rule.evaluate(self.block, proposal, self.policy, context=context)

    def test_occupied_footprint_skips_search_but_checks_destination_access(self):
        for row in range(3):
            for slot in range(4):
                fill(self.block, row, slot)
        context = self.rule.prepare_context(self.block, self.policy)
        with patch.object(self.rule, '_reachable_after', wraps=self.rule._reachable_after) as search:
            border = self.rule.evaluate(
                self.block, PlacementProposal('A', 0, 0, 1, '20'), self.policy, context=context,
            )
            interior = self.rule.evaluate(
                self.block, PlacementProposal('A', 1, 1, 1, '20'), self.policy, context=context,
            )
        search.assert_not_called()
        self.assertTrue(border.allowed)
        self.assertFalse(interior.destination_accessible)
        self.assertEqual(interior.isolated_locations, ())

    def test_shortcut_uses_occupancy_even_when_next_tier_is_zero(self):
        # Preserve the original access semantics for an anomalous imported stack.
        self.block.getStack(0, 0).addContainer(SimpleNamespace(getContSize=lambda: '20'), 2)
        proposal = PlacementProposal('A', 0, 0, 0, '20')
        context = self.rule.prepare_context(self.block, self.policy)
        with patch.object(self.rule, '_reachable_after', wraps=self.rule._reachable_after) as search:
            actual = self.rule.evaluate(self.block, proposal, self.policy, context=context)
        search.assert_not_called()
        self.assertEqual(result_signature(actual), result_signature(
            ReferenceAccessRule().evaluate(self.block, proposal, self.policy),
        ))

    def test_ground_placement_runs_one_search_and_no_whole_block_receiving_scan(self):
        context = self.rule.prepare_context(self.block, self.policy)
        with (
            patch.object(self.rule, '_reachable_after', wraps=self.rule._reachable_after) as search,
            patch.object(self.rule, '_receiving_locations', wraps=self.rule._receiving_locations) as scan,
        ):
            self.rule.evaluate(
                self.block, PlacementProposal('A', 0, 1, 0, '40'), self.policy, context=context,
            )
        search.assert_called_once()
        scan.assert_not_called()

    def test_generated_layouts_match_original_algorithm_and_local_receiving_changes(self):
        rng = random.Random(90210)
        reference = ReferenceAccessRule()
        comparisons = 0
        for row_count, slot_count in ((1, 1), (1, 2), (2, 3), (3, 4), (4, 5)):
            for layout in range(5):
                block = Block(**block_input(row_count, slot_count, tiers=1 + layout % 3))
                for row in range(row_count):
                    slot = 0
                    while slot < slot_count:
                        choice = rng.randrange(4)
                        count = rng.randrange(block.getStack(row, slot).getMaxTier() + 1)
                        if choice == 0:
                            block.getStack(row, slot).makeVoid()
                        elif choice == 1 and slot % 2 == 0 and slot + 1 < slot_count:
                            fill(block, row, slot, '40', count)
                            fill(block, row, slot + 1, '40', count)
                            slot += 1
                        elif choice == 2:
                            fill(block, row, slot, '20', count)
                        slot += 1

                for borders in itertools.product((False, True), repeat=4):
                    policy = LoaderBorderAccessPolicy(*borders)
                    context = self.rule.prepare_context(block, policy)
                    for row in range(row_count):
                        for slot in range(slot_count):
                            tier = block.getStack(row, slot).availableTierInt()
                            if tier is None:
                                continue
                            for size in ('20', '40'):
                                if size == '40' and slot % 2 == 0:
                                    continue
                                proposal = PlacementProposal('A', row, slot, tier, size)
                                try:
                                    reference._validate_proposal(block, proposal)
                                except ValueError:
                                    continue
                                with self.subTest(shape=(row_count, slot_count), layout=layout,
                                                  borders=borders, proposal=proposal):
                                    expected = reference.evaluate(block, proposal, policy)
                                    actual = self.rule.evaluate(block, proposal, policy, context=context)
                                    standalone = self.rule.evaluate(block, proposal, policy)
                                    self.assertEqual(result_signature(expected), result_signature(actual))
                                    self.assertEqual(result_signature(expected), result_signature(standalone))
                                    before = locations(reference._receiving_locations(block))
                                    after = locations(reference._receiving_locations(block, proposal))
                                    removed, added = self.rule._receiving_changes(block, proposal, context)
                                    self.assertEqual(locations(removed), before - after)
                                    self.assertEqual(locations(added), after - before)
                                    comparisons += 1
        self.assertGreater(comparisons, 1000)


class LoaderAccessContextIntegrationTests(unittest.TestCase):
    def make_yard(self, settings=None):
        yard = Yard([block_input(block_id='A'), block_input(block_id='B')],
                    feasibility_settings=settings)
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        yard.params['P'] = parameter
        for block in yard.blocks_by_id.values():
            for row in block.getSlots():
                for stack in row:
                    stack.addParameter(parameter)
        return yard

    def test_context_prepared_once_per_block_and_refreshed_after_changes(self):
        yard = self.make_yard()
        container = SimpleNamespace(getContSize=lambda: '20')
        rule = yard.feasibility.loader_access
        contexts = []
        prepare = rule.prepare_context

        def capture(block, policy):
            context = prepare(block, policy)
            contexts.append(context)
            return context

        with patch.object(rule, 'prepare_context', side_effect=capture) as prepare_spy:
            first = yard.findCoordsCandidates(container)
            self.assertEqual(prepare_spy.call_count, 2)
            # A real storage mutation and policy change between searches.
            fill(yard.getBlockByID('A'), 0, 0)
            yard.loader_access_policies['B'] = LoaderBorderAccessPolicy(False, False, False, False)
            second = yard.findCoordsCandidates(container)
            self.assertEqual(prepare_spy.call_count, 4)
        self.assertNotEqual(first, second)
        self.assertIsNot(contexts[0], contexts[2])
        self.assertIn((0, 0), contexts[0].ground)
        self.assertNotIn((0, 0), contexts[2].ground)
        optimized = yard.feasibility
        yard.feasibility = ReferencePlacementFeasibility(optimized.settings)
        self.assertEqual(second, yard.findCoordsCandidates(container))

    def test_preparation_skipped_for_disabled_access_and_rtg_blocks(self):
        for enabled in (False, True):
            yard = self.make_yard(FeasibilitySettings(loader_access=enabled))
            for block in yard.blocks_by_id.values():
                block.setRTG(RTG('R-' + block.getId(), (block.getId(), 0, 0)))
            if not enabled:
                yard.getBlockByID('A').rtg = None
            rule = yard.feasibility.loader_access
            with patch.object(rule, 'prepare_context', wraps=rule.prepare_context) as prepare:
                yard.findCoordsCandidates(SimpleNamespace(getContSize=lambda: '20'))
            prepare.assert_not_called()

    def test_candidate_order_and_rejections_match_reference(self):
        yard = self.make_yard()
        fill(yard.getBlockByID('A'), 1, 0, '40')
        fill(yard.getBlockByID('A'), 1, 1, '40')
        yard.getStack('B', 1, 2).makeVoid()
        yard.loader_access_policies['B'] = LoaderBorderAccessPolicy(above=False)
        optimized = yard.feasibility
        reference = ReferencePlacementFeasibility(optimized.settings)
        for size in ('20', '40'):
            container = SimpleNamespace(getContSize=lambda: size)
            yard.feasibility = optimized
            actual = yard.findCoordsCandidates(container)
            yard.feasibility = reference
            self.assertEqual(actual, yard.findCoordsCandidates(container))
            for block in yard.blocks_by_id.values():
                policy = yard.loader_access_policies.get(block.getId())
                context = optimized.prepare_loader_context(block, policy)
                for row, stacks in enumerate(block.getSlots()):
                    for slot in range(len(stacks)):
                        self.assertEqual(
                            reference.evaluate(container, block, row, slot, loader_policy=policy),
                            optimized.evaluate(container, block, row, slot,
                                               loader_policy=policy, loader_context=context),
                        )


if __name__ == '__main__':
    unittest.main()

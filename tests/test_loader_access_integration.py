import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config.application.config_loader import parse_config
from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.equipment import Loader, RTG
from entities.feasibility.loader_access import LoaderAccessResult, LoaderBorderAccessPolicy, ReceivingLocation
from entities.feasibility.placement_feasibility import RejectionReason
from entities.heuristic_model import HeuristicModel
from entities.yard import Yard
from stacking_ui.simulation import _calculation


class LoaderAccessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard(
            yard_blocks_input=[
                {
                    'branch_id': 'B', 'block_id': 'A', 'block_code': 'A',
                    'slot_count': '4', 'row_count': '3', 'max_tier': '3',
                    'pos_x': '0', 'pos_y': '0',
                }
            ]
        )
        self.block = self.yard.getBlockByID('A')
        self.container = SimpleNamespace(getContSize=lambda: '20')
        for row_index in range(3):
            for slot_index in range(4):
                self.set_stack(row_index, slot_index, count=3)

    def set_stack(self, row_index, slot_index, container_size='20', count=0):
        stack = self.block.getStack(row_index, slot_index)
        stack.containers = [None] * stack.getMaxTier()
        stack.setMode('0')
        container = SimpleNamespace(getContSize=lambda: container_size)
        for tier_index in range(count):
            stack.addContainer(container, tier_index)

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
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_OCCUPIED_ACCESS_BLOCKED)

    def test_destination_reachability_modes_are_independent_of_access_preservation(self):
        self.set_stack(1, 1)
        coordinate = ("A", 1, 1, 0)
        yard = self.yard
        for mode in ("off", "heuristic", "feasibility"):
            with self.subTest(mode=mode):
                yard.feasibility.settings = replace(
                    yard.feasibility.settings, loader_access_mode="off",
                    loader_destination_access_mode=mode, preserve_occupied_loader_access_mode="off",
                )
                result = yard.feasibility.evaluate(self.container, self.block, 1, 1)
                if mode == "feasibility":
                    self.assertEqual(result.rejection_reason, RejectionReason.LOADER_DESTINATION_INACCESSIBLE)
                    continue
                self.assertEqual(result.coordinates, coordinate)
                with patch.object(yard, "modelEval", return_value=(None, None, 0.0, 1.0, 1.0)):
                    candidate, = yard.bestCoordCandidate(self.container, [coordinate])
                self.assertEqual(candidate.evaluation_score, 0.25 if mode == "heuristic" else 1.0)
                self.assertEqual(candidate.loader_access_multiplier, 1.0)
                committed = yard.feasibility.evaluate(
                    self.container, self.block, 1, 1, include_loader_heuristics=False,
                )
                self.assertTrue(committed.feasible)
                self.assertIsNone(committed.loader_access)

    def test_preservation_can_reject_with_destination_reachability_off(self):
        self.set_stack(0, 1)
        self.set_stack(1, 1, count=1)
        evaluator = self.yard.feasibility
        evaluator.settings = replace(
            evaluator.settings, loader_access_mode="off", loader_destination_access_mode="off",
            preserve_occupied_loader_access_mode="feasibility",
        )
        result = evaluator.evaluate(self.container, self.block, 0, 1, include_loader_heuristics=False)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_OCCUPIED_ACCESS_BLOCKED)

        self.set_stack(1, 1)
        evaluator.settings = replace(
            evaluator.settings, preserve_occupied_loader_access_mode="off",
            preserve_future_loader_access_mode="feasibility",
        )
        result = evaluator.evaluate(self.container, self.block, 0, 1, include_loader_heuristics=False)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_ACCESS_BLOCKED)

    def test_disabling_future_access_still_protects_full_stacks(self):
        evaluator = self.yard.feasibility
        evaluator.settings = replace(evaluator.settings, preserve_future_loader_access=False)
        self.set_stack(0, 0)
        self.set_stack(0, 1)
        for size in ('20', '40'):
            with self.subTest(size=size):
                self.set_stack(1, 0, container_size=size, count=3)
                self.set_stack(1, 1, container_size=size, count=3)
                result = evaluator.evaluate(self.container, self.block, 0, 1)
                self.assertEqual(result.rejection_reason, RejectionReason.LOADER_OCCUPIED_ACCESS_BLOCKED)

    def test_disabling_future_access_only_allows_loss_of_receiving_access(self):
        self.set_stack(0, 0)
        self.set_stack(1, 0)
        evaluator = self.yard.feasibility
        result = evaluator.evaluate(self.container, self.block, 0, 0)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_ACCESS_BLOCKED)

        evaluator.settings = replace(evaluator.settings, preserve_future_loader_access=False)
        _, _, coordinates = self.yard.findCoordsCandidates(self.container)
        self.assertIn(('A', 0, 0, 0), coordinates)
        self.block.getStack(0, 0).addContainer(self.container, 0)
        result = evaluator.evaluate(self.container, self.block, 1, 0)
        self.assertEqual(result.rejection_reason, RejectionReason.LOADER_DESTINATION_INACCESSIBLE)

    def test_future_heuristic_lowers_rank_and_commit_still_checks_occupied_access(self):
        yard = self.yard
        yard.feasibility.settings = replace(
            yard.feasibility.settings,
            loader_access_mode="feasibility",
            preserve_future_loader_access_mode="heuristic",
            ignore_full_stacks_for_loader_access=True,
        )
        for row, slot in ((0, 0), (0, 1), (1, 0), (1, 1)):
            self.set_stack(row, slot)
        loader = Loader("L", ("A", 0, 0))
        yard.master_loaders.append(loader)
        self.block.addLoader(loader)
        container = Container(
            container_id="NEW", principal="", container_condition="", container_fill="",
            container_size="20", container_grade="", pol="", pod="", vessel="",
            voyage="", weight="", move_time="",
        )
        trace = {}
        # Hold other heuristic factors equal so only future access determines rank.
        with patch.object(yard, "modelEval", return_value=(None, loader, 0.0, 1.0, 1.0)):
            result = yard.assignContainer(container, trace=trace)
        entry = next(candidate for candidate in result.sorted_candidate_evaluations
                     if candidate.coordinates == ("A", 0, 0, 0))
        self.assertIn("40", [location.container_size for location in entry.loader_access.isolated_locations])
        self.assertLess(entry.future_loader_access_multiplier, 1.0)
        self.assertEqual(entry.loader_access_multiplier, 1.0)
        self.assertGreater(result.getBestCandidate().evaluation_score, entry.evaluation_score)
        calculation = _calculation(yard, trace, result)
        self.assertIn("future_loader_access_multiplier", calculation["enabled_multipliers"])
        display = next(candidate for candidate in calculation["candidates"]
                       if (candidate["row"], candidate["slot"]) == (1, 1))
        self.assertTrue(display["loader_destination_accessible"])
        self.assertEqual(display["isolated_occupied_locations"], 0)
        self.assertEqual(display["isolated_future_locations"], len(entry.loader_access.isolated_locations))

        # The search result becomes stale when an occupied stack needs the route.
        self.set_stack(1, 0, count=1)
        with self.assertRaisesRegex(PlacementRejected, "loader_occupied_access_blocked"):
            yard.placeContainer(container, entry.coordinates, loader)
        self.set_stack(1, 0)
        yard.placeContainer(container, entry.coordinates, loader)
        self.assertIs(yard.containers["NEW"], container)

    def test_both_heuristics_give_current_access_priority_over_score(self):
        yard = self.yard
        yard.feasibility.settings = replace(
            yard.feasibility.settings, loader_access_mode="heuristic",
            ignore_full_stacks_for_loader_access=True,
        )
        self.set_stack(0, 0)
        self.set_stack(0, 1)
        self.set_stack(1, 0, count=1)
        self.set_stack(1, 1)
        isolates = ("A", 0, 0, 0)
        preserves = ("A", 0, 1, 0)
        with patch.object(yard, "modelEval", side_effect=lambda _, coordinate: (
            None, None, 0.0, 1.0, 100.0 if coordinate == isolates else 1.0,
        )):
            first, second = yard.bestCoordCandidate(self.container, [isolates, preserves])
        self.assertEqual(first.coordinates, preserves)
        self.assertEqual(second.coordinates, isolates)
        self.assertEqual(second.loader_access_multiplier, 0.5)
        self.assertGreater(second.evaluation_score, first.evaluation_score)

    def test_inaccessible_destination_is_penalized_in_heuristic_mode_and_rtg_is_exempt(self):
        yard = self.yard
        yard.feasibility.settings = replace(
            yard.feasibility.settings, loader_access_mode="heuristic",
            preserve_future_loader_access_mode="off",
        )
        self.set_stack(1, 1)
        with patch.object(yard, "modelEval", return_value=(None, None, 0.0, 1.0, 1.0)):
            coordinate = ("A", 1, 1, 0)
            candidate, = yard.bestCoordCandidate(self.container, [coordinate])
            self.assertFalse(candidate.loader_access.destination_accessible)
            self.assertEqual(candidate.loader_destination_multiplier, 0.25)
            self.assertEqual(candidate.loader_access_multiplier, 1.0)
            self.assertEqual(candidate.future_loader_access_multiplier, 1.0)
            self.block.setRTG(RTG("RTG-1", ("A", 0, 0)))
            candidate, = yard.bestCoordCandidate(self.container, [coordinate])
            self.assertIsNone(candidate.loader_access)
            self.assertEqual(candidate.evaluation_score, 1.0)

    def test_configured_loader_weights_are_applied_only_in_heuristic_mode(self):
        settings = parse_config({
            "feasibility": {"loader_access_mode": "heuristic"},
            "heuristic": {
                "loader_inaccessible_destination_multiplier": 0.6,
                "loader_occupied_access_loss_weight": 2,
                "loader_future_access_loss_weight": 0.5,
            },
        })
        yard = self.yard
        yard.feasibility.settings = settings.feasibility
        yard.model = HeuristicModel(settings.heuristic)
        coordinate = ("A", 1, 1, 0)
        occupied = ReceivingLocation(1, 2, "20")
        access = LoaderAccessResult(
            destination_accessible=False,
            isolated_occupied_locations=(occupied,),
            isolated_locations=(occupied, ReceivingLocation(1, 3, "40")),
        )
        with patch.object(yard, "modelEval", return_value=(None, None, 0.0, 1.0, 10.0)):
            candidate, = yard.bestCoordCandidate(self.container, [coordinate], loader_access_results={coordinate: access})
            self.assertAlmostEqual(candidate.loader_destination_multiplier, 0.6)
            self.assertAlmostEqual(candidate.loader_access_multiplier, 1 / 3)
            self.assertEqual(candidate.future_loader_access_multiplier, 0.5)
            self.assertAlmostEqual(candidate.evaluation_score, 1.0)

            yard.feasibility.settings = replace(settings.feasibility, preserve_future_loader_access_mode="off")
            candidate, = yard.bestCoordCandidate(self.container, [coordinate], loader_access_results={coordinate: access})
            self.assertEqual(candidate.future_loader_access_multiplier, 1.0)
            self.assertAlmostEqual(candidate.evaluation_score, 2.0)

    def test_ignoring_full_stacks_preserves_access_to_partially_occupied_stacks(self):
        evaluator = self.yard.feasibility
        evaluator.settings = replace(evaluator.settings, ignore_full_stacks_for_loader_access=True)
        self.set_stack(0, 0)
        self.set_stack(0, 1)
        for size in ('20', '40'):
            with self.subTest(size=size):
                self.set_stack(1, 0, container_size=size, count=3)
                self.set_stack(1, 1, container_size=size, count=3)
                result = evaluator.evaluate(self.container, self.block, 0, 1)
                self.assertEqual(result.coordinates, ('A', 0, 1, 0))
                _, _, candidates = self.yard.findCoordsCandidates(self.container)
                self.assertIn(result.coordinates, candidates)

                self.set_stack(1, 0, container_size=size, count=2)
                self.set_stack(1, 1, container_size=size, count=2)
                result = evaluator.evaluate(self.container, self.block, 0, 1)
                self.assertEqual(result.rejection_reason, RejectionReason.LOADER_OCCUPIED_ACCESS_BLOCKED)

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
        self.block.getStack(1, 0).makeVoid()
        self.block.getStack(1, 1).makeVoid()
        parameter = Mock()
        parameter.evaluate.return_value = 1.0
        self.yard.parameters['P'] = parameter
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
        self.yard.parameters['P'] = parameter
        self.block.getStack(0, 1).addParameter(parameter)
        score, _, coordinates = self.yard.findCoordsCandidates(self.container)
        # Reject the positive-scoring placement that would isolate its neighbour,
        # but retain that neighbour as a feasible, unplanned fallback.
        self.assertNotIn(('A', 0, 1, 0), coordinates)
        self.assertEqual(score, 0)
        self.assertEqual(coordinates, [('A', 1, 1, 1)])


if __name__ == '__main__':
    unittest.main()

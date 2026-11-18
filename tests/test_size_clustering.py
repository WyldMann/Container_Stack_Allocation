import math
import unittest
from types import SimpleNamespace

import pandas as pd

from config import HeuristicSettings
from entities.assign_result import AssignResult, CandidateEvaluation
from entities.equipment import RTG
from entities.heuristic_model import HeuristicModel
from entities.yard import Yard
from presenter import YardPresenter


class SizeClusteringTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([{
            'branch_id': 'B', 'block_id': 'A', 'block_code': 'A',
            'slot_count': '12', 'row_count': '5', 'max_tier': '3',
            'pos_x': '0', 'pos_y': '0',
        }])
        self.yard.getBlockByID('A').setRTG(RTG('RTG', ('A', 2, 4)))

    def container(self, container_size):
        return SimpleNamespace(getContSize=lambda: container_size, getWeight=lambda: 10000)

    def cluster(self, container, coordinate):
        return self.yard.model.sizeCluster(
            container, self.yard.getBlockByID(coordinate[0]), coordinate,
        )

    def occupy(self, row_index, anchor, container_size, height=1):
        slots = (anchor - 1, anchor) if container_size == '40' else (anchor,)
        container = self.container(container_size)
        for slot_index in slots:
            for tier_index in range(height):
                self.yard.getStack('A', row_index, slot_index).addContainer(container, tier_index)

    def test_empty_neighborhood_preserves_previous_scoring(self):
        multiplier = self.cluster(self.container('40'), ('A', 2, 3, 0))
        self.assertEqual(multiplier, 1)
        model = HeuristicModel()
        for delta_container_mass, distance in ((0, 0), (5000, 5), (None, 0), (-1, 0), (0, math.inf)):
            self.assertEqual(model.evaluate(delta_container_mass, distance, multiplier),
                             model.deltaContainerMass(delta_container_mass) * model.equipmentDistance(distance))

    def test_same_size_rewards_and_other_size_penalizes_both_sizes(self):
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                self.setUp()
                self.occupy(2, 1, container_size)
                multiplier = self.cluster(self.container(container_size), ('A', 2, 3, 0))
                self.assertGreater(multiplier, 1)
                other_size = '40' if container_size == '20' else '20'
                multiplier = self.cluster(self.container(other_size), ('A', 2, 3, 0))
                self.assertLess(multiplier, 1)

    def test_forty_foot_pair_counts_once(self):
        self.occupy(2, 1, '40')
        multiplier = self.cluster(self.container('40'), ('A', 2, 3, 0))
        evidence = 2 ** (-1 / 1.5)
        self.assertAlmostEqual(multiplier, 2 ** (evidence / (evidence + 2)))

    def test_height_does_not_change_multiplier(self):
        self.occupy(2, 1, '20')
        container = self.container('20')
        coordinate = ('A', 2, 3, 0)
        before = self.cluster(container, coordinate)
        self.yard.getStack('A', 2, 1).addContainer(container, 1)
        self.assertEqual(self.cluster(container, coordinate), before)

    def test_mixed_neighbors_use_separate_denominators_and_strengths(self):
        self.yard.model = HeuristicModel(HeuristicSettings(
            hl_size_cluster_distance=1,
            size_cluster_reward_bias=1, size_cluster_reward_prior=0.5,
            size_cluster_penalty_bias=3, size_cluster_penalty_prior=1.5,
        ))
        self.occupy(2, 2, '20')
        self.occupy(1, 3, '40')
        # Both neighbors have evidence 0.5. Reward = sqrt(2), penalty = 2 ** -0.75.
        self.assertAlmostEqual(self.cluster(self.container('20'), ('A', 2, 3, 0)), 2 ** -0.25)

    def test_reward_and_penalty_use_their_own_distance_decay(self):
        self.yard.model = HeuristicModel(HeuristicSettings(
            hl_size_cluster_reward_distance=1, hl_size_cluster_penalty_distance=0.5,
        ))
        self.occupy(2, 2, '20')
        self.occupy(1, 3, '40')
        # At distance 1, matching evidence is 0.5 and different-size evidence is 0.25.
        self.assertAlmostEqual(self.cluster(self.container('20'), ('A', 2, 3, 0)),
                               2 ** (0.5 / 2.5 - 0.25 / 2.25))

    def test_reward_and_penalty_switches_independently_control_scoring(self):
        self.occupy(2, 2, '20')
        self.occupy(1, 3, '40')
        cases = ((True, True, 2 ** -0.25), (True, False, 2 ** 0.5),
                 (False, True, 2 ** -0.75), (False, False, 1))
        for reward, penalty, expected in cases:
            with self.subTest(reward=reward, penalty=penalty):
                self.yard.model = HeuristicModel(HeuristicSettings(
                    enable_size_cluster_reward=reward, enable_size_cluster_penalty=penalty,
                    hl_size_cluster_distance=1,
                    size_cluster_reward_bias=1, size_cluster_reward_prior=0.5,
                    size_cluster_penalty_bias=3, size_cluster_penalty_prior=1.5,
                ))
                multiplier = self.cluster(self.container('20'), ('A', 2, 3, 0))
                self.assertAlmostEqual(multiplier, expected)
                self.assertAlmostEqual(self.yard.model.evaluate(0, 0, multiplier), 100 * expected)

    def test_each_radius_filters_only_its_own_neighbor_type(self):
        self.occupy(2, 1, '20')
        self.occupy(0, 3, '40')
        for reward_radius, penalty_radius, expected in ((1, 2, 2 ** -0.2), (2, 1, 2 ** 0.2)):
            with self.subTest(reward_radius=reward_radius, penalty_radius=penalty_radius):
                self.yard.model = HeuristicModel(HeuristicSettings(
                    size_cluster_reward_radius=reward_radius, size_cluster_penalty_radius=penalty_radius,
                    hl_size_cluster_reward_distance=2, hl_size_cluster_penalty_distance=2,
                ))
                self.assertAlmostEqual(self.cluster(self.container('20'), ('A', 2, 3, 0)), expected)

    def test_zero_radius_disables_only_its_own_term(self):
        self.occupy(2, 2, '20')
        self.occupy(1, 3, '40')
        coordinate = ('A', 2, 3, 0)
        for term, expected in (('reward', 2 ** -0.2), ('penalty', 2 ** 0.2)):
            with self.subTest(term=term):
                self.yard.model = HeuristicModel(HeuristicSettings(
                    **{f'size_cluster_{term}_radius': 0},
                    hl_size_cluster_reward_distance=1, hl_size_cluster_penalty_distance=1,
                ))
                self.assertAlmostEqual(self.cluster(self.container('20'), coordinate), expected)

    def test_other_term_distance_does_not_change_single_size_neighborhood(self):
        self.occupy(2, 2, '20')
        coordinate = ('A', 2, 3, 0)
        before = self.cluster(self.container('20'), coordinate)
        self.yard.model = HeuristicModel(HeuristicSettings(hl_size_cluster_penalty_distance=100))
        self.assertEqual(self.cluster(self.container('20'), coordinate), before)

    def test_different_size_evidence_does_not_change_reward(self):
        self.yard.model = HeuristicModel(HeuristicSettings(size_cluster_penalty_bias=0))
        self.occupy(2, 2, '20')
        before = self.cluster(self.container('20'), ('A', 2, 3, 0))
        self.occupy(1, 3, '40')
        self.assertGreater(before, 1)
        self.assertEqual(self.cluster(self.container('20'), ('A', 2, 3, 0)), before)

    def test_same_size_evidence_does_not_change_penalty(self):
        self.yard.model = HeuristicModel(HeuristicSettings(size_cluster_reward_bias=0))
        self.occupy(1, 3, '40')
        before = self.cluster(self.container('20'), ('A', 2, 3, 0))
        self.occupy(2, 2, '20')
        self.assertLess(before, 1)
        self.assertEqual(self.cluster(self.container('20'), ('A', 2, 3, 0)), before)

    def test_term_smoothing_only_changes_its_own_neighbor_type(self):
        self.occupy(2, 2, '20')
        candidate = self.container('20')
        coordinate = ('A', 2, 3, 0)
        before = self.cluster(candidate, coordinate)
        self.yard.model = HeuristicModel(HeuristicSettings(size_cluster_penalty_prior=100))
        self.assertEqual(self.cluster(candidate, coordinate), before)
        self.yard.model = HeuristicModel(HeuristicSettings(size_cluster_reward_prior=100))
        self.assertLess(self.cluster(candidate, coordinate), before)

    def test_equal_balanced_terms_and_zero_strengths_are_neutral(self):
        self.yard.model = HeuristicModel(HeuristicSettings(hl_size_cluster_distance=1))
        self.occupy(2, 2, '20')
        self.occupy(1, 3, '40')
        coordinate = ('A', 2, 3, 0)
        self.assertEqual(self.cluster(self.container('20'), coordinate), 1)
        self.yard.model = HeuristicModel(HeuristicSettings(
            size_cluster_reward_bias=0, size_cluster_penalty_bias=0,
        ))
        self.assertEqual(self.cluster(self.container('40'), coordinate), 1)

    def test_own_supporting_footprint_is_excluded(self):
        for container_size in ('20', '40'):
            with self.subTest(container_size=container_size):
                self.setUp()
                self.occupy(2, 3, container_size)
                self.assertEqual(self.cluster(self.container(container_size), ('A', 2, 3, 1)), 1)

    def test_neighbors_outside_radius_are_ignored(self):
        self.occupy(2, 9, '40')
        self.assertEqual(self.cluster(self.container('40'), ('A', 2, 3, 0)), 1)

    def test_border_does_not_wrap_to_opposite_edge(self):
        self.occupy(4, 11, '20')
        self.assertEqual(self.cluster(self.container('20'), ('A', 0, 0, 0)), 1)

    def test_forty_foot_neighbors_on_either_side_have_equal_influence(self):
        self.occupy(2, 1, '40')
        left = self.cluster(self.container('40'), ('A', 2, 3, 0))
        self.setUp()
        self.occupy(2, 5, '40')
        right = self.cluster(self.container('40'), ('A', 2, 3, 0))
        self.assertEqual(left, right)

    def test_clustering_breaks_equal_mass_and_distance_tie(self):
        self.occupy(2, 3, '40')
        self.occupy(2, 8, '20')
        candidates = self.yard.bestCoordCandidate(
            self.container('40'), [('A', 2, 7, 0), ('A', 2, 1, 0)],
        )
        self.assertEqual(candidates[0].coordinates, ('A', 2, 1, 0))
        self.assertEqual(candidates[0].distance, candidates[1].distance)
        for candidate in candidates:
            self.assertAlmostEqual(candidate.evaluation_score,
                self.yard.model.evaluate(candidate.delta_container_mass, candidate.distance)
                * candidate.size_cluster_multiplier)

    def test_presenter_displays_multiplier_and_final_score(self):
        container = self.container('20')
        candidates = self.yard.bestCoordCandidate(container, [('A', 2, 3, 0)])
        result = AssignResult(container, {}, 0, candidates)
        output = []
        presenter = YardPresenter(lambda *args: output.append(args))
        presenter.outContainer = lambda container: None
        presenter.outAssignResult(result)
        tables = [
            arg
            for args in output
            for arg in args
            if isinstance(arg, pd.DataFrame)
        ]
        self.assertEqual(len(tables), 1)
        table = tables[0]
        self.assertEqual(table['Size Cluster Multiplier'].tolist(), result.getSizeClusterMultipliers())
        self.assertEqual(table['Score'].tolist(), result.getScores())
        self.assertNotIn('Size Affinity', table.columns)

    def test_candidate_construction_omits_affinity(self):
        candidate = CandidateEvaluation(('A', 0, 0, 0), [], None,
                                        RTG('RTG', ('A', 0, 0)), 0, 1, 1)
        self.assertFalse(hasattr(candidate, 'size_affinity'))
        self.assertEqual(candidate.size_cluster_multiplier, 1)


if __name__ == '__main__':
    unittest.main()

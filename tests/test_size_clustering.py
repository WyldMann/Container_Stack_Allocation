import math
import unittest
from types import SimpleNamespace

from entities.assign_result import AssignResult, CandidateEvaluation
from entities.equipment import RTG
from entities.heuristic_model import HeuristicModel
from entities.yard import Yard
from presenter import YardPresenter


class SizeClusteringTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([{
            'BRANCH_ID': 'B', 'BLOCK_ID': 'A', 'BLOCK_CODE': 'A',
            'SLOT_COUNT': '12', 'ROW_COUNT': '5', 'MAX_TIER': '3',
            'POS_X': '0', 'POS_Y': '0',
        }])
        self.yard.getBlockByID('A').setRTG(RTG('RTG', ('A', 2, 4)))

    def container(self, size):
        return SimpleNamespace(getContSize=lambda: size, getWeight=lambda: 10000)

    def affinity(self, container, coord):
        return self.yard.model.sizeAffinity(
            container, self.yard.getBlockByID(coord[0]), coord,
        )

    def occupy(self, row, anchor, size, height=1):
        slots = (anchor - 1, anchor) if size == '40' else (anchor,)
        container = self.container(size)
        for slot in slots:
            for tier in range(height):
                self.yard.getStack('A', row, slot).addContainer(container, tier)

    def test_empty_neighborhood_preserves_previous_scoring(self):
        affinity = self.affinity(self.container('40'), ('A', 2, 3, 0))
        self.assertEqual(affinity, 0)
        model = HeuristicModel()
        for weight, distance in ((0, 0), (5000, 5), (None, 0), (-1, 0), (0, math.inf)):
            self.assertEqual(model.evaluate(weight, distance, affinity),
                             model.deltaWeight(weight) * model.equipmentDistance(distance))

    def test_same_size_rewards_and_other_size_penalizes_both_sizes(self):
        for size in ('20', '40'):
            with self.subTest(size=size):
                self.setUp()
                self.occupy(2, 1, size)
                affinity = self.affinity(self.container(size), ('A', 2, 3, 0))
                self.assertGreater(affinity, 0)
                self.assertGreater(self.yard.model.sizeCluster(affinity), 1)
                other_size = '40' if size == '20' else '20'
                opposite = self.affinity(self.container(other_size), ('A', 2, 3, 0))
                self.assertLess(opposite, 0)
                self.assertLess(self.yard.model.sizeCluster(opposite), 1)

    def test_forty_foot_pair_counts_once(self):
        self.occupy(2, 1, '40')
        affinity = self.affinity(self.container('40'), ('A', 2, 3, 0))
        evidence = 2 ** (-1 / 1.5)
        self.assertAlmostEqual(affinity, evidence / (evidence + 2))

    def test_height_does_not_change_affinity(self):
        self.occupy(2, 1, '20')
        container = self.container('20')
        coord = ('A', 2, 3, 0)
        before = self.affinity(container, coord)
        self.yard.getStack('A', 2, 1).addContainer(container, 1)
        self.assertEqual(self.affinity(container, coord), before)

    def test_own_supporting_footprint_is_excluded(self):
        for size in ('20', '40'):
            with self.subTest(size=size):
                self.setUp()
                self.occupy(2, 3, size)
                self.assertEqual(self.affinity(self.container(size), ('A', 2, 3, 1)), 0)

    def test_neighbors_outside_radius_are_ignored(self):
        self.occupy(2, 9, '40')
        self.assertEqual(self.affinity(self.container('40'), ('A', 2, 3, 0)), 0)

    def test_border_does_not_wrap_to_opposite_edge(self):
        self.occupy(4, 11, '20')
        self.assertEqual(self.affinity(self.container('20'), ('A', 0, 0, 0)), 0)

    def test_forty_foot_neighbors_on_either_side_have_equal_influence(self):
        self.occupy(2, 1, '40')
        left = self.affinity(self.container('40'), ('A', 2, 3, 0))
        self.setUp()
        self.occupy(2, 5, '40')
        right = self.affinity(self.container('40'), ('A', 2, 3, 0))
        self.assertEqual(left, right)

    def test_clustering_breaks_equal_weight_and_distance_tie(self):
        self.occupy(2, 3, '40')
        self.occupy(2, 8, '20')
        candidates = self.yard.bestCoordCandidate(
            self.container('40'), [('A', 2, 7, 0), ('A', 2, 1, 0)],
        )
        self.assertEqual(candidates[0].coords, ('A', 2, 1, 0))
        self.assertEqual(candidates[0].distance, candidates[1].distance)
        for candidate in candidates:
            self.assertAlmostEqual(candidate.eval_score,
                self.yard.model.evaluate(candidate.delta_weight, candidate.distance)
                * candidate.size_cluster_multiplier)

    def test_presenter_displays_affinity_and_multiplier(self):
        container = self.container('20')
        candidates = self.yard.bestCoordCandidate(container, [('A', 2, 3, 0)])
        result = AssignResult(container, {}, 0, candidates)
        output = []
        presenter = YardPresenter(lambda *args: output.append(args))
        presenter.outContainer = lambda container: None
        presenter.outAssignResult(result)
        table = output[1][0]
        self.assertEqual(table['Size Affinity'].tolist(), result.getSizeAffinities())
        self.assertEqual(table['Size Cluster Multiplier'].tolist(), result.getSizeClusterMultipliers())
        self.assertEqual(table['Score'].tolist(), result.getScores())

    def test_existing_candidate_construction_defaults_to_neutral_clustering(self):
        candidate = CandidateEvaluation(('A', 0, 0, 0), [], None,
                                        RTG('RTG', ('A', 0, 0)), 0, 1)
        self.assertEqual(candidate.size_affinity, 0)
        self.assertEqual(candidate.size_cluster_multiplier, 1)


if __name__ == '__main__':
    unittest.main()

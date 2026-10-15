import math
import unittest
from types import SimpleNamespace

import pandas as pd

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

import unittest
from dataclasses import FrozenInstanceError

from entities.feasibility.placement_proposal import PlacementProposal


class PlacementProposalTests(unittest.TestCase):
    def test_twenty_foot_coordinates_and_footprint(self):
        proposal = PlacementProposal("A", 2, 0, 1, "20")

        self.assertEqual(proposal.coordinates, ("A", 2, 0, 1))
        self.assertEqual(proposal.footprint, (("A", 2, 0),))

    def test_forty_foot_coordinates_and_footprint(self):
        proposal = PlacementProposal("A", 2, 3, 1, "40")

        self.assertEqual(proposal.coordinates, ("A", 2, 3, 1))
        self.assertEqual(
            proposal.footprint,
            (("A", 2, 2), ("A", 2, 3)),
        )

    def test_forty_foot_first_valid_anchor(self):
        proposal = PlacementProposal("A", 0, 1, 0, "40")

        self.assertEqual(
            proposal.footprint,
            (("A", 0, 0), ("A", 0, 1)),
        )

    def test_occupies_identifies_only_footprint_stacks(self):
        proposal = PlacementProposal("A", 2, 3, 1, "40")

        self.assertTrue(proposal.occupies(("A", 2, 2)))
        self.assertTrue(proposal.occupies(("A", 2, 3)))
        self.assertFalse(proposal.occupies(("A", 2, 4)))
        self.assertFalse(proposal.occupies(("A", 1, 3)))
        self.assertFalse(proposal.occupies(("B", 2, 3)))

    def test_twenty_foot_does_not_occupy_preceding_stack(self):
        proposal = PlacementProposal("A", 2, 3, 1, "20")

        self.assertTrue(proposal.occupies(("A", 2, 3)))
        self.assertFalse(proposal.occupies(("A", 2, 2)))

    def test_resulting_height_uses_zero_based_tier(self):
        for tier_index in (0, 1, 4):
            with self.subTest(tier_index=tier_index):
                proposal = PlacementProposal("A", 0, 1, tier_index, "40")

                self.assertEqual(proposal.resulting_height, tier_index + 1)

    def test_invalid_block_ids_are_rejected(self):
        for block_id in ("", " ", "\t\n", None, 123):
            with self.subTest(block_id=block_id):
                with self.assertRaises(ValueError):
                    PlacementProposal(block_id, 0, 1, 0, "40")

    def test_unsupported_sizes_are_rejected(self):
        for container_size in ("", "45", "invalid", 20, 40, None):
            with self.subTest(container_size=container_size):
                with self.assertRaises(ValueError):
                    PlacementProposal("A", 0, 1, 0, container_size)

    def test_negative_coordinates_are_rejected(self):
        for field in ("row_index", "slot_index", "tier_index"):
            with self.subTest(field=field):
                values = {
                    "block_id": "A",
                    "row_index": 0,
                    "slot_index": 1,
                    "tier_index": 0,
                    "container_size": "40",
                }
                values[field] = -1

                with self.assertRaises(ValueError):
                    PlacementProposal(**values)

    def test_non_integer_coordinates_are_rejected(self):
        for field in ("row_index", "slot_index", "tier_index"):
            for value in (1.0, "1", None, True, False):
                with self.subTest(field=field, value=value):
                    values = {
                        "block_id": "A",
                        "row_index": 0,
                        "slot_index": 1,
                        "tier_index": 0,
                        "container_size": "40",
                    }
                    values[field] = value

                    with self.assertRaises(TypeError):
                        PlacementProposal(**values)

    def test_even_forty_foot_anchors_are_rejected(self):
        for slot_index in (0, 2, 4):
            with self.subTest(slot_index=slot_index):
                with self.assertRaises(ValueError):
                    PlacementProposal("A", 0, slot_index, 0, "40")

    def test_twenty_foot_accepts_either_slot_parity(self):
        for slot_index in (0, 1, 2, 3):
            with self.subTest(slot_index=slot_index):
                proposal = PlacementProposal("A", 0, slot_index, 0, "20")

                self.assertEqual(
                    proposal.footprint,
                    (("A", 0, slot_index),),
                )

    def test_fields_cannot_be_reassigned(self):
        proposal = PlacementProposal("A", 2, 3, 1, "40")

        for field, value in (
            ("block_id", "B"),
            ("row_index", 3),
            ("slot_index", 5),
            ("tier_index", 2),
            ("container_size", "20"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(FrozenInstanceError):
                    setattr(proposal, field, value)


if __name__ == "__main__":
    unittest.main()

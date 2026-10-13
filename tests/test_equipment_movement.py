import unittest

from entities import Container, Yard
from entities.equipment import Equipment, Loader, RTG


class EquipmentMovementTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([
            dict(branch_id="BR", block_id=block_id, block_code=block_id,
                 slot_count="3", row_count="2", max_tier="3",
                 pos_x="0", pos_y="0")
            for block_id in ("A", "B")
        ])
        self.source = self.yard.getBlockByID("A")
        self.destination = self.yard.getBlockByID("B")
        self.loader = Loader("L", ("A", 0, 0))
        self.yard.master_loaders.append(self.loader)
        self.source.addLoader(self.loader)
        self.rtg = RTG("R", ("A", 0, 0))
        self.source.setRTG(self.rtg)

    def snapshot(self, equipment):
        return (equipment.getCoords(), tuple(self.source.getLoaders()),
                tuple(self.destination.getLoaders()), tuple(self.yard.master_loaders),
                self.source.getRTG(), self.destination.getRTG())

    def assert_rejected(self, equipment, coordinates, error=ValueError):
        before = self.snapshot(equipment)
        with self.assertRaises(error):
            self.yard.moveEquipment(equipment, coordinates)
        self.assertEqual(self.snapshot(equipment), before)

    def test_loader_moves_between_blocks_and_back(self):
        self.yard.moveEquipment(self.loader, ("B", 1, 2))
        self.assertEqual(self.loader.getCoords(), ("B", 1, 2))
        self.assertEqual(self.source.getLoaders(), [])
        self.assertEqual(self.destination.getLoaders(), [self.loader])
        self.assertEqual(self.yard.master_loaders, [self.loader])
        self.yard.moveEquipment(self.loader, ("A", 0, 1))
        self.assertEqual(self.loader.getCoords(), ("A", 0, 1))
        self.assertEqual(self.source.getLoaders(), [self.loader])
        self.assertEqual(self.destination.getLoaders(), [])

    def test_same_block_moves_preserve_membership(self):
        for equipment in (self.loader, self.rtg):
            with self.subTest(equipment=equipment.getCode()):
                before = self.snapshot(equipment)[1:]
                self.yard.moveEquipment(equipment, ("A", 1, 2))
                self.assertEqual(equipment.getCoords(), ("A", 1, 2))
                self.assertEqual(self.snapshot(equipment)[1:], before)

    def test_rtg_cannot_change_blocks(self):
        self.assert_rejected(self.rtg, ("B", 0, 0))

    def test_outside_grid_positions_preserve_same_block_membership(self):
        for equipment in (self.loader, self.rtg):
            before = self.snapshot(equipment)[1:]
            for row_index, slot_index in ((-1, 0), (2, 0), (0, -1), (0, 3), (-5, 20)):
                with self.subTest(equipment=equipment.getCode(), row_index=row_index, slot_index=slot_index):
                    self.yard.moveEquipment(equipment, ("A", row_index, slot_index))
                    self.assertEqual(equipment.getCoords(), ("A", row_index, slot_index))
                    self.assertEqual(self.snapshot(equipment)[1:], before)

    def test_loader_can_change_blocks_to_outside_grid_position(self):
        self.yard.moveEquipment(self.loader, ("B", -1, 5))
        self.assertEqual(self.loader.getCoords(), ("B", -1, 5))
        self.assertEqual(self.source.getLoaders(), [])
        self.assertEqual(self.destination.getLoaders(), [self.loader])
        self.assertEqual(self.yard.master_loaders, [self.loader])
        self.yard.moveEquipment(self.loader, ("A", 0, 0))
        self.assertEqual(self.loader.getCoords(), ("A", 0, 0))
        self.assertEqual(self.source.getLoaders(), [self.loader])
        self.assertEqual(self.destination.getLoaders(), [])

    def test_invalid_destinations_leave_state_unchanged(self):
        for equipment in (self.loader, self.rtg):
            for row_index, slot_index in ((True, 0), (0, False), (1.5, 0), (0, 1.5),
                              ("1", 0), (0, None)):
                with self.subTest(equipment=equipment.getCode(), row_index=row_index, slot_index=slot_index):
                    self.assert_rejected(equipment, ("A", row_index, slot_index))
        self.assert_rejected(self.loader, ("UNKNOWN", 0, 0), KeyError)

    def test_unsupported_and_unregistered_equipment_are_rejected(self):
        self.assert_rejected(Equipment("E", ("A", 0, 0)),
                             ("A", 1, 1), TypeError)
        self.assert_rejected(Loader("OTHER", ("A", 0, 0)), ("B", 0, 0))
        self.assert_rejected(RTG("OTHER", ("A", 0, 0)), ("A", 0, 0))

    def test_inconsistent_source_membership_is_rejected(self):
        self.source.removeLoader(self.loader)
        self.assert_rejected(self.loader, ("B", 0, 0))
        self.source.addLoader(self.loader)
        self.source.addLoader(self.loader)
        self.assert_rejected(self.loader, ("B", 0, 0))

    def test_duplicate_destination_membership_is_rejected(self):
        self.destination.addLoader(self.loader)
        self.assert_rejected(self.loader, ("B", 0, 0))

    def test_placement_updates_loader_location_and_membership(self):
        container = Container(
            container_id="C", principal="", container_condition="", container_fill="",
            container_size="20", container_grade="", pol="", pod="", vessel="",
            voyage="", weight="100", move_time="",
        )
        self.yard.placeContainer(container, ("B", 1, 2, 0), self.loader)
        self.assertIs(self.destination.getStack(1, 2).getContainer(0), container)
        self.assertEqual(self.loader.getCoords(), ("B", 1, 2))
        self.assertEqual(self.source.getLoaders(), [])
        self.assertEqual(self.destination.getLoaders(), [self.loader])


if __name__ == "__main__":
    unittest.main()

import unittest

from entities import Container, Yard
from entities.equipment import Equipment, Loader, RTG


class EquipmentMovementTests(unittest.TestCase):
    def setUp(self):
        self.yard = Yard([
            dict(BRANCH_ID="BR", BLOCK_ID=block_id, BLOCK_CODE=block_id,
                 SLOT_COUNT="3", ROW_COUNT="2", MAX_TIER="3",
                 POS_X="0", POS_Y="0")
            for block_id in ("A", "B")
        ])
        self.source = self.yard.getBlockByID("A")
        self.destination = self.yard.getBlockByID("B")
        self.loader = Loader("L", ("A", 0, 0))
        self.yard.masterLoader.append(self.loader)
        self.source.addLoader(self.loader)
        self.rtg = RTG("R", ("A", 0, 0))
        self.source.setRTG(self.rtg)

    def snapshot(self, equipment):
        return (equipment.getCoords(), tuple(self.source.getLoaders()),
                tuple(self.destination.getLoaders()), tuple(self.yard.masterLoader),
                self.source.getRTG(), self.destination.getRTG())

    def assert_rejected(self, equipment, coords, error=ValueError):
        before = self.snapshot(equipment)
        with self.assertRaises(error):
            self.yard.moveEquipment(equipment, coords)
        self.assertEqual(self.snapshot(equipment), before)

    def test_loader_moves_between_blocks_and_back(self):
        self.yard.moveEquipment(self.loader, ("B", 1, 2))
        self.assertEqual(self.loader.getCoords(), ("B", 1, 2))
        self.assertEqual(self.source.getLoaders(), [])
        self.assertEqual(self.destination.getLoaders(), [self.loader])
        self.assertEqual(self.yard.masterLoader, [self.loader])
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

    def test_invalid_destinations_leave_state_unchanged(self):
        for row, slot in ((-1, 0), (2, 0), (0, -1), (0, 3),
                          (True, 0), (0, 1.5)):
            with self.subTest(row=row, slot=slot):
                self.assert_rejected(self.loader, ("B", row, slot))
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
            CONTNO="C", PRINCIPAL="", DMG_FLAG="", FULLMT="",
            CONTSIZE="20", CONT_GRADE="", POL="", POD="", VESSEL="",
            VOYAGE="", WEIGHT="100", MOVE_TIME="",
        )
        self.yard.placeContainer(container, ("B", 1, 2, 0), self.loader)
        self.assertIs(self.destination.getStack(1, 2).getContainer(0), container)
        self.assertEqual(self.loader.getCoords(), ("B", 1, 2))
        self.assertEqual(self.source.getLoaders(), [])
        self.assertEqual(self.destination.getLoaders(), [self.loader])


if __name__ == "__main__":
    unittest.main()

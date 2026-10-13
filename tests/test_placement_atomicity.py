import unittest
from unittest.mock import patch

from entities import Container, Yard
from entities.bad_yard_data import PlacementRejected
from entities.equipment import Equipment, Loader, RTG


class PlacementAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(
            CONTNO="NEW", PRINCIPAL="", DMG_FLAG="", FULLMT="",
            CONTSIZE="20", CONT_GRADE="", POL="", POD="", VESSEL="",
            VOYAGE="", WEIGHT="", MOVE_TIME="",
        )

    def make_yard(self, size="20"):
        yard = Yard([
            dict(BRANCH_ID="BR", BLOCK_ID=block_id, BLOCK_CODE=block_id,
                 SLOT_COUNT="4", ROW_COUNT="2", MAX_TIER="3",
                 POS_X="0", POS_Y="0")
            for block_id in ("A", "B")
        ])
        loader = Loader("L", ("A", 0, 0))
        yard.masterLoader.append(loader)
        yard.getBlockByID("A").addLoader(loader)
        return yard, loader, Container(**(self.record | {"CONTSIZE": size}))

    def snapshot(self, yard, container, equipment):
        return (
            dict(yard.containers),
            tuple((item, item.getCoordsStrTuple())
                  for item in yard.containers.values()),
            container.getCoordsStrTuple(),
            equipment.getCoords(),
            tuple(yard.masterLoader),
            tuple(
                (block.getId(), tuple(block.getLoaders()), block.getRTG(),
                 tuple((stack.getMode(), tuple(stack.getContainers()))
                       for row in block.getSlots() for stack in row))
                for block in yard.blocks_by_id.values()
            ),
        )

    def assert_unchanged_on_failure(
        self, yard, container, equipment, action, error=PlacementRejected,
    ):
        before = self.snapshot(yard, container, equipment)
        registry = yard.containers
        coordinates = container.getCoordsStr()
        master_loaders = yard.masterLoader
        loaders = [block.getLoaders() for block in yard.blocks_by_id.values()]
        contents = [stack.getContainers()
                    for block in yard.blocks_by_id.values()
                    for row in block.getSlots() for stack in row]
        with self.assertRaises(error):
            action()
        self.assertEqual(self.snapshot(yard, container, equipment), before)
        self.assertIs(yard.containers, registry)
        self.assertIs(container.getCoordsStr(), coordinates)
        self.assertIs(yard.masterLoader, master_loaders)
        for block, original in zip(yard.blocks_by_id.values(), loaders):
            self.assertIs(block.getLoaders(), original)
        for stack, original in zip(
            (stack for block in yard.blocks_by_id.values()
             for row in block.getSlots() for stack in row), contents,
        ):
            self.assertIs(stack.getContainers(), original)

    def test_incomplete_containers_are_rejected_at_every_entry_point_and_recorded_once(self):
        for changes in ({"CONTNO": None}, {"CONTNO": "  "}, {"CONTNO": 123},
                        {"CONTSIZE": "45"}):
            with self.subTest(changes=changes):
                yard, equipment, _ = self.make_yard()
                container = Container(**(self.record | changes))
                for action in (
                    lambda: yard.assignContainer(container),
                    lambda: yard.assign_and_place(container),
                    lambda: yard.placeContainer(container, ("B", 0, 1, 0), equipment),
                    lambda: yard.addContainerByCoords(container, ("B", 0, 1, 0)),
                ):
                    self.assert_unchanged_on_failure(yard, container, equipment, action)
                self.assertEqual(yard.bad_data.getIncompleteInboundContainers(), [container])
                self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 0)

    def test_invalid_equipment_is_rejected_before_container_updates(self):
        for invalid in (None, Equipment("E", ("A", 0, 0)),
                        Loader("OTHER", ("A", 0, 0)), RTG("OTHER", ("A", 0, 0)),
                        Loader("OTHER", ("UNKNOWN", 0, 0))):
            with self.subTest(equipment=invalid):
                yard, registered, container = self.make_yard()
                self.assert_unchanged_on_failure(
                    yard, container, registered,
                    lambda: yard.placeContainer(container, ("B", 0, 1, 0), invalid),
                )
        yard, _, container = self.make_yard()
        rtg = RTG("R", ("A", 0, 0))
        yard.getBlockByID("A").setRTG(rtg)
        self.assert_unchanged_on_failure(
            yard, container, rtg,
            lambda: yard.placeContainer(container, ("B", 0, 1, 0), rtg),
        )

    def test_invalid_coordinates_and_removed_destinations_preserve_state(self):
        for size in ("20", "40"):
            for coords in (("B", -1, 1, 0), ("B", 0, -1, 0), ("B", 0, 1, -1),
                           ("B", 0, 1, 3), ("B", True, 1, 0), ("B", 0, 1.5, 0),
                           ("UNKNOWN", 0, 1, 0)):
                with self.subTest(size=size, coords=coords):
                    yard, equipment, container = self.make_yard(size)
                    self.assert_unchanged_on_failure(
                        yard, container, equipment,
                        lambda: yard.placeContainer(container, coords, equipment),
                    )
            for removed_slot in ((1,) if size == "20" else (0, 1)):
                with self.subTest(size=size, removed_slot=removed_slot):
                    yard, equipment, container = self.make_yard(size)
                    yard.getStack("B", 0, removed_slot).makeVoid()
                    self.assert_unchanged_on_failure(
                        yard, container, equipment,
                        lambda: yard.placeContainer(container, ("B", 0, 1, 0), equipment),
                    )

    def test_duplicate_id_is_rejected_at_assignment_and_placement(self):
        yard, equipment, container = self.make_yard()
        yard.placeContainer(container, ("B", 0, 1, 0), equipment)
        duplicate = Container(**self.record)
        for action in (
            lambda: yard.assignContainer(duplicate),
            lambda: yard.placeContainer(duplicate, ("B", 0, 2, 0), equipment),
            lambda: yard.addContainerByCoords(duplicate, ("B", 0, 2, 0)),
        ):
            self.assert_unchanged_on_failure(yard, duplicate, equipment, action)

    def test_stale_assignment_with_occupied_partner_is_rejected(self):
        yard, equipment, container = self.make_yard("40")
        result = yard.assignContainer(container)
        block_id, row, slot, tier = result.getBestCoordinate()
        other = Container(**(self.record | {"CONTNO": "OTHER"}))
        yard.addContainerByCoords(other, (block_id, row, slot - 1, tier))
        self.assert_unchanged_on_failure(
            yard, container, equipment,
            lambda: yard.placeContainerWithAssignResult(result),
        )

    def test_stale_assignment_is_rejected_when_next_tier_changes(self):
        yard, equipment, container = self.make_yard("40")
        result = yard.assignContainer(container)
        other = Container(**(self.record | {"CONTNO": "OTHER", "CONTSIZE": "40"}))
        yard.addContainerByCoords(other, result.getBestCoordinate())
        self.assert_unchanged_on_failure(
            yard, container, equipment,
            lambda: yard.placeContainerWithAssignResult(result),
        )

    def test_failure_after_second_slot_write_restores_both_slots(self):
        yard, equipment, container = self.make_yard("40")
        stack = yard.getStack("B", 0, 1)
        original = stack.addContainer

        def fail_after_write(item, tier):
            original(item, tier)
            raise RuntimeError("Injected failure after second slot write")

        with patch.object(stack, "addContainer", side_effect=fail_after_write):
            self.assert_unchanged_on_failure(
                yard, container, equipment,
                lambda: yard.placeContainer(container, ("B", 0, 1, 0), equipment),
                RuntimeError,
            )

    def test_failure_after_registry_update_restores_registry_and_coordinates(self):
        yard, equipment, container = self.make_yard()
        other = Container(**(self.record | {"CONTNO": "OTHER"}))
        yard.addContainerByCoords(other, ("A", 0, 3, 0))
        original = yard.addContainer

        def fail_after_registration(item):
            original(item)
            raise RuntimeError("Injected failure after registry update")

        with patch.object(yard, "addContainer", side_effect=fail_after_registration):
            self.assert_unchanged_on_failure(
                yard, container, equipment,
                lambda: yard.placeContainer(container, ("B", 0, 1, 0), equipment),
                RuntimeError,
            )

    def test_failure_after_equipment_move_restores_location_and_membership(self):
        for kind in ("loader", "rtg"):
            with self.subTest(kind=kind):
                yard, equipment, container = self.make_yard("40")
                destination = "B"
                if kind == "rtg":
                    equipment = RTG("R", ("A", 0, 0))
                    yard.getBlockByID("A").setRTG(equipment)
                    destination = "A"
                original = yard.moveEquipment

                def fail_after_move(item, coords):
                    original(item, coords)
                    raise RuntimeError("Injected failure after equipment move")

                with patch.object(yard, "moveEquipment", side_effect=fail_after_move):
                    self.assert_unchanged_on_failure(
                        yard, container, equipment,
                        lambda: yard.placeContainer(
                            container, (destination, 0, 1, 0), equipment),
                        RuntimeError,
                    )

    def test_direct_coordinate_addition_also_rolls_back_after_failure(self):
        yard, equipment, container = self.make_yard("40")
        stack = yard.getStack("B", 0, 1)
        original = stack.addContainer

        def fail_after_write(item, tier):
            original(item, tier)
            raise RuntimeError("Injected direct placement failure")

        with patch.object(stack, "addContainer", side_effect=fail_after_write):
            self.assert_unchanged_on_failure(
                yard, container, equipment,
                lambda: yard.addContainerByCoords(container, ("B", 0, 1, 0)),
                RuntimeError,
            )

    def test_successful_placements_update_complete_footprint_and_equipment(self):
        for size in ("20", "40"):
            for destination in ("A", "B"):
                with self.subTest(size=size, destination=destination):
                    yard, equipment, container = self.make_yard(size)
                    yard.placeContainer(container, (destination, 0, 1, 0), equipment)
                    self.assertEqual(yard.containers, {"NEW": container})
                    self.assertEqual(container.getCoordsStrTuple(),
                                     ("BR", destination, "1", "2", "1"))
                    self.assertEqual(equipment.getCoords(), (destination, 0, 1))
                    self.assertEqual(yard.masterLoader, [equipment])
                    self.assertEqual(yard.getBlockByID(destination).getLoaders(),
                                     [equipment])
                    if destination == "B":
                        self.assertEqual(yard.getBlockByID("A").getLoaders(), [])
                    for slot in ((1,) if size == "20" else (0, 1)):
                        stack = yard.getStack(destination, 0, slot)
                        self.assertIs(stack.getContainer(0), container)
                        self.assertEqual(stack.getMode(), size)

    def test_stack_rejections_preserve_mode_and_contents(self):
        yard, equipment, container = self.make_yard("40")
        stack = yard.getStack("B", 0, 1)
        stack.addContainer(Container(**(self.record | {"CONTNO": "OTHER"})), 0)
        for tier in (0, -1, 3, True):
            with self.subTest(tier=tier):
                self.assert_unchanged_on_failure(
                    yard, container, equipment,
                    lambda: stack.addContainer(container, tier),
                    (TypeError, ValueError),
                )
        stack.makeVoid()
        self.assert_unchanged_on_failure(
            yard, container, equipment,
            lambda: stack.addContainer(container, 0), ValueError,
        )

    def test_bad_yard_data_validates_without_changing_yard_state(self):
        yard, equipment, container = self.make_yard("40")
        before = self.snapshot(yard, container, equipment)
        validated = yard.bad_data.validateInboundPlacement(
            container, ("B", 0, 1, 0), equipment,
            blocks_by_id=yard.blocks_by_id,
            registered_containers=yard.containers,
            master_loaders=yard.masterLoader,
            feasibility=yard.feasibility,
            loader_policies=yard.loader_access_policies,
        )
        self.assertEqual(validated.proposal.coordinates, ("B", 0, 1, 0))
        self.assertIs(validated.equipment, equipment)
        self.assertIs(validated.source_block, yard.getBlockByID("A"))
        self.assertIs(validated.destination_block, yard.getBlockByID("B"))
        self.assertEqual(self.snapshot(yard, container, equipment), before)
        self.assertFalse(yard.bad_data.anyBadData())


if __name__ == "__main__":
    unittest.main()

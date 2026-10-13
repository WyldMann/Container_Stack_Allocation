import unittest
from unittest.mock import Mock, call

from entities import Container, Yard
from entities.bad_yard_data import PlacementRejected
from presenter import BadDataPresenter


class DuplicateContainerIDTests(unittest.TestCase):
    def setUp(self):
        self.block = dict(
            BRANCH_ID="BR", BLOCK_ID="A", BLOCK_CODE="A",
            SLOT_COUNT="4", ROW_COUNT="2", MAX_TIER="3",
            POS_X="0", POS_Y="0",
        )
        self.record = dict(
            CONTNO="C", PRINCIPAL="", DMG_FLAG="", FULLMT="",
            CONTSIZE="20", CONT_GRADE="", POL="", POD="", VESSEL="",
            VOYAGE="", WEIGHT="", MOVE_TIME="01/01/2026 10:00",
            BRANCH="BR", BLOK="A", ROW="1", SLOT="2", TIER="1",
        )

    def make_yard(self, records=()):
        return Yard([self.block], container_input=list(records))

    def inbound_container(self, **changes):
        fields = {key: value for key, value in self.record.items()
                  if key not in ("BRANCH", "BLOK", "ROW", "SLOT", "TIER")}
        return Container(**(fields | changes))

    def snapshot(self, yard):
        return (
            dict(yard.containers),
            tuple((container, container.getCoordsStrTuple())
                  for container in yard.containers.values()),
            tuple((stack.getMode(), tuple(stack.getContainers()))
                  for row in yard.getBlockByID("A").getSlots() for stack in row),
        )

    def test_duplicate_lists_and_recording_helpers_are_independent(self):
        yard, clean = self.make_yard(), self.make_yard()
        existing = Container(**self.record)
        inbound = self.inbound_container()
        for _ in range(2):
            yard.bad_data.addDuplicateExistingContainerID(existing)
            yard.bad_data.addDuplicateInboundContainerID(inbound)
        self.assertIs(yard.bad_data.getDuplicateExistingContainerIDs(),
                      yard.bad_data.duplicateExistingContainerIDs)
        self.assertIs(yard.bad_data.getDuplicateInboundContainerIDs(),
                      yard.bad_data.duplicateInboundContainerIDs)
        self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(), [existing])
        self.assertEqual(yard.bad_data.getDuplicateInboundContainerIDs(), [inbound])
        self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
        self.assertEqual(yard.bad_data.getTotalDuplicateInboundContainerIDs(), 1)
        self.assertEqual(clean.bad_data.duplicateExistingContainerIDs, [])
        self.assertEqual(clean.bad_data.duplicateInboundContainerIDs, [])
        self.assertIsNot(yard.bad_data.duplicateExistingContainerIDs,
                         yard.bad_data.duplicateInboundContainerIDs)
        self.assertTrue(yard.bad_data.anyBadData())
        self.assertFalse(clean.bad_data.anyBadData())

    def test_bad_yard_data_validates_ids_and_records_only_rejections(self):
        yard = self.make_yard([self.record])
        before = self.snapshot(yard)
        unique = self.inbound_container(CONTNO="UNIQUE")
        self.assertTrue(yard.bad_data.validateExistingContainerIDAndRecord(
            unique, yard.containers))
        self.assertTrue(yard.bad_data.validateInboundContainerIDAndRecord(
            unique, yard.containers))
        self.assertFalse(yard.bad_data.anyBadData())

        existing, inbound = Container(**self.record), self.inbound_container()
        self.assertFalse(yard.bad_data.validateExistingContainerIDAndRecord(
            existing, yard.containers))
        self.assertFalse(yard.bad_data.validateInboundContainerIDAndRecord(
            inbound, yard.containers))
        self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(), [existing])
        self.assertEqual(yard.bad_data.getDuplicateInboundContainerIDs(), [inbound])
        self.assertEqual(self.snapshot(yard), before)

    def test_same_location_existing_duplicates_keep_first_record_for_both_sizes(self):
        for size in ("20", "40"):
            for time in ("09:00", "10:00", "11:00"):
                with self.subTest(size=size, time=time):
                    first = self.record | {"CONTSIZE": size}
                    duplicate = first | {"MOVE_TIME": "01/01/2026 " + time}
                    yard = self.make_yard([first, duplicate])
                    kept = yard.containers["C"]
                    rejected = yard.bad_data.getDuplicateExistingContainerIDs()[0]
                    self.assertEqual(kept.getMoveTimeRaw(), first["MOVE_TIME"])
                    self.assertEqual(rejected.getMoveTimeRaw(), duplicate["MOVE_TIME"])
                    self.assertIsNot(kept, rejected)
                    self.assertEqual(len(yard.containers), 1)
                    self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
                    self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
                    self.assertEqual(yard.bad_data.getTotalOverlapping(), 0)
                    for slot in ((1,) if size == "20" else (0, 1)):
                        self.assertIs(yard.getStack("A", 0, slot).getContainer(0), kept)

    def test_distinct_duplicate_records_are_each_reported_and_import_continues(self):
        records = [self.record,
                   self.record | {"SLOT": "4"},
                   self.record | {"ROW": "2"},
                   self.record | {"CONTNO": "VALID", "SLOT": "4"}]
        originals = [record.copy() for record in records]
        yard = self.make_yard(records)
        self.assertEqual(records, originals)
        self.assertEqual(set(yard.containers), {"C", "VALID"})
        self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 2)
        self.assertEqual(yard.bad_data.getTotalDuplicateInboundContainerIDs(), 0)
        self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
        self.assertEqual(yard.getStack("A", 1, 1).occupancy(), 0)

    def test_inbound_duplicate_is_recorded_once_across_entry_points(self):
        yard = self.make_yard([self.record])
        before = self.snapshot(yard)
        inbound = self.inbound_container()
        coordinates = inbound.getCoordsStrTuple()
        for action in (
            lambda: yard.assignContainer(inbound),
            lambda: yard.assign_and_place(inbound),
            lambda: yard.placeContainer(inbound, ("A", 0, 3, 0), None),
            lambda: yard.addContainerByCoords(inbound, ("A", 0, 3, 0)),
        ):
            with self.assertRaisesRegex(PlacementRejected, "already registered"):
                action()
            self.assertEqual(self.snapshot(yard), before)
            self.assertEqual(inbound.getCoordsStrTuple(), coordinates)
        self.assertEqual(yard.bad_data.getDuplicateInboundContainerIDs(), [inbound])
        self.assertEqual(yard.bad_data.getTotalDuplicateInboundContainerIDs(), 1)
        self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 0)
        self.assertEqual(yard.bad_data.getTotalIncompleteInbound(), 0)
        self.assertTrue(yard.bad_data.anyBadData())

    def test_revalidating_existing_duplicate_does_not_add_it_twice(self):
        yard = self.make_yard([self.record])
        duplicate = Container(**(self.record | {"SLOT": "4"}))
        before = self.snapshot(yard)
        for _ in range(2):
            yard.addContainerInput(duplicate)
        self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(), [duplicate])
        self.assertEqual(self.snapshot(yard), before)

    def test_incomplete_inbound_is_classified_before_duplicate_id(self):
        yard = self.make_yard([self.record])
        inbound = self.inbound_container(CONTSIZE="45")
        with self.assertRaises(PlacementRejected):
            yard.assignContainer(inbound)
        self.assertEqual(yard.bad_data.getIncompleteInboundContainers(), [inbound])
        self.assertEqual(yard.bad_data.getDuplicateInboundContainerIDs(), [])

    def test_presenter_reports_duplicate_only_data_and_counts_for_each_category(self):
        for category in ("existing", "inbound", "both"):
            with self.subTest(category=category):
                yard = self.make_yard()
                existing = Container(**self.record)
                inbound = self.inbound_container()
                if category in ("existing", "both"):
                    yard.bad_data.addDuplicateExistingContainerID(existing)
                if category in ("inbound", "both"):
                    yard.bad_data.addDuplicateInboundContainerID(inbound)
                output = Mock()
                presenter = BadDataPresenter(out=output)
                presenter.print(yard.bad_data)
                presenter.printStats(yard.bad_data)
                self.assertNotIn(call("No Bad Data"), output.call_args_list)
                if category in ("existing", "both"):
                    output.assert_any_call("\nDuplicate Existing Container IDs:")
                    output.assert_any_call("C", ["BR", "A", "1", "2", "1"],
                                           "CONTSIZE:", "'20'")
                if category in ("inbound", "both"):
                    output.assert_any_call("\nDuplicate Inbound Container IDs:")
                    output.assert_any_call("C", "CONTSIZE:", "'20'")
                output.assert_any_call("Duplicate Existing Container IDs:",
                                       int(category in ("existing", "both")))
                output.assert_any_call("Duplicate Inbound Container IDs:",
                                       int(category in ("inbound", "both")))


if __name__ == "__main__":
    unittest.main()

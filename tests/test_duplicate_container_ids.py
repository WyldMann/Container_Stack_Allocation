import unittest
from unittest.mock import Mock, call

from entities import Container, Yard
from entities.bad_yard_data import PlacementRejected
from presenter import BadDataPresenter


class DuplicateContainerIDTests(unittest.TestCase):
    def setUp(self):
        self.block = dict(
            branch_id="BR", block_id="A", block_code="A",
            slot_count="4", row_count="2", max_tier="3",
            pos_x="0", pos_y="0",
        )
        self.record = dict(
            container_id="C", principal="", container_condition="", container_fill="",
            container_size="20", container_grade="", pol="", pod="", vessel="",
            voyage="", weight="", move_time="01/01/2026 10:00",
            branch_id="BR", block_code="A", row_no="1", slot_no="2", tier_no="1",
        )

    def make_yard(self, records=()):
        return Yard([self.block], containers_input=list(records))

    def inbound_container(self, **changes):
        fields = {key: value for key, value in self.record.items()
                  if key not in ("branch_id", "block_code", "row_no", "slot_no", "tier_no")}
        return Container(**(fields | changes))

    def snapshot(self, yard):
        return (
            dict(yard.containers),
            tuple((container, container.getCoordsStrTuple())
                  for container in yard.containers.values()),
            tuple((stack.getMode(), tuple(stack.getContainers()))
                  for row_stacks in yard.getBlockByID("A").getSlots() for stack in row_stacks),
        )

    def test_duplicate_lists_and_recording_helpers_are_independent(self):
        yard, clean = self.make_yard(), self.make_yard()
        existing = Container(**self.record)
        inbound = self.inbound_container()
        for _ in range(2):
            yard.bad_data.addDuplicateExistingContainerID(existing)
            yard.bad_data.addDuplicateInboundContainerID(inbound)
        self.assertIs(yard.bad_data.getDuplicateExistingContainerIDs(),
                      yard.bad_data.duplicate_existing_container_i_ds)
        self.assertIs(yard.bad_data.getDuplicateInboundContainerIDs(),
                      yard.bad_data.duplicate_inbound_container_i_ds)
        self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(), [existing])
        self.assertEqual(yard.bad_data.getDuplicateInboundContainerIDs(), [inbound])
        self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
        self.assertEqual(yard.bad_data.getTotalDuplicateInboundContainerIDs(), 1)
        self.assertEqual(clean.bad_data.duplicate_existing_container_i_ds, [])
        self.assertEqual(clean.bad_data.duplicate_inbound_container_i_ds, [])
        self.assertIsNot(yard.bad_data.duplicate_existing_container_i_ds,
                         yard.bad_data.duplicate_inbound_container_i_ds)
        self.assertTrue(yard.bad_data.anyBadData())
        self.assertFalse(clean.bad_data.anyBadData())

    def test_bad_yard_data_validates_ids_and_records_only_rejections(self):
        yard = self.make_yard([self.record])
        before = self.snapshot(yard)
        unique = self.inbound_container(container_id="UNIQUE")
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
        for container_size in ("20", "40"):
            for time in ("09:00", "10:00", "11:00"):
                with self.subTest(container_size=container_size, time=time):
                    first = self.record | {"container_size": container_size}
                    duplicate = first | {"move_time": "01/01/2026 " + time}
                    yard = self.make_yard([first, duplicate])
                    kept = yard.containers["C"]
                    rejected = yard.bad_data.getDuplicateExistingContainerIDs()[0]
                    self.assertEqual(kept.getMoveTimeRaw(), first["move_time"])
                    self.assertEqual(rejected.getMoveTimeRaw(), duplicate["move_time"])
                    self.assertIsNot(kept, rejected)
                    self.assertEqual(len(yard.containers), 1)
                    self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
                    self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
                    self.assertEqual(yard.bad_data.getTotalOverlapping(), 0)
                    for slot_index in ((1,) if container_size == "20" else (0, 1)):
                        self.assertIs(yard.getStack("A", 0, slot_index).getContainer(0), kept)

    def test_distinct_duplicate_records_are_each_reported_and_import_continues(self):
        records = [self.record,
                   self.record | {"slot_no": "4"},
                   self.record | {"row_no": "2"},
                   self.record | {"container_id": "VALID", "slot_no": "4"}]
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
        duplicate = Container(**(self.record | {"slot_no": "4"}))
        before = self.snapshot(yard)
        for _ in range(2):
            yard.addContainerInput(duplicate)
        self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(), [duplicate])
        self.assertEqual(self.snapshot(yard), before)

    def test_incomplete_inbound_is_classified_before_duplicate_id(self):
        yard = self.make_yard([self.record])
        inbound = self.inbound_container(container_size="45")
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
                    output.assert_any_call("C", ("BR", "A", "2", "1", "1"),
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

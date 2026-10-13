import unittest

from entities import Container, Yard


class ContainerImportProtectionTests(unittest.TestCase):
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

    def make_yard(self, records=(), removed=()):
        return Yard([self.block], containers_input=list(records),
                    removed_slots_input=list(removed))

    def snapshot(self, yard):
        return (
            dict(yard.containers),
            tuple((container, container.getCoordsStrTuple())
                  for container in yard.containers.values()),
            tuple((stack.getMode(), stack.getMaxTier(),
                   tuple(stack.getContainers()))
                  for row_stacks in yard.getBlockByID("A").getSlots()
                  for stack in row_stacks),
        )

    def assert_invalid_without_changes(self, yard, record):
        container = Container(**record)
        before = self.snapshot(yard)
        invalid_before = yard.bad_data.getTotalContainerCoordsInvalid()
        yard.addContainerInput(container)
        self.assertEqual(self.snapshot(yard), before)
        self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(),
                         invalid_before + 1)
        self.assertIs(yard.bad_data.getContainerCoordsInvalid()[-1], container)
        self.assertEqual(yard.bad_data.getTotalOverlapping(), 0)

    def test_invalid_coordinate_values_do_not_wrap_or_change_stacks(self):
        for container_size in ("20", "40"):
            for field, upper in (("row_no", "3"), ("slot_no", "5"), ("tier_no", "4")):
                for value in ("0", "-1", "-100", upper, "abc", "1.5"):
                    with self.subTest(container_size=container_size, field=field, value=value):
                        yard = self.make_yard([self.record | {"container_id": "OLD"}])
                        self.assert_invalid_without_changes(
                            yard, self.record | {"container_size": container_size, field: value})

    def test_unknown_branch_or_block_is_reported(self):
        for field in ("branch_id", "block_code"):
            with self.subTest(field=field):
                self.assert_invalid_without_changes(
                    self.make_yard(), self.record | {field: "UNKNOWN"})

    def test_valid_coordinate_boundaries_and_floating_imports_remain_supported(self):
        for container_size, slots in (("20", ("1", "4")), ("40", ("2", "4"))):
            for row_no in ("1", "2"):
                for slot_no in slots:
                    for tier_no in ("1", "3"):
                        with self.subTest(container_size=container_size, row_no=row_no, slot_no=slot_no, tier_no=tier_no):
                            record = self.record | dict(
                                container_size=container_size, row_no=row_no, slot_no=slot_no, tier_no=tier_no)
                            yard = self.make_yard([record])
                            container = yard.containers["C"]
                            footprint = (int(slot_no) - 1,) if container_size == "20" else (
                                int(slot_no) - 2, int(slot_no) - 1)
                            for index in footprint:
                                self.assertIs(yard.getStack("A", int(row_no) - 1, index)
                                              .getContainer(int(tier_no) - 1), container)
                            self.assertEqual(len(yard.containers), 1)
                            self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
                            self.assertEqual(yard.bad_data.getTotalAnomalousStacks(),
                                             len(footprint) if tier_no == "3" else 0)

    def test_removed_anchor_or_partner_leaves_entire_footprint_unchanged(self):
        for container_size, removed_slot in (("20", 1), ("40", 1), ("40", 0)):
            with self.subTest(container_size=container_size, removed_slot=removed_slot):
                yard = self.make_yard(removed=[("A", 0, removed_slot)])
                self.assert_invalid_without_changes(
                    yard, self.record | {"container_size": container_size})

    def test_forty_foot_odd_one_based_anchors_are_rejected(self):
        for slot_no in ("1", "3"):
            with self.subTest(slot_no=slot_no):
                self.assert_invalid_without_changes(
                    self.make_yard(), self.record | {"container_size": "40", "slot_no": slot_no})

    def test_forty_foot_rejects_twenty_foot_in_either_slot(self):
        for occupied_slot in ("1", "2"):
            for existing_tier, incoming_tier in (("1", "1"), ("1", "2"), ("2", "3")):
                with self.subTest(slot_index=occupied_slot, existing_tier=existing_tier,
                                  incoming_tier=incoming_tier):
                    yard = self.make_yard([self.record | dict(
                        container_id="OLD", slot_no=occupied_slot, tier_no=existing_tier)])
                    self.assert_invalid_without_changes(yard, self.record | dict(
                        container_size="40", tier_no=incoming_tier))

    def test_twenty_foot_rejects_floating_forty_foot_contents(self):
        yard = self.make_yard([self.record | dict(
            container_id="OLD", container_size="40", tier_no="2")])
        self.assert_invalid_without_changes(yard, self.record | {"tier_no": "1"})

    def test_twenty_foot_overlap_uses_timestamp_and_reports_both_records(self):
        for time, incoming_wins in (("09:00", False), ("10:00", True), ("11:00", True)):
            with self.subTest(time=time):
                yard = self.make_yard([self.record | {"container_id": "OLD"}])
                existing = yard.containers["OLD"]
                incoming = Container(**(self.record | dict(
                    container_id="NEW", move_time="01/01/2026 " + time)))
                yard.addContainerInput(incoming)
                winner = incoming if incoming_wins else existing
                self.assertEqual(yard.containers, {winner.getId(): winner})
                self.assertIs(yard.getStack("A", 0, 1).getContainer(0), winner)
                self.assertEqual(yard.bad_data.getOverlappingContainers(), {
                    incoming.getCoordsStrTuple(): {existing, incoming}})
                self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
                self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 0)

    def test_forty_foot_overlap_preserves_existing_pair_even_when_incoming_is_newer(self):
        yard = self.make_yard([self.record | dict(container_id="OLD", container_size="40")])
        existing = yard.containers["OLD"]
        before = self.snapshot(yard)
        incoming = Container(**(self.record | dict(
            container_size="40", move_time="01/01/2026 11:00")))
        yard.addContainerInput(incoming)
        self.assertEqual(self.snapshot(yard), before)
        self.assertEqual(yard.bad_data.getOverlappingContainers(), {
            incoming.getCoordsStrTuple(): {existing, incoming}})

    def test_partial_forty_foot_overlap_does_not_read_empty_anchor_or_fill_gaps(self):
        for empty_slot in (0, 1):
            with self.subTest(empty_slot=empty_slot):
                yard = self.make_yard([self.record | dict(container_id="OLD", container_size="40")])
                existing = yard.containers["OLD"]
                # Simulate inconsistent imported state with one occupied half.
                yard.getStack("A", 0, empty_slot).removeContainer(0)
                before = self.snapshot(yard)
                incoming = Container(**(self.record | {"container_size": "40"}))
                yard.addContainerInput(incoming)
                self.assertEqual(self.snapshot(yard), before)
                self.assertEqual(yard.bad_data.getOverlappingContainers(), {
                    incoming.getCoordsStrTuple(): {existing, incoming}})

    def test_duplicate_id_at_another_location_preserves_registry_and_stacks(self):
        for container_size in ("20", "40"):
            for field, value in (("row_no", "2"), ("slot_no", "4"), ("tier_no", "2")):
                with self.subTest(container_size=container_size, field=field):
                    record = self.record | {"container_size": container_size}
                    yard = self.make_yard([record])
                    before = self.snapshot(yard)
                    incoming = Container(**(record | {
                        field: value, "move_time": "01/01/2026 11:00"}))
                    yard.addContainerInput(incoming)
                    self.assertEqual(self.snapshot(yard), before)
                    self.assertEqual(yard.bad_data.getDuplicateExistingContainerIDs(),
                                     [incoming])
                    self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
                    self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)

    def test_constructor_continues_after_rejections_without_changing_input_records(self):
        records = [
            self.record | dict(container_id="OLD", slot_no="1"),
            self.record | dict(container_id="BAD_COORD", row_no="0"),
            self.record | dict(container_id="BAD_PAIR", container_size="40"),
            self.record | dict(container_id="OLD", slot_no="3"),
            self.record | dict(container_id="VALID", slot_no="4"),
        ]
        originals = [record.copy() for record in records]
        yard = self.make_yard(records)
        self.assertEqual(records, originals)
        self.assertEqual(set(yard.containers), {"OLD", "VALID"})
        self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 2)
        self.assertEqual(yard.bad_data.getTotalDuplicateExistingContainerIDs(), 1)
        self.assertEqual(yard.bad_data.getTotalContainers(), 5)
        self.assertEqual(yard.getStack("A", 0, 1).occupancy(), 0)
        self.assertEqual(yard.getStack("A", 0, 2).occupancy(), 0)


if __name__ == "__main__":
    unittest.main()

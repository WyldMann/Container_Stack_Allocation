import unittest

from entities import Container, Yard


class ContainerImportProtectionTests(unittest.TestCase):
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

    def make_yard(self, records=(), removed=()):
        return Yard([self.block], container_input=list(records),
                    removed_slots_input=list(removed))

    def snapshot(self, yard):
        return (
            dict(yard.containers),
            tuple((container, container.getCoordsStrTuple())
                  for container in yard.containers.values()),
            tuple((stack.getMode(), stack.getMaxTier(),
                   tuple(stack.getContainers()))
                  for row in yard.getBlockByID("A").getSlots()
                  for stack in row),
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
        for size in ("20", "40"):
            for field, upper in (("ROW", "3"), ("SLOT", "5"), ("TIER", "4")):
                for value in ("0", "-1", "-100", upper, "abc", "1.5"):
                    with self.subTest(size=size, field=field, value=value):
                        yard = self.make_yard([self.record | {"CONTNO": "OLD"}])
                        self.assert_invalid_without_changes(
                            yard, self.record | {"CONTSIZE": size, field: value})

    def test_unknown_branch_or_block_is_reported(self):
        for field in ("BRANCH", "BLOK"):
            with self.subTest(field=field):
                self.assert_invalid_without_changes(
                    self.make_yard(), self.record | {field: "UNKNOWN"})

    def test_valid_coordinate_boundaries_and_floating_imports_remain_supported(self):
        for size, slots in (("20", ("1", "4")), ("40", ("2", "4"))):
            for row in ("1", "2"):
                for slot in slots:
                    for tier in ("1", "3"):
                        with self.subTest(size=size, row=row, slot=slot, tier=tier):
                            record = self.record | dict(
                                CONTSIZE=size, ROW=row, SLOT=slot, TIER=tier)
                            yard = self.make_yard([record])
                            container = yard.containers["C"]
                            footprint = (int(slot) - 1,) if size == "20" else (
                                int(slot) - 2, int(slot) - 1)
                            for index in footprint:
                                self.assertIs(yard.getStack("A", int(row) - 1, index)
                                              .getContainer(int(tier) - 1), container)
                            self.assertEqual(len(yard.containers), 1)
                            self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)
                            self.assertEqual(yard.bad_data.getTotalAnomalousStacks(),
                                             len(footprint) if tier == "3" else 0)

    def test_removed_anchor_or_partner_leaves_entire_footprint_unchanged(self):
        for size, removed_slot in (("20", 1), ("40", 1), ("40", 0)):
            with self.subTest(size=size, removed_slot=removed_slot):
                yard = self.make_yard(removed=[("A", 0, removed_slot)])
                self.assert_invalid_without_changes(
                    yard, self.record | {"CONTSIZE": size})

    def test_forty_foot_odd_one_based_anchors_are_rejected(self):
        for slot in ("1", "3"):
            with self.subTest(slot=slot):
                self.assert_invalid_without_changes(
                    self.make_yard(), self.record | {"CONTSIZE": "40", "SLOT": slot})

    def test_forty_foot_rejects_twenty_foot_in_either_slot(self):
        for occupied_slot in ("1", "2"):
            for existing_tier, incoming_tier in (("1", "1"), ("1", "2"), ("2", "3")):
                with self.subTest(slot=occupied_slot, existing_tier=existing_tier,
                                  incoming_tier=incoming_tier):
                    yard = self.make_yard([self.record | dict(
                        CONTNO="OLD", SLOT=occupied_slot, TIER=existing_tier)])
                    self.assert_invalid_without_changes(yard, self.record | dict(
                        CONTSIZE="40", TIER=incoming_tier))

    def test_twenty_foot_rejects_floating_forty_foot_contents(self):
        yard = self.make_yard([self.record | dict(
            CONTNO="OLD", CONTSIZE="40", TIER="2")])
        self.assert_invalid_without_changes(yard, self.record | {"TIER": "1"})

    def test_twenty_foot_overlap_uses_timestamp_and_reports_both_records(self):
        for time, incoming_wins in (("09:00", False), ("10:00", True), ("11:00", True)):
            for incoming_id in ("OLD", "NEW"):
                with self.subTest(time=time, incoming_id=incoming_id):
                    yard = self.make_yard([self.record | {"CONTNO": "OLD"}])
                    existing = yard.containers["OLD"]
                    incoming = Container(**(self.record | dict(
                        CONTNO=incoming_id, MOVE_TIME="01/01/2026 " + time)))
                    yard.addContainerInput(incoming)
                    winner = incoming if incoming_wins else existing
                    self.assertEqual(yard.containers, {winner.getId(): winner})
                    self.assertIs(yard.getStack("A", 0, 1).getContainer(0), winner)
                    self.assertEqual(yard.bad_data.getOverlappingContainers(), {
                        incoming.getCoordsStrTuple(): {existing, incoming}})
                    self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 0)

    def test_forty_foot_overlap_preserves_existing_pair_even_when_incoming_is_newer(self):
        yard = self.make_yard([self.record | dict(CONTNO="OLD", CONTSIZE="40")])
        existing = yard.containers["OLD"]
        before = self.snapshot(yard)
        incoming = Container(**(self.record | dict(
            CONTSIZE="40", MOVE_TIME="01/01/2026 11:00")))
        yard.addContainerInput(incoming)
        self.assertEqual(self.snapshot(yard), before)
        self.assertEqual(yard.bad_data.getOverlappingContainers(), {
            incoming.getCoordsStrTuple(): {existing, incoming}})

    def test_partial_forty_foot_overlap_does_not_read_empty_anchor_or_fill_gaps(self):
        for empty_slot in (0, 1):
            with self.subTest(empty_slot=empty_slot):
                yard = self.make_yard([self.record | dict(CONTNO="OLD", CONTSIZE="40")])
                existing = yard.containers["OLD"]
                # Simulate inconsistent imported state with one occupied half.
                yard.getStack("A", 0, empty_slot).removeContainer(0)
                before = self.snapshot(yard)
                incoming = Container(**(self.record | {"CONTSIZE": "40"}))
                yard.addContainerInput(incoming)
                self.assertEqual(self.snapshot(yard), before)
                self.assertEqual(yard.bad_data.getOverlappingContainers(), {
                    incoming.getCoordsStrTuple(): {existing, incoming}})

    def test_duplicate_id_at_another_location_preserves_registry_and_stacks(self):
        for size in ("20", "40"):
            for field, value in (("ROW", "2"), ("SLOT", "4"), ("TIER", "2")):
                with self.subTest(size=size, field=field):
                    record = self.record | {"CONTSIZE": size}
                    yard = self.make_yard([record])
                    self.assert_invalid_without_changes(yard, record | {
                        field: value, "MOVE_TIME": "01/01/2026 11:00"})

    def test_constructor_continues_after_rejections_without_changing_input_records(self):
        records = [
            self.record | dict(CONTNO="OLD", SLOT="1"),
            self.record | dict(CONTNO="BAD_COORD", ROW="0"),
            self.record | dict(CONTNO="BAD_PAIR", CONTSIZE="40"),
            self.record | dict(CONTNO="OLD", SLOT="3"),
            self.record | dict(CONTNO="VALID", SLOT="4"),
        ]
        originals = [record.copy() for record in records]
        yard = self.make_yard(records)
        self.assertEqual(records, originals)
        self.assertEqual(set(yard.containers), {"OLD", "VALID"})
        self.assertEqual(yard.bad_data.getTotalContainerCoordsInvalid(), 3)
        self.assertEqual(yard.bad_data.getTotalContainers(), 5)
        self.assertEqual(yard.getStack("A", 0, 1).occupancy(), 0)
        self.assertEqual(yard.getStack("A", 0, 2).occupancy(), 0)


if __name__ == "__main__":
    unittest.main()

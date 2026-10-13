import unittest
from unittest.mock import Mock, call

from entities import Container, IncompleteContainers
from entities.yard import Yard
from presenter import BadDataPresenter


class ContainerInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.block = dict(
            BRANCH_ID="BR", BLOCK_ID="A", BLOCK_CODE="A",
            SLOT_COUNT="2", ROW_COUNT="1", MAX_TIER="3",
            POS_X="0", POS_Y="0",
        )
        self.record = dict(
            CONTNO="C", PRINCIPAL="", DMG_FLAG="", FULLMT="",
            CONTSIZE="20", CONT_GRADE="", POL="", POD="", VESSEL="",
            VOYAGE="", WEIGHT="", MOVE_TIME="",
            BRANCH="BR", BLOK="A", ROW="1", SLOT="2", TIER="1",
        )

    def assert_rejected(self, record):
        original = record.copy()
        yard = Yard([self.block], container_input=[record])
        self.assertEqual(record, original)
        self.assertTrue(yard.bad_data.anyBadData())
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertEqual(yard.bad_data.getTotalContainers(), 1)
        self.assertEqual(yard.containers, {})
        for slot in range(2):
            stack = yard.getStack("A", 0, slot)
            self.assertEqual(stack.occupancy(), 0)
            self.assertEqual(stack.getMode(), "0")
        return yard

    def test_invalid_sizes_are_reported_without_affecting_stacks(self):
        for size in ("", None, " ", "45", "20 ", 20, 40):
            with self.subTest(size=size):
                self.assert_rejected(self.record | {"CONTSIZE": size})

    def test_absent_size_is_reported_without_changing_input(self):
        del self.record["CONTSIZE"]
        self.assert_rejected(self.record)

    def test_valid_sizes_load_with_correct_footprint(self):
        for size in ("20", "40"):
            with self.subTest(size=size):
                yard = Yard([self.block], container_input=[
                    self.record | {"CONTSIZE": size}
                ])
                self.assertFalse(yard.bad_data.anyBadData())
                container = yard.containers["C"]
                self.assertIs(yard.getStack("A", 0, 1).getContainer(0), container)
                partner = yard.getStack("A", 0, 0)
                if size == "40":
                    self.assertIs(partner.getContainer(0), container)
                    self.assertEqual(partner.getMode(), "40")
                else:
                    self.assertEqual(partner.occupancy(), 0)
                self.assertEqual(yard.getStack("A", 0, 1).getMode(), size)

    def test_missing_id_or_coordinates_remain_incomplete(self):
        for field in ("CONTNO", "BRANCH", "BLOK", "ROW", "SLOT", "TIER"):
            with self.subTest(field=field):
                self.assert_rejected(self.record | {field: ""})

    def test_incomplete_report_displays_rejected_size(self):
        yard = self.assert_rejected(self.record | {"CONTSIZE": "45"})
        output = Mock()
        BadDataPresenter(out=output).print(yard.bad_data)
        output.assert_any_call(
            "C", ["BR", "A", "1", "2", "1"], "CONTSIZE:", "'45'"
        )

    def test_completeness_check_does_not_record_or_modify_container(self):
        collection = IncompleteContainers()
        container = Container(**(self.record | {"CONTSIZE": "45"}))
        original_coords = container.getCoordsStrTuple()

        self.assertFalse(collection.isExistingComplete(container))
        self.assertFalse(collection.isExistingComplete(container))

        self.assertEqual(collection.containers, [])
        self.assertEqual(container.getCoordsStrTuple(), original_coords)
        self.assertEqual(container.getContSize(), "45")

    def test_validation_records_rejections_and_leaves_complete_inputs_out(self):
        collection = IncompleteContainers()
        incomplete = Container(**(self.record | {"CONTSIZE": "45"}))
        complete = Container(**self.record)

        self.assertFalse(collection)
        self.assertFalse(collection.validateExistingAndRecord(incomplete))
        self.assertTrue(collection.validateExistingAndRecord(complete))

        self.assertTrue(collection)
        self.assertEqual(len(collection), 1)
        self.assertIs(collection.containers[0], incomplete)

    def test_incomplete_collections_are_independent_between_yards(self):
        rejected_yard = self.assert_rejected(
            self.record | {"CONTSIZE": "45"}
        )
        clean_yard = Yard([self.block], container_input=[self.record])

        self.assertIsNot(
            rejected_yard.bad_data.incompleteExistingContainer.containers,
            clean_yard.bad_data.incompleteExistingContainer.containers,
        )
        self.assertEqual(rejected_yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertEqual(clean_yard.bad_data.getIncompleteExistingContainers(), [])
        self.assertFalse(clean_yard.bad_data.anyBadData())

    def test_existing_incomplete_helpers_use_the_dataclass_collection(self):
        yard = Yard([self.block])
        container = Container(**(self.record | {"CONTSIZE": "45"}))

        yard.bad_data.addIncompleteExistingContainer(container)

        self.assertIs(
            yard.bad_data.getIncompleteExistingContainers(),
            yard.bad_data.incompleteExistingContainer.containers,
        )
        self.assertIs(yard.bad_data.getIncompleteExistingContainers()[0], container)
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertTrue(yard.bad_data.anyBadData())

    def test_inbound_can_be_complete_without_coordinates(self):
        for size in ("20", "40"):
            with self.subTest(size=size):
                record = {
                    key: value
                    for key, value in self.record.items()
                    if key not in ("BRANCH", "BLOK", "ROW", "SLOT", "TIER")
                } | {"CONTSIZE": size}
                container = Container(**record)
                collection = IncompleteContainers()

                self.assertTrue(collection.isInboundComplete(container))
                self.assertFalse(collection.isExistingComplete(container))
                self.assertTrue(collection.validateInboundAndRecord(container))
                self.assertFalse(collection)
                self.assertEqual(container.getCoordsStr(), [""] * 5)

                self.assertFalse(collection.validateExistingAndRecord(container))
                self.assertIs(collection.containers[0], container)

    def test_incomplete_inbound_is_recorded(self):
        for changes in ({"CONTNO": ""}, {"CONTSIZE": "45"}):
            with self.subTest(changes=changes):
                container = Container(**(self.record | changes))
                collection = IncompleteContainers()

                self.assertFalse(
                    collection.validateInboundAndRecord(container)
                )
                self.assertEqual(len(collection), 1)
                self.assertIs(collection.containers[0], container)

    def test_inbound_helpers_keep_existing_and_inbound_errors_separate(self):
        yard = self.assert_rejected(self.record | {"CONTSIZE": "45"})
        inbound = Container(**(self.record | {
            "CONTNO": "INBOUND", "CONTSIZE": "45",
        }))

        yard.bad_data.addIncompleteInboundContainer(inbound)

        self.assertIs(
            yard.bad_data.getIncompleteInboundContainers(),
            yard.bad_data.incompleteInboundContainer.containers,
        )
        self.assertIs(yard.bad_data.getIncompleteInboundContainers()[0], inbound)
        self.assertEqual(yard.bad_data.getTotalIncompleteInbound(), 1)
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertIsNot(
            yard.bad_data.getIncompleteExistingContainers(),
            yard.bad_data.getIncompleteInboundContainers(),
        )

        clean_yard = Yard([self.block])
        self.assertEqual(clean_yard.bad_data.getIncompleteInboundContainers(), [])
        self.assertEqual(clean_yard.bad_data.getIncompleteExistingContainers(), [])
        self.assertFalse(clean_yard.bad_data.anyBadData())

    def test_inbound_only_errors_are_presented_without_coordinates(self):
        yard = Yard([self.block])
        record = {
            key: value
            for key, value in self.record.items()
            if key not in ("BRANCH", "BLOK", "ROW", "SLOT", "TIER")
        } | {"CONTNO": "INBOUND", "CONTSIZE": "45"}
        inbound = Container(**record)

        self.assertFalse(
            yard.bad_data.incompleteInboundContainer.validateInboundAndRecord(inbound)
        )
        self.assertTrue(yard.bad_data.anyBadData())
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 0)

        output = Mock()
        presenter = BadDataPresenter(out=output)
        presenter.print(yard.bad_data)
        output.assert_any_call("\nIncomplete Inbound Containers:")
        output.assert_any_call("INBOUND", "CONTSIZE:", "'45'")
        self.assertNotIn(
            call("\nIncomplete Existing Containers:"),
            output.call_args_list,
        )
        self.assertNotIn(call("No Bad Data"), output.call_args_list)

        presenter.printStats(yard.bad_data)
        output.assert_any_call("Incomplete Existing Containers:", 0)
        output.assert_any_call("\nIncomplete Inbound Containers:", 1)

    def test_presenter_labels_existing_and_inbound_errors_and_counts(self):
        yard = self.assert_rejected(self.record | {"CONTSIZE": "45"})
        inbound = Container(**(self.record | {
            "CONTNO": "INBOUND", "CONTSIZE": "45",
        }))
        yard.bad_data.addIncompleteInboundContainer(inbound)

        output = Mock()
        presenter = BadDataPresenter(out=output)
        presenter.print(yard.bad_data)
        presenter.printStats(yard.bad_data)

        output.assert_any_call("\nIncomplete Existing Containers:")
        output.assert_any_call(
            "C", ["BR", "A", "1", "2", "1"], "CONTSIZE:", "'45'"
        )
        output.assert_any_call("\nIncomplete Inbound Containers:")
        output.assert_any_call("INBOUND", "CONTSIZE:", "'45'")
        output.assert_any_call("\nTotal Existing Containers:", 1)
        output.assert_any_call("Incomplete Existing Containers:", 1)
        output.assert_any_call("\nIncomplete Inbound Containers:", 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock, call

from entities import (
    Container,
    IncompleteExistingContainers,
    IncompleteInboundContainers,
)
from entities.yard import Yard
from presenter import BadDataPresenter


class ContainerInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.block = dict(
            branch_id="BR", block_id="A", block_code="A",
            slot_count="2", row_count="1", max_tier="3",
            pos_x="0", pos_y="0",
        )
        self.record = dict(
            container_id="C", principal="", container_condition="", container_fill="",
            container_size="20", container_grade="", pol="", pod="", vessel="",
            voyage="", weight="", move_time="",
            branch_id="BR", block_code="A", row_no="1", slot_no="2", tier_no="1",
        )

    def assert_rejected(self, record):
        original = record.copy()
        yard = Yard([self.block], containers_input=[record])
        self.assertEqual(record, original)
        self.assertTrue(yard.bad_data.anyBadData())
        self.assertIsInstance(
            yard.bad_data.incomplete_existing_container,
            IncompleteExistingContainers,
        )
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertEqual(yard.bad_data.getTotalContainers(), 1)
        self.assertEqual(yard.containers, {})
        for slot_index in range(2):
            stack = yard.getStack("A", 0, slot_index)
            self.assertEqual(stack.occupancy(), 0)
            self.assertEqual(stack.getMode(), "0")
        return yard

    def test_invalid_sizes_are_reported_without_affecting_stacks(self):
        for container_size in ("", None, " ", "45", "20 ", 20, 40):
            with self.subTest(container_size=container_size):
                self.assert_rejected(self.record | {"container_size": container_size})

    def test_absent_size_is_reported_without_changing_input(self):
        del self.record["container_size"]
        self.assert_rejected(self.record)

    def test_valid_sizes_load_with_correct_footprint(self):
        for container_size in ("20", "40"):
            with self.subTest(container_size=container_size):
                yard = Yard([self.block], containers_input=[
                    self.record | {"container_size": container_size}
                ])
                self.assertFalse(yard.bad_data.anyBadData())
                container = yard.containers["C"]
                self.assertIs(yard.getStack("A", 0, 1).getContainer(0), container)
                partner = yard.getStack("A", 0, 0)
                if container_size == "40":
                    self.assertIs(partner.getContainer(0), container)
                    self.assertEqual(partner.getMode(), "40")
                else:
                    self.assertEqual(partner.occupancy(), 0)
                self.assertEqual(yard.getStack("A", 0, 1).getMode(), container_size)

    def test_missing_id_or_coordinates_remain_incomplete(self):
        for field in ("container_id", "branch_id", "block_code", "row_no", "slot_no", "tier_no"):
            with self.subTest(field=field):
                self.assert_rejected(self.record | {field: ""})

    def test_incomplete_report_displays_rejected_size(self):
        yard = self.assert_rejected(self.record | {"container_size": "45"})
        output = Mock()
        BadDataPresenter(out=output).print(yard.bad_data)
        output.assert_any_call(
            "C", ("BR", "A", "2", "1", "1"), "CONTSIZE:", "'45'"
        )

    def test_completeness_check_does_not_record_or_modify_container(self):
        collection = IncompleteExistingContainers()
        container = Container(**(self.record | {"container_size": "45"}))
        original_coords = container.getCoordsStrTuple()

        self.assertFalse(collection.isExistingComplete(container))
        self.assertFalse(collection.isExistingComplete(container))

        self.assertEqual(collection.containers, [])
        self.assertEqual(container.getCoordsStrTuple(), original_coords)
        self.assertEqual(container.getContSize(), "45")

    def test_validation_records_rejections_and_leaves_complete_inputs_out(self):
        collection = IncompleteExistingContainers()
        incomplete = Container(**(self.record | {"container_size": "45"}))
        complete = Container(**self.record)

        self.assertFalse(collection)
        self.assertFalse(collection.validateExistingAndRecord(incomplete))
        self.assertTrue(collection.validateExistingAndRecord(complete))

        self.assertTrue(collection)
        self.assertEqual(len(collection), 1)
        self.assertIs(collection.containers[0], incomplete)

    def test_incomplete_collections_are_independent_between_yards(self):
        rejected_yard = self.assert_rejected(
            self.record | {"container_size": "45"}
        )
        clean_yard = Yard([self.block], containers_input=[self.record])

        self.assertIsNot(
            rejected_yard.bad_data.incomplete_existing_container.containers,
            clean_yard.bad_data.incomplete_existing_container.containers,
        )
        self.assertEqual(rejected_yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertEqual(clean_yard.bad_data.getIncompleteExistingContainers(), [])
        self.assertFalse(clean_yard.bad_data.anyBadData())

    def test_existing_incomplete_helpers_use_the_dataclass_collection(self):
        yard = Yard([self.block])
        container = Container(**(self.record | {"container_size": "45"}))

        yard.bad_data.addIncompleteExistingContainer(container)

        self.assertIs(
            yard.bad_data.getIncompleteExistingContainers(),
            yard.bad_data.incomplete_existing_container.containers,
        )
        self.assertIs(yard.bad_data.getIncompleteExistingContainers()[0], container)
        self.assertEqual(yard.bad_data.getTotalIncompleteExisting(), 1)
        self.assertTrue(yard.bad_data.anyBadData())

    def test_inbound_can_be_complete_without_coordinates(self):
        for container_size in ("20", "40"):
            with self.subTest(container_size=container_size):
                record = {
                    key: value
                    for key, value in self.record.items()
                    if key not in ("branch_id", "block_code", "row_no", "slot_no", "tier_no")
                } | {"container_size": container_size}
                container = Container(**record)
                inbound = IncompleteInboundContainers()
                existing = IncompleteExistingContainers()

                self.assertTrue(inbound.isInboundComplete(container))
                self.assertTrue(inbound.validateInboundAndRecord(container))
                self.assertFalse(inbound)
                self.assertEqual(container.getCoordsStr(), [""] * 5)

                self.assertFalse(existing.isExistingComplete(container))
                self.assertFalse(existing.validateExistingAndRecord(container))
                self.assertIs(existing.containers[0], container)

    def test_incomplete_inbound_is_recorded(self):
        for changes in ({"container_id": ""}, {"container_size": "45"}):
            with self.subTest(changes=changes):
                container = Container(**(self.record | changes))
                collection = IncompleteInboundContainers()

                self.assertFalse(
                    collection.validateInboundAndRecord(container)
                )
                self.assertEqual(len(collection), 1)
                self.assertIs(collection.containers[0], container)

    def test_inbound_helpers_keep_existing_and_inbound_errors_separate(self):
        yard = self.assert_rejected(self.record | {"container_size": "45"})
        self.assertIsInstance(
            yard.bad_data.incomplete_inbound_container,
            IncompleteInboundContainers,
        )
        inbound = Container(**(self.record | {
            "container_id": "INBOUND", "container_size": "45",
        }))

        yard.bad_data.addIncompleteInboundContainer(inbound)

        self.assertIs(
            yard.bad_data.getIncompleteInboundContainers(),
            yard.bad_data.incomplete_inbound_container.containers,
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
            if key not in ("branch_id", "block_code", "row_no", "slot_no", "tier_no")
        } | {"container_id": "INBOUND", "container_size": "45"}
        inbound = Container(**record)

        self.assertFalse(
            yard.bad_data.incomplete_inbound_container.validateInboundAndRecord(inbound)
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
        yard = self.assert_rejected(self.record | {"container_size": "45"})
        inbound = Container(**(self.record | {
            "container_id": "INBOUND", "container_size": "45",
        }))
        yard.bad_data.addIncompleteInboundContainer(inbound)

        output = Mock()
        presenter = BadDataPresenter(out=output)
        presenter.print(yard.bad_data)
        presenter.printStats(yard.bad_data)

        output.assert_any_call("\nIncomplete Existing Containers:")
        output.assert_any_call(
            "C", ("BR", "A", "2", "1", "1"), "CONTSIZE:", "'45'"
        )
        output.assert_any_call("\nIncomplete Inbound Containers:")
        output.assert_any_call("INBOUND", "CONTSIZE:", "'45'")
        output.assert_any_call("\nTotal Existing Containers:", 1)
        output.assert_any_call("Incomplete Existing Containers:", 1)
        output.assert_any_call("\nIncomplete Inbound Containers:", 1)


if __name__ == "__main__":
    unittest.main()

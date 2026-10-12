import unittest
from unittest.mock import Mock

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
        self.assertEqual(yard.bad_data.getTotalIncomplete(), 1)
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


if __name__ == "__main__":
    unittest.main()

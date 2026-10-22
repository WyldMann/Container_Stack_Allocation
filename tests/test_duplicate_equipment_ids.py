import unittest

from entities import Yard
from entities.equipment import Loader, RTG


class DuplicateEquipmentIDTests(unittest.TestCase):
    def make_yard(self, **inputs):
        return Yard(
            yard_blocks_input=[
                dict(branch_id="BR", block_id=block_id, block_code=block_id,
                     slot_count="3", row_count="2", max_tier="3",
                     pos_x="0", pos_y="0")
                for block_id in ("A", "B")
            ],
            **inputs,
        )

    def test_duplicates_warn_and_keep_first_equipment_for_both_types(self):
        for first_type in ("LOADER", "RTG"):
            for duplicate_type in ("LOADER", "RTG"):
                with self.subTest(first=first_type, duplicate=duplicate_type):
                    with self.assertWarnsRegex(UserWarning, "Duplicate equipment ID 'E'"):
                        yard = self.make_yard(
                            equipment_input=[
                                dict(equipment_code="E", equipment_type=first_type),
                                dict(equipment_code="E", equipment_type=duplicate_type),
                                dict(equipment_code="NEXT", equipment_type="LOADER"),
                            ],
                            equipment_locations_input={
                                "E": ("BR", "A", 0, 0),
                                "NEXT": ("BR", "B", 1, 2),
                            },
                        )

                    block = yard.getBlockByID("A")
                    if first_type == "RTG":
                        self.assertIsInstance(block.getRTG(), RTG)
                        self.assertEqual(block.getRTG().getCode(), "E")
                        self.assertEqual(block.getLoaders(), [])
                        self.assertEqual(len(yard.master_loaders), 1)
                    else:
                        self.assertIsNone(block.getRTG())
                        self.assertEqual(len(block.getLoaders()), 1)
                        self.assertIsInstance(block.getLoaders()[0], Loader)
                        self.assertEqual(block.getLoaders()[0].getCode(), "E")
                        self.assertEqual(len(yard.master_loaders), 2)
                    self.assertEqual(
                        yard.getBlockByID("B").getLoaders()[0].getCode(), "NEXT"
                    )

    def test_later_import_preserves_existing_equipment_and_its_location(self):
        for equipment_type in ("LOADER", "RTG"):
            with self.subTest(equipment_type=equipment_type):
                record = dict(equipment_code="E", equipment_type=equipment_type)
                yard = self.make_yard(
                    equipment_input=[record],
                    equipment_locations_input={"E": ("BR", "A", 0, 0)},
                )
                source = yard.getBlockByID("A")
                original = (source.getRTG() if equipment_type == "RTG"
                            else source.getLoaders()[0])

                with self.assertWarnsRegex(UserWarning, "Duplicate equipment ID 'E'"):
                    yard.inputEquipment([record], {"E": ("BR", "B", 1, 2)})

                self.assertEqual(original.getCoords(), ("A", 0, 0))
                if equipment_type == "RTG":
                    self.assertIs(source.getRTG(), original)
                    self.assertEqual(yard.master_loaders, [])
                else:
                    self.assertEqual(source.getLoaders(), [original])
                    self.assertEqual(yard.master_loaders, [original])
                self.assertIsNone(yard.getBlockByID("B").getRTG())
                self.assertEqual(yard.getBlockByID("B").getLoaders(), [])

    def test_skipped_equipment_does_not_reserve_its_id(self):
        record = dict(equipment_code="E", equipment_type="LOADER")
        yard = self.make_yard(equipment_input=[record])

        yard.inputEquipment([record], {"E": ("BR", "A", 0, 0)})

        loader, = yard.master_loaders
        self.assertEqual(loader.getCode(), "E")
        self.assertEqual(yard.getBlockByID("A").getLoaders(), [loader])


if __name__ == "__main__":
    unittest.main()

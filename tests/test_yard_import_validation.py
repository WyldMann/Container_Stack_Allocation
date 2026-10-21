from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call

from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping
from entities import Yard
from entities.bad_yard_data import BadYardData, ImportIssue
from repository import CSVLoader
from repository import RemovedSlotsRepository
from presenter import BadDataPresenter


class YardImportValidationTests(unittest.TestCase):
    def setUp(self):
        self.block = dict(
            block_id="A", branch_id="BR", block_code="A",
            row_count="2", slot_count="2", max_tier="3",
            pos_x="0", pos_y="0",
        )
        self.parameter = dict(
            parameter_id="P", parameter_name="First",
            principal="", principal_score="",
            container_condition="", container_condition_score="",
            container_fill="", container_fill_score="",
            container_size="", container_size_score="",
            container_grade="", container_grade_score="",
            pol="", pod="", vessel="", voyage="",
            weight_start="", weight_end="", vessel_voyage_score="",
            weight_range_score="", route_score="",
        )

    def make_yard(self, **inputs):
        return Yard(**({"yard_blocks_input": [self.block]} | inputs))

    def test_duplicate_block_id_keeps_both_indexes_on_first_valid_block(self):
        duplicate = self.block | {"block_code": "OTHER"}
        yard = self.make_yard(yard_blocks_input=[
            self.block, duplicate,
            self.block | {"block_id": "B", "block_code": "B"},
        ])

        self.assertEqual(set(yard.blocks_by_id), {"A", "B"})
        self.assertIs(yard.getBlockByID("A"), yard.getBlockByCode("BR", "A"))
        self.assertNotIn(("BR", "OTHER"), yard.blocks_by_code)
        issue, = yard.bad_data.getImportErrors()
        self.assertEqual(issue, ImportIssue("block", duplicate, "Duplicate block ID."))

    def test_duplicate_block_code_is_rejected_within_its_branch(self):
        yard = self.make_yard(yard_blocks_input=[
            self.block,
            self.block | {"block_id": "REJECTED"},
            self.block | {"block_id": "B", "branch_id": "OTHER"},
        ])

        self.assertEqual(set(yard.blocks_by_id), {"A", "B"})
        self.assertIs(yard.getBlockByCode("BR", "A"), yard.getBlockByID("A"))
        self.assertIs(yard.getBlockByCode("OTHER", "A"), yard.getBlockByID("B"))
        self.assertEqual(yard.bad_data.getTotalImportErrors(), 1)

    def test_invalid_block_dimensions_do_not_reserve_the_id(self):
        for field in ("row_count", "slot_count", "max_tier"):
            for value in ("0", "-1", "bad", "1.5", None, True, 1.5):
                with self.subTest(field=field, value=value):
                    yard = self.make_yard(yard_blocks_input=[
                        self.block | {field: value}, self.block,
                    ])
                    self.assertEqual(len(yard.blocks_by_id), 1)
                    self.assertEqual(yard.getStack("A", 1, 1).getMaxTier(), 3)
                    issue, = yard.bad_data.getImportErrors()
                    self.assertIn(field, issue.reason)

    def test_invalid_block_identifiers_are_recorded_and_import_continues(self):
        for field in ("block_id", "branch_id", "block_code"):
            for value in ("", "  ", None, 1, []):
                with self.subTest(field=field, value=value):
                    yard = self.make_yard(yard_blocks_input=[
                        self.block | {field: value}, self.block,
                    ])
                    self.assertIs(yard.getBlockByID("A"), yard.getBlockByCode("BR", "A"))
                    self.assertEqual(yard.bad_data.getTotalImportErrors(), 1)

    def test_malformed_blocks_are_recorded_before_later_valid_definitions(self):
        missing_position = dict(self.block)
        del missing_position["pos_x"]
        for record in (None, missing_position, self.block | {"pos_y": "bad"}):
            with self.subTest(record=record):
                yard = self.make_yard(yard_blocks_input=[record, self.block])
                self.assertEqual(set(yard.blocks_by_id), {"A"})
                self.assertTrue(yard.bad_data.anyBadData())
                self.assertEqual(yard.bad_data.getTotalImportErrors(), 1)

    def test_duplicate_parameter_preserves_first_definition_and_planning(self):
        yard = self.make_yard(
            parameters_input=[
                self.parameter,
                self.parameter | {"parameter_name": "Replacement"},
            ],
            yard_planning_input={"P": [("A", 0, 0)]},
        )

        self.assertEqual(yard.parameters["P"].getName(), "First")
        self.assertEqual(yard.getStack("A", 0, 0).getParameters(), [yard.parameters["P"]])
        self.assertEqual(yard.bad_data.getImportErrors()[0].category, "parameter")

    def test_invalid_parameters_do_not_reserve_the_id(self):
        missing_name = dict(self.parameter)
        del missing_name["parameter_name"]
        invalid_records = (
            None, missing_name,
            self.parameter | {"parameter_id": " "},
            self.parameter | {"parameter_id": []},
            self.parameter | {"principal_score": "bad"},
            self.parameter | {"weight_start": "bad"},
            self.parameter | {"container_grade": None},
        )
        for record in invalid_records:
            with self.subTest(record=record):
                yard = self.make_yard(parameters_input=[record, self.parameter])
                self.assertEqual(set(yard.parameters), {"P"})
                self.assertEqual(yard.bad_data.getTotalImportErrors(), 1)

    def test_invalid_removed_slots_leave_storage_unchanged(self):
        locations = (
            ("A", -1, 0), ("A", 0, -1), ("A", 2, 0), ("A", 0, 2),
            ("UNKNOWN", 0, 0), ([], 0, 0),
            ("A", True, 0), ("A", 0, False),
            ("A", 0.5, 0), ("A", "0", 0),
            None, ("A", 0),
        )
        for location in locations:
            with self.subTest(location=location):
                yard = self.make_yard(removed_slots_input=[location, ("A", 0, 0)])
                self.assertEqual(yard.getStack("A", 0, 0).getMode(), "X")
                for row, slot in ((0, 1), (1, 0), (1, 1)):
                    self.assertEqual(yard.getStack("A", row, slot).getMode(), "0")
                issue, = yard.bad_data.getImportErrors()
                self.assertEqual(issue.category, "removed_slot")
                self.assertEqual(issue.record, location)

    def test_csv_zero_coordinates_do_not_remove_the_opposite_edge(self):
        profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "removed_slots.csv"
            path.write_text(
                "BLOCK_ID,ROW_NO,SLOT_NO\nA,0,0\nA,1,1\n",
                encoding="utf-8",
            )
            locations = RemovedSlotsRepository(
                CSVLoader(path), profiles["removed_slots"]
            ).read_tuples()
        yard = self.make_yard(removed_slots_input=locations)

        self.assertEqual(yard.getStack("A", 0, 0).getMode(), "X")
        self.assertEqual(yard.getStack("A", 1, 1).getMode(), "0")
        self.assertEqual(yard.bad_data.getImportErrors()[0].record, ("A", -1, -1))

    def test_planning_bounds_use_existing_error_collection_without_wrapping(self):
        for row, slot in ((-1, 0), (0, -1), (2, 0), (0, 2)):
            with self.subTest(row=row, slot=slot):
                yard = self.make_yard(
                    parameters_input=[self.parameter],
                    yard_planning_input={"P": [("A", row, slot), ("A", 0, 0)]},
                )
                self.assertEqual(yard.bad_data.getTotalYardPlanning(), 2)
                self.assertEqual(yard.bad_data.getYPOutOfRange(), [("P", "A", row, slot)])
                self.assertEqual(yard.bad_data.getImportErrors(), ())
                self.assertTrue(yard.bad_data.anyBadData())
                self.assertEqual(yard.getStack("A", 0, 0).getParameters(), [yard.parameters["P"]])
                self.assertEqual(yard.getStack("A", 1, 1).getParameters(), [])

    def test_malformed_planning_locations_are_recorded_and_skipped(self):
        for location in (None, ("A", 0), ("A", True, 0), ("A", 0, 1.5), ("A", 0, "1")):
            with self.subTest(location=location):
                yard = self.make_yard(
                    parameters_input=[self.parameter],
                    yard_planning_input={"P": [location, ("A", 0, 0)]},
                )
                self.assertEqual(yard.bad_data.getTotalImportErrors(), 1)
                self.assertEqual(yard.bad_data.getYPOutOfRange(), [])
                self.assertEqual(yard.getStack("A", 0, 0).getParameters(), [yard.parameters["P"]])

    def test_unknown_planning_references_are_recorded_and_valid_rows_continue(self):
        yard = self.make_yard(
            parameters_input=[self.parameter],
            yard_planning_input={
                "UNKNOWN": [("A", 0, 0)],
                "P": [("UNKNOWN", 0, 0), ("A", 0, 0)],
            },
        )

        self.assertEqual(yard.bad_data.getTotalImportErrors(), 2)
        self.assertTrue(all(issue.category == "yard_planning" for issue in yard.bad_data.getImportErrors()))
        self.assertEqual(yard.getStack("A", 0, 0).getParameters(), [yard.parameters["P"]])

    def test_references_to_rejected_definitions_are_also_recorded(self):
        yard = self.make_yard(
            yard_blocks_input=[self.block | {"row_count": "0"}, self.block | {"block_id": "B", "block_code": "B"}],
            removed_slots_input=[("A", 0, 0)],
            parameters_input=[self.parameter | {"principal_score": "bad"}, self.parameter | {"parameter_id": "Q"}],
            yard_planning_input={"P": [("B", 0, 0)], "Q": [("A", 0, 0), ("B", 0, 0)]},
        )

        self.assertEqual(set(yard.blocks_by_id), {"B"})
        self.assertEqual(set(yard.parameters), {"Q"})
        self.assertEqual(yard.bad_data.getTotalImportErrors(), 5)
        self.assertEqual(yard.getStack("B", 0, 0).getParameters(), [yard.parameters["Q"]])

    def test_validators_do_not_modify_registries_or_stacks(self):
        yard = self.make_yard(parameters_input=[self.parameter])
        bad = BadYardData(0, 0)
        by_id, by_code, parameters = {}, {}, {}
        self.assertIsNotNone(bad.validateBlockAndRecord(self.block, by_id, by_code))
        self.assertIsNotNone(bad.validateParameterAndRecord(self.parameter, parameters))
        self.assertEqual((by_id, by_code, parameters), ({}, {}, {}))

        stack = yard.getStack("A", 0, 0)
        self.assertIs(bad.validateRemovedSlotAndRecord(("A", 0, 0), yard.blocks_by_id), stack)
        self.assertEqual(bad.validateYardPlanningAndRecord("P", ("A", 0, 0), yard.parameters, yard.blocks_by_id), (yard.parameters["P"], stack))
        self.assertEqual(stack.getMode(), "0")
        self.assertEqual(stack.getParameters(), [])
        self.assertFalse(bad.anyBadData())

    def test_issues_preserve_record_snapshots_and_are_per_yard(self):
        duplicate = self.block | {"block_code": "OTHER"}
        location = ["A", -1, 0]
        inputs = dict(yard_blocks_input=[self.block, duplicate], removed_slots_input=[location])
        before = deepcopy(inputs)
        yard = self.make_yard(**inputs)

        self.assertEqual(inputs, before)
        duplicate["block_code"] = "CHANGED"
        location[1] = 0
        self.assertEqual(yard.bad_data.getImportErrors()[0].record, before["yard_blocks_input"][1])
        self.assertEqual(yard.bad_data.getImportErrors()[1].record, ["A", -1, 0])
        self.assertEqual(self.make_yard().bad_data.getImportErrors(), ())

    def test_presenter_reports_import_only_errors_and_counts(self):
        yard = self.make_yard(removed_slots_input=[("UNKNOWN", 0, 0)])
        output = Mock()
        presenter = BadDataPresenter(out=output)
        presenter.print(yard.bad_data)
        presenter.printStats(yard.bad_data)

        self.assertNotIn(call("No Bad Data"), output.call_args_list)
        output.assert_any_call("\nInvalid Import Records:")
        issue, = yard.bad_data.getImportErrors()
        output.assert_any_call(issue.category, "|", issue.reason, "|", repr(issue.record))
        output.assert_any_call("Import Validation Errors:", 1)

    def test_equipment_import_still_accepts_positions_outside_storage_grid(self):
        yard = self.make_yard(
            equipment_input=[{"equipment_code": "L", "equipment_type": "SL"}],
            equipment_locations_input={"L": ("BR", "A", -5, 20)},
        )

        loader, = yard.master_loaders
        self.assertEqual(loader.getCoords(), ("A", -5, 20))
        self.assertEqual(yard.getBlockByID("A").getLoaders(), [loader])
        self.assertFalse(yard.bad_data.anyBadData())


if __name__ == "__main__":
    unittest.main()

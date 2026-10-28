"""The same optional scope filters apply to SQL, CSV yard inputs, and output."""

import csv
import importlib.util
import itertools
import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

from config import ConfigurationError, load_input_config
from config.application.input_filters import active_filters, read_filter_columns
from filewriter import ContainerFileWriter
import main_existing
from repository import CSVLoader, InputError, load_yard_inputs
from repository.input_loader import _sql_loader
from repository.branch_repository import BranchDirectory
from config import DEFAULT_CONFIG_FILE, load_config
from entities import Yard
from tests import test_main_existing as main_tests


class InputFilterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.input_path
        self.root = self.fixture.root

    def set_filters(self, text):
        source = self.path.read_text(encoding="utf-8")
        start = source.index("[input.filters]")
        end = source.index("\n[", start + 1)
        self.path.write_text(
            source[:start] + "[input.filters]\n" + text + "\n" + source[end:], encoding="utf-8",
        )

    def settings(self):
        with patch.dict(os.environ, {
            "YARD_DB_HOST": "db.example.test", "YARD_DB_NAME": "yard_test", "YARD_DB_USER": "reader",
        }):
            return load_input_config(self.path, datasets=main_existing.EXISTING_YARD_DATASETS)

    def test_each_filter_is_independently_optional(self):
        self.fixture.set_source("terminal_branches", "sql")
        names = ("terminal_id", "branch_id")
        columns = ("TERMINAL_ID", "BRANCH_ID")
        values = (1, 2)
        for enabled in itertools.product((False, True), repeat=2):
            with self.subTest(enabled=enabled):
                self.set_filters("\n".join(
                    name + " = " + (str(value) if isinstance(value, int) else '"' + value + '"')
                    if on else name + ' = "  "'
                    for name, value, on in zip(names, values, enabled)
                ))
                settings = self.settings()
                self.assertEqual(settings["sql_datasets"]["terminal_branches"]["filters"], {
                    column: value for column, value, on in zip(columns, values, enabled) if on
                })

    def test_commented_filters_disable_scope_and_do_not_default_to_production_values(self):
        self.fixture.set_source("existing_containers", "sql")
        self.set_filters('# terminal_id = 1\n# branch_id = 2')
        settings = self.settings()
        self.assertEqual(settings["filters"], {})
        self.assertEqual(settings["sql_datasets"]["existing_containers"]["filters"], {})

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_query_applies_resolved_branch_codes(self):
        self.fixture.set_source("existing_containers", "sql")
        self.set_filters('terminal_id = 1\nbranch_id = 2')
        settings = self.settings()
        definition = settings["sql_datasets"]["existing_containers"]
        loader = _sql_loader(None, "existing_containers", definition,
                             branch_column="BRANCH", branch_codes=("JKT74",))
        self.assertEqual(loader.query.as_string(),
            'SELECT * FROM "TERMINAL_APP"."TRM_TRS_TARGET_CONTAINER" '
            'WHERE "BRANCH" = ANY(%s)')
        self.assertEqual(loader.parameters, (["JKT74"],))
        self.set_filters('terminal_id = ""\nbranch_id = ""')
        definition = self.settings()["sql_datasets"]["existing_containers"]
        loader = _sql_loader(None, "existing_containers", definition)
        self.assertNotIn("WHERE", loader.query.as_string())
        self.assertEqual(loader.parameters, ())

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_branch_reference_uses_both_id_filters(self):
        self.fixture.set_source("terminal_branches", "sql")
        definition = self.settings()["sql_datasets"]["terminal_branches"]
        loader = _sql_loader(None, "terminal_branches", definition)
        self.assertEqual(loader.query.as_string(),
            'SELECT * FROM "TERMINAL_APP"."TRM_MST_TERMINAL_BRANCH" '
            'WHERE "TERMINAL_ID" = %s AND "BRANCH_ID" = %s')
        self.assertEqual(loader.parameters, (1, 2))

    def test_zero_and_false_are_active_and_invalid_filter_types_fail(self):
        self.assertEqual(active_filters({"ZERO": 0, "FALSE": False, "EMPTY": " ", "NONE": None}),
                         {"ZERO": 0, "FALSE": False})
        self.set_filters('terminal_id = 0\nbranch_id = 0')
        self.assertEqual(self.settings()["filters"], {"terminal_id": 0, "branch_id": 0})
        for text in ('terminal_id = []', 'terminal_id = true', 'branch_id = 2.5', 'unknown = 1', 'branch = 2'):
            with self.subTest(text=text), self.assertRaises(ConfigurationError):
                self.set_filters(text)
                self.settings()

    def test_csv_filters_are_anded_and_missing_columns_fail_explicitly(self):
        path = self.root / "rows.csv"
        path.write_text("TERMINAL_ID,BRANCH\n1,2\n2,2\n1,3\n01,02\n",
                        encoding="utf-8")
        with CSVLoader(path, filters={"TERMINAL_ID": 1, "BRANCH": 2}).open() as (_, rows):
            self.assertEqual(len(list(rows)), 2)
        with CSVLoader(path, filters={"TERMINAL_ID": "", "BRANCH": " "}).open() as (_, rows):
            self.assertEqual(len(list(rows)), 4)
        with self.assertRaisesRegex(InputError, "missing filter column"):
            with CSVLoader(path, filters={"WRONG_COLUMN": 1}).open():
                pass

    def test_filter_column_mappings_cannot_silently_overwrite_each_other(self):
        with self.assertRaisesRegex(ConfigurationError, "different source column"):
            read_filter_columns({"terminal_id": "BRANCH_ID", "branch_id": "BRANCH_ID"}, "test")

    def test_csv_yard_inputs_and_container_export_use_selected_blocks(self):
        document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        files = document["csv"]["files"]
        data = {}
        headers = {}
        for name in ("terminal_branches", "yard_blocks", "existing_containers", "yard_planning", "parameters", "removed_slots", "equipment_history"):
            with Path(files[name]).open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                data[name] = list(reader)
                headers[name] = reader.fieldnames

        data["terminal_branches"] += [
            {"BRANCH_ID": "3", "TERMINAL_ID": "1", "BRANCH_CODE": "JKT75", "BRANCH_NAME": "CY 220"},
            {"BRANCH_ID": "4", "TERMINAL_ID": "2", "BRANCH_CODE": "JKT76", "BRANCH_NAME": "CY 221"},
        ]
        data["yard_blocks"] += [
            data["yard_blocks"][0] | {"BLOCK_ID": "12", "TERMINAL_ID": "1", "BRANCH_ID": "3"},
            data["yard_blocks"][0] | {"BLOCK_ID": "13", "TERMINAL_ID": "2", "BRANCH_ID": "4", "BLOCK_CODE": "D"},
        ]
        data["existing_containers"] += [
            data["existing_containers"][0] | {"CONTNO": "OTHER_BRANCH", "BRANCH": "JKT75", "BLOK": "2B"},
            data["existing_containers"][0] | {"CONTNO": "OTHER_TERMINAL", "BRANCH": "JKT76", "BLOK": "D"},
        ]
        data["yard_planning"] += [
            data["yard_planning"][0] | {"BLOCK_ID": "12", "TERMINAL_ID": "1", "BRANCH_ID": "3"},
            data["yard_planning"][0] | {"BLOCK_ID": "13", "TERMINAL_ID": "2", "BRANCH_ID": "4"},
        ]
        data["removed_slots"] += [{"BLOCK_ID": "12", "ROW_NO": "11", "SLOT_NO": "11"}]
        for row in data["equipment_history"]:
            row["BLOK"] = "2" + row["BLOK"]
        data["equipment_history"] += [
            data["equipment_history"][0] | {"ALAT": "OTHER_BRANCH_EQUIPMENT", "BRANCH": "3", "BLOK": "2B"},
            data["equipment_history"][0] | {"ALAT": "OTHER_TERMINAL_EQUIPMENT", "BRANCH": "4", "BLOK": "D"},
        ]
        for name, rows in data.items():
            destination = self.root / (name + ".csv")
            with destination.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=headers[name])
                writer.writeheader()
                writer.writerows(rows)
            source = self.path.read_text(encoding="utf-8")
            self.path.write_text(source.replace(files[name], destination.as_posix()), encoding="utf-8")

        cases = (
            ('terminal_id = 1\nbranch_id = 2', {"10", "11"}, 20),
            ('terminal_id = 1\nbranch_id = 3', {"12"}, 1),
            ('terminal_id = 2\nbranch_id = ""', {"13"}, 1),
            ('# terminal_id = 1\n# branch_id = 2', {"10", "11", "12", "13"}, 22),
        )
        for filters, expected_blocks, expected_count in cases:
            with self.subTest(filters=filters):
                self.set_filters(filters)
                inputs = load_yard_inputs(self.settings(), include_shifting=False)
                settings = load_config(DEFAULT_CONFIG_FILE)
                yard = Yard(
                    yard_blocks_input=inputs["yard_blocks"],
                    removed_slots_input=inputs["removed_slots"],
                    parameters_input=inputs["parameters"],
                    yard_planning_input=inputs["yard_planning"],
                    containers_input=inputs["existing_containers"],
                    equipment_input=inputs["master_equipment"],
                    equipment_locations_input=inputs["equipment_history"],
                    feasibility_settings=settings.feasibility, heuristic_settings=settings.heuristic,
                )
                self.assertEqual(set(yard.blocks_by_id), expected_blocks)
                self.assertEqual(len(yard.containers), expected_count)
                selected_coordinates = {(block.getBranch(), block.getCode()) for block in yard.blocks_by_id.values()}
                self.assertTrue(all(location[:2] in selected_coordinates for location in inputs["equipment_history"].values()))
                if expected_blocks == {"12"}:
                    self.assertEqual(set(inputs["equipment_history"]), {"OTHER_BRANCH_EQUIPMENT"})
                elif expected_blocks == {"13"}:
                    self.assertEqual(set(inputs["equipment_history"]), {"OTHER_TERMINAL_EQUIPMENT"})
                output = self.root / "result.csv"
                ContainerFileWriter(output, branch_codes=BranchDirectory(inputs["terminal_branches"]).codes_by_id).writeCSV(yard)
                with output.open(encoding="utf-8", newline="") as stream:
                    exported = list(csv.DictReader(stream))
                self.assertEqual({row["BRANCH"] for row in exported},
                                 {BranchDirectory(inputs["terminal_branches"]).codes_by_id[b.getBranch()]
                                  for b in yard.blocks_by_id.values()})
                self.assertEqual(len(exported), expected_count)
                self.assertEqual({row["CONTNO"] for row in exported}, set(yard.containers))


if __name__ == "__main__":
    unittest.main()

"""The same optional scope filters apply to SQL, CSV yard inputs, and output."""

import csv
import importlib.util
import itertools
import os
from pathlib import Path
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from config import ConfigurationError, load_input_config
from config.application.input_filters import active_filters, read_filter_columns
from filewriter import ContainerFileWriter
import main_existing
from repository import CSVLoader, InputError, load_yard_inputs
from repository.input_loader import _sql_loader
from repository.csvloader import BRANCH_WHITESPACE
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
                             membership_filters=(("BRANCH", ("\t jkt74  ",), "branch_code"),))
        self.assertEqual(loader.query.as_string(),
            'SELECT * FROM "TERMINAL_APP"."TRM_TRS_TARGET_CONTAINER" '
            'WHERE UPPER(BTRIM("BRANCH"::text, %s)) = ANY(%s)')
        self.assertEqual(loader.parameters, (BRANCH_WHITESPACE, ["JKT74"]))
        self.set_filters('terminal_id = ""\nbranch_id = ""')
        definition = self.settings()["sql_datasets"]["existing_containers"]
        loader = _sql_loader(None, "existing_containers", definition)
        self.assertNotIn("WHERE", loader.query.as_string())
        self.assertEqual(loader.parameters, ())

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_membership_combines_normalizations_with_filters_and_order(self):
        payload = "00ab' OR true --"
        definition = dict(schema="yard", relation="slots", filters={"ACTIVE": True},
                          order_by=["ROW_NO"])
        loader = _sql_loader(None, "removed_slots", definition, membership_filters=(
            ("BRANCH", ("\t jkt74 ",), "branch_code"),
            ('DB"BLOCK', ("0010", "000", "", payload), "id"),
        ))
        self.assertEqual(loader.query.as_string(),
            'SELECT * FROM "yard"."slots" WHERE "ACTIVE" = %s '
            'AND UPPER(BTRIM("BRANCH"::text, %s)) = ANY(%s) '
            'AND UPPER(REGEXP_REPLACE(COALESCE("DB""BLOCK"::text, \'\'), '
            "'^0+(?!$)', '')) = ANY(%s) ORDER BY \"ROW_NO\"")
        self.assertEqual(loader.parameters, (
            True, BRANCH_WHITESPACE, ["JKT74"], ["10", "0", "", "AB' OR TRUE --"],
        ))
        self.assertNotIn(payload, loader.query.as_string())

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_removed_slots_scope_uses_csv_or_sql_yard_blocks(self):
        yard_path = self.settings()["csv_files"]["yard_blocks"]
        with yard_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            yard_headers = next(reader)
            yard_rows = [tuple(row) for row in reader if row]
        self.fixture.set_source("yard_blocks", "sql")
        self.fixture.set_source("removed_slots", "sql")
        cases = (
            ('terminal_id = 1\nbranch_id = 2', False, ["10", "11"]),
            ('terminal_id = 1\nbranch_id = ""', False, ["10", "11"]),
            ('terminal_id = ""\nbranch_id = 2', False, ["10", "11"]),
            ('terminal_id = 1\nbranch_id = 2', True, []),
            ('# terminal_id = 1\n# branch_id = 2', False, None),
        )
        for source, (filters, empty, selected) in itertools.product(("csv", "sql"), cases):
            with self.subTest(source=source, filters=filters, empty=empty):
                self.set_filters(filters)
                settings = self.settings()
                settings["sources"]["yard_blocks"] = source
                block_path = self.root / "blocks.csv"
                with block_path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(yard_headers)
                    writer.writerows([] if empty else yard_rows)
                settings["csv_files"]["yard_blocks"] = block_path
                # Use a distinct SQL column to exercise the selected source's mapping.
                mapping_path = self.root / "sql_mapping.toml"
                mapping_path.write_text(
                    settings["mapping_files"]["sql"].read_text(encoding="utf-8").replace(
                        '[sql.removed_slots.columns]\nblock_id = "BLOCK_ID"',
                        '[sql.removed_slots.columns]\nblock_id = "DB_BLOCK"',
                    ), encoding="utf-8",
                )
                settings["mapping_files"]["sql"] = mapping_path
                connection = MagicMock()
                contexts = []
                if source == "sql":
                    context = MagicMock()
                    cursor = context.__enter__.return_value
                    cursor.description = [SimpleNamespace(name=name) for name in yard_headers]
                    cursor.__iter__.return_value = iter([] if empty else yard_rows)
                    contexts.append(context)
                removed_context = MagicMock()
                removed_cursor = removed_context.__enter__.return_value
                removed_cursor.description = [SimpleNamespace(name=name)
                                              for name in ("DB_BLOCK", "ROW_NO", "SLOT_NO")]
                removed_rows = [("0010", 1, 2), ("11", 2, 1)]
                if selected is None:
                    removed_rows.append(("999", 1, 1))
                elif not selected:
                    removed_rows = []
                removed_cursor.__iter__.return_value = iter(removed_rows)
                contexts.append(removed_context)
                connection.cursor.side_effect = contexts

                opened_csv = []
                original_open = CSVLoader.open

                def record_open(loader):
                    opened_csv.append(loader.file_path)
                    return original_open(loader)

                def check_scope(query, parameters):
                    if source == "csv":
                        self.assertIn(block_path, opened_csv)
                    if selected is None:
                        self.assertNotIn("WHERE", query.as_string())
                        self.assertEqual(parameters, ())
                    else:
                        self.assertIn('COALESCE("DB_BLOCK"::text', query.as_string())
                        self.assertIn("= ANY(%s)", query.as_string())
                        self.assertEqual(parameters, (selected,))

                removed_cursor.execute.side_effect = check_scope
                with patch.object(CSVLoader, "open", record_open):
                    inputs = load_yard_inputs(settings, connection=connection, include_shifting=False)
                self.assertEqual(inputs["removed_slots"], [
                    ("10" if block == "0010" else block, row - 1, slot - 1)
                    for block, row, slot in removed_rows
                ])
                self.assertEqual(connection.cursor.call_count, len(contexts))
                removed_cursor.execute.assert_called_once()
                if source == "csv":
                    self.assertEqual(opened_csv.count(block_path), 1)

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
        data["equipment_history"] += [
            data["equipment_history"][0] | {"ALAT": "OTHER_BRANCH_EQUIPMENT", "BRANCH": "JKT75", "BLOK": "2B"},
            data["equipment_history"][0] | {"ALAT": "OTHER_TERMINAL_EQUIPMENT", "BRANCH": "JKT76", "BLOK": "D"},
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

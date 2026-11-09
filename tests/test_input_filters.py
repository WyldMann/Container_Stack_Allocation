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
from config.application.input_filters import active_filters, branch_input_settings, read_filter_columns
from config.csv_import.mapping_loader import load_mapping
from filewriter import ContainerFileWriter
import shifting_report_calculation
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
        self.profiles = load_mapping(
            Path(__file__).resolve().parents[1] / "config" / "csv_mapping.toml", source="csv",
        )
        self.data = {
            "terminal_branches": [
                dict(branch_id="2", terminal_id="1", branch_code="JKT74", branch_name="CY 219 (Lini 2)"),
                dict(branch_id="3", terminal_id="1", branch_code="JKT75", branch_name="CY 220"),
                dict(branch_id="4", terminal_id="2", branch_code="JKT76", branch_name="CY 221"),
            ],
            "yard_blocks": [
                dict(block_id=block, terminal_id=terminal, branch_id=branch, block_code=code,
                     slot_count="4", row_count="2", max_tier="3", pos_x="0", pos_y="0")
                for block, terminal, branch, code in (
                    ("10", "1", "2", "B"), ("11", "1", "2", "C"),
                    ("12", "1", "3", "B"), ("13", "2", "4", "D"),
                )
            ],
            "existing_containers": [
                dict(container_id="BOX_" + code, branch_id=branch, block_code=block,
                     row_no="1", slot_no="1", tier_no="1", container_size="20")
                for code, branch, block in (("A", "JKT74", "B"), ("C", "JKT74", "C"),
                                             ("OTHER", "JKT75", "B"), ("LAST", "JKT76", "D"))
            ],
            "removed_slots": [dict(block_id=block, row_no="2", slot_no="4")
                              for block in ("10", "11", "12", "13")],
            "parameters": [],
            "yard_planning": [],
            "equipment_history": [
                dict(equipment_code="EQ_" + branch, branch_id=branch, block_code=block,
                     row_no="1", slot_no="1", move_time="2026-10-01 00:00:00")
                for branch, block in (("JKT74", "B"), ("JKT75", "B"), ("JKT76", "D"))
            ],
            "master_equipment": [],
            "inbound_containers": [],
        }
        document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        text = self.path.read_text(encoding="utf-8")
        for name, rows in self.data.items():
            path = self.write_records(name, rows)
            text = text.replace(document["csv"]["files"][name], path.as_posix())
        self.path.write_text(text, encoding="utf-8")

    def write_records(self, name, rows):
        profile = self.profiles[name]
        headers = list(dict.fromkeys([
            *(profile.columns.get(field, field) for field in profile.schema.fields),
            *profile.filter_columns.values(),
        ]))
        path = self.root / (name + ".csv")
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    profile.columns.get(field, profile.filter_columns.get(field, field)): value
                    for field, value in row.items()
                })
        return path

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
            return load_input_config(self.path, datasets=shifting_report_calculation.EXISTING_YARD_DATASETS)

    def test_branch_code_is_optional_and_normalized(self):
        for value, expected in (('"JKT74"', {"branch_code": "JKT74"}),
                                ('"  jkt74  "', {"branch_code": "JKT74"}), ('"  "', {}),
                                ('[" jkt74 ", "jkt64"]', {"branch_code": ["JKT74", "JKT64"]})):
            with self.subTest(value=value):
                self.set_filters("branch_code = " + value)
                self.assertEqual(self.settings()["filters"], expected)

    def test_array_is_expanded_without_changing_configured_selection(self):
        self.set_filters('branch_code = ["JKT74", "JKT64"]')
        settings = self.settings()
        selections = list(branch_input_settings(settings))
        self.assertEqual([selection["filters"] for selection in selections],
                         [{"branch_code": "JKT74"}, {"branch_code": "JKT64"}])
        selections[0]["filters"]["branch_code"] = "OTHER"
        self.assertEqual(settings["filters"], {"branch_code": ["JKT74", "JKT64"]})
        self.assertEqual(selections[1]["filters"], {"branch_code": "JKT64"})
        with self.assertRaisesRegex(ConfigurationError, "one branch"):
            load_yard_inputs(settings)

    def test_commented_filters_disable_scope_and_do_not_default_to_production_values(self):
        self.fixture.set_source("existing_containers", "sql")
        self.set_filters('# branch_code = "JKT74"')
        settings = self.settings()
        self.assertEqual(settings["filters"], {})
        self.assertEqual(settings["sql_datasets"]["existing_containers"]["filters"], {})

    def test_csv_reference_accepts_padded_lowercase_codes(self):
        self.data["terminal_branches"][0]["branch_code"] = " \t jkt74 "
        self.write_records("terminal_branches", self.data["terminal_branches"])
        self.set_filters('branch_code = " JkT74 "')
        inputs = load_yard_inputs(self.settings(), include_shifting=False)
        self.assertEqual(len(inputs["terminal_branches"]), 1)
        self.assertEqual({row["block_id"] for row in inputs["yard_blocks"]}, {"10", "11"})
        self.assertEqual({row["branch_id"] for row in inputs["existing_containers"]}, {"2"})

    def test_missing_branch_fails_before_loading_other_inputs(self):
        self.set_filters('branch_code = "MISSING"')
        opened = []
        original_open = CSVLoader.open

        def record_open(loader):
            opened.append(loader.file_path.name)
            return original_open(loader)

        with patch.object(CSVLoader, "open", record_open), self.assertRaisesRegex(InputError, "no branches match"):
            load_yard_inputs(self.settings(), include_shifting=False)
        self.assertEqual(opened, ["terminal_branches.csv"])

    def test_csv_parameters_and_planning_use_resolved_branch_ids(self):
        self.write_records("parameters", [
            dict(parameter_id=parameter, terminal_id=terminal, branch_id=branch)
            for parameter, terminal, branch in (("201", "1", "2"), ("301", "1", "3"), ("401", "2", "4"))
        ])
        self.write_records("yard_planning", [
            dict(parameter_id=parameter, block_id=block, terminal_id=terminal,
                 branch_id=branch, row_no="1", slot_no="1")
            for parameter, block, terminal, branch in (("201", "10", "1", "2"), ("301", "12", "1", "3"))
        ])
        inputs = load_yard_inputs(self.settings(), include_shifting=False)
        self.assertEqual({row["parameter_id"] for row in inputs["parameters"]}, {"201"})
        self.assertEqual(inputs["yard_planning"], {"201": [("10", 0, 0)]})

    def test_inbound_branch_scope_preserves_unassigned_containers(self):
        self.write_records("inbound_containers", [
            dict(container_id=container, branch_id=branch)
            for container, branch in (("SELECTED", "JKT74"), ("OTHER", "JKT75"), ("UNASSIGNED", ""))
        ])
        settings = self.settings()
        # The existing-yard report intentionally omits inbound data; exercise the full loader.
        settings["sources"]["inbound_containers"] = "csv"
        settings["csv_files"]["inbound_containers"] = self.root / "inbound_containers.csv"
        inputs = load_yard_inputs(settings, include_shifting=False)
        self.assertEqual({row["container_id"] for row in inputs["inbound_containers"]}, {"SELECTED", "UNASSIGNED"})

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_parameters_receive_resolved_ids_and_conflicts_are_rejected(self):
        self.fixture.set_source("parameters", "sql")
        settings = self.settings()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        profile = self.profiles["parameters"]
        headers = [profile.columns.get(field, field) for field in profile.schema.fields]
        cursor.description = [SimpleNamespace(name=name) for name in headers]
        cursor.__iter__.return_value = iter(())
        load_yard_inputs(settings, connection=connection, include_shifting=False)
        query, parameters = cursor.execute.call_args.args
        self.assertIn('WHERE "TERMINAL_ID" = %s AND "BRANCH_ID" = %s', query.as_string())
        self.assertEqual(parameters, (1, 2))
        settings["sql_datasets"]["parameters"]["filters"]["BRANCH_ID"] = 999
        with self.assertRaisesRegex(ConfigurationError, "Conflicting filter values.*BRANCH_ID"):
            load_yard_inputs(settings, connection=connection, include_shifting=False)

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "Query composition requires Psycopg")
    def test_sql_query_applies_resolved_branch_codes(self):
        self.fixture.set_source("existing_containers", "sql")
        self.set_filters('branch_code = "JKT74"')
        settings = self.settings()
        definition = settings["sql_datasets"]["existing_containers"]
        loader = _sql_loader(None, "existing_containers", definition,
                             membership_filters=(("BRANCH", ("\t jkt74  ",), "branch_code"),))
        self.assertEqual(loader.query.as_string(),
            'SELECT * FROM "TERMINAL_APP"."TRM_TRS_TARGET_CONTAINER" '
            'WHERE UPPER(BTRIM("BRANCH"::text, %s)) = ANY(%s)')
        self.assertEqual(loader.parameters, (BRANCH_WHITESPACE, ["JKT74"]))
        self.set_filters('branch_code = ""')
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
            ('branch_code = "JKT74"', False, ["10", "11"]),
            ('branch_code = " jkt74 "', False, ["10", "11"]),
            ('branch_code = "JKT74"', True, []),
            ('# branch_code = "JKT74"', False, None),
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
                    selected_rows = [row for row in yard_rows
                                     if selected is None or row[yard_headers.index("BRANCH_ID")] == "2"]
                    cursor.__iter__.return_value = iter([] if empty else selected_rows)
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
    def test_sql_branch_reference_uses_normalized_branch_code_and_resolves_csv_scope(self):
        self.fixture.set_source("terminal_branches", "sql")
        self.set_filters('branch_code = " jkt74 "')
        settings = self.settings()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        headers = ["BRANCH_ID", "TERMINAL_ID", "BRANCH_CODE", "BRANCH_NAME"]
        cursor.description = [SimpleNamespace(name=name) for name in headers]
        cursor.__iter__.return_value = iter([(2, 1, " jkt74 ", "CY 219 (Lini 2)")])
        inputs = load_yard_inputs(settings, connection=connection, include_shifting=False)
        query, parameters = cursor.execute.call_args.args
        self.assertEqual(query.as_string(),
            'SELECT * FROM "TERMINAL_APP"."TRM_MST_TERMINAL_BRANCH" '
            'WHERE UPPER(BTRIM("BRANCH_CODE"::text, %s)) = ANY(%s)')
        self.assertEqual(parameters, (BRANCH_WHITESPACE, ["JKT74"]))
        self.assertEqual({row["block_id"] for row in inputs["yard_blocks"]}, {"10", "11"})

    def test_zero_and_false_are_active_and_invalid_filter_types_fail(self):
        self.assertEqual(active_filters({"ZERO": 0, "FALSE": False, "EMPTY": " ", "NONE": None}),
                         {"ZERO": 0, "FALSE": False})
        for text in ('branch_code = []', 'branch_code = [" "]', 'branch_code = ["JKT74", 2]',
                     'branch_code = ["JKT74", " jkt74 "]', 'branch_code = [["JKT74"]]',
                     'branch_code = true', 'branch_code = 2.5',
                     'branch_code = 2', 'terminal_id = 1', 'branch_id = 2', 'unknown = 1', 'branch = 2'):
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
        cases = (
            ('branch_code = "JKT74"', {"10", "11"}, 2),
            ('branch_code = " jkt75 "', {"12"}, 1),
            ('branch_code = "JKT76"', {"13"}, 1),
            ('# branch_code = "JKT74"', {"10", "11", "12", "13"}, 4),
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
                    self.assertEqual(set(inputs["equipment_history"]), {"EQ_JKT75"})
                elif expected_blocks == {"13"}:
                    self.assertEqual(set(inputs["equipment_history"]), {"EQ_JKT76"})
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

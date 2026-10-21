import csv
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch

from config import (
    ConfigurationError, DEFAULT_CSV_MAPPING_FILE, DEFAULT_INPUT_CONFIG_FILE,
    load_input_config,
)
from config.application.input_config import DATASETS
from repository import load_yard_inputs
from repository.input_loader import _sql_loader


class InputConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "input.toml"
        self.template = DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8")

    def load_text(self, text):
        self.path.write_text(text, encoding="utf-8")
        return load_input_config(self.path)

    def test_relative_locations_are_based_on_config_directory(self):
        settings = self.load_text(self.template)
        base = self.path.parent
        self.assertEqual(settings["mapping_file"], base / "csv_mapping.toml")
        self.assertEqual(settings["csv_files"]["existing_containers"],
                         (base / "../data_CY219/containers.csv").resolve())
        self.assertEqual(settings["output_file"],
                         (base / "../output/result.csv").resolve())

    def test_absolute_csv_paths_are_preserved(self):
        absolute = (self.path.parent / "containers.csv").as_posix()
        settings = self.load_text(self.template.replace("../data_CY219/containers.csv", absolute))
        self.assertEqual(settings["csv_files"]["existing_containers"], Path(absolute))

    def test_invalid_source_and_incomplete_csv_are_rejected(self):
        for text in (
            self.template.replace('source = "csv"', 'source = "other"'),
            self.template.replace('existing_containers = "../data_CY219/containers.csv"', ''),
            self.template.replace('existing_containers = ', 'typo = '),
            self.template.replace('existing_containers = "../data_CY219/containers.csv"',
                                  'existing_containers = 123'),
            self.template + '\n[unknown]\nvalue = true\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_only_selected_source_requires_configuration(self):
        csv_text = self.template[:self.template.index("[sql]")]
        self.assertEqual(self.load_text(csv_text)["source"], "csv")
        sql_text = self.template.replace('source = "csv"', 'source = "sql"')
        start = sql_text.index("[csv.files]")
        end = sql_text.index("[sql]")
        settings = self.load_text(sql_text[:start] + sql_text[end:])
        self.assertEqual(settings["source"], "sql")
        self.assertNotIn("csv_files", settings)

    def test_sql_settings_schema_override_filters_and_order(self):
        text = self.template.replace('source = "csv"', 'source = "sql"')
        text = text.replace('relation = "containers"', '''relation = "containers"
schema = "operations"
filters = { BRANCH = "CY219" }
order_by = ["CONTNO"]''')
        settings = self.load_text(text)
        source = settings["sql_datasets"]["existing_containers"]
        self.assertEqual(source, dict(schema="operations", relation="containers",
                                     filters={"BRANCH": "CY219"}, order_by=["CONTNO"]))
        self.assertEqual(settings["connection"]["host"], "localhost")
        self.assertNotIn("password", settings["connection"])
        self.assertEqual(settings["sql_datasets"]["yard_blocks"]["schema"], "public")

    def test_invalid_sql_configuration_is_rejected(self):
        sql = self.template.replace('source = "csv"', 'source = "sql"')
        for old, new in (
            ('host = "localhost"', 'host = ""'),
            ('port = 5432', 'port = true'),
            ('port = 5432', 'port = 65536'),
            ('consistent_snapshot = true', 'consistent_snapshot = "yes"'),
            ('relation = "containers"', 'relation = ""'),
            ('relation = "containers"', 'table = "containers"'),
            ('relation = "containers"', 'relation = "containers"\nfilters = []'),
            ('relation = "containers"', 'relation = "containers"\nfilters = { BRANCH = [] }'),
            ('order_by = ["MOVE_TIME", "CONTNO"]', 'order_by = "MOVE_TIME"'),
        ):
            with self.subTest(old=old, new=new):
                with self.assertRaises(ConfigurationError):
                    self.load_text(sql.replace(old, new))


class ConfiguredInputLoadingTests(unittest.TestCase):
    def setUp(self):
        self.csv_settings = load_input_config(DEFAULT_INPUT_CONFIG_FILE)
        # Supply the driver boundary without installing or contacting PostgreSQL.
        self.driver = ModuleType("psycopg")
        self.driver.connect = MagicMock()
        self.driver.sql = MagicMock()
        # Psycopg's join consumes the supplied iterator during composition.
        self.driver.sql.SQL.return_value.join.side_effect = lambda parts: tuple(parts)
        self.driver.IsolationLevel = SimpleNamespace(REPEATABLE_READ="repeatable",
                                                    READ_COMMITTED="committed")
        rows = ModuleType("psycopg.rows")
        rows.tuple_row = object()
        self.modules = patch.dict("sys.modules", {"psycopg": self.driver, "psycopg.rows": rows})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.connection = self.driver.connect.return_value.__enter__.return_value
        self.settings = {
            "source": "sql", "mapping_file": DEFAULT_CSV_MAPPING_FILE,
            "connection": {"host": "example", "port": 5432, "dbname": "yard", "user": "reader"},
            "password_env": "TEST_YARD_DB_PASSWORD", "consistent_snapshot": True,
            "sql_datasets": {
                name: dict(schema="public", relation=name, filters={}, order_by=[])
                for name in DATASETS
            },
        }

    def prepare_cursor(self, name):
        with self.csv_settings["csv_files"][name].open(newline="", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            headers = next(reader)
            data = [tuple(row) for row in reader if row]
        context = MagicMock()
        cursor = context.__enter__.return_value
        cursor.description = [SimpleNamespace(name=column) for column in headers]
        cursor.__iter__.side_effect = lambda: iter(data)

        def execute(*args):
            self.assertTrue(self.connection.read_only)
            self.assertEqual(self.connection.isolation_level, "repeatable")

        cursor.execute.side_effect = execute
        return context

    def test_sql_selection_loads_all_datasets_with_same_outputs_as_csv(self):
        # Cursor creation follows the named repository read sequence.
        contexts = [self.prepare_cursor(name) for name in DATASETS]
        # DATASETS follows schema definitions; use acquisition order explicitly.
        by_name = dict(zip(DATASETS, contexts))
        order = ("yard_blocks", "yard_planning", "removed_slots", "parameters",
                 "existing_containers", "inbound_containers", "master_equipment", "equipment_history")
        self.connection.cursor.side_effect = [by_name[name] for name in order]
        expected = load_yard_inputs(self.csv_settings)
        self.driver.connect.assert_not_called()
        with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
            actual = load_yard_inputs(self.settings)
        self.assertEqual(actual, expected)
        self.driver.connect.assert_called_once_with(**self.settings["connection"], password="test-password")
        self.driver.connect.return_value.__exit__.assert_called_once_with(None, None, None)
        for context in contexts:
            context.__exit__.assert_called_once()

    def test_failed_sql_load_exits_transaction_without_csv_fallback(self):
        context = MagicMock()
        context.__enter__.return_value.execute.side_effect = RuntimeError("query failed")
        self.connection.cursor.return_value = context
        with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
            with self.assertRaisesRegex(RuntimeError, "query failed"):
                load_yard_inputs(self.settings)
        self.assertIs(self.driver.connect.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_missing_password_fails_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "TEST_YARD_DB_PASSWORD"):
                load_yard_inputs(self.settings)
        self.driver.connect.assert_not_called()

    def test_snapshot_can_be_disabled_and_password_can_use_driver_defaults(self):
        self.settings.update(consistent_snapshot=False, password_env=None)
        with patch("repository.input_loader._read_datasets", return_value={"loaded": True}):
            self.assertEqual(load_yard_inputs(self.settings), {"loaded": True})
        self.assertEqual(self.connection.isolation_level, "committed")
        self.driver.connect.assert_called_once_with(**self.settings["connection"])

    def test_sql_identifiers_are_composed_and_filter_values_bound(self):
        payload = "CY219' OR true --"
        definition = dict(schema='schema"name', relation="table;name",
                          filters={"BRANCH": payload}, order_by=["MOVE_TIME", "CONTNO"])
        loader = _sql_loader(self.connection, "inbound_containers", definition)
        self.assertEqual(loader.parameters, (payload,))
        self.driver.sql.Identifier.assert_has_calls([
            call('schema"name', "table;name"), call("BRANCH"), call("MOVE_TIME"), call("CONTNO"),
        ])
        self.assertNotIn(payload, str(self.driver.sql.SQL.call_args_list))

    def test_missing_sql_driver_has_actionable_error(self):
        with patch.dict("sys.modules", {"psycopg": None}):
            with self.assertRaisesRegex(ConfigurationError, "requirements-sql.txt"):
                load_yard_inputs(self.settings)


if __name__ == "__main__":
    unittest.main()

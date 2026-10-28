import csv
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch

from config import (
    ConfigurationError, DEFAULT_INPUT_CONFIG_FILE,
    load_input_config,
)
from config.application.input_config import DATASETS
from config.csv_import.mapping_loader import load_mapping
from repository import load_yard_inputs
from repository.input_loader import _sql_loader


class InputConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve() / "input.toml"
        self.template = DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8")
        for name in DATASETS:
            self.template = self.template.replace(f'{name} = "sql"', f'{name} = "csv"')
        self.mapping_path = self.path.with_name("sql_mapping.toml")
        self.mapping_template = DEFAULT_INPUT_CONFIG_FILE.with_name(
            "sql_mapping.toml"
        ).read_text(encoding="utf-8")
        self.mapping_template = self.mapping_template.replace('schema = "TERMINAL_APP"\n', "")
        self.mapping_path.write_text(self.mapping_template, encoding="utf-8")
        self.sql_environment = {
            "YARD_DB_HOST": "db.example.test",
            "YARD_DB_NAME": "yard_test",
            "YARD_DB_USER": "test_reader",
        }
        environment = patch.dict(os.environ, self.sql_environment)
        environment.start()
        self.addCleanup(environment.stop)

    def load_text(self, text):
        self.path.write_text(text, encoding="utf-8")
        return load_input_config(self.path)

    def sql_text(self, *names):
        text = self.template
        for name in names or DATASETS:
            text = text.replace(f'{name} = "csv"', f'{name} = "sql"')
        return text

    def test_relative_locations_are_based_on_config_directory(self):
        settings = self.load_text(self.template)
        base = self.path.parent
        self.assertEqual(settings["mapping_files"]["csv"], base / "csv_mapping.toml")
        self.assertEqual(settings["csv_files"]["existing_containers"],
                         (base / "../data_CY219/containers.csv").resolve())
        self.assertEqual(settings["output_file"],
                         (base / "../output/result.csv").resolve())

    def test_absolute_csv_paths_are_preserved(self):
        absolute = (self.path.parent / "containers.csv").as_posix()
        settings = self.load_text(self.template.replace("../data_CY219/containers.csv", absolute))
        self.assertEqual(settings["csv_files"]["existing_containers"], Path(absolute))

    def test_source_specific_mapping_defaults(self):
        text = self.template.replace('mapping_file = "csv_mapping.toml"', '')
        self.assertEqual(self.load_text(text)["mapping_files"]["csv"],
                         self.path.parent / "csv_mapping.toml")
        text = self.sql_text().replace('mapping_file = "sql_mapping.toml"', '')
        self.assertEqual(self.load_text(text)["mapping_files"]["sql"], self.mapping_path)

    def test_sql_mapping_location_is_relative_to_input_configuration(self):
        directory = self.path.parent / "mappings"
        directory.mkdir()
        mapping_path = directory / "database.toml"
        mapping_path.write_text(self.mapping_template, encoding="utf-8")
        text = self.sql_text()
        text = text.replace('"sql_mapping.toml"', '"mappings/database.toml"')
        self.assertEqual(self.load_text(text)["mapping_files"]["sql"], mapping_path)
        text = text.replace('"mappings/database.toml"',
                            f'"{mapping_path.as_posix()}"')
        self.assertEqual(self.load_text(text)["mapping_files"]["sql"], mapping_path)

    def test_invalid_source_and_incomplete_csv_are_rejected(self):
        for text in (
            self.template.replace('yard_blocks = "csv"', 'yard_blocks = "other"'),
            self.template.replace('yard_blocks = "csv"', 'yard_blocks = true'),
            self.template.replace('yard_blocks = "csv"', ''),
            self.template.replace('yard_blocks = "csv"', 'unknown = "csv"'),
            self.template.replace('[input.sources]', '[input]'),
            self.template.replace('existing_containers = "../data_CY219/containers.csv"', ''),
            self.template.replace('existing_containers = "../data_CY219/containers.csv"',
                                  'typo = "../data_CY219/containers.csv"'),
            self.template.replace('existing_containers = "../data_CY219/containers.csv"',
                                  'existing_containers = 123'),
            self.template + '\n[unknown]\nvalue = true\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_only_selected_source_requires_configuration(self):
        csv_text = self.template[:self.template.index("[sql]")]
        self.mapping_path.unlink()
        self.assertEqual(set(self.load_text(csv_text)["sources"].values()), {"csv"})
        self.mapping_path.write_text(self.mapping_template, encoding="utf-8")
        sql_text = self.sql_text()
        start = sql_text.index("[csv]")
        end = sql_text.index("[sql]")
        settings = self.load_text(sql_text[:start] + sql_text[end:])
        self.assertEqual(set(settings["sources"].values()), {"sql"})
        self.assertNotIn("csv_files", settings)

    def test_csv_does_not_require_sql_environment_variables(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(set(self.load_text(self.template)["sources"].values()), {"csv"})

    def test_sql_connection_uses_configured_environment_variable_names(self):
        sql = self.sql_text()
        environment = {}
        for name, value in self.sql_environment.items():
            sql = sql.replace(f'"{name}"', f'"CUSTOM_{name}"')
            environment[f"CUSTOM_{name}"] = value
        with patch.dict(os.environ, environment, clear=True):
            settings = self.load_text(sql)
        self.assertEqual(settings["connection"], {
            "host": "db.example.test", "dbname": "yard_test", "user": "test_reader",
            "port": 5432, "connect_timeout": 10, "sslmode": "prefer",
        })

    def test_sql_environment_values_must_be_present_and_non_empty(self):
        sql = self.sql_text()
        for name in self.sql_environment:
            for value in (None, "", "   "):
                with self.subTest(name=name, value=value):
                    environment = dict(self.sql_environment)
                    if value is None:
                        del environment[name]
                    else:
                        environment[name] = value
                    with patch.dict(os.environ, environment, clear=True):
                        with self.assertRaisesRegex(ConfigurationError, name):
                            self.load_text(sql)

    def test_sql_environment_variable_names_must_be_non_empty_strings(self):
        sql = self.sql_text()
        for setting, name in (
            ("host_env", "YARD_DB_HOST"),
            ("dbname_env", "YARD_DB_NAME"),
            ("user_env", "YARD_DB_USER"),
        ):
            original = f'{setting} = "{name}"'
            for replacement in ("", f'{setting} = ""',
                                f'{setting} = "   "', f'{setting} = 123'):
                with self.subTest(setting=setting, replacement=replacement):
                    with self.assertRaisesRegex(ConfigurationError, f"sql[.]{setting}"):
                        self.load_text(sql.replace(original, replacement))

    def test_sql_settings_schema_override_filters_and_order(self):
        text = self.sql_text()
        mapping = self.mapping_template.replace('[sql.existing_containers]', '''[sql.existing_containers]
schema = "operations"
filters = { BRANCH = "CY219" }
order_by = ["CONTNO"]''')
        self.mapping_path.write_text(mapping, encoding="utf-8")
        settings = self.load_text(text)
        source = settings["sql_datasets"]["existing_containers"]
        relation = tomllib.loads(self.mapping_template)["sql"]["existing_containers"]["relation"]
        self.assertEqual(source, dict(schema="operations", relation=relation,
                                     filters={"BRANCH": "CY219"}, order_by=["CONTNO"]))
        self.assertEqual(settings["connection"]["host"], "db.example.test")
        self.assertNotIn("password", settings["connection"])
        self.assertEqual(settings["sql_datasets"]["yard_blocks"]["schema"], "TERMINAL_APP")

    def test_invalid_sql_configuration_is_rejected(self):
        sql = self.sql_text()
        for old, new in (
            ('host_env = "YARD_DB_HOST"', 'host = "localhost"'),
            ('port = 5432', 'port = true'),
            ('port = 5432', 'port = 65536'),
            ('consistent_snapshot = true', 'consistent_snapshot = "yes"'),
            ('mapping_file = "sql_mapping.toml"', 'mapping_file = 123'),
        ):
            with self.subTest(old=old, new=new):
                with self.assertRaises(ConfigurationError):
                    self.load_text(sql.replace(old, new))

    def test_invalid_sql_dataset_configuration_is_rejected(self):
        sql = self.sql_text()
        for old, new in (
            ('relation = "TRM_MST_YARD_BLOCK"', 'relation = ""'),
            ('relation = "TRM_MST_YARD_BLOCK"', 'table = "blocks"'),
            ('[sql.yard_blocks]', '[sql.yard_blocks]\nfilters = []'),
            ('[sql.yard_blocks]', '[sql.yard_blocks]\nfilters = { BRANCH = [] }'),
            ('order_by = ["MOVE_TIME", "CONTNO"]', 'order_by = "MOVE_TIME"'),
            ('[sql.yard_blocks]', '[sql.unknown]'),
            ('[sql.yard_blocks]', '[csv.yard_blocks]'),
            ('[sql.yard_blocks]', '[other]'),
        ):
            with self.subTest(old=old, new=new):
                self.mapping_path.write_text(
                    self.mapping_template.replace(old, new), encoding="utf-8"
                )
                with self.assertRaises(ConfigurationError):
                    self.load_text(sql)

    def test_missing_sql_mapping_is_reported(self):
        self.mapping_path.unlink()
        sql = self.sql_text()
        with self.assertRaisesRegex(ConfigurationError, "Cannot read.*sql_mapping"):
            self.load_text(sql)

    def test_sql_mapping_requires_selected_dataset(self):
        self.mapping_path.write_text(
            self.mapping_template[self.mapping_template.index("[sql.yard_planning]"):],
            encoding="utf-8",
        )
        sql = self.sql_text("yard_blocks")
        with self.assertRaisesRegex(ConfigurationError, "missing datasets.*yard_blocks"):
            self.load_text(sql)

    def test_mixed_sources_require_only_selected_paths_and_relations(self):
        text = self.sql_text("existing_containers", "equipment_history")
        text = text.replace('existing_containers = "../data_CY219/containers.csv"', '')
        text = text.replace('equipment_history = "../data_CY219/equipment_history.csv"', '')
        self.mapping_path.write_text(
            '[sql.existing_containers]\nrelation = "containers"\n'
            '[sql.equipment_history]\nrelation = "equipment_moves"\n',
            encoding="utf-8",
        )
        settings = self.load_text(text)
        sql_names = {"existing_containers", "equipment_history"}
        self.assertEqual(settings["sources"], {
            name: "sql" if name in sql_names else "csv" for name in DATASETS
        })
        self.assertEqual(set(settings["csv_files"]), set(DATASETS) - sql_names)
        self.assertEqual(set(settings["sql_datasets"]), sql_names)
        self.assertEqual(settings["mapping_files"], {
            "csv": self.path.parent / "csv_mapping.toml", "sql": self.mapping_path,
        })


class ConfiguredInputLoadingTests(unittest.TestCase):
    def setUp(self):
        document = tomllib.loads(DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8"))
        document["input"]["sources"] = dict.fromkeys(DATASETS, "csv")
        document["input"]["filters"] = {}
        document["csv"].pop("shifting_summary_file", None)
        document["csv"].pop("shifting_workbook_file", None)
        with patch("config.application.input_config._read_document", return_value=document):
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
            "sources": dict.fromkeys(DATASETS, "sql"),
            "mapping_files": {"sql": DEFAULT_INPUT_CONFIG_FILE.with_name("sql_mapping.toml")},
            "connection": {"host": "example", "port": 5432, "dbname": "yard", "user": "reader"},
            "password_env": "TEST_YARD_DB_PASSWORD", "consistent_snapshot": True,
            "sql_datasets": {
                name: dict(schema="public", relation=name, filters={}, order_by=[])
                for name in DATASETS
            },
        }

    def mixed_settings(self, *sql_names):
        return {
            **self.settings,
            "sources": {name: "sql" if name in sql_names else "csv" for name in DATASETS},
            "mapping_files": {
                **self.csv_settings["mapping_files"], **self.settings["mapping_files"],
            },
            "csv_files": {
                name: path for name, path in self.csv_settings["csv_files"].items()
                if name not in sql_names
            },
            "sql_datasets": {name: self.settings["sql_datasets"][name] for name in sql_names},
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
        order = ("terminal_branches", "yard_blocks", "yard_planning", "removed_slots", "parameters",
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

    def test_csv_selection_does_not_require_sql_driver_or_environment(self):
        with patch.dict("sys.modules", {"psycopg": None}), patch.dict(os.environ, {}, clear=True):
            actual = load_yard_inputs(self.csv_settings)
        self.assertEqual(set(actual), set(DATASETS))
        self.driver.connect.assert_not_called()

    def test_each_dataset_can_use_sql_while_others_use_csv(self):
        expected = load_yard_inputs(self.csv_settings)
        for name in DATASETS:
            with self.subTest(name=name):
                settings = self.mixed_settings(name)
                context = self.prepare_cursor(name)
                self.connection.cursor.return_value = context
                self.driver.connect.reset_mock()
                with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
                    self.assertEqual(load_yard_inputs(settings), expected)
                self.driver.connect.assert_called_once_with(
                    **settings["connection"], password="test-password"
                )
                self.connection.cursor.assert_called_once()
                context.__exit__.assert_called_once()
                self.driver.connect.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_mixed_sources_share_connection_and_use_independent_column_mappings(self):
        expected = load_yard_inputs(self.csv_settings)
        settings = self.mixed_settings("yard_blocks", "equipment_history")
        contexts = [self.prepare_cursor(name) for name in ("yard_blocks", "equipment_history")]
        contexts[0].__enter__.return_value.description[0].name = "DB_BLOCK_ID"
        self.connection.cursor.side_effect = contexts
        mapping = settings["mapping_files"]["sql"].read_text(encoding="utf-8").replace(
            'block_id = "BLOCK_ID"', 'block_id = "DB_BLOCK_ID"', 1,
        )
        with tempfile.TemporaryDirectory() as directory:
            mapping_path = Path(directory) / "sql_mapping.toml"
            mapping_path.write_text(mapping, encoding="utf-8")
            settings["mapping_files"]["sql"] = mapping_path
            with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
                self.assertEqual(load_yard_inputs(settings), expected)
        self.driver.connect.assert_called_once_with(**settings["connection"], password="test-password")
        self.assertEqual(self.connection.cursor.call_count, 2)
        for context in contexts:
            context.__exit__.assert_called_once()
        self.driver.connect.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_missing_selected_mapping_profile_fails_before_connecting(self):
        settings = self.mixed_settings("yard_blocks")
        for missing_source, name in (("csv", "inbound_containers"), ("sql", "yard_blocks")):
            with self.subTest(source=missing_source):
                def load_profiles(path, *, source):
                    profiles = load_mapping(path, source=source)
                    if source == missing_source:
                        del profiles[name]
                    return profiles

                with patch("repository.input_loader.load_mapping", side_effect=load_profiles):
                    with self.assertRaisesRegex(ConfigurationError, f"Missing {missing_source.upper()} mapping"):
                        load_yard_inputs(settings)
                self.driver.connect.assert_not_called()

    def test_failed_sql_load_exits_transaction_without_csv_fallback(self):
        context = MagicMock()
        context.__enter__.return_value.execute.side_effect = RuntimeError("query failed")
        self.connection.cursor.return_value = context
        for settings in (self.settings, self.mixed_settings("yard_blocks")):
            with self.subTest(sources=settings["sources"]):
                with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
                    with self.assertRaisesRegex(RuntimeError, "query failed"):
                        load_yard_inputs(settings)
                self.assertIs(self.driver.connect.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_sql_column_names_can_differ_from_csv(self):
        expected = load_yard_inputs(self.csv_settings)
        contexts = {name: self.prepare_cursor(name) for name in DATASETS}
        contexts["yard_blocks"].__enter__.return_value.description[0].name = "DB_BLOCK_ID"
        order = ("terminal_branches", "yard_blocks", "yard_planning", "removed_slots", "parameters",
                 "existing_containers", "inbound_containers", "master_equipment", "equipment_history")
        self.connection.cursor.side_effect = [contexts[name] for name in order]
        mapping = self.settings["mapping_files"]["sql"].read_text(encoding="utf-8").replace(
            'block_id = "BLOCK_ID"', 'block_id = "DB_BLOCK_ID"', 1
        )
        with tempfile.TemporaryDirectory() as directory:
            mapping_path = Path(directory) / "sql_mapping.toml"
            mapping_path.write_text(mapping, encoding="utf-8")
            self.settings["mapping_files"]["sql"] = mapping_path
            with patch.dict(os.environ, {"TEST_YARD_DB_PASSWORD": "test-password"}):
                self.assertEqual(load_yard_inputs(self.settings), expected)

    def test_missing_password_fails_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "TEST_YARD_DB_PASSWORD"):
                load_yard_inputs(self.settings)
        self.driver.connect.assert_not_called()

    def test_snapshot_can_be_disabled_and_password_can_use_driver_defaults(self):
        self.settings.update(consistent_snapshot=False, password_env=None)
        reference = [{"branch_id": "2", "terminal_id": "1", "branch_code": "JKT74", "branch_name": "CY 219"}]
        with patch("repository.input_loader._read_datasets", side_effect=[
            {"terminal_branches": reference}, {"loaded": True},
        ]):
            self.assertEqual(load_yard_inputs(self.settings), {"terminal_branches": reference, "loaded": True})
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

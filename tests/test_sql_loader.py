import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping
from repository import CSVLoader
from repository import InputError
from repository import Repository, RemovedSlotsRepository, EquipmentMoveRepository
from repository import SQLLoader
from utils import parse_datetime


class SQLLoaderTests(unittest.TestCase):
    def setUp(self):
        # Exercise the DB-API boundary without requiring a database or driver.
        rows_module = ModuleType("psycopg.rows")
        rows_module.tuple_row = object()
        self.modules = patch.dict("sys.modules", {"psycopg.rows": rows_module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)

    def loader(self, headers, rows):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.description = [SimpleNamespace(name=h) for h in headers]
        self.cursor.__iter__.side_effect = lambda: iter(rows)
        return SQLLoader(self.connection, "SELECT example WHERE branch = %s",
                         parameters=("BR",), source="example")

    def test_csv_and_sql_produce_identical_coordinates(self):
        loader = self.loader(["BLOCK_ID", "ROW_NO", "SLOT_NO"], [("000A", 2, 4)])
        actual = RemovedSlotsRepository(loader, self.profiles["removed_slots"]).read_tuples()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slots.csv"
            path.write_text("BLOCK_ID,ROW_NO,SLOT_NO\n000A,2,4\n", encoding="utf-8")
            expected = RemovedSlotsRepository(CSVLoader(path), self.profiles["removed_slots"]).read_tuples()
        self.assertEqual(actual, expected)
        self.cursor.execute.assert_called_once_with(loader.query, ("BR",))
        self.connection.cursor.return_value.__exit__.assert_called_once()
        self.connection.commit.assert_not_called()
        self.connection.close.assert_not_called()

    def test_native_values_and_timestamp_precision(self):
        dt = datetime(2026, 10, 21, 12, 30, 42, 123456, tzinfo=timezone.utc)
        loader = self.loader(["id", "weight", "missing", "move_time"],
                             [("001", Decimal("123.50"), None, dt)])
        record = Repository(loader).read_records()[0]
        self.assertEqual(record["id"], "1")
        self.assertEqual(record["weight"], "123.50")
        self.assertEqual(record["missing"], "")
        self.assertEqual(parse_datetime(record["move_time"]), dt)

    def test_duplicate_headers_rejected_before_rows_are_consumed(self):
        loader = self.loader(["ID", " id "], [(1, 2)])
        with self.assertRaisesRegex(InputError, "ambiguous"):
            Repository(loader).read_records()
        self.cursor.__iter__.assert_not_called()
        self.connection.cursor.return_value.__exit__.assert_called_once()

    def test_empty_result_still_validates_required_columns(self):
        loader = self.loader(["ROW_NO", "SLOT_NO"], [])
        with self.assertRaisesRegex(InputError, "block_id"):
            RemovedSlotsRepository(loader, self.profiles["removed_slots"]).read_tuples()

    def test_valid_empty_result(self):
        loader = self.loader(["BLOCK_ID", "ROW_NO", "SLOT_NO"], [])
        self.assertEqual(RemovedSlotsRepository(loader, self.profiles["removed_slots"]).read_tuples(), [])

    def test_query_without_result_columns(self):
        loader = self.loader([], [])
        self.cursor.description = None
        with self.assertRaisesRegex(InputError, "no columns"):
            Repository(loader).read_records()
        self.connection.cursor.return_value.__exit__.assert_called_once()

    def test_conversion_error_closes_cursor_and_identifies_row(self):
        loader = self.loader(["BLOCK_ID", "ROW_NO", "SLOT_NO"], [("A", "bad", 1)])
        with self.assertRaisesRegex(InputError, "example, result row 1.*row_no"):
            RemovedSlotsRepository(loader, self.profiles["removed_slots"]).read_tuples()
        self.connection.cursor.return_value.__exit__.assert_called_once()

    def test_equipment_native_timestamp_and_null(self):
        loader = self.loader(
            ["ALAT", "BRANCH", "BLOK", "ROW", "SLOT", "MOVE_DATE"],
            [("RTG1", "BR", "A", 1, 1, None),
             ("RTG1", "BR", "A", 2, 3, datetime(2026, 10, 21, tzinfo=timezone.utc))],
        )
        self.assertEqual(EquipmentMoveRepository(loader, self.profiles["equipment_history"]).read_locations(),
                         {"RTG1": ("BR", "A", 1, 2)})

    def test_mixed_timezone_values_report_source_context(self):
        loader = self.loader(
            ["ALAT", "BRANCH", "BLOK", "ROW", "SLOT", "MOVE_DATE"],
            [("RTG1", "BR", "A", 1, 1, datetime(2026, 10, 20)),
             ("RTG1", "BR", "A", 2, 3, datetime(2026, 10, 21, tzinfo=timezone.utc))],
        )
        with self.assertRaisesRegex(InputError, "result row 2.*mixed timezone"):
            EquipmentMoveRepository(loader, self.profiles["equipment_history"]).read_locations()


if __name__ == "__main__":
    unittest.main()

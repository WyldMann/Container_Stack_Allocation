import tempfile
import unittest
from pathlib import Path

from config import (
    ConfigurationError, DEFAULT_CSV_MAPPING_FILE, DEFAULT_INPUT_CONFIG_FILE,
    load_csv_mapping,
)
from config.csv_import.mapping_loader import load_mapping


class SQLMappingLoaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sql_mapping.toml"

    def load_text(self, text):
        self.path.write_text(text, encoding="utf-8")
        return load_mapping(self.path, source="sql")

    def test_default_sql_columns_match_csv(self):
        sql_profiles = load_mapping(
            DEFAULT_INPUT_CONFIG_FILE.with_name("sql_mapping.toml"), source="sql"
        )
        self.assertEqual(sql_profiles, load_csv_mapping(DEFAULT_CSV_MAPPING_FILE))
        with self.assertRaises(TypeError):
            sql_profiles["removed_slots"].columns["block_id"] = "Changed"

    def test_sql_metadata_is_allowed_and_unmapped_fields_keep_their_names(self):
        profiles = self.load_text(
            '[sql.removed_slots]\nrelation = "slots"\nschema = "operations"\n'
            'filters = { BRANCH = "CY219" }\norder_by = ["DB_BLOCK"]\n'
            '[sql.removed_slots.columns]\nblock_id = "DB_BLOCK"\n'
        )
        self.assertEqual(dict(profiles["removed_slots"].columns),
                         {"block_id": "DB_BLOCK"})

    def test_invalid_sql_columns_and_profiles_are_rejected(self):
        for text in (
            '[csv.removed_slots.columns]\nblock_id = "BLOCK_ID"\n',
            '[sql.unknown.columns]\nblock_id = "BLOCK_ID"\n',
            '[sql.removed_slots]\nunknown = true\n',
            '[sql.removed_slots]\ncolumns = []\n',
            '[sql.removed_slots.columns]\nunknown = "BLOCK_ID"\n',
            '[sql.removed_slots.columns]\nblock_id = ""\n',
            '[sql.removed_slots.columns]\nblock_id = 123\n',
            '[sql.removed_slots.columns]\nblock_id = "ROW_NO"\n',
            '[sql.removed_slots.columns]\nblock_id = "Location"\nrow_no = " location "\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)


if __name__ == "__main__":
    unittest.main()

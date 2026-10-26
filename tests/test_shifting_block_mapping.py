"""Explicit shifting-code mappings preserve observations and validate block identity."""

from pathlib import Path
import tempfile
import unittest

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping
from repository import InputError
from repository.shifting_repository import (
    load_shifting_summary, validate_shifting_blocks,
)


class ShiftingBlockMappingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.mapping = self.root / "mapping.toml"
        self.csv = self.root / "shifting.csv"

    def write_mapping(self, text):
        self.mapping.write_text(text, encoding="utf-8")

    def write_csv(self, rows, code_header="shifting_code"):
        self.csv.write_text(
            f"cy_name,{code_header},lifting_count,shifting_count\n" + rows,
            encoding="utf-8",
        )

    def load(self):
        return load_shifting_summary(self.csv, "CY219", self.mapping, {"10", "11"})

    def test_selected_cy_codes_normalized_and_many_codes_can_share_block(self):
        self.write_mapping('[CY218]\nSL = "99"\n[" cy219 "]\n" SL " = "10"\n"RS MDL" = "10"\n')
        self.write_csv("CY219,sl,100,10\nCY219,RS MDL,100,20\nCY219,sl,100,10\nCY218,OTHER,1,1\n")
        rows = self.load()
        self.assertEqual([row.block_id for row in rows], ["10", "10", "10"])
        self.assertEqual([row.shifting_code for row in rows], ["sl", "RS MDL", "sl"])
        self.assertEqual(sum(row.shifting_count for row in rows), 40)

    def test_legacy_header_resolves_to_same_record(self):
        self.write_mapping('[CY219]\nSL = "10"\n')
        self.write_csv("CY219,SL,100,10\n")
        expected = self.load()
        self.write_csv("CY219,SL,100,10\n", code_header="equipment_group")
        self.assertEqual(self.load(), expected)

    def test_ambiguous_headers_rejected(self):
        self.write_mapping('[CY219]\nSL = "10"\n')
        self.csv.write_text(
            "cy_name,shifting_code,equipment_group,lifting_count,shifting_count\n"
            "CY219,SL,SL,100,10\n", encoding="utf-8",
        )
        with self.assertRaisesRegex(InputError, "exactly one"):
            self.load()

    def test_unmapped_code_is_not_dropped(self):
        self.write_mapping('[CY219]\nSL = "10"\n')
        self.write_csv("CY219,SL,100,10\nCY219,UNKNOWN,100,20\n")
        with self.assertRaisesRegex(InputError, "unmapped shifting code.*UNKNOWN"):
            self.load()

    def test_block_must_exist_in_loaded_yard(self):
        self.write_mapping('[CY219]\nSL = "99"\n')
        self.write_csv("CY219,SL,100,10\n")
        with self.assertRaisesRegex(ConfigurationError, "absent from the yard"):
            self.load()

    def test_rejected_yard_block_is_detected_after_construction(self):
        self.write_mapping('[CY219]\nSL = "10"\n')
        self.write_csv("CY219,SL,100,10\n")
        rows = self.load()
        with self.assertRaisesRegex(InputError, "outside the loaded yard"):
            validate_shifting_blocks(rows, {"11"})

    def test_invalid_or_missing_mapping_is_actionable(self):
        for text in (
            '[CY218]\nSL = "10"\n',
            '[CY219]\n',
            '[CY219]\nSL = 10\n',
            '[CY219]\nSL = ["10", "11"]\n',
            '[CY219]\nSL = ""\n',
            '[CY219]\n" " = "10"\n',
            '[CY219]\nSL = "10"\n" sl " = "11"\n',
            '[CY219]\nSL = "10"\n[cy219]\nSL = "11"\n',
            'CY219 = "10"\n',
            '[broken',
        ):
            with self.subTest(text=text):
                self.write_mapping(text)
                with self.assertRaises(ConfigurationError):
                    load_shifting_block_mapping(self.mapping, "CY219")

    def test_missing_mapping_file(self):
        with self.assertRaisesRegex(ConfigurationError, "Cannot read"):
            load_shifting_block_mapping(self.mapping, "CY219")


if __name__ == "__main__":
    unittest.main()

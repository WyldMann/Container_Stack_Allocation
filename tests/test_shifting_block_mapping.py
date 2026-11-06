"""Explicit shifting-code mappings preserve observations and validate block identity."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping
from repository import InputError, CSVLoader
from repository.shifting_repository import (
    load_shifting_summary, resolve_shifting_blocks, validate_shifting_blocks,
)


class ShiftingBlockMappingTests(unittest.TestCase):
    def test_full_branch_names_match_uppercase_with_whitespace_significant(self):
        self.write_mapping('["  CY 219 (LINI 2) "]\nSL = "B"\n')
        self.assertEqual(load_shifting_block_mapping(self.mapping, "  Cy 219 (Lini 2) "), {"sl": "B"})
        with self.assertRaises(ConfigurationError):
            load_shifting_block_mapping(self.mapping, "Cy 219 (Lini 2)")

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
        return load_shifting_summary(
            CSVLoader(self.csv), "CY219", self.mapping,
            [{"block_code": "B", "block_id": "10"}, {"block_code": "C", "block_id": "11"}],
        )

    def test_codes_resolve_to_current_ids_without_falling_back_to_ids(self):
        mapping = {"sl": "b", "rs": "10", "other": "2A"}
        self.assertEqual(resolve_shifting_blocks(mapping, [
            {"block_code": "B", "block_id": "10"},
            {"block_code": "2A", "block_id": "34"},
        ]), {"sl": ("10",), "rs": (), "other": ("34",)})
        self.assertEqual(resolve_shifting_blocks({"sl": "B"}, [
            {"block_code": "B", "block_id": "29"},
        ]), {"sl": ("29",)})

    def test_ambiguous_mapped_block_code_is_rejected(self):
        with self.assertRaisesRegex(InputError, "block_code.*B.*multiple"):
            resolve_shifting_blocks({"sl": "B"}, [
                {"block_code": "B", "block_id": "10"},
                {"block_code": "B", "block_id": "29"},
            ])

    def test_multiple_blocks_are_resolved_once_and_missing_blocks_are_omitted(self):
        self.write_mapping('[CY219]\nSL = [" B ", "C", "b", "99"]\n')
        self.write_csv("CY219,SL,100,10\n")
        rows = self.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mapped_block_ids, ("10", "11"))
        self.assertEqual((rows[0].lifting_count, rows[0].shifting_count), (100, 10))
        retained = validate_shifting_blocks(rows, {"11"})
        self.assertEqual(retained[0].block_id, "11")
        self.assertEqual(retained[0].mapped_block_ids, ("11",))

    def test_sql_counts_equipment_once_when_it_maps_to_multiple_blocks(self):
        from repository.sql_shifting_repository import load_sql_shifting_summary

        self.write_mapping('[CY219]\nRTG04 = ["1A", "2A"]\n')
        loader = MagicMock()
        loader.open.return_value.__enter__.return_value = (
            ["operation_count"], [("SQL", {"operation_count": 5})],
        )
        with patch("repository.sql_shifting_repository.operations_count_query"), patch(
            "repository.sql_shifting_repository.SQLLoader", return_value=loader,
        ) as loader_class:
            rows = load_sql_shifting_summary(
                MagicMock(), {"datetime_format": "DD-MM-YYYY HH24:MI"},
                {"lifting": ["Lift"], "shifting": ["Shift"]},
                "CY219", "JKT64", self.mapping,
                [{"block_code": "1A", "block_id": "10"},
                 {"block_code": "2A", "block_id": "11"}], recorded_at=1000000,
            )
        self.assertEqual(loader_class.call_count, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mapped_block_ids, ("10", "11"))

    def test_sql_uses_resolved_ids_and_does_not_query_absent_codes(self):
        from repository.sql_shifting_repository import load_sql_shifting_summary

        self.write_mapping('[CY219]\nSL = "2A"\nABSENT = "99"\n')
        loader = MagicMock()
        loader.open.return_value.__enter__.return_value = (
            ["operation_count"], [("SQL", {"operation_count": 5})],
        )
        with patch("repository.sql_shifting_repository.operations_count_query"), patch(
            "repository.sql_shifting_repository.SQLLoader", return_value=loader,
        ) as loader_class:
            rows = load_sql_shifting_summary(
                MagicMock(), {"datetime_format": "DD-MM-YYYY HH24:MI"},
                {"lifting": ["Lift"], "shifting": ["Shift"]},
                "CY219", "JKT74", self.mapping,
                [{"block_code": "2A", "block_id": "34"}], recorded_at=1000000,
            )
        self.assertEqual([(row.shifting_code, row.block_id) for row in rows], [("SL", "34")])
        self.assertEqual(loader_class.call_count, 2)

    def test_selected_cy_codes_normalized_and_many_codes_can_share_block(self):
        self.write_mapping('[CY218]\nSL = "99"\n[CY219]\n" SL " = "B"\n"RS MDL" = "B"\n')
        self.write_csv("CY219,sl,100,10\nCY219,RS MDL,100,20\nCY219,sl,100,10\nCY218,OTHER,1,1\n")
        rows = self.load()
        self.assertEqual([row.block_id for row in rows], ["10", "10", "10"])
        self.assertEqual([row.shifting_code for row in rows], ["sl", "RS MDL", "sl"])
        self.assertEqual(sum(row.shifting_count for row in rows), 40)

    def test_unmapped_code_is_not_dropped(self):
        self.write_mapping('[CY219]\nSL = "B"\n')
        self.write_csv("CY219,SL,100,10\nCY219,UNKNOWN,100,20\n")
        with self.assertRaisesRegex(InputError, "unmapped shifting code.*UNKNOWN"):
            self.load()

    def test_nonexistent_block_is_omitted_while_present_block_loads(self):
        self.write_mapping('[CY219]\nSL = "99"\nRS = "B"\n')
        self.write_csv("CY219,SL,100,10\nCY219,RS,100,20\nCY219,RS,100,20\n")
        rows = self.load()
        self.assertEqual([row.block_id for row in rows], ["10", "10"])
        self.assertEqual(sum(row.shifting_count for row in rows), 40)

    def test_all_nonexistent_blocks_produce_empty_observations(self):
        self.write_mapping('[CY219]\nSL = "99"\n')
        self.write_csv("CY219,SL,100,10\n")
        self.assertEqual(self.load(), [])

    def test_absent_block_missing_or_invalid_counts_are_never_validated(self):
        self.write_mapping('[CY219]\nSL = "99"\nRS = "B"\n')
        for values in ("100,", ",", "bad,-1"):
            with self.subTest(values=values):
                self.write_csv("CY219,SL," + values + "\nCY219,RS,100,20\n")
                self.assertEqual([row.shifting_code for row in self.load()], ["RS"])

    def test_unused_missing_block_mapping_does_not_block_valid_data(self):
        self.write_mapping('[CY219]\nSL = "B"\nRS = "99"\n')
        self.write_csv("CY219,SL,100,10\n")
        self.assertEqual(self.load()[0].block_id, "10")

    def test_rejected_yard_block_is_detected_after_construction(self):
        self.write_mapping('[CY219]\nSL = "B"\n')
        self.write_csv("CY219,SL,100,10\n")
        rows = self.load()
        self.assertEqual(validate_shifting_blocks(rows, {"11"}), [])

    def test_invalid_or_missing_mapping_is_actionable(self):
        for text in (
            '[CY218]\nSL = "B"\n',
            '[CY219]\n',
            '[CY219]\nSL = 10\n',
            '[CY219]\nSL = []\n',
            '[CY219]\nSL = ["B", ""]\n',
            '[CY219]\nSL = ["B", 11]\n',
            '[CY219]\nSL = ""\n',
            '[CY219]\n" " = "B"\n',
            '[CY219]\nSL = "B"\n" sl " = "C"\n',
            '[CY219]\nSL = "B"\n[cy219]\nSL = "C"\n',
            'CY219 = "B"\n',
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

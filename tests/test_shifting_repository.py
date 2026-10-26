"""Shifting CSV observations are selected by CY, without period filtering."""

import copy
import io
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from config import ConfigurationError, DEFAULT_INPUT_CONFIG_FILE, load_input_config
from config.application.input_config import DATASETS
from repository import CSVLoader, InputError, load_yard_inputs
from repository.shifting_repository import ShiftingRepository


HEADER = "cy_name,equipment_group,lifting_count,shifting_count"


class ShiftingRepositoryTests(unittest.TestCase):
    def read(self, text, cy_name="CY219"):
        with patch("pathlib.Path.open", return_value=io.StringIO(text)):
            return ShiftingRepository(CSVLoader("memory.csv")).read_summaries(cy_name)

    def test_all_selected_observations_retained_without_period_columns(self):
        rows = self.read(
            HEADER + "\nCY219,SL,100,10\nCY218,SL,999,99\n"
            " cy219 ,SL,100,10\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0].cy_name, "CY219")
        self.assertEqual(rows[0].shifting_code, "SL")
        self.assertEqual(rows[0].shifting_ratio, 0.1)
        self.assertIsNone(rows[0].report_month)
        self.assertIsNone(rows[0].week_number)

    def test_raw_period_metadata_preserved_and_totals_excluded(self):
        rows = self.read(
            HEADER + ",REPORT_MONTH,WEEK_NUMBER\n"
            "CY219,SL,100,10,2026-01,1\n"
            "CY219,SL,100,10,unspecified,unknown\n"
            "CY219,SL,100,10,unspecified,unknown\n"
            "CY219,SL,300,30,, total \n"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].week_number, "1")
        self.assertEqual(rows[1].report_month, "unspecified")
        self.assertEqual(rows[1].week_number, "unknown")

    def test_missing_and_zero_counts_are_distinct(self):
        rows = self.read(
            HEADER + "\nCY219,SL,,\nCY219,SL,0,0\nCY219,SL,10,0\n"
        )
        self.assertIsNone(rows[0].lifting_count)
        self.assertIsNone(rows[0].shifting_ratio)
        self.assertEqual(rows[1].lifting_count, 0)
        self.assertIsNone(rows[1].shifting_ratio)
        self.assertEqual(rows[2].shifting_ratio, 0)

    def test_invalid_counts_and_equipment_report_source_location(self):
        for values in ("SL,-1,0", "SL,1.5,0", "SL,10,", "SL,,1", ",10,1"):
            with self.subTest(values=values), self.assertRaisesRegex(InputError, "line 2"):
                self.read(HEADER + "\nCY219," + values + "\n")

    def test_missing_selected_cy_is_reported(self):
        with self.assertRaisesRegex(InputError, "no records"):
            self.read(HEADER + "\nCY218,SL,1,1\n")

    def test_empty_cy_is_rejected(self):
        with self.assertRaisesRegex(InputError, "non-empty"):
            self.read(HEADER + "\n", " ")

    def test_invalid_headers_and_row_widths_are_rejected(self):
        for text in (
            "cy_name,equipment_group\nCY219,SL\n",
            HEADER + ",CY_NAME\nCY219,SL,1,1,CY219\n",
            HEADER + "\nCY219,SL,1\n",
            HEADER + "\nCY219,SL,1,1,extra\n",
        ):
            with self.subTest(text=text), self.assertRaises(InputError):
                self.read(text)


class ShiftingInputTests(unittest.TestCase):
    def setUp(self):
        self.document = tomllib.loads(DEFAULT_INPUT_CONFIG_FILE.read_text(encoding="utf-8"))
        self.document["input"]["sources"] = dict.fromkeys(DATASETS, "csv")

    def settings(self, document):
        with patch("config.application.input_config._read_document", return_value=document):
            return load_input_config(DEFAULT_INPUT_CONFIG_FILE)

    def test_optional_report_does_not_change_existing_dataset_set(self):
        self.document["input"].pop("cy_name", None)
        settings = self.settings(self.document)
        self.assertNotIn("shifting_summary_file", settings)
        self.assertEqual(set(load_yard_inputs(settings)), set(DATASETS))

    def test_report_path_is_relative_to_configuration_and_cy_trimmed(self):
        self.document["input"]["cy_name"] = " CY219 "
        self.document["csv"]["shifting_summary_file"] = "../reports/shifting.csv"
        settings = self.settings(self.document)
        self.assertEqual(settings["cy_name"], "CY219")
        self.assertEqual(
            settings["shifting_block_mapping_file"],
            DEFAULT_INPUT_CONFIG_FILE.with_name("shifting_block_mapping.toml"),
        )
        self.assertEqual(
            settings["shifting_summary_file"],
            (DEFAULT_INPUT_CONFIG_FILE.parent / "../reports/shifting.csv").resolve(),
        )

    def test_report_requires_valid_cy_and_path(self):
        for cy, path in ((None, "shifting.csv"), (" ", "shifting.csv"),
                         (123, "shifting.csv"), ("CY219", ""), ("CY219", 123)):
            document = copy.deepcopy(self.document)
            if cy is None:
                document["input"].pop("cy_name", None)
            else:
                document["input"]["cy_name"] = cy
            document["csv"]["shifting_summary_file"] = path
            with self.subTest(cy=cy, path=path), self.assertRaises(ConfigurationError):
                self.settings(document)

    def test_mapping_path_is_configurable_and_validated(self):
        self.document["csv"]["shifting_summary_file"] = "shifting.csv"
        self.document["csv"]["shifting_block_mapping_file"] = "mappings/blocks.toml"
        self.assertEqual(
            self.settings(self.document)["shifting_block_mapping_file"],
            DEFAULT_INPUT_CONFIG_FILE.parent / "mappings" / "blocks.toml",
        )
        for value in ("", 123):
            self.document["csv"]["shifting_block_mapping_file"] = value
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                self.settings(self.document)

    def test_report_loaded_with_existing_yard_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shifting.csv"
            mapping = Path(directory) / "mapping.toml"
            mapping.write_text('[CY219]\nSL = "10"\n', encoding="utf-8")
            self.document["csv"]["shifting_block_mapping_file"] = mapping.as_posix()
            path.write_text(
                HEADER + "\nCY219,SL,100,10\nCY218,SL,200,20\n"
                "CY219,SL,100,10\n",
                encoding="utf-8-sig",
            )
            self.document["csv"]["shifting_summary_file"] = path.as_posix()
            inputs = load_yard_inputs(self.settings(self.document))
        self.assertEqual(set(inputs), set(DATASETS) | {"shifting_summary"})
        self.assertEqual(len(inputs["shifting_summary"]), 2)
        self.assertEqual(inputs["shifting_summary"][0].lifting_count, 100)
        self.assertEqual(inputs["shifting_summary"][0].block_id, "10")


if __name__ == "__main__":
    unittest.main()

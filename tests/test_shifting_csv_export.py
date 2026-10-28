"""Workbook edits are exported before each shifting-data load."""

import csv
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from config import ConfigurationError
from repository import InputError, load_yard_inputs
from repository.shifting_csv_export import refresh_shifting_csv
from tests import test_main_existing as main_tests
from tests import test_shifting_repository as shifting_tests
import main_existing


_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def write_workbook(path, lifting=100, shifting=10, week=44, old_lifting=50, old_shifting=5, branch_name="CY 219 (LINI 2)"):
    sheet = ET.Element("{" + _NS + "}worksheet")
    data = ET.SubElement(sheet, "{" + _NS + "}sheetData")
    values = {
        3: {"E": "Oct-26"},
        7: {"B": branch_name, "E": "CY 218 (LINI 2)"},
        8: {"B": "SL", "E": "RTG 03"},
        9: {"B": "LIFTING", "C": "SHIFTING", "D": "%",
            "E": "LIFTING", "F": "SHIFTING", "G": "%"},
        10: {"A": "WEEK 43", "B": old_lifting, "C": old_shifting, "E": 200, "F": 20},
        11: {"A": "WEEK " + str(week), "B": lifting, "C": shifting, "E": 900, "F": 90},
        12: {"A": "TOTAL", "B": 99999, "C": 99999, "E": 99999, "F": 99999},
    }
    for number, cells in values.items():
        row = ET.SubElement(data, "{" + _NS + "}row", r=str(number))
        for column, value in cells.items():
            if value is None:
                continue
            cell = ET.SubElement(row, "{" + _NS + "}c", r=column + str(number))
            if isinstance(value, str):
                cell.set("t", "inlineStr")
                ET.SubElement(ET.SubElement(cell, "{" + _NS + "}is"), "{" + _NS + "}t").text = value
            else:
                ET.SubElement(cell, "{" + _NS + "}v").text = str(value)
    merges = ET.SubElement(sheet, "{" + _NS + "}mergeCells")
    for ref in ("B7:D7", "E7:G7", "B8:D8", "E8:G8"):
        ET.SubElement(merges, "{" + _NS + "}mergeCell", ref=ref)
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml",
            '<workbook xmlns="' + _NS + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Per Alat Weekly" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))


class ShiftingCsvExportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.workbook = self.root / "shifting.xlsx"
        self.output = self.root / "shifting.csv"

    def read_csv(self):
        with self.output.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_workbook_edits_refresh_existing_csv_every_time(self):
        write_workbook(self.workbook)
        original = self.workbook.read_bytes()
        self.assertEqual(refresh_shifting_csv(self.workbook, self.output), 4)
        self.assertEqual(self.read_csv()[2]["shifting_count"], "10")
        self.assertEqual(self.workbook.read_bytes(), original)
        write_workbook(self.workbook, lifting=500, shifting=100, week=45)
        refresh_shifting_csv(self.workbook, self.output)
        rows = self.read_csv()
        self.assertEqual(rows[2]["lifting_count"], "500")
        self.assertEqual(rows[2]["shifting_count"], "100")
        self.assertEqual(rows[2]["week_number"], "45")
        self.assertEqual(rows[2]["report_month"], "2026-10")
        self.assertEqual(rows[2]["cy_name"], "CY 219 (LINI 2)")
        self.assertEqual(rows[2]["shifting_code"], "SL")
        self.assertTrue(all(row["week_number"] != "TOTAL" for row in rows))
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_workbook_branch_name_keeps_case_and_whitespace(self):
        name = "  Cy 219 (Lini 2)\t"
        write_workbook(self.workbook, branch_name=name)
        refresh_shifting_csv(self.workbook, self.output)
        self.assertEqual(self.read_csv()[0]["cy_name"], name)

    def test_missing_historical_counts_are_preserved_for_later_week_selection(self):
        write_workbook(self.workbook, old_lifting=50, old_shifting=None)
        refresh_shifting_csv(self.workbook, self.output)
        rows = self.read_csv()
        self.assertEqual(rows[0]["lifting_count"], "50")
        self.assertEqual(rows[0]["shifting_count"], "")
        self.assertEqual(rows[2]["shifting_count"], "10")

    def test_failed_refresh_preserves_old_csv_and_raises(self):
        self.output.write_text("existing data", encoding="utf-8")
        self.workbook.write_bytes(b"not an xlsx file")
        with self.assertRaisesRegex(InputError, "Cannot refresh"):
            refresh_shifting_csv(self.workbook, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "existing data")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_missing_source_sheet_and_invalid_output_paths(self):
        with self.assertRaises(InputError):
            refresh_shifting_csv(self.workbook, self.output)
        write_workbook(self.workbook)
        with self.assertRaisesRegex(InputError, "Missing shifting worksheet"):
            refresh_shifting_csv(self.workbook, self.output, "Missing")
        with self.assertRaisesRegex(InputError, "separate .csv"):
            refresh_shifting_csv(self.workbook, self.workbook)


class WorkbookMainIntegrationTests(unittest.TestCase):
    setUp = main_tests.ExistingYardMainTests.setUp
    write_shifting = main_tests.ExistingYardMainTests.write_shifting

    def test_recording_uses_updated_workbook_on_every_load(self):
        workbook = self.root / "report.xlsx"
        write_workbook(workbook, lifting=200, shifting=20, old_shifting=None)
        text = self.input_path.read_text(encoding="utf-8")
        text = text.replace(
            'shifting_summary_file = "' + self.shifting_path.as_posix() + '"',
            'shifting_summary_file = "' + self.shifting_path.as_posix() + '"\n'
            'shifting_workbook_file = "' + workbook.as_posix() + '"',
        )
        self.input_path.write_text(text, encoding="utf-8")
        first = main_existing.build_report(self.input_path)
        self.assertEqual(first["lifting_count"], 200)
        self.assertEqual(first["shifting_count"], 20)
        self.assertEqual(first["missing_shifting_observations"], 0)
        self.assertAlmostEqual(first["shifting_percentage"], 100 * 20 / 220)
        self.assertEqual(first["shifting_workbook_source"], str(workbook.resolve()))
        write_workbook(workbook, lifting=500, shifting=100, week=45)
        second = main_existing.build_report(self.input_path)
        self.assertEqual(second["latest_week"], 45)
        self.assertEqual(second["lifting_count"], 500)
        self.assertEqual(second["shifting_count"], 100)
        self.assertAlmostEqual(second["shifting_percentage"], 100 * 100 / 600)
        workbook.unlink()
        with self.assertRaises(InputError):
            main_existing.build_report(self.input_path)


class WorkbookSharedInputTests(unittest.TestCase):
    setUp = shifting_tests.ShiftingInputTests.setUp
    settings = shifting_tests.ShiftingInputTests.settings

    def test_configuration_and_shared_loader_refresh_the_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook, output, mapping = (root / name for name in ("report.xlsx", "report.csv", "mapping.toml"))
            write_workbook(workbook)
            mapping.write_text('["CY 219 (Lini 2)"]\nSL = "10"\n', encoding="utf-8")
            self.document["csv"].update(
                shifting_summary_file=output.as_posix(),
                shifting_workbook_file=workbook.as_posix(),
                shifting_block_mapping_file=mapping.as_posix(),
                shifting_workbook_sheet="Per Alat Weekly",
            )
            settings = self.settings(self.document)
            first = load_yard_inputs(settings)["shifting_summary"]
            self.assertEqual(first[-1].shifting_count, 10)
            write_workbook(workbook, shifting=25)
            second = load_yard_inputs(settings)["shifting_summary"]
            self.assertEqual(second[-1].shifting_count, 25)

    def test_workbook_configuration_is_validated_without_opening_sources(self):
        self.document["csv"]["shifting_workbook_file"] = "../reports/source.xlsx"
        with self.assertRaisesRegex(ConfigurationError, "requires csv.shifting_summary_file"):
            self.settings(self.document)
        self.document["csv"]["shifting_summary_file"] = "../reports/output.csv"
        settings = self.settings(self.document)
        self.assertEqual(settings["shifting_workbook_sheet"], "Per Alat Daily")
        self.assertEqual(settings["shifting_workbook_file"].name, "source.xlsx")
        for invalid in ("", 123):
            self.document["csv"]["shifting_workbook_file"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                self.settings(self.document)


if __name__ == "__main__":
    unittest.main()

"""Select one complete closed day and record its midnight-WIB Unix boundaries."""

from contextlib import redirect_stdout
import csv
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from config import DEFAULT_INPUT_CONFIG_FILE
import main_existing
from repository import InputError, load_yard_inputs
from repository.shifting_csv_export import refresh_shifting_csv
from repository.shifting_dates import daily_boundaries, report_date
from repository.shifting_repository import load_shifting_summary
from tests import test_main_existing as main_tests
from tests.test_shifting_csv_export import write_workbook


CY = "CY 219 (Lini 2)"
TODAY = date(2026, 10, 28)
NOW = int(datetime(2026, 10, 27, 18, tzinfo=timezone.utc).timestamp())
HEADER = "cy_name,shifting_code,lifting_count,shifting_count,report_date\n"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def daily_workbook(path, lifting=200, shifting=20, latest="10/27/2026", serial=False):
    write_workbook(path, lifting=lifting, shifting=shifting)
    with ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(contents["xl/worksheets/sheet1.xml"])
    for cell in root.findall("m:sheetData/m:row/m:c", NS):
        if cell.get("r") in ("A10", "A11"):
            value = "10/26/2026" if cell.get("r") == "A10" else latest
            if serial:
                cell.attrib.pop("t", None)
                for child in list(cell):
                    cell.remove(child)
                ET.SubElement(cell, "{" + NS["m"] + "}v").text = str((date(2026, 10, 27) - date(1899, 12, 30)).days)
            else:
                cell.find("m:is/m:t", NS).text = value
    contents["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    contents["xl/workbook.xml"] = contents["xl/workbook.xml"].replace(b"Per Alat Weekly", b"Per Alat Daily")
    with ZipFile(path, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)


class DailyShiftingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.csv = self.root / "daily.csv"
        self.mapping = self.root / "mapping.toml"
        self.mapping.write_text('["' + CY + '"]\nSL = "11"\nRS = "10"\nABSENT = "9"\n', encoding="utf-8")

    def load(self, rows, **kwargs):
        self.csv.write_text(HEADER + rows, encoding="utf-8")
        return load_shifting_summary(self.csv, CY, self.mapping, {"10", "11"}, today=TODAY, **kwargs)

    def test_latest_closed_day_excludes_today_future_and_other_cys(self):
        rows = self.load(
            f"{CY},SL,200,20,2026-10-27\n{CY},RS,100,10,2026-10-27\n"
            f"{CY},SL,900,90,2026-10-28\n{CY},RS,900,90,2026-10-28\n"
            f"{CY},SL,wrong,count,2026-10-29\n{CY},RS,,,2026-10-29\n"
            "Other CY,SL,1,,2026-10-27\n"
            f"{CY},SL,invalid,old,2026-10-26\n"
        )
        self.assertEqual({row.report_date for row in rows}, {"2026-10-27"})
        self.assertEqual(sum(row.lifting_count for row in rows), 300)
        expected = int(datetime(2026, 10, 26, 17, tzinfo=timezone.utc).timestamp())
        self.assertEqual(rows[0].period_start, expected)
        self.assertEqual(rows[0].period_end, expected + 86400)

    def test_incomplete_latest_day_falls_back_without_combining_days(self):
        for latest in (
            f"{CY},SL,100,,2026-10-27\n{CY},RS,50,5,2026-10-27\n",
            f"{CY},SL,100,10,2026-10-27\n",
            f"{CY},SL,,,2026-10-27\n{CY},RS,,,2026-10-27\n",
        ):
            with self.subTest(latest=latest):
                rows = self.load(f"{CY},SL,20,2,2026-10-26\n{CY},RS,30,3,2026-10-26\n" + latest)
                self.assertEqual({row.report_date for row in rows}, {"2026-10-26"})
                self.assertEqual(sum(row.lifting_count for row in rows), 50)

    def test_missing_counts_for_absent_block_do_not_prevent_selection(self):
        rows = self.load(
            f"{CY},SL,200,20,2026-10-27\n{CY},RS,100,10,2026-10-27\n"
            f"{CY},ABSENT,10,,2026-10-27\n",
        )
        self.assertEqual(len(rows), 2)

    def test_absent_block_dates_duplicates_and_invalid_counts_have_no_effect(self):
        included = f"{CY},SL,200,20,2026-10-27\n{CY},RS,100,10,2026-10-27\n"
        expected = self.load(included)
        with warnings.catch_warnings(record=True) as messages:
            rows = self.load(included +
                f"{CY},ABSENT,bad,-1,invalid-date\n"
                f"{CY},ABSENT,,,2026-10-27\n"
                f"{CY},ABSENT,100,10,2026-10-27\n")
        self.assertEqual(rows, expected)
        self.assertEqual(messages, [])

    def test_all_absent_blocks_return_no_observations_without_date_validation(self):
        self.assertEqual(self.load(f"{CY},ABSENT,bad,,invalid-date\n"), [])

    def test_zero_counts_are_complete_and_no_complete_day_is_an_error(self):
        rows = self.load(f"{CY},SL,0,0,2026-10-27\n{CY},RS,0,0,2026-10-27\n")
        self.assertEqual(rows[0].lifting_count, 0)
        self.assertIsNone(main_existing.shifting_metrics(rows)["shifting_percentage"])
        for text in (
            f"{CY},SL,100,,2026-10-27\n{CY},RS,,,2026-10-27\n",
            f"{CY},SL,100,10,2026-10-28\n{CY},RS,100,10,2026-10-28\n",
        ):
            with self.subTest(text=text), self.assertRaisesRegex(InputError, "no complete daily"):
                self.load(text)

    def test_duplicate_codes_and_invalid_counts_do_not_produce_metrics(self):
        for text, error in (
            (f"{CY},SL,10,1,2026-10-27\n{CY},SL,10,1,2026-10-27\n{CY},RS,10,1,2026-10-27\n", "duplicate daily"),
            (f"{CY},SL,bad,1,2026-10-27\n{CY},RS,10,1,2026-10-27\n", "non-negative integer"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(InputError, error):
                self.load(text)

    def test_csv_unix_boundaries_must_match_the_date_in_wib(self):
        self.csv.write_text(
            HEADER.rstrip() + ",period_start\n" +
            f"{CY},SL,10,1,2026-10-27,0\n{CY},RS,10,1,2026-10-27,0\n", encoding="utf-8",
        )
        with self.assertRaisesRegex(InputError, "midnight WIB"):
            load_shifting_summary(self.csv, CY, self.mapping, {"10", "11"}, today=TODAY)

    def test_midnight_wib_handles_month_year_and_leap_day(self):
        for day in (date(2026, 1, 1), date(2026, 11, 1), date(2024, 2, 29)):
            start, end = daily_boundaries(day)
            self.assertEqual(end - start, 86400)
            self.assertEqual(datetime.fromtimestamp(start, timezone.utc).hour, 17)
        self.assertEqual(report_date("10/27/2026", month="2026-10"), date(2026, 10, 27))
        self.assertEqual(report_date("27/10/2026", month="2026-10"), date(2026, 10, 27))
        with self.assertRaises(InputError):
            report_date("10/31/2026", month="2026-11")

    def test_daily_workbook_exports_all_dates_and_midnight_unix_then_refreshes(self):
        workbook = self.root / "daily.xlsx"
        daily_workbook(workbook)
        original = workbook.read_bytes()
        self.assertEqual(refresh_shifting_csv(workbook, self.csv, "Per Alat Daily"), 4)
        with self.csv.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[2]["report_date"], "2026-10-27")
        self.assertEqual(int(rows[2]["period_end"]) - int(rows[2]["period_start"]), 86400)
        self.assertNotIn("week_number", rows[0])
        self.assertEqual(workbook.read_bytes(), original)
        daily_workbook(workbook, lifting=500, shifting=50)
        refresh_shifting_csv(workbook, self.csv, "Per Alat Daily")
        with self.csv.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(list(csv.DictReader(stream))[2]["lifting_count"], "500")
        daily_workbook(workbook, serial=True)
        refresh_shifting_csv(workbook, self.csv, "Per Alat Daily")
        with self.csv.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(list(csv.DictReader(stream))[0]["report_date"], "2026-10-27")


class DailyMainTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.input_path
        source = self.path.read_text(encoding="utf-8")
        start = source.index("[shifting_period]")
        end = source.index("[input.sources]", start)
        self.path.write_text(source[:start] + source[end:], encoding="utf-8")
        self.fixture.shifting_path.write_text(HEADER +
            f"{CY},SL,200,20,2026-10-27\n{CY},RS,100,10,2026-10-27\n"
            f"{CY},SL,999,999,2026-10-28\n{CY},RS,999,999,2026-10-28\n", encoding="utf-8")

    def test_main_needs_no_benchmark_and_uses_wib_day_at_utc_evening(self):
        with patch.object(main_existing, "time", return_value=NOW):
            report = main_existing.build_report(self.path)
        self.assertEqual(report["recorded_at"], NOW)
        self.assertEqual(report["latest_date"], "2026-10-27")
        self.assertEqual(report["period_granularity"], "daily")
        self.assertNotIn("latest_week", report)
        self.assertEqual(report["lifting_count"], 300)
        self.assertEqual(report["shifting_count"], 30)
        self.assertAlmostEqual(report["shifting_percentage"], 100 * 30 / 330)
        self.assertEqual(report["missing_lifting_observations"], 0)

    def test_shared_input_loader_also_selects_one_complete_day(self):
        settings = main_existing.load_input_config(self.path)
        with patch("repository.shifting_repository.today_wib", return_value=TODAY):
            inputs = load_yard_inputs(settings)
        self.assertEqual({row.report_date for row in inputs["shifting_summary"]}, {"2026-10-27"})

    def test_absent_block_observations_never_change_or_appear_in_recorded_report(self):
        with patch.object(main_existing, "time", return_value=NOW):
            expected = main_existing.build_report(self.path)
        with self.fixture.mapping_path.open("a", encoding="utf-8") as stream:
            stream.write('ABSENT = "9"\n')
        with self.fixture.shifting_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{CY},ABSENT,bad,,invalid-date\n{CY},ABSENT,,,2026-10-27\n")
        with patch.object(main_existing, "time", return_value=NOW), warnings.catch_warnings(record=True) as messages:
            report, yard = main_existing._build_report_and_yard(self.path)
        self.assertEqual(report, expected)
        self.assertEqual(messages, [])
        captured = io.StringIO()
        with patch.object(main_existing, "_build_report_and_yard", return_value=(report, yard)), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.fixture.root / "config" / "input.toml",
        ), patch.object(main_existing, "YardPresenter"), redirect_stdout(captured):
            main_existing.main()
        recorded = (self.fixture.root / "output" / "existing_yard_metrics.jsonl").read_text(encoding="utf-8")
        self.assertEqual(json.loads(recorded), expected)
        self.assertNotIn("ABSENT", recorded)
        self.assertNotIn("skipped_shifting", recorded)
        self.assertNotIn("Skipped shifting", captured.getvalue())

    def test_main_prints_daily_period_records_and_yard(self):
        with patch.object(main_existing, "time", return_value=NOW):
            report, yard = main_existing._build_report_and_yard(self.path)
        output = io.StringIO()
        with patch.object(main_existing, "_build_report_and_yard", return_value=(report, yard)), patch.object(
            main_existing, "DEFAULT_INPUT_CONFIG_FILE", self.fixture.root / "config" / "input.toml",
        ), patch.object(main_existing, "YardPresenter") as presenter, redirect_stdout(output):
            main_existing.main()
        self.assertIn("Latest complete operations date (WIB): 2026-10-27", output.getvalue())
        self.assertNotIn("operations week", output.getvalue())
        presenter.return_value.outYard.assert_called_once_with(yard)


if __name__ == "__main__":
    unittest.main()

"""Branch identity is resolved before containers enter yard coordinates."""

import unittest
from pathlib import Path
from unittest.mock import patch

from config import ConfigurationError, load_input_config
from repository import InputError, load_yard_inputs
from repository.branch_repository import BranchDirectory
from tests import test_main_existing as main_tests
import main_existing


def branch(branch_id="2", terminal_id="1", code="JKT74", name="CY 219 (Lini 2)"):
    return dict(branch_id=branch_id, terminal_id=terminal_id, branch_code=code, branch_name=name)


class BranchDirectoryTests(unittest.TestCase):
    def test_code_translation_preserves_internal_ids_and_display_name(self):
        directory = BranchDirectory([branch()])
        row = dict(container_id="BOX", branch_id=" jkt74 ", block_code="2C")
        self.assertEqual(directory.normalize_containers([row])[0]["branch_id"], "2")
        self.assertEqual(directory.codes_by_id, {"2": "JKT74"})
        self.assertEqual(directory.cy_name(), "CY219")
        self.assertEqual(directory.records[0]["branch_name"], "CY 219 (Lini 2)")
        self.assertEqual(row["branch_id"], " jkt74 ")

    def test_empty_unknown_and_ambiguous_references_fail(self):
        for rows in ([], [branch(code="")], [branch(), branch(code="jkt74", branch_id="3")],
                     [branch(), branch(terminal_id="2", code="OTHER")]):
            with self.subTest(rows=rows), self.assertRaises(InputError):
                BranchDirectory(rows)
        directory = BranchDirectory([branch()])
        row = dict(container_id="BOX", branch_id="UNKNOWN")
        with self.assertRaisesRegex(InputError, "unknown BRANCH"):
            directory.normalize_containers([row])
        self.assertEqual(directory.normalize_containers([row], scoped=True), [])

    def test_inbound_without_coordinates_remains_assignable(self):
        row = dict(container_id="INBOUND", branch_id="", block_code="")
        self.assertEqual(BranchDirectory([branch()]).normalize_containers([row]), [row])

    def test_multiple_branches_and_non_cy_names_require_explicit_reporting_scope(self):
        for records in ([branch(), branch("3", code="JKT75")], [branch(name="Jakarta")]):
            with self.subTest(records=records), self.assertRaises(ConfigurationError):
                BranchDirectory(records).cy_name()


class BranchLoadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_tests.ExistingYardMainTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.input_path

    def test_current_csv_fixture_derives_cy_and_loads_twenty_containers(self):
        report = main_existing.build_report(self.path)
        self.assertEqual(report["cy_name"], "CY219")
        self.assertEqual(report["branch"], branch())
        self.assertEqual(report["loaded_containers"], 20)
        self.assertNotIn("cy_name", load_input_config(self.path))

    def test_missing_reference_match_fails_before_reading_containers(self):
        self.path.write_text(self.path.read_text().replace("branch_id = 2", "branch_id = 999"))
        with self.assertRaisesRegex(InputError, "no branches match"):
            load_yard_inputs(load_input_config(self.path), include_shifting=False)

    def test_unfiltered_unknown_container_code_is_reported(self):
        settings = load_input_config(self.path)
        settings["filters"] = {}
        container_path = Path(settings["csv_files"]["existing_containers"])
        destination = self.fixture.root / "unknown.csv"
        destination.write_text(container_path.read_text().replace("JKT74", "UNKNOWN"))
        settings["csv_files"]["existing_containers"] = destination
        with self.assertRaisesRegex(InputError, "unknown BRANCH"):
            load_yard_inputs(settings, include_shifting=False)

    def test_multiple_branches_load_without_shifting_but_report_rejects_ambiguity(self):
        settings = load_input_config(self.path)
        reference_path = self.fixture.root / "branches.csv"
        reference_path.write_text(
            "BRANCH_ID,TERMINAL_ID,BRANCH_CODE,BRANCH_NAME\n"
            "2,1,JKT74,CY 219 (Lini 2)\n3,1,JKT75,CY 220\n"
        )
        settings["csv_files"]["terminal_branches"] = reference_path
        settings["filters"] = {}
        inputs = load_yard_inputs(settings, include_shifting=False)
        self.assertEqual(len(inputs["terminal_branches"]), 2)
        with self.assertRaisesRegex(ConfigurationError, "exactly one branch"):
            load_yard_inputs(settings)
        with patch.object(main_existing, "load_input_config", return_value=settings):
            with self.assertRaisesRegex(ConfigurationError, "exactly one branch"):
                main_existing.build_report(self.path)


if __name__ == "__main__":
    unittest.main()

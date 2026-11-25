"""Block borders affect placements and survive simulator data exports."""

from io import BytesIO
import base64
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from entities.feasibility.equipment_access import BlockBorderAccessPolicy
from repository.block_accessibility import access_policies, policies_csv, read_policies
from stacking_ui.configuration import PROJECT_ROOT, dump_toml
from stacking_ui.scenario import prepare_scenario, public_preview
from stacking_ui.session import SimulationSession
from stacking_ui.simulation import SimulationError
from tests import test_stacking_scenario


class BlockAccessibilityTests(unittest.TestCase):
    def fixture(self):
        fixture = test_stacking_scenario.ScenarioTests()
        fixture.setUp()
        fixture.rows["master_equipment"] = []
        fixture.rows["equipment_history"] = []
        fixture.rows["existing_containers"] = []
        fixture.write_files()
        return fixture

    def test_csv_round_trip_and_strict_values(self):
        policies = {"10": BlockBorderAccessPolicy(above=False, left=False)}
        self.assertEqual(read_policies(policies_csv(policies)), policies)
        row = dict(block_id="10", above="FALSE", below="TRUE", left="TRUE", right="TRUE")
        for records in ([row, row], [row | {"above": "maybe"}], [row | {"block_id": ""}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                access_policies(records)

    def test_csv_import_reaches_map_and_loader_checks(self):
        fixture = self.fixture()
        fixture.rows["block_accessibility"] = [dict(block_id="10", **dict.fromkeys(("above", "below", "left", "right"), "FALSE"))]
        fixture.write_files()
        scenario = prepare_scenario(fixture.payload)
        branch, = scenario["branches"]
        block, = public_preview(scenario)["branches"][0]["yard_map"]["blocks"]
        self.assertEqual(block["id"], "10")
        self.assertEqual(block["border_access"], dict.fromkeys(("above", "below", "left", "right"), False))
        self.assertEqual(branch["yard"].findCoordsCandidates(SimpleNamespace(getContSize=lambda: "20"))[2], [])

    def test_legacy_missing_optional_upload_defaults_to_open(self):
        fixture = self.fixture()
        del fixture.payload["files"]["block_accessibility"]
        inputs = tomllib.loads(fixture.payload["input_toml"])
        del inputs["input"]["sources"]["block_accessibility"]
        del inputs["csv"]["files"]["block_accessibility"]
        fixture.payload["input_toml"] = dump_toml(inputs)
        mapping = tomllib.loads(fixture.payload["mapping_toml"])
        del mapping["csv"]["block_accessibility"]
        fixture.payload["mapping_toml"] = dump_toml(mapping)
        branch, = public_preview(prepare_scenario(fixture.payload))["branches"]
        self.assertTrue(all(branch["yard_map"]["blocks"][0]["border_access"].values()))

    def test_live_changes_affect_first_step_and_lock_after_start(self):
        fixture = self.fixture()
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": fixture.payload})
        request = dict(op="update_block_access", id=response["simulation"]["id"], branch="JKT74",
                       policies=[dict(block_id="10", **dict.fromkeys(("above", "below", "left", "right"), False))])
        session.request(request)
        step = session.request(dict(op="step", id=request["id"], branch="JKT74", position=1))
        self.assertEqual(step["row"]["status"], "unplaced")
        with self.assertRaisesRegex(SimulationError, "locked"):
            session.request(request)

    def test_unknown_blocks_and_stale_preview_are_rejected(self):
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": self.fixture().payload})
        request = dict(op="update_block_access", id=response["simulation"]["id"], branch="JKT74",
                       policies=[dict(block_id="other", **dict.fromkeys(("above", "below", "left", "right"), True))])
        with self.assertRaisesRegex(SimulationError, "unknown block"):
            session.request(request)
        with self.assertRaisesRegex(SimulationError, "fresh preview"):
            session.request(request | {"id": "old"})

    def test_saved_csv_keeps_other_blocks_and_is_in_bundled_download(self):
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": self.fixture().payload})
        session.request(dict(op="update_block_access", id=response["simulation"]["id"], branch="JKT74",
                             policies=[dict(block_id="10", above=False, below=True, left=False, right=True)]))
        with TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "block_accessibility.csv"
            other = BlockBorderAccessPolicy(right=False)
            path.write_text(policies_csv({"999": other}), encoding="utf-8", newline="")
            with patch.object(session, "block_access_path", return_value=path):
                saved = session.request({"op": "save_block_access", "id": response["simulation"]["id"],
                                         "branch": "JKT74", "block_id": "10"})
                self.assertEqual(read_policies(saved["text"])["999"], other)
                self.assertFalse(read_policies(saved["text"])["10"].above)
                with patch("stacking_ui.session.load_input_config", return_value={"csv_files": {"block_accessibility": path}}):
                    archive = session.request({"op": "bundled_csvs"})
                with ZipFile(BytesIO(base64.b64decode(archive["base64"]))) as bundle:
                    self.assertEqual(bundle.read(path.relative_to(PROJECT_ROOT).as_posix()).decode(), saved["text"])
                restored = SimulationSession()
                with patch.object(restored, "block_access_path", return_value=path):
                    restored.request({"op": "restore_block_access", "text": saved["text"]})
                    self.assertEqual(read_policies(path.read_text()), read_policies(saved["text"]))

    def test_each_save_only_persists_its_block_and_preserves_other_dirty_baselines(self):
        fixture = self.fixture()
        fixture.rows["yard_blocks"].append(fixture.rows["yard_blocks"][0] | {"block_id": "11", "block_code": "B"})
        fixture.write_files()
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": fixture.payload})
        identity = {"id": response["simulation"]["id"], "branch": "JKT74"}
        session.request({"op": "update_block_access", **identity, "policies": [
            dict(block_id="10", above=False, below=True, left=True, right=True),
            dict(block_id="11", above=True, below=True, left=False, right=True),
        ]})
        with TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "block_accessibility.csv"
            path.write_text(policies_csv({}), encoding="utf-8", newline="")
            with patch.object(session, "block_access_path", return_value=path):
                saved = session.request({"op": "save_block_access", **identity, "block_id": "10"})
            policies = read_policies(saved["text"])
            self.assertEqual(set(policies), {"10"})
            self.assertFalse(policies["10"].above)
            repaired = session.request({"op": "repair_tier_gaps", **identity})
            blocks = {block["id"]: block for block in repaired["yard_map"]["blocks"]}
            self.assertEqual(blocks["10"]["border_access"], blocks["10"]["saved_border_access"])
            self.assertFalse(blocks["11"]["border_access"]["left"])
            self.assertTrue(blocks["11"]["saved_border_access"]["left"])

    def test_round_trip_on_empty_csv_does_not_add_a_default_row(self):
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": self.fixture().payload})
        identity = {"id": response["simulation"]["id"], "branch": "JKT74"}
        row = dict(block_id="10", above=False, below=True, left=True, right=True)
        session.request({"op": "update_block_access", **identity, "policies": [row]})
        session.request({"op": "update_block_access", **identity, "policies": [row | {"above": True}]})
        with TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "block_accessibility.csv"
            path.write_text(policies_csv({}), encoding="utf-8", newline="")
            original = path.read_bytes()
            with patch.object(session, "block_access_path", return_value=path), patch.object(session, "write_block_access") as write:
                saved = session.request({"op": "save_block_access", **identity, "block_id": "10"})
                write.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(read_policies(saved["text"]), {})

    def test_save_requires_current_preview_and_one_known_block(self):
        session = SimulationSession()
        response = session.request({"op": "preview", "draft": self.fixture().payload})
        request = {"op": "save_block_access", "id": response["simulation"]["id"], "branch": "JKT74", "block_id": "10"}
        for overrides in ({"id": "stale"}, {"branch": "unknown"}, {"block_id": "unknown"}, {"block_id": None}):
            with self.subTest(overrides=overrides), self.assertRaises(SimulationError):
                session.request(request | overrides)


if __name__ == "__main__":
    unittest.main()

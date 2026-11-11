"""Scenario preparation reuses stacking imports without assigning containers."""

from copy import deepcopy
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tomllib
import unittest
from unittest.mock import patch
import zipfile

from config.application.config_loader import ConfigurationError, parse_config
from config.csv_import.mapping_loader import parse_mapping
from filewriter import ContainerFileWriter
from stacking_ui.configuration import defaults, dump_toml
from stacking_ui.scenario import prepare_scenario, public_preview
from stacking_ui.simulation import Simulation, SimulationError, export_yard_csv
from stacking_ui.__main__ import main


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.payload = defaults()
        self.profiles = parse_mapping(tomllib.loads(self.payload["mapping_toml"]))
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["filters"]["branch_code"] = ["JKT74"]
        self.payload["input_toml"] = dump_toml(document)
        self.payload["files"] = {}
        self.rows = {name: [] for name in self.profiles}
        self.rows.update({
            "terminal_branches": [dict(branch_id="2", terminal_id="1", branch_code="JKT74", branch_name="Test yard")],
            "yard_blocks": [dict(block_id="10", terminal_id="1", branch_id="2", block_code="A",
                                 row_count="2", slot_count="4", max_tier="3", pos_x="0", pos_y="0")],
            "master_equipment": [dict(equipment_code="RTG1", equipment_type="RTG")],
            "equipment_history": [dict(equipment_code="RTG1", branch_id="JKT74", block_code="A", row_no="1", slot_no="1", move_time="")],
            "existing_containers": [dict(container_id="OLD", container_size="20", branch_id="JKT74", block_code="A", row_no="1", slot_no="1", tier_no="1", weight="100")],
            "inbound_containers": [dict(container_id="NEW1", container_size="20"), dict(container_id="NEW2", container_size="40")],
        })
        self.write_files()

    def write_files(self):
        for name, profile in self.profiles.items():
            headers = list(dict.fromkeys([
                *(profile.columns.get(field, field) for field in profile.schema.fields),
                *profile.filter_columns.values(),
            ]))
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            for row in self.rows[name]:
                writer.writerow({profile.columns.get(key, profile.filter_columns.get(key, key)): value
                                 for key, value in row.items()})
            self.payload["files"][name] = {"name": name + ".csv", "content": stream.getvalue()}

    def preview(self):
        self.write_files()
        return public_preview(prepare_scenario(self.payload))

    def test_builds_yard_and_ordered_queue_without_placement_or_payload_mutation(self):
        original = deepcopy(self.payload)
        result = prepare_scenario(self.payload)
        self.assertEqual(self.payload, original)
        branch, = result["branches"]
        self.assertEqual(list(branch["yard"].containers), ["OLD"])
        self.assertEqual([row["container_id"] for row in branch["queue"]], ["NEW1", "NEW2"])
        self.assertEqual(branch["queue"][0]["sources"], [{"file": "inbound_containers.csv", "line": 2}])
        preview = public_preview(result)
        self.assertTrue(preview["ready"], preview)
        json.dumps(preview, allow_nan=False)

    def test_multiple_branches_get_independent_yards_and_unscoped_inbound(self):
        self.rows["terminal_branches"].append(dict(branch_id="3", terminal_id="1", branch_code="JKT64", branch_name="Second yard"))
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {"block_id": "11", "branch_id": "3"})
        self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"branch_id": "JKT64"})
        self.rows["existing_containers"].append(self.rows["existing_containers"][0] | {"branch_id": "JKT64", "container_id": "OTHER"})
        self.rows["inbound_containers"].append(dict(container_id="SCOPED", container_size="20", branch_id="JKT64"))
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["filters"]["branch_code"] = ["JKT74", "JKT64"]
        self.payload["input_toml"] = dump_toml(document)
        mapping = tomllib.loads(self.payload["mapping_toml"])
        for branch_kind, branch_value in (("code", "JKT64"), ("id", "3")):
            with self.subTest(branch_kind=branch_kind):
                mapping["csv"]["inbound_containers"]["branch_kind"] = branch_kind
                self.payload["mapping_toml"] = dump_toml(mapping)
                self.profiles = parse_mapping(mapping)
                self.rows["inbound_containers"][-1]["branch_id"] = branch_value
                self.write_files()
                result = prepare_scenario(self.payload)
                first, second = result["branches"]
                self.assertTrue(public_preview(result)["ready"], public_preview(result))
                self.assertIsNot(first["yard"], second["yard"])
                self.assertEqual(list(first["yard"].containers), ["OLD"])
                self.assertEqual(list(second["yard"].containers), ["OTHER"])
                self.assertEqual(len(first["queue"]), 2)
                self.assertEqual(len(second["queue"]), 3)
                self.assertEqual(second["queue"][-1]["sources"][0]["line"], 4)

    def test_yard_export_round_trips_active_mapping_and_placed_containers(self):
        for custom_headers, branch_kind in ((False, "code"), (True, "code"), (True, "id")):
            with self.subTest(custom_headers=custom_headers, branch_kind=branch_kind):
                self.setUp()
                mapping = tomllib.loads(self.payload["mapping_toml"])
                profile = mapping["csv"]["existing_containers"]
                profile["branch_kind"] = branch_kind
                if custom_headers:
                    profile["columns"] = {field: "custom_" + field
                                          for field in self.profiles["existing_containers"].schema.fields}
                    # Omitted mappings use the domain field as the CSV header.
                    del profile["columns"]["weight"]
                    profile["columns"].update(row_no="SLOT", slot_no="ROW")
                if branch_kind == "id":
                    profile["filter_columns"] = {
                        "branch_id": profile["columns"]["branch_id"],
                        "terminal_id": "TERMINAL", "branch_code": "YARD_CODE",
                    }
                    self.rows["existing_containers"][0].update(
                        branch_id="2", terminal_id="1", branch_code="JKT74")
                self.payload["mapping_toml"] = dump_toml(mapping)
                self.profiles = parse_mapping(mapping)
                self.write_files()
                scenario = prepare_scenario(self.payload)
                self.assertTrue(public_preview(scenario)["ready"], public_preview(scenario))
                simulation = Simulation(scenario)
                for position in (1, 2):
                    step = simulation.step(simulation.id, "JKT74", position)
                    self.assertEqual(step["row"]["status"], "placed")
                branch, = scenario["branches"]
                expected = ContainerFileWriter("unused.csv").buildRows(branch["yard"])
                exported = export_yard_csv(scenario["branches"])
                records = list(csv.DictReader(io.StringIO(exported)))
                self.assertEqual(len(records), 3)  # Includes the 40-foot container once.
                self.assertEqual(records[0][profile["columns"]["branch_id"]],
                                 "2" if branch_kind == "id" else "JKT74")
                if branch_kind == "id":
                    self.assertTrue(all(row["TERMINAL"] == "1" and row["YARD_CODE"] == "JKT74"
                                        for row in records))
                self.rows["inbound_containers"] = []
                self.write_files()
                self.payload["files"]["existing_containers"]["content"] = exported
                reimported = prepare_scenario(self.payload)
                self.assertTrue(public_preview(reimported)["ready"], public_preview(reimported))
                self.assertEqual(ContainerFileWriter("unused.csv").buildRows(
                    reimported["branches"][0]["yard"]), expected)

    def test_yard_export_preserves_each_branch_scope(self):
        self.rows["terminal_branches"].append(dict(
            branch_id="3", terminal_id="1", branch_code="JKT64", branch_name="Second yard"))
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {"block_id": "11", "branch_id": "3"})
        self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"branch_id": "JKT64"})
        self.rows["existing_containers"].append(
            self.rows["existing_containers"][0] | {"branch_id": "JKT64", "container_id": "OTHER"})
        self.rows["inbound_containers"] = []
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["filters"]["branch_code"] = ["JKT74", "JKT64"]
        self.payload["input_toml"] = dump_toml(document)
        self.write_files()
        scenario = prepare_scenario(self.payload)
        self.assertTrue(public_preview(scenario)["ready"], public_preview(scenario))
        self.payload["files"]["existing_containers"]["content"] = export_yard_csv(scenario["branches"])
        reimported = prepare_scenario(self.payload)
        self.assertTrue(public_preview(reimported)["ready"], public_preview(reimported))
        self.assertEqual([list(branch["yard"].containers) for branch in reimported["branches"]],
                         [["OLD"], ["OTHER"]])

    def test_duplicate_queue_ids_are_not_removed_and_link_to_source(self):
        self.rows["inbound_containers"] += [dict(container_id="NEW1", container_size="20"), dict(container_id="OLD", container_size="20")]
        preview = self.preview()
        branch, = preview["branches"]
        self.assertFalse(preview["ready"])
        self.assertEqual([row["status"] for row in branch["queue"]], ["pending", "pending", "invalid", "invalid"])
        self.assertEqual([row["sources"][0]["line"] for row in branch["queue"]], [2, 3, 4, 5])
        self.assertEqual([item["sources"][0]["line"] for item in branch["issues"]], [4, 5])

    def test_simulation_skips_invalid_rows_and_places_each_footprint_once(self):
        self.rows["inbound_containers"].insert(0, dict(container_id="OLD", container_size="20"))
        self.write_files()
        scenario = prepare_scenario(self.payload)
        branch, = scenario["branches"]
        simulation = Simulation(scenario)

        def step(position):
            return simulation.step(simulation.id, "JKT74", position)

        with self.assertRaises(SimulationError):
            step(2)
        skipped = step(1)
        self.assertEqual(skipped["row"]["status"], "invalid")
        self.assertIsNone(skipped["calculation"])
        self.assertEqual(list(branch["yard"].containers), ["OLD"])
        self.assertEqual(step(2)["row"]["status"], "placed")
        result = step(3)
        self.assertEqual(result["row"]["status"], "placed")
        calculation = result["calculation"]
        self.assertEqual(calculation["checked"], 8)
        self.assertGreater(calculation["rejections"]["invalid_forty_foot_anchor"], 0)
        self.assertLessEqual(calculation["candidate_count"], 8 - sum(calculation["rejections"].values()))
        self.assertGreaterEqual(calculation["winning_score_ties"], 1)
        self.assertEqual(list(branch["yard"].containers), ["OLD", "NEW1", "NEW2"])
        placement = result["placement"]
        winner, = [candidate for candidate in calculation["candidates"] if candidate["selected"]]
        self.assertEqual([winner[key] for key in ("block", "row", "slot", "tier")],
                         [placement[key] for key in ("block", "row", "slot", "tier")])
        self.assertEqual([stack["slot"] for stack in placement["stacks"]], [placement["slot"] - 1, placement["slot"]])
        for stack in placement["stacks"]:
            self.assertEqual(stack["tiers"][-1]["container_id"], "NEW2")
            self.assertEqual(stack["tiers"][-1]["tier"], placement["tier"])
        self.assertEqual(step(3), result)
        self.assertEqual(list(branch["yard"].containers), ["OLD", "NEW1", "NEW2"])
        with self.assertRaises(SimulationError):
            step(4)
        json.dumps(result, allow_nan=False)

    def test_simulation_trace_only_lists_locations_passing_parameter_selection(self):
        self.rows["parameters"] = [dict(parameter_id="38", parameter_name="20 ft", container_size="20",
                                         container_size_score="2", terminal_id="1", branch_id="2")]
        self.rows["yard_planning"] = [dict(parameter_id="38", block_id="10", row_no="2", slot_no="3",
                                            terminal_id="1", branch_id="2")]
        self.write_files()
        scenario = prepare_scenario(self.payload)
        block, = public_preview(scenario)["branches"][0]["yard_map"]["blocks"]
        self.assertEqual(block["parameter_compliance"], 0)
        simulation = Simulation(scenario)
        step = simulation.step(simulation.id, "JKT74", 1)
        self.assertEqual(step["placement"]["parameter_compliance"], 0.5)
        calculation = step["calculation"]
        candidates = calculation["candidates"]

        self.assertGreater(calculation["checked"] - sum(calculation["rejections"].values()), len(candidates))
        self.assertEqual(calculation["candidate_count"], 1)
        candidate, = candidates
        self.assertTrue(candidate["selected"])
        self.assertEqual((candidate["row"], candidate["slot"]), (2, 3))
        self.assertAlmostEqual(candidate["score"], candidate["mass_multiplier"] *
                               candidate["distance_multiplier"] * candidate["cluster_multiplier"])

    def test_simulation_advances_when_no_stack_qualifies(self):
        self.rows["existing_containers"] = []
        self.rows["removed_slots"] = [
            dict(block_id="10", row_no=str(row), slot_no=str(slot))
            for row in range(1, 3) for slot in range(1, 5)
        ]
        self.write_files()
        scenario = prepare_scenario(self.payload)
        block, = public_preview(scenario)["branches"][0]["yard_map"]["blocks"]
        self.assertIsNone(block["parameter_compliance"])
        simulation = Simulation(scenario)
        for position in (1, 2):
            result = simulation.step(simulation.id, "JKT74", position)
            self.assertEqual(result["row"]["status"], "unplaced")
            self.assertIsNone(result["placement"])
            self.assertEqual(result["calculation"]["rejections"], {"stack_unavailable": 8})
            self.assertEqual(result["calculation"]["candidates"], [])
        self.assertFalse(scenario["branches"][0]["yard"].containers)

    def test_invalid_container_date_has_filename_line_and_field(self):
        self.rows["existing_containers"][0]["move_time"] = "not a date"
        preview = self.preview()
        problem = preview["branches"][0]["issues"][0]
        self.assertEqual(problem["field"], "move_time")
        self.assertEqual(problem["sources"], [{"file": "existing_containers.csv", "line": 2}])
        self.assertFalse(preview["ready"])

    def test_map_preserves_tier_gaps_paired_footprints_and_assigned_rules(self):
        self.rows["parameters"] = [dict(parameter_id="38", parameter_name="GRADING PG",
                                         container_grade="PG", container_grade_score="2",
                                         terminal_id="1", branch_id="2")]
        self.rows["yard_planning"] = [dict(parameter_id="38", block_id="10", row_no="2", slot_no="2",
                                            terminal_id="1", branch_id="2")]
        self.rows["removed_slots"] = [dict(block_id="10", row_no="2", slot_no="4")]
        self.rows["existing_containers"].append(dict(
            container_id="PAIR", container_size="40", branch_id="JKT74", block_code="A",
            row_no="2", slot_no="2", tier_no="2",
        ))

        view = self.preview()["branches"][0]["yard_map"]
        block, = view["blocks"]
        self.assertEqual((block["x"], block["y"], block["rows"], block["slots"]), (0, 0, 2, 4))
        self.assertEqual((block["container_count"], block["occupied_tiers"], block["tier_capacity"]), (2, 3, 21))
        left, right = block["stacks"][4:6]
        self.assertTrue(left["anomaly"] and right["anomaly"])
        self.assertEqual(left["tiers"], right["tiers"])
        self.assertEqual((right["tiers"][0]["tier"], right["tiers"][0]["anchor_slot"]), (2, 2))
        self.assertEqual(right["parameters"], ["38"])
        self.assertTrue(block["stacks"][-1]["removed"])
        self.assertEqual(view["parameters"]["38"]["criteria"], [{"label": "Grade", "value": "PG", "points": 2}])

    def test_invalid_inbound_date_keeps_yard_map_and_reports_queue_row(self):
        self.rows["inbound_containers"][0]["move_time"] = "not a date"
        preview = self.preview()
        branch, = preview["branches"]
        self.assertFalse(preview["ready"])
        self.assertTrue(branch["yard_map"]["blocks"])
        self.assertEqual([row["status"] for row in branch["queue"]], ["invalid", "pending"])
        issue, = branch["issues"]
        self.assertEqual(issue["field"], "move_time")
        self.assertEqual(issue["sources"], [{"file": "inbound_containers.csv", "line": 2}])

    def test_unknown_block_dropped_by_legacy_scope_is_reported(self):
        self.rows["existing_containers"][0]["block_code"] = "UNKNOWN"
        preview = self.preview()
        self.assertFalse(preview["ready"])
        self.assertIn("Unknown block", preview["branches"][0]["issues"][0]["message"])

    def test_invalid_block_dimensions_use_domain_validation_and_source(self):
        self.rows["yard_blocks"][0]["max_tier"] = "0"
        preview = self.preview()
        problem = next(item for item in preview["branches"][0]["issues"] if item["category"] == "block")
        self.assertIn("max_tier", problem["message"])
        self.assertEqual(problem["sources"][0]["line"], 2)

    def test_missing_equipment_blocks_readiness_but_keeps_preview(self):
        self.rows["master_equipment"] = []
        preview = self.preview()
        self.assertFalse(preview["ready"])
        self.assertEqual(preview["branches"][0]["summary"]["existing_containers"], 1)
        self.assertIn("no RTG", preview["branches"][0]["issues"][0]["message"])

    def test_missing_file_is_not_silently_empty(self):
        del self.payload["files"]["parameters"]
        preview = public_preview(prepare_scenario(self.payload))
        self.assertFalse(preview["ready"])
        self.assertEqual(preview["issues"][0]["dataset"], "parameters")

    def test_bad_headers_and_row_shape_report_original_filename(self):
        self.payload["files"]["yard_blocks"] = {"name": "my-blocks.csv", "content": "X\n1\n"}
        preview = public_preview(prepare_scenario(self.payload))
        self.assertIn("my-blocks.csv", preview["issues"][0]["message"])
        self.assertIn("missing required", preview["issues"][0]["message"])

    def test_no_branch_is_rejected(self):
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["filters"] = {}
        self.payload["input_toml"] = dump_toml(document)
        with self.assertRaisesRegex(ConfigurationError, "branch"):
            prepare_scenario(self.payload)

    def test_sql_is_rejected_before_any_connection(self):
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["sources"]["yard_blocks"] = "sql"
        self.payload["input_toml"] = dump_toml(document)
        with self.assertRaisesRegex(ConfigurationError, "CSV sources only"):
            prepare_scenario(self.payload)

    def test_toml_settings_roundtrip_and_validation(self):
        document = {"feasibility": {"loader_access": False}, "heuristic": {"size_cluster_radius": 0}}
        self.assertEqual(tomllib.loads(dump_toml(document)), document)
        self.assertFalse(parse_config(document).feasibility.loader_access)
        with self.assertRaises(ConfigurationError):
            parse_config({"heuristic": {"hl_equipment_distance": 0}})
        with self.assertRaises(ConfigurationError):
            parse_config({"heuristc": {}})

    def test_simulator_validates_loader_modes_and_round_trips_mixed_mode(self):
        self.payload["config_toml"] = (
            '[feasibility]\nloader_access_mode = "heuristic"\n'
            'preserve_future_loader_access_mode = "feasibility"\n'
        )
        with self.assertRaisesRegex(ConfigurationError, "exceeds"):
            prepare_scenario(self.payload)
        self.payload["config_toml"] = (
            '[feasibility]\nloader_access_mode = "feasibility"\n'
            'preserve_future_loader_access_mode = "heuristic"\n'
        )
        preview = self.preview()
        self.assertTrue(preview["ready"], preview)
        settings = parse_config(tomllib.loads(preview["config_toml"])).feasibility
        self.assertEqual(settings.effective_loader_access_mode, "feasibility")
        self.assertEqual(settings.effective_future_loader_access_mode, "heuristic")

    def test_worker_reads_current_project_tomls_on_each_request(self):
        with TemporaryDirectory() as directory:
            files = {key: Path(directory) / (key + ".toml") for key in ("config_toml", "input_toml", "mapping_toml")}
            original = {key: self.payload[key] for key in files}
            for key, path in files.items():
                path.write_text(original[key], encoding="utf-8")
            updated = "[feasibility]\nloader_access = false\n"

            def requests():
                yield b'{"op":"project_tomls"}\n'
                files["config_toml"].write_text(updated, encoding="utf-8")
                yield b'{"op":"project_tomls"}\n'

            output = io.StringIO()
            with patch("stacking_ui.configuration.TOML_FILES", files), patch(
                "sys.stdin", SimpleNamespace(buffer=requests()),
            ), redirect_stdout(output):
                main(["--simulation-stdin"])

            first, second = map(json.loads, output.getvalue().splitlines())
            self.assertEqual(first["result"], original)
            self.assertEqual(second["result"], original | {"config_toml": updated})

    def test_bundle_is_portable_and_upload_names_cannot_write_paths(self):
        self.payload["files"]["yard_blocks"]["name"] = "../../escape.csv"
        document = tomllib.loads(self.payload["input_toml"])
        document["csv"]["files"]["yard_blocks"] = "C:/never/read/this.csv"
        self.payload["input_toml"] = dump_toml(document)
        self.assertTrue(public_preview(prepare_scenario(self.payload))["ready"])
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            draft = Path(directory) / "scenario draft.json"
            draft.write_text(json.dumps(self.payload), encoding="utf-8")
            main([str(draft), "--bundle"])
            with zipfile.ZipFile(draft.with_suffix(".zip")) as bundle:
                self.assertNotIn("../../escape.csv", bundle.namelist())
                config = tomllib.loads(bundle.read("container_stacking_input.toml").decode())
                self.assertEqual(config["csv"]["files"]["yard_blocks"], "yard_blocks.csv")
                self.assertEqual(len(bundle.namelist()), 12)

    def test_offline_draft_uses_project_defaults_and_mapped_empty_csv(self):
        # The HTML page leaves unset TOML fields null and sends an empty marker.
        mapping = tomllib.loads(self.payload["mapping_toml"])
        mapping["csv"]["removed_slots"]["columns"]["block_id"] = "CUSTOM_BLOCK"
        draft_payload = {
            "version": 1,
            "files": self.payload["files"] | {"removed_slots": {"name": "removed_slots.csv", "empty": True}},
            "config_toml": None,
            "input_toml": None,
            "mapping_toml": dump_toml(mapping),
            "branch_codes": ["JKT74"],
        }
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            draft = Path(directory) / "scenario draft.json"
            draft.write_text(json.dumps(draft_payload), encoding="utf-8")
            main([str(draft), "--bundle"])
            preview = json.loads(draft.with_suffix(".preview.json").read_text(encoding="utf-8"))
            self.assertEqual(preview["kind"], "stacking-preview")
            self.assertTrue(preview["ready"], preview)
            self.assertEqual([branch["branch_code"] for branch in preview["branches"]], ["JKT74"])
            self.assertEqual(preview["datasets"]["removed_slots"]["rows"], 0)
            with zipfile.ZipFile(draft.with_suffix(".zip")) as bundle:
                self.assertIn(b"CUSTOM_BLOCK", bundle.read("removed_slots.csv"))

    def test_folder_draft_reads_configured_csvs_and_reports_missing_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            input_path = root / "config" / "container_stacking" / "container_stacking_input.toml"
            input_path.parent.mkdir(parents=True)
            data = root / "yard-data"
            data.mkdir()
            document = tomllib.loads(self.payload["input_toml"])
            del document["input"]["sources"]
            for name, upload in self.payload["files"].items():
                filename = "local_" + upload["name"]
                document["csv"]["files"][name] = "../../yard-data/" + filename
                if name != "inbound_containers":
                    (data / filename).write_text(upload["content"], encoding="utf-8", newline="")

            draft = self.payload | {"file_source": "folder", "files": {},
                                    "input_toml": dump_toml(document)}
            with patch("stacking_ui.configuration.PROJECT_ROOT", root), patch(
                "stacking_ui.configuration.DEFAULT_STACKING_INPUT_CONFIG_FILE", input_path,
            ):
                preview = public_preview(prepare_scenario(draft))
                self.assertFalse(preview["ready"])
                self.assertEqual([item["dataset"] for item in preview["issues"]], ["inbound_containers"])
                self.assertEqual(
                    preview["issues"][0]["message"],
                    "Configured CSV file not found: ../../yard-data/local_inbound_containers.csv",
                )
                branch, = preview["branches"]
                self.assertFalse(branch["ready"])
                self.assertFalse(branch["inbound_available"])
                self.assertNotIn("inbound_containers", branch["summary"])
                self.assertEqual(branch["yard_map"]["blocks"][0]["container_count"], 1)

                draft["files"]["inbound_containers"] = {"empty": True}
                preview = public_preview(prepare_scenario(draft))
                self.assertTrue(preview["ready"], preview)
                self.assertEqual(preview["datasets"]["yard_blocks"]["file"], "local_yard_blocks.csv")
                self.assertEqual(preview["branches"][0]["queue"], [])


if __name__ == "__main__":
    unittest.main()

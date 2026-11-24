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
from stacking_ui.comparison import compare_yard
from stacking_ui.configuration import defaults, dump_toml
from stacking_ui.scenario import prepare_scenario, public_preview
from stacking_ui.session import SimulationSession
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

    def test_sd179_mixed_case_dummy_loader_is_registered_and_used(self):
        self.payload["branch_codes"] = ["SD179"]
        self.rows["terminal_branches"] = [dict(
            branch_id="15", terminal_id="13", branch_code="SD179", branch_name="Surabaya",
        )]
        self.rows["yard_blocks"] = [self.rows["yard_blocks"][0] | dict(
            block_id=block_id, branch_id="15", terminal_id="13", block_code=code,
        ) for block_id, code in (("60", "Repair"), ("59", "G"))]
        self.rows["existing_containers"] = []
        self.rows["master_equipment"] = [dict(equipment_code="SL.Dummy.SD179", equipment_type="SL")]
        self.rows["equipment_history"] = [dict(
            equipment_code="SL.Dummy.SD179", branch_id="SD179", block_code="Repair",
            row_no="1", slot_no="1", move_time="",
        )]
        self.write_files()

        scenario = prepare_scenario(self.payload)
        branch, = scenario["branches"]
        loader, = branch["yard"].master_loaders
        self.assertEqual(loader.getCode(), "SL.DUMMY.SD179")
        self.assertEqual(loader.getCoords(), ("60", 0, 0))
        self.assertTrue(all(branch["yard"].canServeBlock(block)
                            for block in branch["yard"].blocks_by_id.values()))
        self.assertEqual(branch["issues"], [])
        self.assertTrue(public_preview(scenario)["ready"])
        simulation = Simulation(scenario)
        step = simulation.step(simulation.id, "SD179", 1)
        self.assertEqual(step["row"]["status"], "placed")
        selected, = [candidate for candidate in step["calculation"]["candidates"] if candidate["selected"]]
        self.assertEqual(selected["equipment"], "SL.DUMMY.SD179")

    def test_zero_prefixed_branch_codes_preserve_containers_and_diagnostic_sources(self):
        self.payload["branch_codes"] = ["00SD179"]
        self.rows["terminal_branches"][0]["branch_code"] = "00SD179"
        self.rows["existing_containers"][0]["branch_id"] = "00sd179"
        self.rows["equipment_history"][0]["branch_id"] = "00sd179"
        self.rows["inbound_containers"][0].update(branch_id="00sd179", move_time="invalid date")
        self.write_files()
        scenario = prepare_scenario(self.payload)
        branch, = scenario["branches"]
        self.assertEqual(list(branch["yard"].containers), ["OLD"])
        self.assertEqual(len(branch["queue"]), 2)
        self.assertEqual(branch["queue"][0]["status"], "invalid")
        self.assertEqual(branch["queue"][0]["sources"], [{"file": "inbound_containers.csv", "line": 2}])
        problem, = branch["issues"]
        self.assertEqual(problem["sources"], [{"file": "inbound_containers.csv", "line": 2}])

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
                simulation = Simulation(result)
                simulation.reorder_queue(simulation.id, "JKT64", [3, 1, 2])
                self.assertEqual([row["container_id"] for row in first["queue"]], ["NEW1", "NEW2"])
                self.assertEqual(simulation.step(simulation.id, "JKT64", 1)["row"]["container_id"], "SCOPED")

    def test_existing_container_import_and_diagnostics_use_selected_branches(self):
        self.rows["terminal_branches"].append(dict(
            branch_id="3", terminal_id="1", branch_code="JKT64", branch_name="Other yard"))
        mapping = tomllib.loads(self.payload["mapping_toml"])
        for kind, selected, other, unknown in (
            ("code", " jkt74 ", "JKT64", "UNKNOWN"), ("id", "002", "3", "999"),
        ):
            with self.subTest(branch_kind=kind):
                mapping["csv"]["existing_containers"]["branch_kind"] = kind
                self.payload["mapping_toml"] = dump_toml(mapping)
                self.profiles = parse_mapping(mapping)
                existing = self.rows["existing_containers"][0] | {"branch_id": selected}
                self.rows["existing_containers"] = [existing, *(
                    existing | {"container_id": f"EXCLUDED{index}", "branch_id": branch_id,
                                "block_code": "UNKNOWN", "move_time": "not a date"}
                    for index, branch_id in enumerate((other, unknown, ""), 1)
                )]
                self.write_files()
                scenario = prepare_scenario(self.payload)
                preview = public_preview(scenario)
                self.assertTrue(preview["ready"], preview)
                self.assertEqual(list(scenario["branches"][0]["yard"].containers), ["OLD"])
                self.assertEqual(preview["issues"], [])
                self.assertEqual(preview["branches"][0]["issues"], [])
                self.assertIn("JKT74", Simulation(scenario).branches)

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
                comparison = compare_yard(branch, "export.csv", exported)
                self.assertEqual(comparison["counts"],
                                 {"same": 3, "moved": 0, "simulated_only": 0, "reference_only": 0})
                self.assertEqual(comparison["simulated"], comparison["reference"])
                for item in comparison["blocks"]:
                    self.assertEqual(item["layout"]["simulated"], item["layout"]["reference"])
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

    def test_overcapacity_csv_roundtrip_preserves_tiers_and_nominal_capacity(self):
        self.rows["yard_blocks"][0].update(row_count="1", slot_count="2", max_tier="1")
        record = self.rows["existing_containers"][0] | {"container_size": "40", "slot_no": "2"}
        self.rows["existing_containers"] = [
            record | {"container_id": f"TIER-{tier}", "tier_no": str(tier)} for tier in (3, 1, 2)
        ]
        self.write_files()
        scenario = prepare_scenario(self.payload)
        branch, = scenario["branches"]
        preview = public_preview(scenario)
        block, = preview["branches"][0]["yard_map"]["blocks"]
        self.assertEqual((block["occupied_tiers"], block["tier_capacity"]), (6, 2))
        self.assertEqual([tier["tier"] for tier in block["stacks"][1]["tiers"]], [1, 2, 3])
        exported = export_yard_csv([branch])
        comparison = compare_yard(branch, "export.csv", exported)
        self.assertEqual(comparison["simulated"], comparison["reference"])
        self.assertEqual(comparison["reference"]["occupancy_rate"], 3.0)
        self.payload["files"]["existing_containers"]["content"] = exported
        reopened, = prepare_scenario(self.payload)["branches"]
        self.assertEqual(reopened["yard"].containers["TIER-3"].getCoordsInt()[-1], 2)

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

    def test_completed_yard_comparison_reports_changes_without_mutating_simulation(self):
        session = SimulationSession()
        result = session.request({"op": "preview", "draft": self.payload})
        request = {"id": result["simulation"]["id"], "branch": "JKT74"}
        comparison = {"op": "compare_yard", **request, "name": "reference.csv"}
        with self.assertRaisesRegex(SimulationError, "Finish the inbound queue"):
            session.request(comparison)
        for position in (1, 2):
            session.request({"op": "step", **request, "position": position})
        original_csv = session.request({"op": "yard_csv"})
        valid = self.rows["existing_containers"][0]
        self.rows["existing_containers"] = [
            valid | {"row_no": "2", "slot_no": "3"},
            valid | {"container_id": "EXTRA", "row_no": "2", "slot_no": "4"},
            valid | {"container_id": "INVALID", "row_no": "99"},
            valid | {"container_id": "FOREIGN", "branch_id": "OTHER"},
        ]
        self.write_files()
        report = session.request(comparison | {"text": self.payload["files"]["existing_containers"]["content"]})
        self.assertEqual(report["counts"],
                         {"same": 0, "moved": 1, "simulated_only": 2, "reference_only": 1})
        self.assertEqual(report["excluded"], 1)
        self.assertEqual([(item["line"], item["container"]) for item in report["issues"]], [(4, "INVALID")])
        moved, = [item for item in report["differences"] if item["status"] == "moved"]
        self.assertEqual(moved["container"], "OLD")
        self.assertEqual((moved["simulated"]["row"], moved["reference"]["row"]), (1, 2))
        self.assertEqual(report["simulated"]["occupied_tiers"], 4)
        self.assertEqual(report["reference"]["occupied_tiers"], 2)
        self.assertEqual(report["blocks"][0]["reference"]["occupancy_rate"], 2 / 24)
        layout = report["blocks"][0]["layout"]
        self.assertEqual((layout["rows"], layout["slots"]), (2, 4))
        pair_slots = [slot for slot in layout["simulated"]
                      if any(tier.get("container") == "NEW2" for tier in slot["tiers"])]
        self.assertEqual(len(pair_slots), 2)
        left, right = pair_slots
        self.assertEqual((left["row"], left["slot"] + 1), (right["row"], right["slot"]))
        self.assertEqual(left["tiers"], right["tiers"])
        self.assertEqual([(slot["row"], slot["slot"]) for slot in layout["reference"]], [(2, 3), (2, 4)])
        self.assertEqual(session.request({"op": "yard_csv"}), original_csv)

        self.rows["existing_containers"] = [valid | {"branch_id": "OTHER"}]
        self.write_files()
        with self.assertRaisesRegex(ValueError, "no container records for branch JKT74"):
            session.request(comparison | {"text": self.payload["files"]["existing_containers"]["content"]})

    def test_dummy_containers_do_not_affect_block_or_yard_parameter_compliance(self):
        first_block = self.rows["yard_blocks"][0]
        self.rows["yard_blocks"].extend([
            first_block | {"block_id": "11", "block_code": "B"},
            first_block | {"block_id": "12", "block_code": "C"},
        ])
        self.rows["existing_containers"].append(
            self.rows["existing_containers"][0] | {"container_id": "OTHER", "block_code": "B"}
        )
        self.rows["parameters"] = [dict(parameter_id="38", parameter_name="20 ft", container_size="20",
                                         container_size_score="2", terminal_id="1", branch_id="2")]
        self.rows["yard_planning"] = [dict(parameter_id="38", block_id="10", row_no="1", slot_no="1",
                                            terminal_id="1", branch_id="2")]
        self.rows["inbound_containers"] = []
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}

        for position, (block, size, expected) in enumerate((("A", "20", 1.0), ("C", "40", None)), 1):
            session.request({"op": "add_queue_row", "size": size, "dummy": True, **request})
            suggestion = session.request({"op": "suggest", **request})
            step = session.request({
                "op": "step", "position": position, "suggestion_id": suggestion["suggestion_id"],
                "manual_destination": {"block": block, "row": 1, "slot": 2, "tier": 1}, **request,
            })
            self.assertEqual(step["placement"]["parameter_compliance"], expected)
        session.request({"op": "add_stack_dummy", "block": "A", "row": 1, "slot": 1, **request})

        exported = session.request({"op": "yard_csv"})
        report = session.request({"op": "compare_yard", "name": "export.csv", "text": exported, **request})
        scores = {block["block"]: block["simulated"]["parameter_compliance"] for block in report["blocks"]}
        self.assertEqual(scores, {"A": 1.0, "B": 0.0, "C": None})
        self.assertEqual(report["simulated"]["parameter_compliance"], 0.5)
        self.assertEqual(report["simulated"]["parameter_compliance"], report["reference"]["parameter_compliance"])
        self.assertEqual(report["simulated"]["occupied_tiers"] - report["reference"]["occupied_tiers"], 4)

    def test_duplicate_queue_ids_are_not_removed_and_link_to_source(self):
        self.rows["inbound_containers"] += [dict(container_id="NEW1", container_size="20"), dict(container_id="OLD", container_size="20")]
        preview = self.preview()
        branch, = preview["branches"]
        self.assertTrue(preview["ready"])
        self.assertEqual([row["status"] for row in branch["queue"]], ["pending", "pending", "invalid", "invalid"])
        self.assertEqual([row["sources"][0]["line"] for row in branch["queue"]], [2, 3, 4, 5])
        self.assertEqual([item["sources"][0]["line"] for item in branch["issues"]], [4, 5])

    def test_suggest_reorder_and_confirm_only_the_displayed_assignment(self):
        self.rows["inbound_containers"].append(dict(container_id="OLD", container_size="20"))
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        suggest = {"op": "suggest", **request}
        reorder = {"op": "reorder_queue", **request}
        confirm = {"op": "step", **request, "position": 1}
        initial_yard = session.request({"op": "yard_csv"})

        first = session.request(suggest)
        self.assertEqual((first["row"]["container_id"], first["row"]["status"]), ("NEW1", "suggested"))
        session.request(reorder | {"order": [1, 3, 2]})
        self.assertEqual(session.request(suggest), first)
        self.assertFalse(session.simulation.last_steps)
        session.request(reorder | {"order": [2, 3, 1]})
        current = session.request(suggest)
        self.assertEqual(current["row"]["container_id"], "NEW2")
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request(confirm | {"suggestion_id": first["suggestion_id"]})
        self.assertEqual(session.request({"op": "yard_csv"}), initial_yard)

        placed = session.request(confirm | {"suggestion_id": current["suggestion_id"]})
        self.assertEqual(placed["row"]["status"], "placed")
        winner, = [candidate for candidate in current["calculation"]["candidates"] if candidate["selected"]]
        for field in ("block", "row", "slot", "tier"):
            self.assertEqual(placed["placement"][field], winner[field])
        self.assertEqual(current["row"]["status"], "suggested")
        self.assertEqual(session.request(confirm | {"suggestion_id": current["suggestion_id"]}), placed)
        self.assertEqual(session.request(suggest)["row"]["status"], "invalid")
        session.request(confirm | {"position": 2})
        self.assertEqual(session.request(suggest)["row"]["container_id"], "NEW1")
        session.request(confirm | {"position": 3})
        self.assertIsNone(session.request(suggest))

    def test_alternate_placement_uses_the_current_candidate_and_exports_its_coordinate(self):
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        session.request({"op": "reorder_queue", **request, "order": [2, 1]})
        suggestion = session.request({"op": "suggest", **request})
        candidates = suggestion["calculation"]["candidates"]
        alternate = next(candidate for candidate in candidates if candidate["candidate_rank"] == 2)
        original_yard = session.request({"op": "yard_csv"})
        step = {"op": "step", **request, "position": 1, "suggestion_id": suggestion["suggestion_id"]}
        for rank in (True, 1, len(candidates) + 1):
            with self.subTest(rank=rank), self.assertRaisesRegex(SimulationError, "Choose an alternate location"):
                session.request(step | {"alternate_rank": rank})
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request(step | {"alternate_rank": 2, "suggestion_id": "stale"})
        self.assertEqual(session.request({"op": "yard_csv"}), original_yard)

        placed = session.request(step | {"alternate_rank": 2})
        self.assertEqual(placed["alternate_rank"], 2)
        self.assertEqual(placed["calculation"], suggestion["calculation"])
        location_fields = ("block", "row", "slot", "tier")
        self.assertEqual([placed["placement"][field] for field in location_fields],
                         [alternate[field] for field in location_fields])
        self.assertEqual([stack["slot"] for stack in placed["placement"]["stacks"]],
                         [alternate["slot"] - 1, alternate["slot"]])
        self.assertEqual(session.request(step | {"alternate_rank": 2}), placed)
        with self.assertRaisesRegex(SimulationError, "already been processed"):
            session.request(step | {"alternate_rank": 3})
        records = csv.DictReader(io.StringIO(session.request({"op": "yard_csv"})))
        exported, = (record for record in records if record["CONTNO"] == "NEW2")
        self.assertEqual([exported[key] for key in ("BLOK", "ROW", "SLOT", "TIER")],
                         [str(alternate[field]) for field in location_fields])
        self.assertEqual(session.request({"op": "suggest", **request})["row"]["container_id"], "NEW1")

    def test_manual_placement_can_override_a_removed_slot_and_replace_a_paired_occupant(self):
        self.rows["removed_slots"] = [
            dict(block_id="10", row_no=str(row), slot_no=str(slot))
            for row in range(1, 3) for slot in range(1, 5)
        ]
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        session.request({"op": "reorder_queue", **request, "order": [2, 1]})
        suggested = session.request({"op": "suggest", **request})
        self.assertEqual(suggested["row"]["status"], "unplaced")
        coordinate = {"block": "A", "row": 2, "slot": 2, "tier": 3}
        step = {"op": "step", **request, "position": 1, "suggestion_id": suggested["suggestion_id"]}
        with self.assertRaisesRegex(SimulationError, "inside the yard grid"):
            session.request(step | {"manual_destination": coordinate | {"tier": 4}})
        self.assertEqual(session.request({"op": "suggest", **request}), suggested)

        placed = session.request(step | {"manual_destination": coordinate})
        self.assertEqual(placed["manual_destination"], coordinate)
        self.assertEqual(placed["row"]["status"], "placed")
        self.assertEqual([stack["slot"] for stack in placed["placement"]["stacks"]], [1, 2])
        self.assertTrue(all(stack["removed"] and stack["anomaly"] for stack in placed["placement"]["stacks"]))
        self.assertEqual(session.request(step | {"manual_destination": coordinate}), placed)

        second = session.request({"op": "suggest", **request})
        replacement = session.request(step | {"position": 2, "suggestion_id": second["suggestion_id"],
                                               "manual_destination": coordinate | {"slot": 1}})
        self.assertEqual(replacement["placement"]["displaced"], ["NEW2"])
        self.assertEqual([stack["slot"] for stack in replacement["placement"]["updated_stacks"]], [1, 2])
        self.assertEqual(replacement["placement"]["updated_stacks"][1]["tiers"], [])
        records = list(csv.DictReader(io.StringIO(session.request({"op": "yard_csv"}))))
        container, = records
        self.assertEqual([container[key] for key in ("CONTNO", "BLOK", "ROW", "SLOT", "TIER")],
                         ["NEW1", "A", "2", "1", "3"])

    def test_manual_placement_only_accepts_available_equipment_and_moves_it(self):
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
            "block_id": "11", "block_code": "B", "pos_x": "10",
        })
        self.rows["master_equipment"].append(dict(equipment_code="SL1", equipment_type="SL"))
        self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"equipment_code": "SL1"})
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        yard_map = preview["preview"]["branches"][0]["yard_map"]
        self.assertEqual(yard_map["loader_codes"], ["SL1"])
        self.assertEqual([block["rtg_code"] for block in yard_map["blocks"]], ["RTG1", None])
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        suggestion = session.request({"op": "suggest", **request})
        step = {"op": "step", "position": 1, "suggestion_id": suggestion["suggestion_id"], **request}
        destination = {"block": "B", "row": 2, "slot": 2, "tier": 1}
        yard = session.yard_branches[0]["yard"]
        loader, = yard.master_loaders
        for unavailable in ("RTG1", "UNKNOWN", None):
            with self.subTest(equipment=unavailable), self.assertRaisesRegex(SimulationError, "equipment available"):
                session.request(step | {"manual_destination": destination | {"equipment": unavailable}})
        self.assertEqual(loader.getCoords(), ("10", 0, 0))
        self.assertNotIn("NEW1", yard.containers)

        destination["equipment"] = "SL1"
        result = session.request(step | {"manual_destination": destination})
        self.assertEqual(result["manual_destination"], destination)
        self.assertEqual(result["placement"]["equipment"], "SL1")
        self.assertEqual(result["placement"]["equipment_updates"], {"10": ["RTG1"], "11": ["SL1"]})
        self.assertEqual(loader.getCoords(), ("11", 1, 1))
        self.assertEqual(session.request(step | {"manual_destination": destination}), result)
        with self.assertRaisesRegex(SimulationError, "already been processed"):
            session.request(step | {"manual_destination": destination | {"equipment": "RTG1"}})

    def test_manual_equipment_can_prefer_local_or_nearer_reachable_equipment(self):
        for block_id, code, x in (("11", "B", "10"), ("12", "C", "11")):
            self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
                "block_id": block_id, "block_code": code, "pos_x": x,
            })
        for code, block, row, slot in (("A-REMOTE", "A", "1", "1"), ("C-REMOTE", "C", "1", "1"),
                                       ("FAR", "B", "2", "4"), ("NEAR", "B", "1", "2")):
            self.rows["master_equipment"].append(dict(equipment_code=code, equipment_type="SL"))
            self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {
                "equipment_code": code, "block_code": block, "row_no": row, "slot_no": slot,
            })
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        suggestion = session.request({"op": "suggest", **request})
        destination = {"block": "B", "row": 1, "slot": 2, "tier": 1}
        lookup = {"op": "manual_equipment", "suggestion_id": suggestion["suggestion_id"],
                  "destination": destination, **request}
        self.assertEqual(session.request(lookup), ["A-REMOTE", "C-REMOTE", "FAR", "NEAR"])
        preferred = lookup | {"preferred_first": True}
        self.assertEqual(session.request(preferred)[0], "NEAR")
        self.assertEqual(session.request(preferred | {"destination": destination | {"block": "A"}})[0], "RTG1")

        yard = session.yard_branches[0]["yard"]
        for loader in yard.getBlockByID("11").getLoaders()[:]:
            yard.moveEquipment(loader, ("10", 0, 0))
        self.assertEqual(session.request(preferred)[0], "C-REMOTE")

    def test_manual_equipment_respects_loader_approaches_and_allows_overrides_without_equipment(self):
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
            "block_id": "11", "block_code": "B", "pos_x": "10",
        })
        self.rows["existing_containers"].append(self.rows["existing_containers"][0] | {
            "container_id": "OBSTACLE", "block_code": "B", "row_no": "2", "slot_no": "2",
        })
        self.rows["block_accessibility"] = [dict(block_id="11", above="false", below="true", left="true", right="true")]
        for code, kind in (("SL1", "SL"), ("RS1", "RS")):
            self.rows["master_equipment"].append(dict(equipment_code=code, equipment_type=kind))
            self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"equipment_code": code})
        config = tomllib.loads(self.payload["config_toml"])
        config["feasibility"]["loader_destination_access_mode"] = "off"
        self.payload["config_toml"] = dump_toml(config)
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        destination = {"block": "B", "row": 1, "slot": 2, "tier": 1}
        suggestion = session.request({"op": "suggest", **request})
        lookup = {"op": "manual_equipment", "suggestion_id": suggestion["suggestion_id"],
                  "destination": destination, **request}
        self.assertEqual(session.request(lookup), ["RS1"])
        self.assertEqual(session.request(lookup | {"preferred_first": True}), ["RS1"])
        self.assertEqual(session.request(lookup | {"destination": destination | {"block": "A"}}),
                         ["RTG1", "RS1", "SL1"])
        step = {"op": "step", "position": 1, "suggestion_id": suggestion["suggestion_id"], **request}
        with self.assertRaisesRegex(SimulationError, "SL1 cannot reach the selected stack"):
            session.request(step | {"manual_destination": destination | {"equipment": "SL1"}})
        self.assertFalse(session.simulation.last_steps)

        session.request({"op": "reorder_queue", "order": [2, 1], **request})
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request(lookup)
        suggestion = session.request({"op": "suggest", **request})
        self.assertEqual(suggestion["row"]["size"], "40")
        self.assertEqual(session.request(lookup | {"suggestion_id": suggestion["suggestion_id"]}), [])
        yard = session.yard_branches[0]["yard"]
        before = [loader.getCoords() for loader in yard.master_loaders]
        placed = session.request(step | {"suggestion_id": suggestion["suggestion_id"],
                                         "manual_destination": destination | {"equipment": None}})
        self.assertEqual(placed["row"]["status"], "placed")
        self.assertIsNone(placed["placement"]["equipment"])
        self.assertEqual([loader.getCoords() for loader in yard.master_loaders], before)

    def test_suggestions_refresh_after_changes_to_yard_access_or_tier_gaps(self):
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        suggest = {"op": "suggest", **request}
        for change in ({"op": "update_block_access", "policies": [
                dict(block_id="10", above=False, below=True, left=True, right=True)]},
                {"op": "repair_tier_gaps"}):
            before = session.request(suggest)
            session.request(change | request)
            with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
                session.request({"op": "step", **request, "position": 1, "suggestion_id": before["suggestion_id"]})
            self.assertNotEqual(session.request(suggest)["suggestion_id"], before["suggestion_id"])
        self.assertFalse(session.simulation.last_steps)

    def test_queue_reordering_preserves_source_rows_placements_and_step_history(self):
        self.rows["inbound_containers"].append(dict(container_id="NEW1", container_size="40"))
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        reorder = {"op": "reorder_queue", **request}
        step = {"op": "step", **request}
        session.request(reorder | {"order": [2, 1, 3]})
        session.request(reorder | {"order": [2, 1, 3]})
        first = session.request(step | {"position": 1})
        self.assertEqual(first["row"]["sources"][0]["line"], 3)
        self.assertEqual(first["placement"]["container_id"], "NEW2")
        self.assertEqual(len(first["placement"]["stacks"]), 2)

        session.request(reorder | {"order": [3, 1]})
        for order in ([2, 1, 3], [2, 1], [1, 1], [1], [3, True], None):
            with self.subTest(order=order), self.assertRaises(SimulationError):
                session.request(reorder | {"order": order})
        for stale in ({"id": "old"}, {"branch": "unknown"}):
            with self.subTest(stale=stale), self.assertRaises(SimulationError):
                session.request(reorder | {"order": [1, 3]} | stale)
        self.assertEqual(session.request(step | {"position": 1}), first)
        skipped = session.request(step | {"position": 2})
        self.assertEqual((skipped["row"]["position"], skipped["row"]["status"]), (2, "invalid"))
        self.assertEqual(skipped["row"]["sources"][0]["line"], 4)
        last = session.request(step | {"position": 3})
        self.assertEqual(last["placement"]["container_id"], "NEW1")
        self.assertEqual(len(last["placement"]["stacks"]), 1)
        self.assertEqual(last["row"]["sources"][0]["line"], 2)
        with self.assertRaises(SimulationError):
            session.request(reorder | {"order": [1]})

    def test_add_queue_row_preserves_the_current_suggestion_and_reuses_queue_actions(self):
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        add = {"op": "add_queue_row", **request, "size": "20", "dummy": False}
        suggest = {"op": "suggest", **request}
        current = session.request(suggest)
        for fields in ({"container_id": " "}, {"container_id": " old "},
                       {"container_id": "new1"}, {"container_id": "NEW3", "size": "45"}):
            with self.subTest(fields=fields), self.assertRaises(SimulationError):
                session.request(add | fields)

        manual = session.request(add | {"container_id": " dummy-inbound-4 "})
        self.assertEqual((manual["position"], manual["container_id"]), (3, "DUMMY-INBOUND-4"))
        dummy = session.request(add | {"dummy": True})
        self.assertEqual((dummy["position"], dummy["container_id"]), (4, "DUMMY-INBOUND-5"))
        self.assertEqual(session.request(suggest), current)
        session.request({"op": "reorder_queue", **request, "order": [4, 1, 2, 3]})
        self.assertEqual(session.request(suggest)["row"], dummy | {"position": 1, "status": "suggested"})
        session.request({"op": "delete_queue_row", **request, "input_position": dummy["input_position"]})
        self.assertEqual(session.request(suggest)["row"]["container_id"], "NEW1")

        restored = session.request({"op": "preview", "draft": self.payload})
        self.assertEqual([row["container_id"] for row in restored["preview"]["branches"][0]["queue"]],
                         ["NEW1", "NEW2"])

    def test_add_queue_row_with_details_preserves_them_through_placement_and_export(self):
        self.payload["files"].pop("inbound_containers")
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        add = {"op": "add_queue_row", **request, "container_id": "NEW3", "size": "20", "dummy": False}
        for fields, message in (({"weight": "inf"}, "finite weight"),
                                ({"move_time": "sometime"}, "valid move time"),
                                ({"container_fill": "unknown"}, "Choose Full or Empty")):
            with self.subTest(fields=fields), self.assertRaisesRegex(SimulationError, message):
                session.request(add | {"details": fields})
        self.assertIsNone(session.request({"op": "suggest", **request}))

        move_time = "2026-11-23T07:10:43+07:00"
        details = dict(container_fill=" f ", weight=" 12345.6789 ", container_condition="av",
                       container_grade="fg", operation_type="d", principal="mrt",
                       pol="THLCH", pot="SGSIN", pod="IDJKT", vessel="mps", voyage="kn286w",
                       vessel_operator="mrt", move_time=f" {move_time} ")
        row = session.request(add | {"details": details})
        self.assertEqual({name: row[name] for name in (
            "position", "fill", "weight", "condition", "grade", "operation", "principal", "pol", "pot",
            "pod", "vessel", "voyage", "vessel_operator", "move_time",
        )}, dict(position=1, fill="F", weight=12345.6789, condition="AV", grade="FG", operation="D",
                 principal="MRT", pol="THLCH", pot="SGSIN", pod="IDJKT", vessel="MPS", voyage="KN286W",
                 vessel_operator="MRT", move_time=move_time))
        step = session.request({"op": "step", **request, "position": 1})
        self.assertEqual(step["row"], row | {"status": "placed"})
        records = csv.DictReader(io.StringIO(session.request({"op": "yard_csv"})))
        exported, = (record for record in records if record["CONTNO"] == "NEW3")
        self.assertEqual({key: exported[key] for key in (
            "FULLMT", "WEIGHT", "DMG_FLAG", "CONT_GRADE", "OPERATION_TYPE", "PRINCIPAL", "POL", "POT",
            "POD", "VESSEL", "VOYAGE", "VESSEL_OPERATOR", "MOVE_TIME",
        )}, dict(FULLMT="F", WEIGHT="12345.6789", DMG_FLAG="AV", CONT_GRADE="FG", OPERATION_TYPE="D",
                 PRINCIPAL="MRT", POL="THLCH", POT="SGSIN", POD="IDJKT", VESSEL="MPS", VOYAGE="KN286W",
                 VESSEL_OPERATOR="MRT", MOVE_TIME=move_time))

        dummy = session.request(add | {"size": "40", "dummy": True, "details": {"container_fill": "E"}})
        self.assertEqual(dummy["weight"], 4000)

    def test_dummy_can_start_an_empty_queue_and_is_excluded_from_yard_export(self):
        self.payload["files"].pop("inbound_containers")
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        add = {"op": "add_queue_row", **request}
        step = {"op": "step", **request}
        self.assertFalse(preview["preview"]["branches"][0]["inbound_available"])
        original_yard = session.request({"op": "yard_csv"})
        dummy = session.request(add | {"size": "40", "dummy": True})
        placed = session.request(step | {"position": 1})
        self.assertEqual(placed["placement"]["container_id"], dummy["container_id"])
        self.assertEqual(len(placed["placement"]["stacks"]), 2)
        self.assertEqual(session.request({"op": "yard_csv"}), original_yard)

        manual = session.request(add | {"container_id": "NEW3", "size": "20", "dummy": False})
        self.assertEqual(manual["position"], 2)
        self.assertEqual(session.request(step | {"position": 2})["placement"]["container_id"], "NEW3")
        self.assertIn("NEW3", session.request({"op": "yard_csv"}))

    def test_delete_queue_row_uses_source_position_and_refreshes_the_current_suggestion(self):
        self.rows["inbound_containers"].extend([
            dict(container_id="NEW3", container_size="20"),
            dict(container_id="OLD", container_size="20"),
        ])
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        delete = {"op": "delete_queue_row", **request}
        suggest = {"op": "suggest", **request}
        step = {"op": "step", **request}
        original_yard = session.request({"op": "yard_csv"})
        session.request({"op": "reorder_queue", **request, "order": [2, 1, 4, 3]})

        first = session.request(suggest)
        session.request(delete | {"input_position": 4})
        session.request(delete | {"input_position": 4})
        self.assertEqual(session.request(suggest), first)
        session.request(delete | {"input_position": 2})
        current = session.request(suggest)
        self.assertEqual((current["row"]["input_position"], current["row"]["position"]), (1, 1))
        self.assertEqual(session.request({"op": "yard_csv"}), original_yard)
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request(step | {"position": 1, "suggestion_id": first["suggestion_id"]})

        placed = session.request(step | {"position": 1, "suggestion_id": current["suggestion_id"]})
        with self.assertRaisesRegex(SimulationError, "Processed containers"):
            session.request(delete | {"input_position": 1})
        self.assertEqual(session.request(suggest)["row"]["position"], 2)
        session.request(delete | {"input_position": 3})
        self.assertIsNone(session.request(suggest))
        self.assertEqual(session.request(step | {"position": 1}), placed)

        restored = session.request({"op": "preview", "draft": self.payload})
        self.assertEqual(len(restored["preview"]["branches"][0]["queue"]), 4)

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
        self.assertEqual(problem["severity"], "warning")
        self.assertTrue(preview["ready"])
        self.assertEqual(preview["branches"][0]["summary"]["existing_containers"], 0)

    def test_map_reports_dummy_tiers_paired_footprints_and_assigned_rules(self):
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

        self.write_files()
        session = SimulationSession()
        result = session.request({"op": "preview", "draft": self.payload})
        preview = result["preview"]
        self.assertTrue(preview["ready"])
        branch, = preview["branches"]
        self.assertEqual(branch["summary"]["anomalous_stacks"], 2)
        self.assertEqual(branch["summary"]["stacks_with_dummy_containers"], 0)
        self.assertEqual(branch["issues"], [])
        self.assertEqual(branch["tier_gaps"], [
            {"block": "A", "row": 2, "slot": slot, "missing_tiers": [1], "dummy_tiers": []}
            for slot in (1, 2)
        ])
        raw_block, = branch["yard_map"]["blocks"]
        self.assertEqual(raw_block["occupied_tiers"], 3)
        self.assertTrue(all(stack["anomaly"] for stack in raw_block["stacks"][4:6]))

        request = {"id": result["simulation"]["id"], "branch": branch["branch_code"]}
        original_csv = session.request({"op": "yard_csv"})
        bad_data = session.yard_branches[0]["yard"].bad_data
        self.assertTrue(bad_data.anyBadData())
        repaired = session.request({"op": "repair_tier_gaps", **request})
        self.assertFalse(bad_data.anyBadData())
        self.assertTrue(repaired["tier_gap_repair_attempted"])
        self.assertEqual(repaired["summary"]["anomalous_stacks"], 0)
        self.assertEqual(repaired["summary"]["stacks_with_dummy_containers"], 2)
        self.assertEqual(repaired["tier_gaps"], [
            {"block": "A", "row": 2, "slot": slot, "missing_tiers": [], "dummy_tiers": [1]}
            for slot in (1, 2)
        ])
        self.assertEqual(session.request({"op": "yard_csv"}), original_csv)
        view = repaired["yard_map"]
        block, = view["blocks"]
        self.assertEqual((block["x"], block["y"], block["rows"], block["slots"]), (0, 0, 2, 4))
        self.assertEqual((block["container_count"], block["occupied_tiers"], block["tier_capacity"]), (2, 5, 21))
        left, right = block["stacks"][4:6]
        self.assertFalse(left["anomaly"] or right["anomaly"])
        self.assertEqual(left["tiers"], right["tiers"])
        self.assertEqual(right["tiers"][0], {"tier": 1, "dummy": True, "size": "40", "anchor_slot": 2})
        self.assertEqual((right["tiers"][1]["tier"], right["tiers"][1]["anchor_slot"]), (2, 2))
        self.assertEqual(right["parameters"], ["38"])
        self.assertTrue(block["stacks"][-1]["removed"])
        self.assertEqual(view["parameters"]["38"]["criteria"], [{"label": "Grade", "value": "PG", "points": 2}])
        session.request({"op": "step", "position": 1, **request})
        with self.assertRaisesRegex(SimulationError, "before running"):
            session.request({"op": "repair_tier_gaps", **request})
        fresh = session.request({"op": "preview", "draft": self.payload})["preview"]["branches"][0]
        self.assertEqual(fresh["tier_gaps"], branch["tier_gaps"])

    def test_add_stack_dummy_counts_as_occupied_and_refreshes_suggestions(self):
        self.rows["removed_slots"] = [dict(block_id="10", row_no="1", slot_no="4")]
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        original_csv = session.request({"op": "yard_csv"})
        old_suggestion = session.request({"op": "suggest", **request})
        location = {**request, "op": "add_stack_dummy", "block": "A", "row": 1, "slot": 1}

        added = session.request(location)
        placement = added["placement"]
        self.assertEqual(placement["tier"], 2)
        self.assertEqual(placement["stacks"][0]["tiers"][-1], {"tier": 2, "dummy": True})
        self.assertEqual(added["counts"]["stacks_with_dummy_containers"], 1)
        self.assertEqual(added["tier_gaps"][0]["missing_tiers"], [])
        self.assertFalse(session.yard_branches[0]["yard"].bad_data.anyBadData())
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request({"op": "step", "position": 1, "suggestion_id": old_suggestion["suggestion_id"], **request})

        self.assertEqual(session.request(location)["placement"]["tier"], 3)
        with self.assertRaisesRegex(ValueError, "no tier available"):
            session.request(location)
        with self.assertRaisesRegex(ValueError, "removed stack"):
            session.request(location | {"slot": 4})
        with self.assertRaisesRegex(SimulationError, "inside the yard grid"):
            session.request(location | {"row": 0})
        empty_placement = session.request(location | {"slot": 2})["placement"]
        self.assertEqual(empty_placement["stacks"][0]["tiers"], [{"tier": 1, "dummy": True}])
        self.assertEqual(session.request({"op": "yard_csv"}), original_csv)

        fresh = session.request({"op": "preview", "draft": self.payload})["preview"]["branches"][0]
        self.assertEqual(fresh["summary"]["stacks_with_dummy_containers"], 0)

    def test_add_stack_dummy_shares_40_ft_footprint_and_keeps_gaps_for_repair(self):
        self.rows["yard_blocks"][0]["max_tier"] = "4"
        self.rows["existing_containers"].append(dict(
            container_id="PAIR", container_size="40", branch_id="JKT74", block_code="A",
            row_no="2", slot_no="2", tier_no="2",
        ))
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        location = {**request, "op": "add_stack_dummy", "block": "A", "row": 2, "slot": 1}

        for tier in (3, 4):
            added = session.request(location)
            placement = added["placement"]
            self.assertEqual((placement["slot"], placement["tier"]), (2, tier))
            left, right = placement["stacks"]
            self.assertEqual((left["slot"], right["slot"]), (1, 2))
            self.assertEqual(left["tiers"][-1], {"tier": tier, "dummy": True, "size": "40", "anchor_slot": 2})
            self.assertEqual(left["tiers"], right["tiers"])
            self.assertEqual(added["counts"]["anomalous_stacks"], 2)
        block = session.yard_branches[0]["yard"].getBlockByID("10")
        self.assertIs(block.getStack(1, 0).getContainer(3), block.getStack(1, 1).getContainer(3))
        self.assertTrue(session.yard_branches[0]["yard"].bad_data.anyBadData())

        repaired = session.request({"op": "repair_tier_gaps", **request})
        self.assertEqual(repaired["summary"]["anomalous_stacks"], 0)
        self.assertEqual([entry["dummy_tiers"] for entry in repaired["tier_gaps"]], [[1, 3, 4], [1, 3, 4]])

    def test_explicit_40_ft_stack_dummy_can_use_a_level_pair(self):
        self.rows["yard_blocks"][0]["slot_count"] = "5"
        self.rows["removed_slots"] = [dict(block_id="10", row_no="2", slot_no="4")]
        existing = self.rows["existing_containers"][0]
        self.rows["existing_containers"].extend(
            existing | {"container_id": f"BASE{slot}", "slot_no": str(slot)} for slot in (3, 4)
        )
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74", "block": "A"}
        add = {**request, "op": "add_stack_dummy", "size": "40"}
        original_csv = session.request({"op": "yard_csv"})
        yard = session.yard_branches[0]["yard"]
        block = yard.getBlockByID("10")
        baseline_score = block.parameterCompliance()

        for row, slot, message in ((1, 1, "same stack height"), (2, 3, "removed stack"), (2, 5, "complete slot pair")):
            with self.subTest(row=row, slot=slot), self.assertRaisesRegex(ValueError, message):
                session.request(add | {"row": row, "slot": slot})
        self.assertEqual(block.getStack(0, 0).occupiedHeight(), 1)
        self.assertEqual(block.getStack(0, 1).occupiedHeight(), 0)

        placed = session.request(add | {"row": 2, "slot": 2})["placement"]
        self.assertEqual((placed["tier"], placed["slot"]), (1, 2))
        self.assertEqual([stack["slot"] for stack in placed["stacks"]], [1, 2])
        tier = {"tier": 1, "dummy": True, "size": "40", "anchor_slot": 2}
        self.assertEqual([stack["tiers"] for stack in placed["stacks"]], [[tier], [tier]])
        self.assertIs(block.getStack(1, 0).getContainer(0), block.getStack(1, 1).getContainer(0))
        self.assertEqual([block.getStack(1, slot).getMode() for slot in (0, 1)], ["40", "40"])

        placed = session.request(add | {"row": 1, "slot": 3})["placement"]
        self.assertEqual((placed["tier"], placed["slot"]), (2, 4))
        self.assertEqual([block.getStack(0, slot).getMode() for slot in (2, 3)], ["mixed", "mixed"])
        removed = session.request({
            **request, "op": "remove_stack_top", "row": 1, "slot": 4, "tier": 2, "container_id": None,
        })["placement"]
        self.assertEqual([stack["tiers"][0]["container_id"] for stack in removed["stacks"]], ["BASE3", "BASE4"])
        self.assertEqual([block.getStack(0, slot).getMode() for slot in (2, 3)], ["20", "20"])
        self.assertEqual(block.parameterCompliance(), baseline_score)
        self.assertEqual(session.request({"op": "yard_csv"}), original_csv)

    def test_remove_stack_top_updates_csv_and_rejects_stale_confirmations(self):
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        location = {**request, "block": "A", "row": 1, "slot": 1}
        original_csv = session.request({"op": "yard_csv"})
        session.request({"op": "add_stack_dummy", **location})
        suggestion = session.request({"op": "suggest", **request})
        removal = {**location, "op": "remove_stack_top", "tier": 2, "container_id": None}
        result = session.request(removal)
        self.assertTrue(result["placement"]["removed"])
        self.assertTrue(result["placement"]["dummy"])
        self.assertEqual(result["counts"]["stacks_with_dummy_containers"], 0)
        self.assertEqual(session.request({"op": "yard_csv"}), original_csv)
        with self.assertRaisesRegex(ValueError, "top container changed"):
            session.request(removal)
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request({"op": "step", "position": 1, "suggestion_id": suggestion["suggestion_id"], **request})

        removal = removal | {"tier": 1, "container_id": "OLD"}
        placement = session.request(removal)["placement"]
        self.assertFalse(placement["dummy"])
        self.assertEqual(placement["stacks"][0]["tiers"], [])
        yard = session.yard_branches[0]["yard"]
        self.assertEqual(yard.getStack("10", 0, 0).getMode(), "0")
        self.assertNotIn("OLD", yard.containers)
        self.assertNotIn("OLD", session.request({"op": "yard_csv"}))
        with self.assertRaisesRegex(ValueError, "selected stack is empty"):
            session.request(removal)

    def test_removing_an_existing_container_reopens_its_inbound_assignment(self):
        self.rows["inbound_containers"] = [dict(container_id="OLD", container_size="20")] * 2
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        suggest = {"op": "suggest", **request}
        before = session.request(suggest)
        self.assertEqual(before["row"]["status"], "invalid")

        session.request({"op": "remove_stack_top", "block": "A", "row": 1, "slot": 1,
                         "tier": 1, "container_id": "OLD", **request})
        step = {"op": "step", "position": 1, **request}
        with self.assertRaisesRegex(SimulationError, "suggestion has changed"):
            session.request(step | {"suggestion_id": before["suggestion_id"]})
        current = session.request(suggest)
        self.assertEqual(current["row"]["status"], "suggested")
        self.assertIsNone(current["row"]["reason"])
        placed = session.request(step | {"suggestion_id": current["suggestion_id"]})
        self.assertEqual(placed["placement"]["container_id"], "OLD")
        self.assertEqual(session.request(suggest)["row"]["status"], "invalid")

    def test_remove_stack_top_clears_both_slots_for_a_real_pair_and_repair_dummy(self):
        self.rows["existing_containers"].append(dict(
            container_id="PAIR", container_size="40", branch_id="JKT74", block_code="A",
            row_no="2", slot_no="2", tier_no="2",
        ))
        self.write_files()
        session = SimulationSession()
        preview = session.request({"op": "preview", "draft": self.payload})
        request = {"id": preview["simulation"]["id"], "branch": "JKT74"}
        session.request({"op": "repair_tier_gaps", **request})
        location = {**request, "op": "remove_stack_top", "block": "A", "row": 2, "slot": 1}

        result = session.request(location | {"tier": 2, "container_id": "PAIR"})
        stacks = result["placement"]["stacks"]
        self.assertEqual([stack["slot"] for stack in stacks], [1, 2])
        tier = {"tier": 1, "dummy": True, "size": "40", "anchor_slot": 2}
        self.assertEqual([stack["tiers"] for stack in stacks], [[tier], [tier]])
        yard = session.yard_branches[0]["yard"]
        self.assertEqual([yard.getStack("10", 1, slot).getMode() for slot in (0, 1)], ["40", "40"])
        self.assertNotIn("PAIR", yard.containers)

        result = session.request(location | {"slot": 2, "tier": 1, "container_id": None})
        self.assertTrue(result["placement"]["dummy"])
        self.assertEqual([stack["tiers"] for stack in result["placement"]["stacks"]], [[], []])
        self.assertEqual([yard.getStack("10", 1, slot).getMode() for slot in (0, 1)], ["0", "0"])

    def test_invalid_inbound_date_keeps_yard_map_and_reports_queue_row(self):
        self.rows["inbound_containers"][0]["move_time"] = "not a date"
        preview = self.preview()
        branch, = preview["branches"]
        self.assertTrue(preview["ready"])
        self.assertTrue(branch["yard_map"]["blocks"])
        self.assertEqual([row["status"] for row in branch["queue"]], ["invalid", "pending"])
        issue, = branch["issues"]
        self.assertEqual(issue["severity"], "warning")
        self.assertEqual(issue["field"], "move_time")
        self.assertEqual(issue["sources"], [{"file": "inbound_containers.csv", "line": 2}])

    def test_unknown_block_and_out_of_bounds_containers_warn_without_blocking_simulation(self):
        valid = self.rows["existing_containers"][0]
        for index, coordinates in enumerate((
            {"block_code": "UNKNOWN"}, {"row_no": "3"}, {"slot_no": "5"}, {"tier_no": "5"},
        ), 1):
            self.rows["existing_containers"].append(valid | coordinates | {"container_id": f"SKIPPED{index}"})
        self.write_files()
        scenario = prepare_scenario(self.payload)
        preview = public_preview(scenario)
        self.assertTrue(preview["ready"], preview)
        branch, = preview["branches"]
        self.assertEqual(branch["issue_counts"], {"warning": 4})
        self.assertIn("Unknown block", branch["issues"][0]["message"])
        self.assertEqual([item["sources"][0]["line"] for item in branch["issues"]], [3, 4, 5, 6])
        self.assertEqual(list(scenario["branches"][0]["yard"].containers), ["OLD"])
        simulation = Simulation(scenario)
        self.assertEqual(simulation.step(simulation.id, "JKT74", 1)["row"]["status"], "placed")

    def test_incompatible_existing_footprint_warns_without_blocking_simulation(self):
        self.rows["existing_containers"][0]["container_size"] = "40"
        self.write_files()
        scenario = prepare_scenario(self.payload)
        branch, = public_preview(scenario)["branches"]
        self.assertEqual(branch["issue_counts"], {"warning": 1})
        self.assertIn("incompatible footprint", branch["issues"][0]["message"])
        self.assertIn("JKT74", Simulation(scenario).branches)

    def test_skipped_records_across_datasets_leave_usable_yard_runnable(self):
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
            "block_id": "11", "block_code": "B", "max_tier": "0",
        })
        self.rows["parameters"] = [dict(parameter_id="", branch_id="2", terminal_id="1")]
        self.rows["yard_planning"] = [
            dict(parameter_id="MISSING", block_id="10", row_no="1", slot_no="1", branch_id="2", terminal_id="1"),
            dict(parameter_id="MISSING", block_id="10", row_no="bad", slot_no="1", branch_id="2", terminal_id="1"),
        ]
        self.rows["removed_slots"] = [
            dict(block_id="10", row_no="1", slot_no="bad"),
            dict(block_id="10", row_no="99", slot_no="1"),
        ]
        self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"move_time": "bad date"})
        self.rows["inbound_containers"].append(dict(container_id="OTHER", branch_id="UNKNOWN", container_size="20"))
        self.write_files()
        scenario = prepare_scenario(self.payload)
        preview = public_preview(scenario)
        self.assertTrue(preview["ready"], preview)
        self.assertEqual([(item["dataset"], item["severity"]) for item in preview["issues"]],
                         [("inbound_containers", "warning")])
        branch, = preview["branches"]
        self.assertEqual(sorted((item["dataset"], item["sources"][0]["line"]) for item in branch["issues"]), [
            ("equipment_history", 3), ("parameters", 2), ("removed_slots", 2), ("removed_slots", 3),
            ("yard_blocks", 3), ("yard_planning", 2), ("yard_planning", 3),
        ])
        self.assertEqual(branch["issue_counts"], {"warning": 7})
        self.assertEqual(branch["summary"]["blocks"], 1)
        simulation = Simulation(scenario)
        self.assertEqual(simulation.step(simulation.id, "JKT74", 1)["row"]["status"], "placed")

    def test_invalid_block_dimensions_use_domain_validation_and_source(self):
        self.rows["yard_blocks"][0]["max_tier"] = "0"
        preview = self.preview()
        problem = next(item for item in preview["branches"][0]["issues"] if item["category"] == "block")
        self.assertIn("max_tier", problem["message"])
        self.assertEqual(problem["sources"][0]["line"], 2)

    def test_shared_master_equipment_does_not_warn_for_other_branches(self):
        self.payload["branch_codes"] = ["JKT74", "JKT64", "SD179"]
        for branch_id, code, block_id, block_code, equipment, equipment_type in (
            ("1", "JKT64", "11", "B", "RTG2", "RTG"),
            ("15", "SD179", "60", "Repair", "SL.Dummy.SD179", "SL"),
        ):
            self.rows["terminal_branches"].append(dict(
                branch_id=branch_id, terminal_id="1", branch_code=code, branch_name=code,
            ))
            self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | dict(
                branch_id=branch_id, block_id=block_id, block_code=block_code,
            ))
            self.rows["master_equipment"].append(dict(equipment_code=equipment, equipment_type=equipment_type))
            self.rows["equipment_history"].append(dict(
                equipment_code=equipment, branch_id=code, block_code=block_code,
                row_no="1", slot_no="1", move_time="",
            ))
        mapping = tomllib.loads(self.payload["mapping_toml"])
        for branch_kind in ("code", "id"):
            with self.subTest(branch_kind=branch_kind):
                mapping["csv"]["equipment_history"]["branch_kind"] = branch_kind
                self.payload["mapping_toml"] = dump_toml(mapping)
                if branch_kind == "id":
                    for row, branch_id in zip(self.rows["equipment_history"], ("2", "1", "15")):
                        row["branch_id"] = branch_id
                preview = self.preview()
                self.assertTrue(preview["ready"], preview)
                self.assertEqual(preview["issues"], [])
                for branch in preview["branches"]:
                    self.assertEqual(branch["issues"], [], branch["branch_code"])
                    self.assertEqual(branch["counts"]["equipment_history"], 1)

    def test_invalid_selected_equipment_location_keeps_actionable_warnings(self):
        self.rows["equipment_history"][0]["row_no"] = "invalid"
        preview = self.preview()
        branch, = preview["branches"]
        invalid, = [problem for problem in branch["issues"] if problem["dataset"] == "equipment_history"]
        self.assertIn("row_no must be an integer", invalid["message"])
        self.assertEqual(invalid["sources"], [{"file": "equipment_history.csv", "line": 2}])
        equipment_warning, = [problem for problem in branch["issues"] if problem["dataset"] == "master_equipment"]
        self.assertIn("Block A has no RTG and no registered loader", equipment_warning["message"])
        self.assertEqual(equipment_warning["severity"], "warning")

    def test_block_equipment_updates_when_a_placement_moves_a_loader(self):
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
            "block_id": "11", "block_code": "B", "pos_x": "10",
        })
        for code in ("SL2", "SL1"):
            self.rows["master_equipment"].append(dict(equipment_code=code, equipment_type="SL"))
            self.rows["equipment_history"].append(self.rows["equipment_history"][0] | {"equipment_code": code})
        self.rows["parameters"] = [dict(parameter_id="P", container_size="20",
                                        container_size_score="1", terminal_id="1", branch_id="2")]
        self.rows["yard_planning"] = [dict(parameter_id="P", block_id="11", row_no="1", slot_no="1",
                                           terminal_id="1", branch_id="2")]
        self.write_files()

        scenario = prepare_scenario(self.payload)
        branch, = public_preview(scenario)["branches"]
        source, destination = branch["yard_map"]["blocks"]
        self.assertEqual(source["equipment_codes"], ["RTG1", "SL1", "SL2"])
        self.assertEqual(destination["equipment_codes"], [])

        simulation = Simulation(scenario)
        step = simulation.step(simulation.id, "JKT74", 1)
        self.assertEqual(step["placement"]["block"], "B")
        moved = next(candidate["equipment"] for candidate in step["calculation"]["candidates"] if candidate["selected"])
        self.assertIn(moved, ("SL1", "SL2"))
        self.assertEqual(step["placement"]["equipment_updates"], {
            "10": [code for code in source["equipment_codes"] if code != moved], "11": [moved],
        })

    def test_missing_equipment_uses_null_and_keeps_distance_disabled(self):
        self.rows["master_equipment"] = []
        self.rows["equipment_history"] = []
        self.payload["config_toml"] = self.payload["config_toml"].replace(
            "enable_equipment_distance = false", "enable_equipment_distance = true"
        )
        self.write_files()
        scenario = prepare_scenario(self.payload)
        preview = public_preview(scenario)
        self.assertTrue(preview["ready"], preview)
        self.assertIn("no RTG", preview["branches"][0]["issues"][0]["message"])
        self.assertEqual(preview["branches"][0]["summary"]["existing_containers"], 1)
        self.assertEqual(preview["branches"][0]["issues"][0]["severity"], "warning")
        simulation = Simulation(scenario)
        step = simulation.step(simulation.id, "JKT74", 1)
        self.assertEqual(step["row"]["status"], "placed")
        self.assertIsNone(step["calculation"]["candidates"][0]["equipment"])
        self.assertIsNone(step["calculation"]["candidates"][0]["distance"])
        self.assertNotIn("distance_multiplier", step["calculation"]["enabled_multipliers"])
        self.assertEqual(step["calculation"]["candidates"][0]["distance_multiplier"], 1.0)
        self.assertIn("NEW1", scenario["branches"][0]["yard"].containers)
        suggestion = simulation.suggest(simulation.id, "JKT74")
        manual = simulation.step(simulation.id, "JKT74", 2, suggestion["suggestion_id"], manual_destination={
            "block": "A", "row": 2, "slot": 2, "tier": 1, "equipment": None,
        })
        self.assertEqual(manual["row"]["status"], "placed")
        self.assertIsNone(manual["placement"]["equipment"])

    def test_two_yards_run_independently_when_one_has_no_equipment(self):
        self.rows["terminal_branches"].append(dict(branch_id="3", terminal_id="1", branch_code="JKT64", branch_name="Second yard"))
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {"block_id": "11", "branch_id": "3"})
        document = tomllib.loads(self.payload["input_toml"])
        document["input"]["filters"]["branch_code"] = ["JKT74", "JKT64"]
        self.payload["input_toml"] = dump_toml(document)
        self.write_files()
        scenario = prepare_scenario(self.payload)
        preview = public_preview(scenario)
        self.assertTrue(preview["ready"], preview)
        simulation = Simulation(scenario)
        self.assertEqual(set(simulation.branches), {"JKT74", "JKT64"})
        equipped = simulation.step(simulation.id, "JKT74", 1)
        unequipped = simulation.step(simulation.id, "JKT64", 1)
        self.assertEqual(equipped["row"]["status"], "placed")
        self.assertEqual(unequipped["row"]["status"], "placed")
        self.assertEqual(equipped["calculation"]["candidates"][0]["equipment"], "RTG1")
        self.assertIsNone(unequipped["calculation"]["candidates"][0]["equipment"])

    def test_unserved_block_does_not_hide_rtg_block_with_lower_parameter_score(self):
        self.rows["yard_blocks"].append(self.rows["yard_blocks"][0] | {
            "block_id": "11", "block_code": "B", "pos_x": "10",
        })
        self.rows["parameters"] = [dict(parameter_id="P", container_size="20",
                                        container_size_score="1", terminal_id="1", branch_id="2")]
        self.rows["yard_planning"] = [dict(parameter_id="P", block_id="11", row_no="1", slot_no="1",
                                           terminal_id="1", branch_id="2")]
        self.write_files()
        scenario = prepare_scenario(self.payload)
        preview = public_preview(scenario)
        self.assertTrue(preview["ready"], preview["branches"][0]["issues"])
        problem, = preview["branches"][0]["issues"]
        self.assertEqual(problem["severity"], "warning")
        self.assertIn("Block B", problem["message"])

        simulation = Simulation(scenario)
        step = simulation.step(simulation.id, "JKT74", 1)
        self.assertEqual(step["row"]["status"], "placed")
        self.assertEqual(step["placement"]["block"], "A")
        self.assertEqual(step["calculation"]["rejections"]["no_available_equipment"], 8)

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
                self.assertEqual(len(bundle.namelist()), 13)
                self.assertIn("block_accessibility.csv", bundle.namelist())

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

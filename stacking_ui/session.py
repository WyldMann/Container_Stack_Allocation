"""Handle stacking requests from the desktop launcher and the browser worker."""

from contextlib import redirect_stdout
import json
import sys

from config.application.config_loader import ConfigurationError

from .configuration import read_project_tomls, save_project_toml, validate_project_toml
from .scenario import prepare_scenario, public_branch, public_preview
from .simulation import Simulation, SimulationError, export_yard_csv, save_yard_csv


def prepare_draft(draft):
    if not isinstance(draft, dict) or draft.get("version") != 1 or "files" not in draft:
        raise ConfigurationError("Expected a saved stacking scenario draft.")
    return prepare_scenario(draft)


def preview_document(scenario):
    return {"version": 1, "kind": "stacking-preview", **public_preview(scenario)}


class SimulationSession:
    def __init__(self):
        self.simulation = None
        self.yard_branches = []

    def request(self, request):
        operation = request.get("op")
        if operation == "project_tomls":
            return read_project_tomls()
        if operation == "save_project_toml":
            return save_project_toml(request.get("key"), request.get("text"), request.get("expected"))
        if operation == "export_toml":
            text = request.get("text")
            path = validate_project_toml(request.get("key"), text)
            return {"name": path.name, "text": text}
        if operation == "yard_csv":
            return export_yard_csv(self.yard_branches)
        if operation == "save_yard_csv":
            return save_yard_csv(self.yard_branches)
        if operation == "preview":
            scenario = prepare_draft(request.get("draft"))
            preview = preview_document(scenario)
            self.simulation = Simulation(scenario)
            self.yard_branches = [branch for branch in scenario["branches"]
                                  if branch["yard"] is not None and branch["yard"].blocks_by_id]
            return {"preview": preview, "simulation": {
                "id": self.simulation.id, "branches": list(self.simulation.branches),
            }}
        if operation == "step" and self.simulation is not None:
            return self.simulation.step(request.get("id"), request.get("branch"), request.get("position"))
        if operation == "repair_tier_gaps":
            return self.repair_tier_gaps(request.get("id"), request.get("branch"))
        raise SimulationError("Generate a preview before running the simulation.")

    def repair_tier_gaps(self, simulation_id, branch_code):
        if self.simulation is None or simulation_id != self.simulation.id:
            raise SimulationError("Generate a fresh preview before repairing tier gaps.")
        branch = next((item for item in self.yard_branches if item["branch_code"] == branch_code), None)
        if branch is None:
            raise SimulationError("This branch has no yard to repair.")
        if branch_code in self.simulation.last_steps:
            raise SimulationError("Generate a fresh preview to repair tier gaps before running the queue.")
        if not branch.get("tier_gap_repair_attempted"):
            yard = branch["yard"]
            yard.fillDummyContainer()
            yard.anomalyCheck()
            branch["tier_gap_repair_attempted"] = True
        return public_branch(branch)

    def handle_json(self, text):
        try:
            with redirect_stdout(sys.stderr):
                response = {"result": self.request(json.loads(text))}
        except (ValueError, OSError) as error:
            response = {"error": str(error)}
        return json.dumps(response, allow_nan=False)

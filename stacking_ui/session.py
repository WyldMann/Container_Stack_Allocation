"""Handle stacking requests from the desktop launcher and the browser worker."""

from contextlib import redirect_stdout
from dataclasses import asdict
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from config.application.config_loader import ConfigurationError
from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import load_input_config
from entities.feasibility.loader_access import LoaderBorderAccessPolicy
from repository.block_accessibility import access_policies, policies_csv, read_policies

from .comparison import compare_yard
from .configuration import PROJECT_ROOT, read_project_tomls, save_project_toml, validate_project_toml
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
        if operation == "update_block_access":
            return self.update_block_access(request)
        if operation == "save_block_access":
            return self.save_block_access(request)
        if operation == "restore_block_access":
            return self.write_block_access(read_policies(request.get("text", "")))
        if operation == "bundled_csvs":
            return self.bundled_csvs()
        if operation == "preview":
            scenario = prepare_draft(request.get("draft"))
            self.simulation = Simulation(scenario)
            self.yard_branches = [branch for branch in scenario["branches"]
                                  if branch["yard"] is not None and branch["yard"].blocks_by_id]
            for branch in self.yard_branches:
                yard = branch["yard"]
                branch["saved_block_access"] = {
                    block_id: asdict(yard.loader_access_policies.get(block_id, LoaderBorderAccessPolicy()))
                    for block_id in yard.blocks_by_id
                }
            preview = preview_document(scenario)
            return {"preview": preview, "simulation": {
                "id": self.simulation.id, "branches": list(self.simulation.branches),
            }}
        if operation == "suggest" and self.simulation is not None:
            return self.simulation.suggest(request.get("id"), request.get("branch"))
        if operation == "step" and self.simulation is not None:
            return self.simulation.step(request.get("id"), request.get("branch"), request.get("position"),
                                        request.get("suggestion_id"))
        if operation == "reorder_queue" and self.simulation is not None:
            return self.simulation.reorder_queue(request.get("id"), request.get("branch"), request.get("order"))
        if operation == "repair_tier_gaps":
            return self.repair_tier_gaps(request.get("id"), request.get("branch"))
        if operation == "compare_yard":
            return self.compare_completed_yard(request)
        raise SimulationError("Generate a preview before running the simulation.")

    def update_block_access(self, request):
        simulation = self.simulation
        code = request.get("branch")
        if simulation is None or request.get("id") != simulation.id:
            raise SimulationError("Generate a fresh preview before changing block access.")
        branch = next((item for item in self.yard_branches if item["branch_code"] == code), None)
        if branch is None:
            raise SimulationError("Select a branch with a yard.")
        if code in simulation.last_steps:
            raise SimulationError("Block access is locked after this branch starts. Generate a fresh preview to change it.")
        records = request.get("policies")
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise SimulationError("Supply block accessibility records.")
        policies = access_policies(records)
        if set(policies) - set(branch["yard"].blocks_by_id):
            raise SimulationError("Block accessibility refers to an unknown block in this branch.")
        branch["yard"].loader_access_policies.update(policies)
        simulation.invalidate_suggestion(code)
        return {block_id: asdict(policy) for block_id, policy in policies.items()}

    def block_access_path(self):
        settings = load_input_config(DEFAULT_STACKING_INPUT_CONFIG_FILE)
        path = settings.get("csv_files", {}).get(
            "block_accessibility", PROJECT_ROOT / "data_container_stacking" / "block_accessibility.csv")
        if not path.is_relative_to(PROJECT_ROOT) or path.suffix.lower() != ".csv":
            raise SimulationError("Choose a block accessibility CSV inside the project.")
        return path

    def write_block_access(self, policies):
        path = self.block_access_path()
        text = policies_csv(policies)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, encoding="utf-8", mode="w", newline="", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(text)
                stream.close()
                temporary.replace(path)
            finally:
                stream.close()
                temporary.unlink(missing_ok=True)
        return {"name": path.name, "text": text}

    def save_block_access(self, request):
        if self.simulation is None or request.get("id") != self.simulation.id:
            raise SimulationError("Generate a fresh preview before saving block access.")
        branch = next((item for item in self.yard_branches if item["branch_code"] == request.get("branch")), None)
        block_id = request.get("block_id")
        if branch is None or not isinstance(block_id, str) or block_id not in branch["yard"].blocks_by_id:
            raise SimulationError("Select a known block in this branch to save its access.")
        path = self.block_access_path()
        text = path.read_text(encoding="utf-8") if path.exists() else policies_csv({})
        policies = read_policies(text)
        policy = branch["yard"].loader_access_policies.get(block_id, LoaderBorderAccessPolicy())
        if asdict(policy) == branch["saved_block_access"][block_id]:
            return {"name": path.name, "text": text}
        policies[block_id] = policy
        saved = self.write_block_access(policies)
        branch["saved_block_access"][block_id] = asdict(policy)
        return saved

    def bundled_csvs(self):
        paths = load_input_config(DEFAULT_STACKING_INPUT_CONFIG_FILE)["csv_files"]
        paths.setdefault("block_accessibility", self.block_access_path())
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for path in sorted(set(paths.values())):
                if not path.is_relative_to(PROJECT_ROOT):
                    raise SimulationError("Bundled CSV paths must stay inside the project.")
                name = path.relative_to(PROJECT_ROOT).as_posix()
                if path == self.block_access_path() and not path.exists():
                    archive.writestr(name, policies_csv({}))
                else:
                    archive.write(path, name)
        return {"name": "bundled-csvs.zip", "base64": base64.b64encode(buffer.getvalue()).decode("ascii")}

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
            self.simulation.invalidate_suggestion(branch_code)
            branch["tier_gap_repair_attempted"] = True
        return public_branch(branch)

    def compare_completed_yard(self, request):
        simulation = self.simulation
        branch_code = request.get("branch")
        if simulation is None or request.get("id") != simulation.id:
            raise SimulationError("Finish the current simulation before comparing yards.")
        if not isinstance(branch_code, str) or branch_code not in simulation.branches:
            raise SimulationError("Select a branch with a completed simulation.")
        branch = simulation.branches[branch_code]
        last_step = simulation.last_steps.get(branch_code)
        if last_step is None or last_step["row"]["position"] != len(branch["queue"]):
            raise SimulationError("Finish the inbound queue before comparing yards.")
        return compare_yard(branch, request.get("name"), request.get("text"))

    def handle_json(self, text):
        try:
            with redirect_stdout(sys.stderr):
                response = {"result": self.request(json.loads(text))}
        except (ValueError, OSError) as error:
            response = {"error": str(error)}
        return json.dumps(response, allow_nan=False)

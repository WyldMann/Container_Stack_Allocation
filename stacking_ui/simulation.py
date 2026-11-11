"""Advance a prepared yard one inbound CSV row at a time."""

import csv
from io import StringIO
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.feasibility.placement_proposal import PlacementProposal
from filewriter import ContainerFileWriter
from repository.branch_repository import BranchDirectory

from .yard_view import stack_view


CONTAINER_EXPORT_COLUMNS = {
    "container_id": "CONTNO", "branch_id": "BRANCH", "block_code": "BLOK",
    "row_no": "ROW", "slot_no": "SLOT", "tier_no": "TIER", "principal": "PRINCIPAL",
    "container_condition": "DMG_FLAG", "container_fill": "FULLMT",
    "operation_type": "OPERATION_TYPE", "container_size": "CONTSIZE",
    "container_grade": "CONT_GRADE", "pol": "POL", "pot": "POT", "pod": "POD",
    "vessel_operator": "VESSEL_OPERATOR", "vessel": "VESSEL", "voyage": "VOYAGE",
    "weight": "WEIGHT", "move_time": "MOVE_TIME",
}


class SimulationError(ValueError):
    """The request cannot be completed with the current simulation state."""


def export_yard_csv(branches):
    if not branches:
        raise SimulationError("Generate a preview with a yard before saving containers.csv.")
    # Keep the prepared yard's mapping even if the project settings change later.
    profile = branches[0]["container_profile"]
    columns = {field: profile.columns.get(field, field) for field in CONTAINER_EXPORT_COLUMNS}
    headers = {column.strip().casefold(): column for column in columns.values()}
    for column in profile.filter_columns.values():
        headers.setdefault(column.strip().casefold(), column)
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers.values()))
    writer.writeheader()
    for branch in branches:
        directory = BranchDirectory(branch["inputs"]["terminal_branches"])
        branch_codes = directory.codes_by_id if profile.branch_kind == "code" else None
        container_writer = ContainerFileWriter("containers.csv", branch_codes=branch_codes)
        identity = directory.by_code[branch["branch_code"]]
        for record in container_writer.buildRows(branch["yard"]):
            row = {columns[field]: record[source] for field, source in CONTAINER_EXPORT_COLUMNS.items()}
            for field, column in profile.filter_columns.items():
                row[headers[column.strip().casefold()]] = identity[field]
            writer.writerow(row)
    return buffer.getvalue()


def save_yard_csv(branches):
    content = export_yard_csv(branches)
    try:
        from tkinter import TclError, Tk, filedialog
    except ImportError as error:
        raise SimulationError("Saving the yard CSV requires Python's Tk file dialog.") from error

    try:
        window = Tk()
        try:
            window.withdraw()
            window.attributes("-topmost", True)
            filename = filedialog.asksaveasfilename(
                parent=window, title="Save yard CSV", initialfile="containers.csv",
                defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            )
        finally:
            window.destroy()
    except TclError as error:
        raise SimulationError(f"Could not open the Save yard CSV dialog. {error}") from error
    if not filename:
        return None

    path = Path(filename)
    with TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        temporary.write_text(content, encoding="utf-8", newline="")
        temporary.replace(path)
    return str(path)


def _number(value):
    return value if value is not None and isfinite(value) else None


def _location(yard, coordinates):
    block_id, row, slot, tier = coordinates
    return {"block": yard.getBlockByID(block_id).getCode(), "row": row + 1, "slot": slot + 1, "tier": tier + 1}


def _calculation(yard, search, result):
    candidates = result.sorted_candidate_evaluations if result is not None else []
    winner = candidates[0] if candidates else None
    ranked_by_location = {candidate.coordinates: candidate for candidate in candidates}
    top_ranks = {candidate.coordinates: rank for rank, candidate in enumerate(candidates[:5], 1)}
    qualified = []
    for coordinates in search["candidate_coordinates"]:
        candidate = ranked_by_location[coordinates]
        qualified.append({
            **_location(yard, coordinates),
            "selected": candidate is winner,
            "rank": top_ranks.get(coordinates),
            "parameters": [parameter.getId() for parameter in candidate.parameters],
            "equipment": candidate.equipment.getCode(),
            "distance": _number(candidate.distance),
            "equipment_outside_block": candidate.distance == float("inf"),
            "mass_difference": _number(candidate.delta_container_mass),
            "mass_multiplier": _number(yard.model.deltaContainerMass(candidate.delta_container_mass)),
            "distance_multiplier": _number(yard.model.equipmentDistance(candidate.distance)),
            "cluster_multiplier": _number(candidate.size_cluster_multiplier),
            "score": _number(candidate.evaluation_score),
        })
    return {
        "checked": search["checked"],
        "rejections": search["rejections"],
        "parameter_scores": [
            {"id": parameter_id, "name": yard.parameters[parameter_id].getName(), "score": _number(score)}
            for parameter_id, score in search["parameter_scores"].items()
        ],
        "max_parameter_score": _number(search["max_parameter_score"]),
        "candidate_count": len(qualified),
        "winning_score_ties": sum(candidate.evaluation_score == winner.evaluation_score for candidate in candidates),
        "enabled_multipliers": [
            name for name, enabled in (
                ("mass_multiplier", yard.model.enable_delta_container_mass),
                ("distance_multiplier", yard.model.enable_equipment_distance),
                ("cluster_multiplier", yard.model.enable_size_cluster),
            )
            if enabled
        ],
        "candidates": qualified,
    }


class Simulation:
    def __init__(self, scenario):
        self.id = uuid4().hex
        self.branches = {}
        self.last_steps = {}
        if any(problem["severity"] == "error" and problem["dataset"] != "inbound_containers"
               for problem in scenario["issues"]):
            return
        for branch in scenario["branches"]:
            yard = branch["yard"]
            if (yard is not None and yard.blocks_by_id and branch["inbound_available"] and branch["queue"]
                    and not any(problem["severity"] == "error" and problem["dataset"] != "inbound_containers"
                                for problem in branch["issues"])):
                self.branches[branch["branch_code"]] = branch

    def step(self, simulation_id, branch_code, position):
        if simulation_id != self.id:
            raise SimulationError("Generate a new preview to start a simulation.")
        if not isinstance(branch_code, str) or branch_code not in self.branches:
            raise SimulationError("This branch has no runnable inbound queue.")
        if type(position) is not int:
            raise SimulationError("An inbound queue position is required.")

        branch = self.branches[branch_code]
        previous = self.last_steps.get(branch_code)
        if previous and position == previous["row"]["position"]:
            return previous
        next_position = previous["row"]["position"] + 1 if previous else 1
        if position != next_position or position > len(branch["queue"]):
            raise SimulationError("That row is outside the next step of this simulation.")

        row = dict(branch["queue"][position - 1])
        outcome = {"row": row, "placement": None, "calculation": None}
        if row["status"] == "pending":
            yard = branch["yard"]
            container = Container(**branch["inputs"]["inbound_containers"][position - 1])
            search = {}
            try:
                result = yard.assignContainer(container, trace=search)
                outcome["calculation"] = _calculation(yard, search, result)
                if result is not None:
                    yard.placeContainerWithAssignResult(result)
            except PlacementRejected as error:
                row.update(status="unplaced", reason=str(error))
            else:
                if result is None:
                    row.update(status="unplaced", reason="No stack qualified under the current placement rules.")
                else:
                    row["status"] = "placed"
                    coordinates = result.getBestCoordinate()
                    proposal = PlacementProposal(*coordinates, container.getContSize())
                    outcome["placement"] = {
                        **_location(yard, coordinates),
                        "container_id": container.getId(),
                        "parameter_compliance": yard.getBlockByID(proposal.block_id).parameterCompliance(),
                        "stacks": [
                            stack_view(yard.getStack(block_id, r, s), r + 1, s + 1)
                            for block_id, r, s in proposal.footprint
                        ],
                    }
        self.last_steps[branch_code] = outcome
        return outcome

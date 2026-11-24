"""Advance a prepared yard one inbound CSV row at a time."""

import csv
from io import StringIO
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.container import InboundDummyContainer
from entities.feasibility.placement_proposal import PlacementProposal
from filewriter import ContainerFileWriter
from repository.branch_repository import BranchDirectory
from utils import parse_optional_finite_float, strGeneralize

from .scenario import inbound_queue_row
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
INBOUND_DETAIL_CODES = (
    "container_fill", "container_condition", "container_grade", "operation_type", "principal",
    "pol", "pot", "pod", "vessel", "voyage", "vessel_operator",
)


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


def _manual_proposal(yard, container, destination):
    if not isinstance(destination, dict) or destination.keys() != {"block", "row", "slot", "tier"}:
        raise SimulationError("Choose a block, row, slot, and tier.")
    block = next((block for block in yard.blocks_by_id.values() if block.getCode() == destination["block"]), None)
    indices = [destination[key] for key in ("row", "slot", "tier")]
    if block is None or any(type(index) is not int or index < 1 for index in indices):
        raise SimulationError("Choose a coordinate inside the yard grid.")
    row, slot, tier = (index - 1 for index in indices)
    try:
        return PlacementProposal(block.getId(), row, slot, tier, container.getContSize())
    except ValueError as error:
        raise SimulationError("Choose a complete 40 ft slot pair inside the yard grid.") from error


def _placement_view(yard, container, proposal):
    block = yard.getBlockByID(proposal.block_id)
    return {
        **_location(yard, proposal.coordinates),
        "container_id": container.getId(),
        "parameter_compliance": block.parameterCompliance(),
        "stacks": [
            stack_view(yard.getStack(block_id, row, slot), row + 1, slot + 1)
            for block_id, row, slot in proposal.footprint
        ],
    }


def _inbound_container(branch, row):
    container_type = InboundDummyContainer if row.get("dummy") else Container
    return container_type(**branch["inputs"]["inbound_containers"][row["input_position"] - 1])


def _calculation(yard, search, result):
    settings = yard.feasibility.settings
    prioritize_current_access = settings.prioritize_current_loader_access
    destination_mode = settings.effective_destination_loader_access_mode
    occupied_mode = settings.effective_occupied_loader_access_mode
    score_destination = destination_mode == "heuristic"
    prioritize_destination = settings.prioritize_loader_destination
    future_mode = settings.effective_future_loader_access_mode
    candidates = result.sorted_candidate_evaluations if result is not None else []
    winner = candidates[0] if candidates else None
    winning_key = winner.ranking_key(prioritize_current_access, prioritize_destination) if winner else None
    ranked_by_location = {candidate.coordinates: (rank, candidate) for rank, candidate in enumerate(candidates, 1)}
    qualified = []
    for coordinates in search["candidate_coordinates"]:
        rank, candidate = ranked_by_location[coordinates]
        access = candidate.loader_access
        qualified.append({
            **_location(yard, coordinates),
            "selected": candidate is winner,
            "rank": rank if rank <= 5 else None,
            "candidate_rank": rank,
            "parameters": [parameter.getId() for parameter in candidate.parameters],
            "equipment": candidate.equipment.getCode() if candidate.equipment is not None else None,
            "distance": _number(candidate.distance),
            "equipment_outside_block": candidate.distance == float("inf"),
            "mass_difference": _number(candidate.delta_container_mass),
            "mass_multiplier": _number(yard.model.deltaContainerMass(candidate.delta_container_mass)),
            "distance_multiplier": _number(yard.model.equipmentDistance(candidate.distance)),
            "cluster_multiplier": _number(candidate.size_cluster_multiplier),
            "loader_destination_accessible": access.destination_accessible if access and destination_mode != "off" else None,
            "isolated_occupied_locations": len(access.isolated_occupied_locations) if access and occupied_mode != "off" else None,
            "isolated_future_locations": (
                len(access.isolated_locations) if access and future_mode != "off" else None
            ),
            "loader_access_multiplier": candidate.loader_access_multiplier,
            "loader_destination_multiplier": candidate.loader_destination_multiplier,
            "future_loader_access_multiplier": candidate.future_loader_access_multiplier,
            "stacking_safety_multiplier": candidate.stacking_safety_multiplier,
            "capacity_multiplier": candidate.capacity_multiplier,
            "overcapacity_tiers": candidate.overcapacity_tiers,
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
        "winning_score_ties": sum(candidate.ranking_key(prioritize_current_access, prioritize_destination) == winning_key
                                  for candidate in candidates),
        "prioritize_current_loader_access": prioritize_current_access,
        "prioritize_loader_destination": prioritize_destination,
        "enabled_multipliers": [
            name for name, enabled in (
                ("mass_multiplier", yard.model.enable_delta_container_mass),
                ("distance_multiplier", yard.model.enable_equipment_distance and yard.hasEquipment()),
                ("cluster_multiplier", yard.model.enable_size_cluster),
                ("loader_destination_multiplier", score_destination),
                ("loader_access_multiplier", occupied_mode == "heuristic"),
                ("future_loader_access_multiplier", future_mode == "heuristic"),
                ("stacking_safety_multiplier", settings.effective_stacking_safety_mode == "heuristic"),
                ("capacity_multiplier", settings.stack_capacity_mode == "heuristic"),
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
        self._suggestions = {}
        if any(problem["severity"] == "error" and problem["dataset"] != "inbound_containers"
               for problem in scenario["issues"]):
            return
        for branch in scenario["branches"]:
            yard = branch["yard"]
            if (yard is not None and yard.blocks_by_id
                    and not any(problem["severity"] == "error" and problem["dataset"] != "inbound_containers"
                                for problem in branch["issues"])):
                self.branches[branch["branch_code"]] = branch

    def _active_branch(self, simulation_id, branch_code):
        if simulation_id != self.id:
            raise SimulationError("Generate a new preview to start a simulation.")
        if not isinstance(branch_code, str) or branch_code not in self.branches:
            raise SimulationError("This branch has no runnable inbound queue.")
        return self.branches[branch_code]

    def add_queue_row(self, simulation_id, branch_code, container_id, size, dummy, details=None):
        branch = self._active_branch(simulation_id, branch_code)
        if size not in ("20", "40"):
            raise SimulationError("Choose a container size of 20 or 40 ft.")
        if type(dummy) is not bool:
            raise SimulationError("Choose whether this is a dummy container.")
        queue = branch["queue"]
        existing_records = branch["inputs"].get("inbound_containers", ())
        input_position = len(existing_records) + 1
        used_ids = branch["yard"].containers.keys() | {row["container_id"] for row in queue}
        if dummy:
            number = input_position
            container_id = f"DUMMY-INBOUND-{number}"
            while container_id in used_ids:
                number += 1
                container_id = f"DUMMY-INBOUND-{number}"
        else:
            if not isinstance(container_id, str) or not container_id.strip():
                raise SimulationError("Enter a container ID.")
            container_id = strGeneralize(container_id.strip())
            if container_id in used_ids:
                raise SimulationError("That container ID is already in the yard or inbound queue.")

        if details is None:
            details = {}
        if not isinstance(details, dict) or any(not isinstance(value, str) for value in details.values()):
            raise SimulationError("Enter container details as text or numbers in the form.")
        record = {field: strGeneralize(details.get(field, "").strip()) for field in INBOUND_DETAIL_CODES}
        record.update(container_id=container_id, container_size=size, weight=details.get("weight", "").strip(),
                      move_time=details.get("move_time", "").strip())
        if record["container_fill"] not in ("", "F", "E"):
            raise SimulationError("Choose Full or Empty, or leave that field blank.")
        if record["weight"] and parse_optional_finite_float(record["weight"]) is None:
            raise SimulationError("Enter a finite weight.")
        try:
            container = Container(**record)
        except (ValueError, OverflowError, OSError) as error:
            raise SimulationError("Enter a valid move time, such as YYYY-MM-DD HH:MM.") from error

        row = inbound_queue_row(record, len(queue) + 1, input_position, weight=container.getWeight())
        row.update(manual=True, dummy=dummy)
        branch["inputs"].setdefault("inbound_containers", []).append(record)
        queue.append(row)
        summary = branch["summary"]
        summary["inbound_containers"] = len(queue)
        summary["valid_inbound"] = summary.get("valid_inbound", 0) + 1
        return row

    def reorder_queue(self, simulation_id, branch_code, order):
        branch = self._active_branch(simulation_id, branch_code)
        queue = branch["queue"]
        previous = self.last_steps.get(branch_code)
        processed = previous["row"]["position"] if previous else 0
        remaining = {row["input_position"]: row for row in queue[processed:]}
        if (not isinstance(order, list) or len(order) != len(remaining)
                or any(type(key) is not int for key in order) or set(order) != remaining.keys()):
            raise SimulationError("The new order must include each remaining inbound row exactly once.")
        if order and order[0] != queue[processed]["input_position"]:
            self.invalidate_suggestion(branch_code)
        queue[processed:] = [dict(remaining[key], position=position)
                             for position, key in enumerate(order, processed + 1)]

    def delete_queue_row(self, simulation_id, branch_code, input_position):
        branch = self._active_branch(simulation_id, branch_code)
        records = branch["inputs"].get("inbound_containers", ())
        if type(input_position) is not int or not 1 <= input_position <= len(records):
            raise SimulationError("Select an inbound row to delete.")
        previous = self.last_steps.get(branch_code)
        processed = previous["row"]["position"] if previous else 0
        queue = branch["queue"]
        for index, row in enumerate(queue):
            if row["input_position"] != input_position:
                continue
            if index < processed:
                raise SimulationError("Processed containers cannot be deleted from the queue.")
            queue.pop(index)
            for position in range(index, len(queue)):
                queue[position]["position"] = position + 1
            branch["summary"]["inbound_containers"] -= 1
            branch["summary"]["valid_inbound"] -= row["status"] == "pending"
            if index == processed:
                self.invalidate_suggestion(branch_code)
            return

    def invalidate_suggestion(self, branch_code):
        self._suggestions.pop(branch_code, None)

    def suggest(self, simulation_id, branch_code):
        branch = self._active_branch(simulation_id, branch_code)
        if branch_code in self._suggestions:
            return self._suggestions[branch_code][0]
        previous = self.last_steps.get(branch_code)
        index = previous["row"]["position"] if previous else 0
        if index == len(branch["queue"]):
            return None
        row = dict(branch["queue"][index])
        yard = branch["yard"]
        if (row["input_position"] in branch.get("yard_conflicts", ())
                and row["container_id"] not in yard.containers):
            row.update(status="pending", reason=None)
        suggestion = {"suggestion_id": uuid4().hex, "row": row, "calculation": None}
        result = None
        if row["status"] == "pending":
            container = _inbound_container(branch, row)
            search = {}
            try:
                result = yard.assignContainer(container, trace=search)
            except PlacementRejected as error:
                row.update(status="unplaced", reason=str(error))
            else:
                suggestion["calculation"] = _calculation(yard, search, result)
                if result is None:
                    row.update(status="unplaced", reason="No stack qualified under the current placement rules.")
                else:
                    row["status"] = "suggested"
        self._suggestions[branch_code] = (suggestion, result)
        return suggestion

    def step(self, simulation_id, branch_code, position, suggestion_id=None, alternate_rank=None, manual_destination=None):
        branch = self._active_branch(simulation_id, branch_code)
        manual = manual_destination is not None
        if type(position) is not int:
            raise SimulationError("An inbound queue position is required.")
        if alternate_rank is not None and (type(alternate_rank) is not int or alternate_rank < 2 or not suggestion_id):
            raise SimulationError("Choose an alternate location from the current assignment.")
        if manual and (not suggestion_id or alternate_rank is not None):
            raise SimulationError("Choose one manual location for the current container.")

        previous = self.last_steps.get(branch_code)
        if previous and position == previous["row"]["position"]:
            if suggestion_id is not None and suggestion_id != previous["suggestion_id"]:
                raise SimulationError("The current suggestion has changed.")
            if alternate_rank is not None and alternate_rank != previous.get("alternate_rank"):
                raise SimulationError("This container has already been processed at a different location.")
            if manual and manual_destination != previous.get("manual_destination"):
                raise SimulationError("This container has already been processed at a different location.")
            return previous
        next_position = previous["row"]["position"] + 1 if previous else 1
        if position != next_position or position > len(branch["queue"]):
            raise SimulationError("That row is outside the next step of this simulation.")

        suggestion = self.suggest(simulation_id, branch_code)
        if suggestion_id is not None and suggestion_id != suggestion["suggestion_id"]:
            raise SimulationError("The current suggestion has changed.")
        row = dict(suggestion["row"])
        outcome = {**suggestion, "row": row, "placement": None}
        result = self._suggestions[branch_code][1]
        yard = branch["yard"]
        if alternate_rank is not None and (result is None or alternate_rank > len(result.sorted_candidate_evaluations)):
            raise SimulationError("Choose an alternate location from the current assignment.")
        if manual:
            if suggestion["calculation"] is None:
                raise SimulationError("Choose a valid inbound container.")
            container = result.container if result is not None else _inbound_container(branch, row)
            proposal = _manual_proposal(yard, container, manual_destination)
            try:
                updates, displaced = yard.placeContainerManually(container, proposal)
            except PlacementRejected as error:
                raise SimulationError(str(error)) from error
            outcome["manual_destination"] = _location(yard, proposal.coordinates)
            outcome["placement"] = {
                **_placement_view(yard, container, proposal),
                "updated_stacks": [stack_view(stack, stack.getCoords()[1] + 1, stack.getCoords()[2] + 1) for stack in updates],
                "displaced": displaced,
                "manual": True,
            }
            row["status"] = "placed"
        elif result is not None:
            candidate = result.sorted_candidate_evaluations[alternate_rank - 1] if alternate_rank else result.getBestCandidate()
            coordinates = candidate.coordinates
            try:
                yard.placeContainer(result.container, coordinates, candidate.equipment)
            except PlacementRejected as error:
                if alternate_rank is not None:
                    self.invalidate_suggestion(branch_code)
                    raise SimulationError(str(error)) from error
                row.update(status="unplaced", reason=str(error))
            else:
                row["status"] = "placed"
                if alternate_rank is not None:
                    outcome["alternate_rank"] = alternate_rank
                proposal = PlacementProposal(*coordinates, result.container.getContSize())
                outcome["placement"] = _placement_view(yard, result.container, proposal)
        self.last_steps[branch_code] = outcome
        self.invalidate_suggestion(branch_code)
        return outcome

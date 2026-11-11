"""Advance a prepared yard one inbound CSV row at a time."""

from math import isfinite
from uuid import uuid4

from entities import Container
from entities.bad_yard_data import PlacementRejected
from entities.feasibility.placement_proposal import PlacementProposal

from .yard_view import stack_view


class SimulationError(ValueError):
    """The requested step does not belong to the active run."""


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

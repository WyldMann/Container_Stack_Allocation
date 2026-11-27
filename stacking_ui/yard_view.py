"""Serialize the built yard for the offline preview map."""

from math import isfinite
from dataclasses import asdict

from config.application.heuristic_settings import BLOCK_STACKING_START_HALF_DISTANCE
from entities.container import DummyContainer
from entities.feasibility.equipment_access import BlockBorderAccessPolicy


def _parameter_view(parameter):
    criteria = []
    for label, expected, points in (
        ("Size", parameter.container_size, parameter.container_size_score),
        ("Fill", parameter.container_fill, parameter.container_fill_score),
        ("Grade", ", ".join(filter(None, parameter.container_grade)), parameter.container_grade_score),
        ("Condition", parameter.container_condition, parameter.container_condition_score),
        ("Operation", parameter.operation_type, parameter.operation_type_score),
        ("Principal", parameter.principal, parameter.principal_score),
    ):
        if expected:
            criteria.append({"label": label, "value": expected, "points": points})
    for label, first, second, points in (
        ("Route (POL / POD)", parameter.pol, parameter.pod, parameter.route_score),
        ("Vessel / voyage", parameter.vessel, parameter.voyage, parameter.vessel_voyage_score),
    ):
        if first or second:
            criteria.append({"label": label, "value": f"{first or 'Any'} / {second or 'Any'}", "points": points})
    if parameter.weight_range_score or parameter.weight_start or isfinite(parameter.weight_end):
        upper = f"{parameter.weight_end:g}" if isfinite(parameter.weight_end) else "no limit"
        criteria.append({
            "label": "Weight",
            "value": f"{parameter.weight_start:g} to {upper}",
            "points": parameter.weight_range_score,
        })
    return {"name": parameter.getName(), "criteria": criteria, "and_score": parameter.and_score}


def dummy_tier_view(container, tier):
    view = {"tier": tier, "dummy": True}
    if container.spans_pair:
        view.update(size="40", anchor_slot=container.getCoordsInt()[3] + 1)
    return view


def stack_view(stack, row, slot):
    tiers = []
    for tier_no, container in enumerate(stack.getContainers(), 1):
        if container is None:
            continue
        if isinstance(container, DummyContainer):
            tiers.append(dummy_tier_view(container, tier_no))
            continue
        weight = container.getWeight()
        tiers.append({
            "tier": tier_no,
            "container_id": container.getId(),
            "size": container.getContSize(),
            "fill": container.getContFill(),
            "operation": container.getOpType(),
            "grade": container.getContGrade(),
            "weight": weight if weight is not None and isfinite(weight) else None,
            "anchor_slot": container.getCoordsInt()[3] + 1,
        })
    return {
        "row": row, "slot": slot, "capacity": stack.getMaxTier(),
        "removed": stack.getMode() == "X", "anomaly": stack.anomaly(),
        "parameters": [parameter.getId() for parameter in stack.getParameters()],
        "tiers": tiers,
    }


def block_equipment_codes(block):
    rtg = block.getRTG()
    codes = [rtg.getCode()] if rtg is not None else []
    codes.extend(sorted(loader.getCode() for loader in block.getLoaders()))
    return codes


def stacking_start_view(yard, block):
    override = yard.stacking_start_by_block.get(block.getId())
    effective = asdict(yard.stackingStartForBlock(block))
    if effective["axis"] != "off" and effective["half_distance"] is None:
        effective["half_distance"] = BLOCK_STACKING_START_HALF_DISTANCE
    return {"override": asdict(override) if override is not None else None, "effective": effective,
            "half_distance_if_blank": BLOCK_STACKING_START_HALF_DISTANCE,
            "error": yard.stackingStartError(block, override)}


def yard_view(yard):
    """Build a read-only map with one-based locations and sparse tier contents."""
    parameters = {}
    blocks = []
    for block in sorted(yard.blocks_by_id.values(), key=lambda b: (b.getPosY(), b.getPosX(), b.getCode())):
        grid = block.getSlots()
        rtg = block.getRTG()
        stacks = []
        containers = set()
        for row_no, row in enumerate(grid, 1):
            for slot_no, stack in enumerate(row, 1):
                for parameter in stack.getParameters():
                    key = parameter.getId()
                    if key not in parameters:
                        parameters[key] = _parameter_view(parameter)
                view = stack_view(stack, row_no, slot_no)
                containers.update(tier["container_id"] for tier in view["tiers"] if not tier.get("dummy"))
                stacks.append(view)
        blocks.append({
            "id": block.getId(),
            "border_access": asdict(yard.border_access_policies.get(block.getId(), BlockBorderAccessPolicy())),
            "stacking_start": stacking_start_view(yard, block),
            "code": block.getCode(), "x": block.getPosX(), "y": block.getPosY(),
            "rtg_code": rtg.getCode() if rtg is not None else None,
            "equipment_codes": block_equipment_codes(block),
            "rows": len(grid), "slots": len(grid[0]),
            "tier_limit": block.max_tier,
            "occupied_tiers": sum(len(stack["tiers"]) for stack in stacks),
            "tier_capacity": sum(stack["capacity"] for stack in stacks),
            "container_count": len(containers),
            "parameter_compliance": block.parameterCompliance(),
            "stacks": stacks,
        })
    return {"blocks": blocks, "parameters": parameters,
            "ground_equipment_codes": sorted(loader.getCode() for loader in yard.master_loaders)}

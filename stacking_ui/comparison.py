"""Compare a completed simulated yard with a CSV snapshot of the same branch."""

from collections import Counter
from csv import Error as CSVError
from pathlib import Path
from tempfile import TemporaryDirectory

from config.application.input_filters import mapped_filters
from entities import Container, Yard
from entities.container import DummyContainer
from repository import CSVLoader, InputError
from repository.repository import Repository
from utils import strGeneralize


class SnapshotRepository(Repository):
    required_fields = ("branch_id", "block_code", "row_no", "slot_no", "tier_no", "container_size")


def _read_snapshot(branch, name, text):
    profile = branch["container_profile"]
    identity, = branch["inputs"]["terminal_branches"]
    scope_ids = {}
    for field in ("branch_id", "terminal_id"):
        value = identity[field]
        try:
            scope_ids[field] = int(value)
        except ValueError:
            scope_ids[field] = value
    with TemporaryDirectory(prefix="stacking-compare-") as directory:
        path = Path(directory) / "containers.csv"
        path.write_text(text, encoding="utf-8", newline="")
        try:
            records = SnapshotRepository(CSVLoader(path), profile).read_source_records()
            if profile.filter_columns:
                branch_column = profile.filter_columns.get("branch_code")
                loader = CSVLoader(path, filters=mapped_filters(scope_ids, profile.filter_columns),
                                   branch_column=branch_column, branch_codes=(branch["branch_code"],))
                scoped = SnapshotRepository(loader, profile).read_source_records()
            else:
                scoped = records
        except (ValueError, CSVError) as error:
            raise InputError(str(error).replace(str(path), name)) from error

    selected = []
    branch_id = identity["branch_id"]
    for location, raw in scoped:
        value = raw["branch_id"].strip().upper()
        if profile.branch_kind == "code":
            matches = value == branch["branch_code"]
        else:
            matches = strGeneralize(value) == strGeneralize(branch_id)
        if matches:
            record = {key: strGeneralize(value) for key, value in raw.items()}
            record["branch_id"] = branch_id
            selected.append((int(location.rsplit(", line ", 1)[1]), record))
    if records and not selected:
        raise InputError(f"{name} has no container records for branch {branch['branch_code']}.")
    return selected, len(records) - len(selected)


def _snapshot_yard(inputs, records):
    yard = Yard(inputs["yard_blocks"], removed_slots_input=inputs["removed_slots"],
                parameters_input=inputs["parameters"], yard_planning_input=inputs["yard_planning"])
    issues = []
    candidates = []
    for line, record in records:
        try:
            container = Container(**record)
        except (ValueError, TypeError, OverflowError, OSError) as error:
            issues.append({"line": line, "container": record["container_id"], "message": str(error)})
            continue
        candidates.append((line, container))
        if yard.bad_data.incomplete_existing_container.validateExistingAndRecord(container):
            yard.addContainerInput(container)

    bad = yard.bad_data
    incomplete = set(bad.getIncompleteExistingContainers())
    duplicates = set(bad.getDuplicateExistingContainerIDs())
    invalid = set(bad.getContainerCoordsInvalid())
    for line, container in candidates:
        if yard.containers.get(container.getId()) is container:
            continue
        if container in incomplete:
            message = "Missing container ID, size, or coordinates."
        elif container in duplicates:
            message = "Duplicate container ID."
        elif container in invalid:
            message = "Unknown block, invalid coordinates, or incompatible footprint."
        else:
            message = "Overlapping container record was excluded."
        issues.append({"line": line, "container": container.getId(), "message": message})
    return yard, sorted(issues, key=lambda item: item["line"])


def _placement(container):
    if container is None:
        return None
    _, block, row, slot, tier = container.getCoordsInt()
    return {"block": block, "row": row + 1, "slot": slot + 1, "tier": tier + 1,
            "size": container.getContSize()}


def _overview(yard):
    container_counts = Counter(container.getCoordsStr()[1] for container in yard.containers.values())
    blocks = {}
    for block in yard.blocks_by_id.values():
        stacks = [stack for row in block.getSlots() for stack in row]
        blocks[block.getCode()] = {
            "containers": container_counts[block.getCode()],
            "occupied_tiers": sum(stack.occupancy() for stack in stacks),
            "tier_capacity": sum(stack.getMaxTier() for stack in stacks),
            "dummy_tiers": sum(isinstance(container, DummyContainer) for stack in stacks
                               for container in stack.getContainers()),
            "anomalous_stacks": sum(stack.anomaly() for stack in stacks),
            "parameter_compliance": block.parameterCompliance(),
        }
    total = {key: sum(block[key] for block in blocks.values()) for key in (
        "containers", "occupied_tiers", "tier_capacity", "dummy_tiers", "anomalous_stacks",
    )}
    total["parameter_compliance"] = (
        sum(block["containers"] * (block["parameter_compliance"] or 0) for block in blocks.values())
        / total["containers"] if total["containers"] else None
    )
    for metrics in (total, *blocks.values()):
        capacity = metrics["tier_capacity"]
        metrics["occupancy_rate"] = metrics["occupied_tiers"] / capacity if capacity else None
    return total, blocks


def _occupied_slots(block):
    slots = []
    for row_no, row in enumerate(block.getSlots(), 1):
        for slot_no, stack in enumerate(row, 1):
            if not stack.occupancy():
                continue
            tiers = [
                {"tier": tier, "container": container.getId(), "size": container.getContSize()}
                if not isinstance(container, DummyContainer) else {"tier": tier, "dummy": True}
                for tier, container in enumerate(stack.getContainers(), 1) if container is not None
            ]
            slots.append({"row": row_no, "slot": slot_no, "tiers": tiers})
    return slots


def _block_comparisons(simulated, reference, actual_metrics, reference_metrics):
    blocks = []
    for code, actual in sorted(simulated.blocks_by_code.items()):
        other = reference.blocks_by_code[code]
        grid = actual.getSlots()
        block_code = actual.getCode()
        blocks.append({
            "block": block_code,
            "simulated": actual_metrics[block_code], "reference": reference_metrics[block_code],
            "layout": {
                "rows": len(grid), "slots": len(grid[0]),
                "removed": [[r, s] for r, row in enumerate(grid, 1) for s, stack in enumerate(row, 1)
                            if stack.getMode() == "X"],
                "simulated": _occupied_slots(actual), "reference": _occupied_slots(other),
            },
        })
    return blocks


def compare_yard(branch, name, text):
    if not isinstance(name, str) or not name.lower().endswith(".csv") or not isinstance(text, str):
        raise InputError("Choose a UTF-8 CSV in the same format as containers.csv.")
    records, excluded = _read_snapshot(branch, name, text)
    reference, issues = _snapshot_yard(branch["inputs"], records)
    simulated = branch["yard"]
    counts = dict.fromkeys(("same", "moved", "simulated_only", "reference_only"), 0)
    differences = []
    for container_id in sorted(simulated.containers.keys() | reference.containers.keys()):
        actual = _placement(simulated.containers.get(container_id))
        other = _placement(reference.containers.get(container_id))
        if actual == other:
            counts["same"] += 1
            continue
        status = "reference_only" if actual is None else "simulated_only" if other is None else "moved"
        counts[status] += 1
        differences.append({"container": container_id, "status": status,
                            "simulated": actual, "reference": other})
    actual_total, actual_blocks = _overview(simulated)
    other_total, other_blocks = _overview(reference)
    return {
        "file": name, "branch": branch["branch_code"], "counts": counts, "differences": differences,
        "simulated": actual_total, "reference": other_total, "excluded": excluded, "issues": issues,
        "blocks": _block_comparisons(simulated, reference, actual_blocks, other_blocks),
    }

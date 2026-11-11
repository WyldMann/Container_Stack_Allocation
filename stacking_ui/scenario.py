"""Prepare CSV scenarios with the existing repository and yard rules.

prepare_scenario returns the actual Yard and ordered inbound inputs to future
simulation callers. public_preview returns only JSON-safe review information.
No placements, output CSV writes, or changes to project configuration occur.
"""

from collections import Counter, defaultdict, deque
import csv
from dataclasses import asdict
from pathlib import Path
import tempfile
import warnings

from config.application.config_loader import ConfigurationError
from config.application.input_config import parse_input_config
from config.application.input_filters import branch_input_settings
from config.csv_import.mapping_settings import SCHEMAS
from entities import Container, Yard
from entities.bad_yard_data import BadYardData, PlacementRejected
from repository import CSVLoader, InputError, load_yard_inputs
from repository.repository import Repository
from utils import strGeneralize

from .configuration import configuration, draft_files, dump_toml, portable_input
from .yard_view import yard_view


def issue(dataset, message, *, severity="error", sources=(), field=None, category="input"):
    return {"dataset": dataset, "severity": severity, "category": category,
            "message": message, "field": field, "sources": list(sources)}


def _count(value):
    if isinstance(value, dict):
        return sum(len(items) for items in value.values())
    return len(value)


def prepare_scenario(payload):
    """Build independent branch previews from one immutable request draft."""
    settings, mapping, profiles, input_document = configuration(payload)
    files = draft_files(payload, profiles, input_document)
    input_document = portable_input(input_document)
    result = {"branches": [], "issues": [], "datasets": {},
              "config_toml": dump_toml(asdict(settings)),
              "mapping_toml": dump_toml(mapping), "input_toml": dump_toml(input_document)}
    source_records = {}
    with tempfile.TemporaryDirectory(prefix="stacking-import-") as temporary:
        root = Path(temporary)
        (root / "csv_mapping.toml").write_text(dump_toml(mapping), encoding="utf-8")
        for name in SCHEMAS:
            upload = files.get(name)
            if isinstance(upload, dict) and upload.get("error"):
                result["issues"].append(issue(name, upload["error"]))
                continue
            if not isinstance(upload, dict) or not isinstance(upload.get("content"), str):
                result["issues"].append(issue(name, "Select a CSV or explicitly choose an empty dataset."))
                continue
            filename = upload.get("name", name + ".csv")
            if not isinstance(filename, str) or not filename.lower().endswith(".csv"):
                result["issues"].append(issue(name, "The selected file must be a UTF-8 CSV."))
                continue
            # Names supplied by the browser are labels only, never paths.
            path = root / (name + ".csv")
            path.write_text(upload["content"].lstrip("\ufeff"), encoding="utf-8", newline="")
            try:
                records = Repository(CSVLoader(path), profiles[name]).read_source_records()
            except (InputError, UnicodeError, ValueError, csv.Error) as error:
                message = str(error).replace(str(path), filename)
                result["issues"].append(issue(name, message))
                continue
            # Retain source scope columns too: parameters/equipment may reuse IDs
            # across branches even when those columns are not domain fields.
            with CSVLoader(path).open() as (headers, raw_rows):
                header_lookup = {header.strip().casefold(): header for header in headers}
                scopes = {location: {field: raw.get(header_lookup.get(column.strip().casefold()), "")
                                     for field, column in profiles[name].filter_columns.items()}
                          for location, raw in raw_rows}
            source_records[name] = [
                ({"file": filename, "line": int(location.rsplit("line ", 1)[1])}, record, scopes[location])
                for location, record in records
            ]
            result["datasets"][name] = {"file": filename, "rows": len(records),
                "columns": {field: profiles[name].columns.get(field, field)
                            for field in profiles[name].schema.fields}}
        # The shared validator still handles filter types and all source choices.
        input_settings = parse_input_config(input_document, base_dir=root)
        if not input_settings["filters"].get("branch_code"):
            raise ConfigurationError("Select at least one branch code; each yard is prepared separately.")
        if any(problem["dataset"] != "inbound_containers" for problem in result["issues"]):
            return result
        inbound_available = "inbound_containers" in source_records
        if not inbound_available:
            input_settings["sources"].pop("inbound_containers", None)
            source_records["inbound_containers"] = []
        known_codes = {row["branch_code"].strip().upper() for _, row, _ in source_records["terminal_branches"]}
        known_ids = {strGeneralize(row["branch_id"].strip()) for _, row, _ in source_records["terminal_branches"]}
        for name in ("existing_containers", "inbound_containers", "equipment_history"):
            for origin, row, _ in source_records[name]:
                identity = row["branch_id"].strip().upper()
                if name == "inbound_containers" and not identity:
                    continue
                known = known_codes if profiles[name].branch_kind == "code" else known_ids
                if profiles[name].branch_kind == "id":
                    identity = strGeneralize(identity)
                if identity not in known:
                    result["issues"].append(issue(name, "Unknown or missing branch reference; record cannot be assigned to a yard.",
                                                  sources=[origin], field="branch_id"))
        for selection in branch_input_settings(input_settings):
            code = selection["filters"]["branch_code"]
            branch = {"branch_code": code, "issues": [], "queue": [], "yard": None,
                      "inputs": None, "counts": {}, "summary": {},
                      "container_profile": profiles["existing_containers"],
                      "inbound_available": inbound_available}
            result["branches"].append(branch)
            try:
                inputs = load_yard_inputs(selection, include_shifting=False)
                branch["inputs"] = inputs
                branch["branch_name"] = inputs["terminal_branches"][0]["branch_name"]
                branch["counts"] = {name: len(value) if name != "yard_planning" else _count(value)
                                    for name, value in inputs.items()}
                _build_branch(branch, inputs, settings, profiles, source_records)
            except (InputError, ConfigurationError, ValueError, TypeError, KeyError, OverflowError) as error:
                message = str(error)
                for name, upload in files.items():
                    message = message.replace(str(root / (name + ".csv")), upload.get("name", name + ".csv"))
                branch["issues"].append(issue("scenario", message))
    return result


def _build_branch(branch, inputs, settings, profiles, source_records):
    branch_id = inputs["terminal_branches"][0]["branch_id"]
    code = branch["branch_code"]

    def in_scope(scope):
        identity = inputs["terminal_branches"][0]
        for field, actual in scope.items():
            expected = identity[field]
            if field == "branch_code":
                if actual.strip().upper() != code:
                    return False
            else:
                try:
                    expected = int(expected)
                except ValueError:
                    pass
                if not CSVLoader._matches(actual, expected):
                    return False
        return True

    source_indexes = {}

    def source_index(name, fields):
        index = defaultdict(list)
        for origin, raw, scope in source_records[name]:
            if not in_scope(scope):
                continue
            row = {key: strGeneralize(value) for key, value in raw.items()}
            if name == "terminal_branches":
                row = {key: value.strip() for key, value in raw.items()}
            if profiles[name].branch_kind == "code" and row.get("branch_id", "").strip().upper() == code:
                row["branch_id"] = branch_id
            # A blank inbound branch intentionally belongs to each selected run.
            if name in ("existing_containers", "inbound_containers", "equipment_history"):
                expected_id = branch_id if profiles[name].branch_kind == "code" else strGeneralize(branch_id)
                if row.get("branch_id", "").strip() not in ("", expected_id):
                    continue
            index[tuple(row.get(key) for key in fields)].append(origin)
        return index

    def sources(name, criteria):
        fields = tuple(sorted(criteria))
        key = (name, fields)
        if key not in source_indexes:
            source_indexes[key] = source_index(name, fields)
        return source_indexes[key].get(tuple(criteria[field] for field in fields), ())

    def add(name, message, criteria=None, **kwargs):
        branch["issues"].append(issue(name, message,
            sources=sources(name, criteria) if criteria is not None else (), **kwargs))

    # Surface genuinely unknown references which the legacy scoping pass drops.
    # References to a known block in another branch are simply out of scope.
    known_blocks = {strGeneralize(row["block_id"]) for _, row, _ in source_records["yard_blocks"]}
    known_coords = {(strGeneralize(row["branch_id"]), strGeneralize(row["block_code"]))
                    for _, row, _ in source_records["yard_blocks"]}
    for name in ("removed_slots", "yard_planning", "existing_containers"):
        for origin, raw, scope in source_records[name]:
            if not in_scope(scope):
                continue
            row = {key: strGeneralize(value) for key, value in raw.items()}
            if name == "existing_containers":
                row_branch = row["branch_id"].strip().upper()
                expected = code if profiles[name].branch_kind == "code" else branch_id
                if row_branch != expected:
                    continue
                unknown = (branch_id, row["block_code"]) not in known_coords
            else:
                unknown = row["block_id"] not in known_blocks
            if unknown:
                branch["issues"].append(issue(name, "Unknown block reference; record was excluded by yard filtering.",
                    sources=[origin], field="block_code" if name == "existing_containers" else "block_id"))

    # Date parsing can otherwise abort Yard construction before BadYardData runs.
    for row in inputs["existing_containers"]:
        try:
            container = Container(**row)
            if row["weight"].strip() and container.getWeight() is None:
                add("existing_containers", "Invalid weight is treated as unknown by the stacking engine.", row,
                    field="weight", severity="warning")
        except (ValueError, TypeError, OverflowError, OSError) as error:
            add("existing_containers", str(error), row, field="move_time")
    if any(item["field"] == "move_time" and item["severity"] == "error" for item in branch["issues"]):
        return

    # Guard accidental enormous grids before allocating nested Stack objects.
    cells = 0
    for row in inputs["yard_blocks"]:
        try:
            cells += max(0, int(row["row_count"])) * max(0, int(row["slot_count"])) * max(0, int(row["max_tier"]))
        except ValueError:
            continue  # Existing domain validation reports malformed dimensions.
    if cells > 2_000_000:
        add("yard_blocks", "Preview exceeds the limit of 2,000,000 tier cells. Check block dimensions.")
        return

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        yard = Yard(
            yard_blocks_input=inputs["yard_blocks"], removed_slots_input=inputs["removed_slots"],
            parameters_input=inputs["parameters"], yard_planning_input=inputs["yard_planning"],
            containers_input=inputs["existing_containers"], equipment_input=inputs["master_equipment"],
            equipment_locations_input=inputs["equipment_history"],
            feasibility_settings=settings.feasibility, heuristic_settings=settings.heuristic,
        )
    branch["yard"] = yard
    for warning in recorded:
        add("master_equipment", str(warning.message), severity="warning")
    bad = yard.bad_data
    categories = {"block": "yard_blocks", "parameter": "parameters", "removed_slot": "removed_slots",
                  "yard_planning": "yard_planning"}

    def location_criteria(location):
        return {"block_id": location[0], "row_no": str(location[1] + 1), "slot_no": str(location[2] + 1)}

    for problem in bad.getImportErrors():
        name = categories[problem.category]
        criteria = problem.record
        if problem.category == "removed_slot":
            criteria = location_criteria(criteria)
        elif problem.category == "yard_planning":
            criteria = location_criteria(criteria["location"]) | {"parameter_id": criteria["parameter_id"]}
        add(name, problem.reason, criteria, category=problem.category)
    for parameter, block, row, slot in bad.getYPOutOfRange():
        add("yard_planning", "Yard planning coordinates are outside the block.",
            location_criteria((block, row, slot)) | {"parameter_id": parameter})
    for containers, message in (
        (bad.getIncompleteExistingContainers(), "Existing container has an incomplete ID, size, or coordinates."),
        (bad.getDuplicateExistingContainerIDs(), "Duplicate existing container ID; record skipped."),
        (bad.getContainerCoordsInvalid(), "Invalid container coordinates or incompatible footprint; record skipped."),
    ):
        for container in containers:
            add("existing_containers", message, {"container_id": container.getId(),
                **dict(zip(("branch_id", "block_code", "row_no", "slot_no", "tier_no"), container.getCoordsStr()))})
    for containers in bad.getOverlappingContainers().values():
        for container in sorted(containers, key=lambda item: item.getId()):
            retained = yard.containers.get(container.getId()) is container
            add("existing_containers", f"Overlapping container {container.getId()}: "
                + ("retained" if retained else "excluded") + " by existing import rules.",
                {"container_id": container.getId()}, severity="warning", category="overlap")
    for stack in bad.getAnomalousStacks():
        block_id, row, slot = stack.getCoords()
        block = yard.getBlockByID(block_id)
        add("existing_containers", f"Floating contents in {block.getCode()}, row {row + 1}, slot {slot + 1}.",
            {"branch_id": branch_id, "block_code": block.getCode(), "row_no": str(row + 1)},
            severity="warning", category="anomaly")

    # Queue validation uses a separate collector and never places anything.
    validator = BadYardData(0, 0)
    seen = dict(yard.containers)
    origins_by_record = {}
    for index, row in enumerate(inputs.get("inbound_containers", ())):
        key = tuple(sorted(row.items()))
        if key not in origins_by_record:
            origins_by_record[key] = deque(sources("inbound_containers", row))
        origins = origins_by_record[key]
        origin = [origins.popleft()] if origins else []
        status, reason = "pending", None
        try:
            container = Container(**row)
        except (ValueError, TypeError, OverflowError, OSError) as error:
            status, reason = "invalid", str(error)
            branch["issues"].append(issue("inbound_containers", reason, sources=origin, field="move_time"))
        else:
            if row["weight"].strip() and container.getWeight() is None:
                branch["issues"].append(issue("inbound_containers", "Invalid weight is treated as unknown by the stacking engine.",
                                              severity="warning", sources=origin, field="weight"))
            try:
                validator.validateInboundContainer(container, seen)
                seen[container.getId()] = container
            except PlacementRejected as error:
                status, reason = "invalid", str(error)
                branch["issues"].append(issue("inbound_containers", reason, sources=origin))
        branch["queue"].append({"position": index + 1, "container_id": row["container_id"],
                                "size": row["container_size"], "status": status,
                                "reason": reason, "sources": origin})
    if not yard.blocks_by_id:
        add("yard_blocks", "No valid blocks are available for this branch.")
    for block in yard.blocks_by_id.values():
        if block.getRTG() is None and not yard.master_loaders:
            add("master_equipment", f"Block {block.getCode()} has no RTG and no registered loader is available.")
    for row in inputs["master_equipment"]:
        if row["equipment_code"] not in inputs["equipment_history"]:
            add("master_equipment", "Equipment has no selected location and is not registered in the yard.",
                row, severity="warning")
    branch["summary"] = {"blocks": len(yard.blocks_by_id), "existing_containers": len(yard.containers),
                         "anomalous_stacks": len(bad.getAnomalousStacks())}
    if branch["inbound_available"]:
        branch["summary"].update(inbound_containers=len(branch["queue"]),
                                 valid_inbound=sum(row["status"] == "pending" for row in branch["queue"]))


def public_preview(result):
    """Do not serialize mutable domain objects into the browser response."""
    preview = {key: value for key, value in result.items() if key != "branches"}
    preview["branches"] = []
    for branch in result["branches"]:
        entry = {key: value for key, value in branch.items()
                 if key not in ("yard", "inputs", "container_profile")}
        yard = branch["yard"]
        entry["yard_map"] = yard_view(yard) if yard is not None else None
        entry["ready"] = (yard is not None and branch["inbound_available"]
                          and not any(item["severity"] == "error" for item in branch["issues"]))
        entry["issue_counts"] = dict(Counter(item["severity"] for item in branch["issues"]))
        preview["branches"].append(entry)
    preview["ready"] = bool(preview["branches"]) and not preview["issues"] and all(branch["ready"] for branch in preview["branches"])
    return preview

"""Record existing-yard compliance and latest-week operations for one CY."""

from collections import Counter, defaultdict
from dataclasses import asdict
import json
from time import time

from config import (
    ConfigurationError, DEFAULT_CONFIG_FILE, DEFAULT_INPUT_CONFIG_FILE,
    load_config, load_input_config,
)
from entities import Yard
from presenter import YardPresenter
from repository import load_yard_inputs
from repository.branch_repository import BranchDirectory
from repository.shifting_repository import load_shifting_summary


EXISTING_YARD_DATASETS = (
    "terminal_branches", "yard_blocks", "removed_slots", "parameters", "yard_planning",
    "existing_containers", "master_equipment", "equipment_history",
)


def shifting_metrics(observations):
    """Sum available operations; percentages require complete nonzero totals."""
    known = [row.shifting_count for row in observations if row.shifting_count is not None]
    lifting = [row.lifting_count for row in observations if row.lifting_count is not None]
    missing = len(observations) - len(known)
    missing_lifting = len(observations) - len(lifting)
    total = sum(known) + sum(lifting) if known and lifting else None
    return {
        "shifting_data_points": len(observations),
        "lifting_count": sum(lifting) if lifting else None,
        "shifting_count": sum(known) if known else None,
        "total_operations": total,
        "shifting_percentage": (
            100 * sum(known) / total if total and not missing and not missing_lifting else None
        ),
        "missing_shifting_observations": missing,
        "missing_lifting_observations": missing_lifting,
    }


def _build_report_and_yard(input_path):
    input_settings = load_input_config(input_path, datasets=EXISTING_YARD_DATASETS)
    period_settings = input_settings.get("shifting_period")
    if period_settings is None:
        raise ConfigurationError("Configure [shifting_period] before recording weekly metrics.")
    if "shifting_summary_file" not in input_settings:
        raise ConfigurationError("csv.shifting_summary_file is required for weekly recording.")
    shifting_path = input_settings["shifting_summary_file"]
    shifting_mapping_path = input_settings["shifting_block_mapping_file"]
    workbook_path = input_settings.get("shifting_workbook_file")
    workbook_sheet = input_settings.get("shifting_workbook_sheet", "Per Alat Weekly")

    # Honor each selected source without loading inbound or historical operations.
    inputs = load_yard_inputs(input_settings, include_shifting=False)
    branches = BranchDirectory(inputs["terminal_branches"])
    cy_name = branches.cy_name()

    settings = load_config(DEFAULT_CONFIG_FILE)
    yard = Yard(
        yard_blocks_input=inputs["yard_blocks"],
        removed_slots_input=inputs["removed_slots"],
        parameters_input=inputs["parameters"],
        yard_planning_input=inputs["yard_planning"],
        containers_input=inputs["existing_containers"],
        equipment_input=inputs["master_equipment"],
        equipment_locations_input=inputs["equipment_history"],
        feasibility_settings=settings.feasibility,
        heuristic_settings=settings.heuristic,
    )

    skipped_observations = []
    observations = load_shifting_summary(
        shifting_path, cy_name, shifting_mapping_path, yard.blocks_by_id,
        skipped=skipped_observations,
        period_settings=period_settings,
        latest_only=True,
        workbook_path=workbook_path,
        workbook_sheet=workbook_sheet,
    )
    latest_start = max((row.period_start for row in observations), default=None)
    latest_observations = [row for row in observations if row.period_start == latest_start]
    latest = latest_observations[0] if latest_observations else None
    by_block = defaultdict(list)
    for row in latest_observations:
        by_block[row.block_id].append(row)

    # The accepted-container registry counts each 40-foot container once.
    counts = Counter(
        tuple(container.getCoordsStr()[:2])
        for container in yard.containers.values()
    )
    blocks = []
    weighted_compliance = 0.0
    container_count = 0
    for block in yard.blocks_by_id.values():
        count = counts[(block.getBranch(), block.getCode())]
        compliance = block.parameterCompliance()
        blocks.append({
            "block_id": block.getId(),
            "branch_id": block.getBranch(),
            "block_code": block.getCode(),
            "container_count": count,
            "parameter_compliance": compliance,
            **shifting_metrics(by_block[block.getId()]),
        })
        if compliance is not None:
            weighted_compliance += compliance * count
            container_count += count

    report = {
        "recorded_at": int(time()),
        "period_start": latest_start,
        "period_end": latest.period_end if latest else None,
        "latest_week": int(latest.week_number) if latest else None,
        "report_month": latest.report_month if latest else None,
        "parameter_compliance_basis": "current_yard_snapshot",
        "cy_name": cy_name,
        "branch": dict(branches.records[0]),
        "input_sources": dict(input_settings["sources"]),
        "input_filters": dict(input_settings.get("filters", {})),
        "existing_input_rows": len(inputs["existing_containers"]),
        "loaded_containers": len(yard.containers),
        "has_bad_data": yard.bad_data.anyBadData(),
        "parameter_compliance": (
            weighted_compliance / container_count
            if container_count else None
        ),
        "blocks": blocks,
        "shifting_source": str(shifting_path),
        "shifting_workbook_source": str(workbook_path) if workbook_path is not None else None,
        "shifting_block_mapping_source": str(shifting_mapping_path),
        **shifting_metrics(latest_observations),
        "loaded_shifting_data_points": len(observations),
        "shifting_observations": [
            {**asdict(row), "shifting_percentage": row.shifting_percentage}
            for row in observations
        ],
        "skipped_shifting_data_points": len(skipped_observations),
        "skipped_shifting_observations": [asdict(row) for row in skipped_observations],
    }
    return report, yard


def build_report(input_path=DEFAULT_INPUT_CONFIG_FILE):
    report, _ = _build_report_and_yard(input_path)
    return report


def main():
    report, yard = _build_report_and_yard(DEFAULT_INPUT_CONFIG_FILE)
    output = (
        DEFAULT_INPUT_CONFIG_FILE.parent.parent
        / "output" / "existing_yard_metrics.jsonl"
    )
    line = json.dumps(report, ensure_ascii=False, allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as file:
        file.write(line + "\n")

    compliance = report["parameter_compliance"]
    print("CY:", report["cy_name"])
    print("Existing containers source:", report["input_sources"]["existing_containers"])
    print("Loaded existing containers:", report["loaded_containers"])
    print("Parameter compliance:",
          "N/A" if compliance is None else f"{compliance:.2%}")
    print("Time of recording (Unix):", report["recorded_at"])
    print("Latest operations week:", report["latest_week"])
    print("Operations period start (Unix):", report["period_start"])
    print("Operations period end (Unix):", report["period_end"])
    print("Lifting count:", "N/A" if report["lifting_count"] is None else report["lifting_count"])
    print("Shifting count:",
          "N/A" if report["shifting_count"] is None
          else report["shifting_count"])
    percentage = report["shifting_percentage"]
    print("Shifting percentage:", "N/A" if percentage is None else f"{percentage:.2f}%")
    print("Missing shifting observations:", report["missing_shifting_observations"])
    print("Missing lifting observations:", report["missing_lifting_observations"])
    print("Skipped shifting observations:", report["skipped_shifting_data_points"])
    print("Yard has bad data:", report["has_bad_data"])
    print("Recorded to:", output)
    print()
    YardPresenter().outYard(yard)


if __name__ == "__main__":
    main()

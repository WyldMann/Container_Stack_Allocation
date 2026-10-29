"""Record existing-yard compliance and operations from the selected source."""

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
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
from repository.operations_input import load_operations
from repository.sql_connection import input_connection
from repository.sql_shifting_repository import sql_period_boundaries
from repository.shifting_dates import WIB


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
    with input_connection(input_settings) as connection:
        inputs = load_yard_inputs(input_settings, include_shifting=False, connection=connection)
        return _build_loaded_report(input_settings, inputs, connection)


def _build_loaded_report(input_settings, inputs, connection):
    period_settings = input_settings.get("shifting_period")
    operations_source = input_settings.get("shifting_source", "csv")
    sql_operations = operations_source == "sql"
    if not sql_operations and "shifting_summary_file" not in input_settings:
        raise ConfigurationError("csv.shifting_summary_file is required for operations recording.")
    shifting_path = input_settings.get("shifting_summary_file")
    shifting_mapping_path = input_settings["shifting_block_mapping_file"]
    workbook_path = input_settings.get("shifting_workbook_file")
    workbook_sheet = input_settings.get("shifting_workbook_sheet", "Per Alat Weekly")

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

    recorded_at = int(time())
    observations = load_operations(
        input_settings, branches, yard.blocks_by_id,
        connection=connection, latest_only=True,
        today=datetime.fromtimestamp(recorded_at, WIB).date(),
        recorded_at=recorded_at,
    )
    latest_start = max((row.period_start for row in observations), default=None)
    latest_observations = [row for row in observations if row.period_start == latest_start]
    latest = latest_observations[0] if latest_observations else None
    if sql_operations:
        granularity = input_settings.get("shifting_granularity", "daily")
        period_start, period_end = sql_period_boundaries(granularity, recorded_at)
        period_metadata = {"period_granularity": granularity}
    else:
        daily = bool(latest and latest.report_date)
        if latest is None:
            daily = "daily" in workbook_sheet.casefold() or period_settings is None
        period_start = latest_start
        period_end = latest.period_end if latest else None
        period_metadata = (
            {"latest_date": latest.report_date if latest else None, "period_granularity": "daily"}
            if daily else {
                "latest_week": int(latest.week_number) if latest else None, "period_granularity": "weekly",
            }
        )
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
        "recorded_at": recorded_at,
        "period_start": period_start,
        "period_end": period_end,
        **period_metadata,
        "report_month": latest.report_month if latest else None,
        "parameter_compliance_basis": "current_yard_snapshot",
        "cy_name": cy_name,
        "branch": dict(branches.records[0]),
        "input_sources": {**input_settings["sources"], "shifting_summary": operations_source},
        "input_filters": dict(input_settings.get("filters", {})),
        "existing_input_rows": len(inputs["existing_containers"]),
        "loaded_containers": len(yard.containers),
        "has_bad_data": yard.bad_data.anyBadData(),
        "parameter_compliance": (
            weighted_compliance / container_count
            if container_count else None
        ),
        "blocks": blocks,
        "shifting_source": (
            input_settings["sql_shifting"]["schema"] + "." + input_settings["sql_shifting"]["detail_relation"]
            if sql_operations else str(shifting_path)
        ),
        "shifting_workbook_source": str(workbook_path) if workbook_path is not None else None,
        "shifting_block_mapping_source": str(shifting_mapping_path),
        **({
            "shifting_sql_mapping": input_settings["sql_shifting"],
            "shifting_activities": {kind: list(values) for kind, values in input_settings["shifting_activities"].items()},
            "operations_period_basis": "rolling_window",
            "operations_completeness": "unverified",
        } if sql_operations else {}),
        **shifting_metrics(latest_observations),
        "loaded_shifting_data_points": len(observations),
        "shifting_observations": [
            {**asdict(row), "shifting_percentage": row.shifting_percentage}
            for row in observations
        ],
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

    presenter = YardPresenter()
    presenter.outRecordedMetrics(report)
    print("Recorded to:", output)
    print()
    presenter.outYard(yard)


if __name__ == "__main__":
    main()

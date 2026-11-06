"""Record existing-yard compliance and operations from the selected source."""

from collections import Counter
from datetime import datetime
import json
from time import time
from urllib.parse import quote

from config import (
    ConfigurationError, DEFAULT_CONFIG_FILE, DEFAULT_INPUT_CONFIG_FILE,
    load_config, load_input_config,
)
from config.application.input_filters import branch_input_settings
from entities import Yard
from presenter import YardPresenter
from repository import load_yard_inputs
from repository.branch_repository import BranchDirectory
from repository.operations_input import load_operations
from repository.sql_connection import input_connection
from repository.shifting_dates import WIB, operations_period_boundaries


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


def block_shifting_observations(observations, cy_name, yard, compliance_by_block):
    """Combine the selected period's equipment counts into one row per branch/block."""
    by_block = {}
    for row in observations:
        by_block.setdefault((row.branch_code, row.block_id), []).append(row)
    result = []
    for (branch_code, block_id), rows in by_block.items():
        metrics = shifting_metrics(rows)
        result.append({
            "cy_name": cy_name,
            "branch_code": branch_code,
            "block_code": yard.blocks_by_id[block_id].getCode(),
            "shifting_code": ", ".join(sorted({row.shifting_code for row in rows}, key=str.casefold)),
            "lifting_count": metrics["lifting_count"],
            "shifting_count": metrics["shifting_count"],
            "shifting_percentage": metrics["shifting_percentage"],
            "parameter_compliance": compliance_by_block[block_id],
        })
    return result


def _build_report_and_yard(input_path, *, branch_code=None):
    input_settings = load_input_config(input_path, datasets=EXISTING_YARD_DATASETS)
    selections = list(branch_input_settings(input_settings))
    if branch_code is not None:
        code = branch_code.strip().upper()
        selections = [selection for selection in selections
                      if selection.get("filters", {}).get("branch_code") in (None, code)]
        selections = [{**selection, "filters": {**selection.get("filters", {}), "branch_code": code}}
                      for selection in selections]
    if len(selections) != 1:
        raise ConfigurationError("Select one configured branch_code or use build_reports() for all branches.")
    input_settings = selections[0]
    with input_connection(input_settings) as connection:
        inputs = load_yard_inputs(input_settings, include_shifting=False, connection=connection)
        return _build_loaded_report(input_settings, inputs, connection)


def _build_reports_and_yards(input_path):
    """Build every yard separately using one shared read-only SQL snapshot."""
    settings = load_input_config(input_path, datasets=EXISTING_YARD_DATASETS)
    results = {}
    with input_connection(settings) as connection:
        recorded_at = int(time())
        for scoped in branch_input_settings(settings):
            inputs = load_yard_inputs(scoped, include_shifting=False, connection=connection)
            branches = BranchDirectory(inputs["terminal_branches"])
            branches.cy_name()  # Require an unambiguous identity even without observations.
            code = branches.records[0]["branch_code"].strip().upper()
            results[code] = _build_loaded_report(scoped, inputs, connection, recorded_at=recorded_at)
    return results


def _build_loaded_report(input_settings, inputs, connection, *, recorded_at=None):
    period_settings = input_settings.get("shifting_period")
    operations_source = input_settings.get("shifting_source", "xlsx")
    sql_operations = operations_source == "sql"
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

    if recorded_at is None:
        recorded_at = int(time())
    observations = load_operations(
        input_settings, branches,
        [{"block_id": block.getId(), "block_code": block.getCode()}
         for block in yard.blocks_by_id.values()],
        connection=connection, latest_only=True,
        today=datetime.fromtimestamp(recorded_at, WIB).date(),
        recorded_at=recorded_at,
    )
    latest_start = max((row.period_start for row in observations), default=None)
    latest_observations = [row for row in observations if row.period_start == latest_start]
    latest = latest_observations[0] if latest_observations else None
    if sql_operations:
        granularity = input_settings.get("shifting_granularity", "daily")
        period_start, period_end = operations_period_boundaries(granularity, recorded_at)
    elif operations_source == "csv":
        granularity = input_settings.get("shifting_granularity", "daily")
        period_start = latest_start
        period_end = latest.period_end if latest else None
    else:
        daily = bool(latest and latest.report_date)
        if latest is None:
            daily = "daily" in workbook_sheet.casefold() or period_settings is None
        period_start = latest_start
        period_end = latest.period_end if latest else None
        granularity = "daily" if daily else "weekly"

    latest_date = latest.report_date if latest else None
    if latest_date is None and period_end is not None:
        # XLSX periods end exclusively; raw CSV/SQL dates label the window end.
        date_timestamp = period_end - 1 if operations_source == "xlsx" else period_end
        latest_date = datetime.fromtimestamp(date_timestamp, WIB).date().isoformat()

    # The accepted-container registry counts each 40-foot container once.
    counts = Counter(
        tuple(container.getCoordsStr()[:2])
        for container in yard.containers.values()
    )
    compliance_by_block = {}
    weighted_compliance = 0.0
    container_count = 0
    for block in yard.blocks_by_id.values():
        count = counts[(block.getBranch(), block.getCode())]
        compliance = block.parameterCompliance()
        compliance_by_block[block.getId()] = compliance * 100 if compliance is not None else None
        if compliance is not None:
            weighted_compliance += compliance * count
            container_count += count

    report = {
        "recorded_at": recorded_at,
        "period_start": period_start,
        "period_end": period_end,
        "latest_date": latest_date,
        "period_granularity": granularity,
        "avg_shifting_percentage": shifting_metrics(latest_observations)["shifting_percentage"],
        "avg_parameter_compliance": (
            weighted_compliance / container_count * 100
            if container_count else None
        ),
        "shifting_observations": block_shifting_observations(
            latest_observations, cy_name, yard, compliance_by_block,
        ),
    }
    return report, yard


def build_report(input_path=DEFAULT_INPUT_CONFIG_FILE, *, branch_code=None):
    """Build one report; a multi-branch config requires an explicit branch code."""
    report, _ = _build_report_and_yard(input_path, branch_code=branch_code)
    return report


def build_reports(input_path=DEFAULT_INPUT_CONFIG_FILE):
    """Return reports keyed by branch code, including yards without operations."""
    return {code: report for code, (report, _) in _build_reports_and_yards(input_path).items()}


def main():
    reports = _build_reports_and_yards(DEFAULT_INPUT_CONFIG_FILE)
    # Validate every record before appending any of this run's reports.
    lines = {code: json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(", ", ": "))
             for code, (report, _) in reports.items()}
    presenter = YardPresenter()
    for code, (report, yard) in reports.items():
        output = (DEFAULT_INPUT_CONFIG_FILE.parent.parent / "output"
                  / f"existing_yard_metrics_{quote(code, safe='')}.jsonl")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as file:
            file.write(lines[code] + "\n")

        print("Branch:", code)
        presenter.outRecordedMetrics(report)
        print("Recorded to:", output)
        print()
        presenter.outYard(yard)


if __name__ == "__main__":
    main()

"""Record existing-yard compliance and latest-week operations for one CY."""

from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import tomllib
from time import time

from config import (
    ConfigurationError, DEFAULT_CONFIG_FILE, DEFAULT_INPUT_CONFIG_FILE,
    load_config, load_csv_mapping,
)
from config.application.shifting_period import parse_shifting_period
from entities import Yard
from repository import (
    CSVLoader, Repository, ContainerRepository, RemovedSlotsRepository,
    YardPlanningRepository, EquipmentMoveRepository,
)
from repository.shifting_repository import load_shifting_summary


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


def build_report(input_path=DEFAULT_INPUT_CONFIG_FILE):
    input_path = Path(input_path).resolve()
    with input_path.open("rb") as file:
        document = tomllib.load(file)
    period_settings = parse_shifting_period(document, required=True)

    def required_text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{label} must be a non-empty string.")
        return value.strip()

    def resolve(value, label):
        return (input_path.parent / required_text(value, label)).resolve()

    cy_name = required_text(
        document.get("input", {}).get("cy_name"), "input.cy_name"
    )
    csv_settings = document.get("csv", {})
    files = csv_settings.get("files", {})
    shifting_path = resolve(
        csv_settings.get("shifting_summary_file"),
        "csv.shifting_summary_file",
    )
    shifting_mapping_path = resolve(
        csv_settings.get("shifting_block_mapping_file", "shifting_block_mapping.toml"),
        "csv.shifting_block_mapping_file",
    )
    profiles = load_csv_mapping(resolve(
        csv_settings.get("mapping_file", "csv_mapping.toml"),
        "csv.mapping_file",
    ))

    # This entrypoint uses CSV paths directly and never opens inbound data.
    readers = {
        "yard_blocks": (Repository, "read_records"),
        "removed_slots": (RemovedSlotsRepository, "read_tuples"),
        "parameters": (Repository, "read_records"),
        "yard_planning": (YardPlanningRepository, "read_grouped"),
        "existing_containers": (ContainerRepository, "read_records"),
        "master_equipment": (Repository, "read_records"),
        "equipment_history": (EquipmentMoveRepository, "read_locations"),
    }

    inputs = {}
    for name, (repository_type, method) in readers.items():
        if name not in profiles:
            raise ConfigurationError(f"Missing CSV mapping profile: {name}.")
        reader = repository_type(
            CSVLoader(resolve(files.get(name), f"csv.files.{name}")),
            profiles[name],
        )
        inputs[name] = getattr(reader, method)()

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

    return {
        "recorded_at": int(time()),
        "period_start": latest_start,
        "period_end": latest.period_end if latest else None,
        "latest_week": int(latest.week_number) if latest else None,
        "report_month": latest.report_month if latest else None,
        "parameter_compliance_basis": "current_yard_snapshot",
        "cy_name": cy_name,
        "existing_input_rows": len(inputs["existing_containers"]),
        "loaded_containers": len(yard.containers),
        "has_bad_data": yard.bad_data.anyBadData(),
        "parameter_compliance": (
            weighted_compliance / container_count
            if container_count else None
        ),
        "blocks": blocks,
        "shifting_source": str(shifting_path),
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


def main():
    report = build_report()
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


if __name__ == "__main__":
    main()

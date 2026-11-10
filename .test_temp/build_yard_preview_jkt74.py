"""Build the standalone yard preview in output/."""

import csv
import json
import math
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import DATASETS, load_input_config
from config.application.input_filters import branch_input_settings
from entities import Yard
from repository import load_yard_inputs


def criteria(row):
    fields = (
        ("Size", "container_size", "container_size_score"),
        ("Fill", "container_fill", "container_fill_score"),
        ("Grade", "container_grade", "container_grade_score"),
        ("Condition", "container_condition", "container_condition_score"),
        ("Operation", "operation_type", "operation_type_score"),
        ("Principal", "principal", "principal_score"),
    )
    rules = [{"name": label, "value": row[key], "score": row[score]}
             for label, key, score in fields if row.get(key)]
    for label, keys, score in (
        ("Route", ("pol", "pod"), "route_score"),
        ("Vessel and voyage", ("vessel", "voyage"), "vessel_voyage_score"),
    ):
        if any(row.get(key) for key in keys):
            rules.append({"name": label, "value": " / ".join(row.get(key) or "Any" for key in keys),
                          "score": row[score]})
    if any(row.get(key) for key in ("weight_start", "weight_end", "weight_range_score")):
        rules.append({"name": "Weight", "value": f"{row['weight_start'] or '0'} to {row['weight_end'] or 'no limit'}",
                      "score": row["weight_range_score"]})
    return rules


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build():
    settings = load_input_config(
        DEFAULT_STACKING_INPUT_CONFIG_FILE,
        datasets=tuple(name for name in DATASETS if name != "inbound_containers"),
    )
    branch = next(settings for settings in branch_input_settings(settings)
                  if settings["filters"].get("branch_code") == "JKT74")
    data = load_yard_inputs(branch, include_shifting=False)
    yard = Yard(
        yard_blocks_input=data["yard_blocks"],
        removed_slots_input=data["removed_slots"],
        parameters_input=data["parameters"],
        yard_planning_input=data["yard_planning"],
        containers_input=data["existing_containers"],
    )

    blocks, stack_rows, tier_rows = [], [], []
    assigned_ids = set()
    for block in sorted(yard.blocks_by_id.values(), key=lambda b: (b.getPosY(), b.getPosX(), b.getCode())):
        code = block.getCode()
        grid = block.getSlots()
        stacks = []
        unique = set()
        for row_no, row in enumerate(grid, 1):
            for slot, stack in enumerate(row, 1):
                assigned = [p.getId() for p in stack.getParameters()]
                assigned_ids.update(assigned)
                tiers = []
                for tier, container in enumerate(stack.getContainers(), 1):
                    value = None
                    if container:
                        weight = container.getWeight()
                        anchor = container.getCoordsInt()[3] + 1
                        value = {
                            "container_id": container.getId(), "size_ft": container.getContSize(),
                            "fill": container.getContFill(), "grade": container.getContGrade(),
                            "weight": weight if weight is not None and math.isfinite(weight) else None,
                            "anchor_slot": anchor,
                        }
                        unique.add(value["container_id"])
                    tiers.append(value)
                    tier_rows.append({"block": code, "row": row_no, "slot": slot, "tier": tier,
                                      **(value or dict.fromkeys(
                                          ["container_id", "size_ft", "fill", "grade", "weight", "anchor_slot"], ""))})
                stack_data = {
                    "row": row_no, "slot": slot, "occupied": stack.occupancy(),
                    "capacity": stack.getMaxTier(), "removed": stack.getMode() == "X",
                    "anomaly": stack.anomaly(), "parameters": assigned,
                }
                stacks.append({**stack_data, "tiers": tiers})
                stack_rows.append({"block": code, **stack_data, "parameters": "|".join(assigned)})
        blocks.append({
            "code": code, "x": block.getPosX(), "y": block.getPosY(),
            "rows": len(grid), "slots": len(grid[0]), "tier_limit": max(s["capacity"] for s in stacks),
            "occupied_tiers": sum(s["occupied"] for s in stacks),
            "tier_capacity": sum(s["capacity"] for s in stacks),
            "container_count": len(unique), "anomalies": sum(s["anomaly"] for s in stacks),
            "stacks": stacks,
        })

    raw_parameters = [row for row in data["parameters"] if row["parameter_id"] in assigned_ids]
    colors = {"33": ["#dceafa", "#346ca6"], "35": ["#eee4fa", "#7952a0"],
              "38": ["#d9efe6", "#28765e"]}
    other_colors = [
        ["#f4e2e1", "#9d514e"], ["#d9eef3", "#276d80"], ["#f6e6cc", "#915d26"],
        ["#e9ead4", "#6a702d"], ["#f5e0ef", "#98597d"],
    ]
    parameters = {}
    for index, row in enumerate(sorted(raw_parameters, key=lambda row: row["parameter_id"])):
        id = row["parameter_id"]
        parameters[id] = {
            "name": row["parameter_name"],
            "colors": colors.get(id, other_colors[index % len(other_colors)]),
            "criteria": criteria(row), "and_score": row.get("and_score", ""),
        }
    name = data["terminal_branches"][0]["branch_name"]
    snapshot = {"branch": "JKT74", "name": name, "blocks": blocks, "parameters": parameters}

    package = ROOT / "output" / "yard-preview-jkt74"
    package.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("yard_preview_jkt74.template.html").read_text(encoding="utf-8")
    encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    (package / "index.html").write_text(source.replace("<!-- SNAPSHOT_DATA -->", encoded), encoding="utf-8")
    write_csv(package / "yard-blocks.csv", [{k: v for k, v in block.items() if k != "stacks"} for block in blocks])
    write_csv(package / "yard-stacks.csv", stack_rows)
    write_csv(package / "yard-tiers.csv", tier_rows)
    write_csv(package / "yard-parameters.csv", raw_parameters)
    (package / "README.txt").write_text(
        "JKT74 yard preview\n"
        "Extract this ZIP and open index.html in a browser. The page works offline.\n"
        "Click a block on the map or its tab, then click a stack to inspect its tiers and parameters.\n\n"
        "This is a snapshot of the current JKT74 layout, yard plan and containers accepted by the yard model.\n"
        "The HTML includes the same snapshot data as the CSVs. Editing the CSVs does not change this preview.\n\n"
        "yard-blocks.csv: Block coordinates, dimensions and totals.\n"
        "yard-stacks.csv: One row per stack with occupancy, capacity and parameter IDs.\n"
        "yard-tiers.csv: One row per tier position, including empty positions. A 40 ft container appears\n"
        "in both occupied slots. Use container_id for unique counts and anchor_slot to locate its anchor.\n"
        "yard-parameters.csv: Definitions of the assigned parameters. Weight values use the source units.\n",
        encoding="utf-8",
    )
    files = ("index.html", "yard-blocks.csv", "yard-stacks.csv", "yard-tiers.csv", "yard-parameters.csv", "README.txt")
    destination = package.with_suffix(".zip")
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        for filename in files:
            bundle.write(package / filename, filename)
    print(destination)
    print([(b["code"], len(b["stacks"]), b["container_count"], b["occupied_tiers"]) for b in blocks])
    print("Parameters:", list(parameters))


if __name__ == "__main__":
    build()

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class CSVSchema:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    @property
    def fields(self) -> tuple[str, ...]:
        return self.required + self.optional


@dataclass(frozen=True)
class CSVMappingProfile:
    name: str
    schema: CSVSchema
    columns: Mapping[str, str]
    filter_columns: Mapping[str, str] = field(default_factory=dict)


CONTAINER_SCHEMA = CSVSchema(
    required=tuple(
        "container_id principal container_condition container_fill container_grade "
        "pol pod vessel voyage weight move_time".split()
    ),
    optional=tuple(
        "container_size branch_id block_code row_no slot_no tier_no "
        "operation_type pot vessel_operator".split()
    ),
)

SCHEMAS = {
    "yard_blocks": CSVSchema(required=tuple(
        "block_id branch_id block_code row_count slot_count "
        "max_tier pos_x pos_y".split()
    )),
    "removed_slots": CSVSchema(
        required=("block_id", "row_no", "slot_no"),
    ),
    "parameters": CSVSchema(
        required=tuple(
            "parameter_id parameter_name principal principal_score "
            "container_condition container_condition_score "
            "container_fill container_fill_score "
            "container_size container_size_score container_grade container_grade_score "
            "pol pod route_score vessel voyage vessel_voyage_score "
            "weight_start weight_end weight_range_score".split()
        ),
        optional=("and_score", "operation_type", "operation_type_score"),
    ),
    "yard_planning": CSVSchema(
        required=("parameter_id", "block_id", "row_no", "slot_no"),
    ),
    "existing_containers": CONTAINER_SCHEMA,
    "inbound_containers": CONTAINER_SCHEMA,
    "master_equipment": CSVSchema(
        required=("equipment_code", "equipment_type"),
    ),
    "equipment_history": CSVSchema(
        required=(
            "equipment_code", "branch_id", "block_code",
            "row_no", "slot_no", "move_time",
        ),
    ),
}

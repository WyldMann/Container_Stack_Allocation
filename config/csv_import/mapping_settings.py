from dataclasses import dataclass
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


CONTAINER_SCHEMA = CSVSchema(
    required=tuple(
        "CONTNO PRINCIPAL DMG_FLAG FULLMT CONT_GRADE POL POD "
        "VESSEL VOYAGE WEIGHT MOVE_TIME".split()
    ),
    optional=tuple(
        "CONTSIZE BRANCH BLOK ROW SLOT TIER "
        "OPERATION_TYPE POT VESSEL_OPERATOR".split()
    ),
)

SCHEMAS = {
    "yard_blocks": CSVSchema(required=tuple(
        "BLOCK_ID BRANCH_ID BLOCK_CODE ROW_COUNT SLOT_COUNT "
        "MAX_TIER POS_X POS_Y".split()
    )),
    "removed_slots": CSVSchema(
        required=("BLOCK_ID", "ROW_NO", "SLOT_NO"),
    ),
    "parameters": CSVSchema(
        required=tuple(
            "PARAM_ID PARAM_NAME PRINCIPAL PRINCIPAL_SCORE "
            "CONT_CONDITION CONT_CONDITION_SCORE CONT_FILL CONT_FILL_SCORE "
            "CONT_SIZE CONT_SIZE_SCORE CONT_GRADE CONT_GRADE_SCORE "
            "POL POD ROUTE_SCORE VESSEL VOYAGE VESSEL_VOYAGE_SCORE "
            "WEIGHT_START WEIGHT_END WEIGHT_RANGE_SCORE".split()
        ),
        optional=("AND_SCORE",),
    ),
    "yard_planning": CSVSchema(
        required=("PARAM_ID", "BLOCK_ID", "ROW", "SLOT"),
    ),
    "existing_containers": CONTAINER_SCHEMA,
    "inbound_containers": CONTAINER_SCHEMA,
    "master_equipment": CSVSchema(
        required=("EQUIPMENT_CODE", "EQUIPMENT_TYPE"),
    ),
    "equipment_history": CSVSchema(
        required=("ALAT", "BRANCH", "BLOK", "ROW", "SLOT", "MOVE_DATE"),
    ),
}

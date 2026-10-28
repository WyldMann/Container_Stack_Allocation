import csv
from pathlib import Path

from entities.container import DummyContainer
from entities.yard import Yard


class ContainerFileWriter:
    FIELDNAMES = (
        "CONTNO", "BRANCH", "BLOK", "BLOK_ID", "SLOT", "ROW", "TIER",
        "PRINCIPAL", "DMG_FLAG", "FULLMT", "OPERATION_TYPE",
        "CONTSIZE", "CONT_GRADE", "POL", "POT", "POD",
        "VESSEL_OPERATOR", "VESSEL", "VOYAGE", "WEIGHT", "MOVE_TIME",
    )

    def __init__(self, file_path: str | Path, *, branch_codes=None):
        self.file_path = Path(file_path)
        self.branch_codes = branch_codes

    @staticmethod
    def _sortKey(record: dict[str, str | int | float]):
        block_id = str(record["BLOK_ID"])
        # Numeric block IDs sort as 1, 2, 10; other IDs follow alphabetically.
        block_key = (
            (0, int(block_id), block_id)
            if block_id.isdecimal()
            else (1, 0, block_id)
        )
        return (
            block_key,
            int(record["SLOT"]),
            int(record["ROW"]),
            int(record["TIER"]),
            str(record["CONTNO"]),
        )

    def buildRows(self, yard: Yard) -> list[dict[str, str | int | float]]:
        """Build sorted rows without changing the yard or writing a file."""
        rows: list[dict[str, str | int | float]] = []
        # The registry exports each container once, including 40-foot containers.
        for container in yard.containers.values():
            if isinstance(container, DummyContainer):
                continue

            branch_id, block_code, row_no, slot_no, tier_no = container.getCoordsStrTuple()
            block_id = yard.getBlockIDbyCode(branch_id, block_code)
            weight = container.getWeight()
            weight_value: str | int | float
            if weight is None:
                weight_value = ""
            elif weight.is_integer():
                weight_value = int(weight)
            else:
                weight_value = weight

            rows.append({
                "CONTNO": container.getId(),
                "BRANCH": self.branch_codes[branch_id] if self.branch_codes is not None else branch_id,
                "BLOK": block_code,
                "BLOK_ID": block_id,
                "SLOT": slot_no,
                "ROW": row_no,
                "TIER": tier_no,
                "PRINCIPAL": container.getPrincipal(),
                "DMG_FLAG": container.getContCondition(),
                "FULLMT": container.getContFill(),
                "OPERATION_TYPE": container.getOpType(),
                "CONTSIZE": container.getContSize(),
                "CONT_GRADE": container.getContGrade(),
                "POL": container.getPol(),
                "POT": container.getPot(),
                "POD": container.getPod(),
                "VESSEL_OPERATOR": container.getVesselOperator(),
                "VESSEL": container.getVessel(),
                "VOYAGE": container.getVoyage(),
                "WEIGHT": weight_value,
                "MOVE_TIME": container.getMoveTimeRaw(),
            })

        return sorted(rows, key=self._sortKey)

    def writeCSV(self, yard: Yard) -> None:
        """Create or overwrite the CSV with the current yard containers."""
        # Prepare rows before opening the destination so conversion errors
        # do not truncate an existing file.
        rows = self.buildRows(yard)
        with self.file_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

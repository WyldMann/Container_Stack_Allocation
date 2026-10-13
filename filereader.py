import csv
from pathlib import Path
from typing import Any, Iterator

from config import CSVMappingProfile
from utils import parse_datetime, strGeneralize


class CSVInputError(ValueError):
    """The CSV headers or rows do not match the expected input."""


class FileReader:
    required_fields: tuple[str, ...] = ()

    def __init__(
        self,
        file_path: str | Path,
        profile: CSVMappingProfile | None = None,
    ):
        self.file_path = Path(file_path)
        self.profile = profile

    def _resolve_columns(
        self, headers: list[str] | None,
    ) -> dict[str, str | None]:
        if not headers:
            raise CSVInputError(f"{self.file_path}: missing CSV header row.")

        header_index = {}
        for header in headers:
            normalized = header.strip().casefold()
            if not normalized:
                continue
            if normalized in header_index:
                raise CSVInputError(
                    f"{self.file_path}: ambiguous CSV headers "
                    f"{header_index[normalized]!r} and {header!r}."
                )
            header_index[normalized] = header

        if self.profile is None:
            fields = tuple(dict.fromkeys((*headers, *self.required_fields)))
            required = set(self.required_fields)
            columns = {}
        else:
            schema = self.profile.schema
            incompatible = set(self.required_fields) - set(schema.fields)
            if incompatible:
                raise CSVInputError(
                    f"Profile {self.profile.name!r} does not define: "
                    + ", ".join(sorted(incompatible))
                )
            fields = schema.fields
            required = set(schema.required) | set(self.required_fields)
            columns = self.profile.columns

        resolved = {}
        missing = []
        for field in fields:
            expected = columns.get(field, field)
            source = header_index.get(expected.strip().casefold())
            # Preserve a legacy unnamed column when no profile is supplied.
            if self.profile is None and field == "":
                source = ""

            if source is None and field in required:
                missing.append(f"{field} (CSV header {expected!r})")
            resolved[field] = source

        if missing:
            raise CSVInputError(
                f"{self.file_path}: missing required columns: "
                + ", ".join(missing)
            )
        return resolved

    def _iter_rows(self) -> Iterator[tuple[int, dict[str, str]]]:
        with self.file_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            columns = self._resolve_columns(reader.fieldnames)

            for source_row in reader:
                if None in source_row:
                    raise CSVInputError(
                        f"{self.file_path}, line {reader.line_num}: "
                        "too many values."
                    )
                if any(value is None for value in source_row.values()):
                    raise CSVInputError(
                        f"{self.file_path}, line {reader.line_num}: "
                        "too few values."
                    )

                record = {
                    field: source_row[source] if source is not None else ""
                    for field, source in columns.items()
                }
                yield reader.line_num, record

    def _coordinate(self, value: str, field: str, line: int) -> int:
        try:
            return int(value) - 1
        except ValueError as error:
            raise CSVInputError(
                f"{self.file_path}, line {line}: "
                f"{field} must be an integer; received {value!r}."
            ) from error

    def readCSV(self) -> list[dict[str, str]]:
        return [
            {key: strGeneralize(value) for key, value in record.items()}
            for _, record in self._iter_rows()
        ]

    @staticmethod
    def group_rows(data):
        result = {}
        for record in data:
            result.setdefault(record[0], []).append(tuple(record[1:]))
        return result

    def readCSVTuple(self) -> list[Any]:
        raise NotImplementedError("Subclasses must override readCSVTuple()")

    def readCSVDictTuple(self):
        return self.group_rows(self.readCSVTuple())


class ContainerFileReader(FileReader):
    pass


class RemovedSlotsFileReader(FileReader):
    required_fields = ("block_id", "row_no", "slot_no")

    def readCSVTuple(self) -> list[tuple[str, int, int]]:
        return [
            (
                strGeneralize(record["block_id"]),
                self._coordinate(record["row_no"], "row_no", line),
                self._coordinate(record["slot_no"], "slot_no", line),
            )
            for line, record in self._iter_rows()
        ]


class YardPlanningFileReader(FileReader):
    required_fields = ("parameter_id", "block_id", "row_no", "slot_no")

    def readCSVTuple(self) -> list[tuple[str, str, int, int]]:
        return [
            (
                strGeneralize(record["parameter_id"]),
                strGeneralize(record["block_id"]),
                self._coordinate(record["row_no"], "row_no", line),
                self._coordinate(record["slot_no"], "slot_no", line),
            )
            for line, record in self._iter_rows()
        ]


class EquipmentMoveFileReader(FileReader):
    required_fields = ("equipment_code", "branch_id", "block_code", "row_no", "slot_no", "move_time")

    def readCSVDict(self) -> dict[str, tuple[str, str, int, int]]:
        result = {}
        for line, record in self._iter_rows():
            try:
                dt = parse_datetime(record["move_time"])
            except (ValueError, OverflowError, OSError) as error:
                raise CSVInputError(
                    f"{self.file_path}, line {line}: "
                    f"invalid MOVE_DATE {record['move_time']!r}."
                ) from error

            coordinates = (
                record["branch_id"],
                record["block_code"],
                self._coordinate(record["row_no"], "row_no", line),
                self._coordinate(record["slot_no"], "slot_no", line),
            )
            equipment_code = record["equipment_code"]
            if equipment_code not in result or dt > result[equipment_code][0]:
                result[equipment_code] = (dt, coordinates)

        return {equipment_code: coordinates for equipment_code, (_, coordinates) in result.items()}

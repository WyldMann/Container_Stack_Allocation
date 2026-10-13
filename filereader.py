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

                row = {
                    field: source_row[source] if source is not None else ""
                    for field, source in columns.items()
                }
                yield reader.line_num, row

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
            {key: strGeneralize(value) for key, value in row.items()}
            for _, row in self._iter_rows()
        ]

    @staticmethod
    def group_rows(data):
        result = {}
        for row in data:
            result.setdefault(row[0], []).append(tuple(row[1:]))
        return result

    def readCSVTuple(self) -> list[Any]:
        raise NotImplementedError("Subclasses must override readCSVTuple()")

    def readCSVDictTuple(self):
        return self.group_rows(self.readCSVTuple())


class ContainerFileReader(FileReader):
    pass


class RemovedSlotsFileReader(FileReader):
    required_fields = ("BLOCK_ID", "ROW_NO", "SLOT_NO")

    def readCSVTuple(self) -> list[tuple[str, int, int]]:
        return [
            (
                strGeneralize(row["BLOCK_ID"]),
                self._coordinate(row["ROW_NO"], "ROW_NO", line),
                self._coordinate(row["SLOT_NO"], "SLOT_NO", line),
            )
            for line, row in self._iter_rows()
        ]


class YardPlanningFileReader(FileReader):
    required_fields = ("PARAM_ID", "BLOCK_ID", "ROW", "SLOT")

    def readCSVTuple(self) -> list[tuple[str, str, int, int]]:
        return [
            (
                strGeneralize(row["PARAM_ID"]),
                strGeneralize(row["BLOCK_ID"]),
                self._coordinate(row["ROW"], "ROW", line),
                self._coordinate(row["SLOT"], "SLOT", line),
            )
            for line, row in self._iter_rows()
        ]


class EquipmentMoveFileReader(FileReader):
    required_fields = ("ALAT", "BRANCH", "BLOK", "ROW", "SLOT", "MOVE_DATE")

    def readCSVDict(self) -> dict[str, tuple[str, str, int, int]]:
        result = {}
        for line, row in self._iter_rows():
            try:
                dt = parse_datetime(row["MOVE_DATE"])
            except (ValueError, OverflowError, OSError) as error:
                raise CSVInputError(
                    f"{self.file_path}, line {line}: "
                    f"invalid MOVE_DATE {row['MOVE_DATE']!r}."
                ) from error

            coords = (
                row["BRANCH"],
                row["BLOK"],
                self._coordinate(row["ROW"], "ROW", line),
                self._coordinate(row["SLOT"], "SLOT", line),
            )
            id_ = row["ALAT"]
            if id_ not in result or dt > result[id_][0]:
                result[id_] = (dt, coords)

        return {id_: coords for id_, (_, coords) in result.items()}

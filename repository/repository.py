from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from config import CSVMappingProfile
from .loader import InputError, Loader
from utils import parse_datetime, strGeneralize


class Repository:
    required_fields: tuple[str, ...] = ()

    def __init__(
        self,
        loader: Loader,
        profile: CSVMappingProfile | None = None,
    ):
        self.loader = loader
        self.profile = profile

    def _resolve_columns(
        self, headers: Sequence[str] | None,
    ) -> dict[str, str | None]:
        if not headers:
            raise InputError(f"{self.loader.source}: missing source columns.")

        header_index = {}
        for header in headers:
            normalized = header.strip().casefold()
            if not normalized:
                continue
            if normalized in header_index:
                raise InputError(
                    f"{self.loader.source}: ambiguous source columns "
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
                raise InputError(
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
                missing.append(f"{field} (source column {expected!r})")
            resolved[field] = source

        if missing:
            raise InputError(
                f"{self.loader.source}: missing required columns: "
                + ", ".join(missing)
            )
        return resolved

    @staticmethod
    def _text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _iter_rows(self) -> Iterator[tuple[str, dict[str, str]]]:
        with self.loader.open() as (headers, rows):
            columns = self._resolve_columns(headers)
            for location, source_row in rows:
                record = {
                    field: self._text(source_row[source]) if source is not None else ""
                    for field, source in columns.items()
                }
                yield location, record

    def _coordinate(self, value: str, field: str, location: str) -> int:
        try:
            return int(value) - 1
        except ValueError as error:
            raise InputError(
                f"{location}: "
                f"{field} must be an integer; received {value!r}."
            ) from error

    def read_records(self) -> list[dict[str, str]]:
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

    def read_tuples(self) -> list[Any]:
        raise NotImplementedError("Subclasses must override read_tuples()")

    def read_grouped(self):
        return self.group_rows(self.read_tuples())


class ContainerRepository(Repository):
    pass


class RemovedSlotsRepository(Repository):
    required_fields = ("block_id", "row_no", "slot_no")

    def read_tuples(self) -> list[tuple[str, int, int]]:
        return [
            (
                strGeneralize(record["block_id"]),
                self._coordinate(record["row_no"], "row_no", location),
                self._coordinate(record["slot_no"], "slot_no", location),
            )
            for location, record in self._iter_rows()
        ]


class YardPlanningRepository(Repository):
    required_fields = ("parameter_id", "block_id", "row_no", "slot_no")

    def read_tuples(self) -> list[tuple[str, str, int, int]]:
        return [
            (
                strGeneralize(record["parameter_id"]),
                strGeneralize(record["block_id"]),
                self._coordinate(record["row_no"], "row_no", location),
                self._coordinate(record["slot_no"], "slot_no", location),
            )
            for location, record in self._iter_rows()
        ]


class EquipmentMoveRepository(Repository):
    required_fields = ("equipment_code", "branch_id", "block_code", "row_no", "slot_no", "move_time")

    def read_locations(self) -> dict[str, tuple[str, str, int, int]]:
        result = {}
        timestamp_kinds = set()
        for location, record in self._iter_rows():
            try:
                dt = parse_datetime(record["move_time"])
            except (ValueError, OverflowError, OSError) as error:
                raise InputError(
                    f"{location}: "
                    f"invalid MOVE_DATE {record['move_time']!r}."
                ) from error

            # Empty dates remain older than real dates. Do not silently guess
            # a timezone when a source mixes naive and aware timestamps.
            if dt != datetime.min:
                aware = dt.utcoffset() is not None
                timestamp_kinds.add(aware)
                if len(timestamp_kinds) > 1:
                    raise InputError(
                        f"{location}: mixed timezone-aware and naive movement times."
                    )
                if aware:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

            coordinates = (
                record["branch_id"],
                record["block_code"],
                self._coordinate(record["row_no"], "row_no", location),
                self._coordinate(record["slot_no"], "slot_no", location),
            )
            equipment_code = record["equipment_code"]
            if equipment_code not in result or dt > result[equipment_code][0]:
                result[equipment_code] = (dt, coordinates)

        return {equipment_code: coordinates for equipment_code, (_, coordinates) in result.items()}

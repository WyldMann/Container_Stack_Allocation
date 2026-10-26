"""Optional shifting summaries for analysis, scoped to one configured CY."""

from dataclasses import dataclass, replace

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import CSVLoader
from .loader import InputError
from .repository import Repository


@dataclass(frozen=True)
class ShiftingSummary:
    cy_name: str
    shifting_code: str
    lifting_count: int | None
    shifting_count: int | None
    report_month: str | None = None
    week_number: str | None = None
    block_id: str | None = None

    @property
    def shifting_ratio(self) -> float | None:
        if self.lifting_count in (None, 0) or self.shifting_count is None:
            return None
        return self.shifting_count / self.lifting_count


class ShiftingRepository(Repository):
    required_fields = (
        "cy_name",
        "lifting_count", "shifting_count",
    )

    def _resolve_columns(self, headers):
        columns = super()._resolve_columns(headers)
        names = {header.strip().casefold(): header for header in headers}
        aliases = [name for name in ("shifting_code", "equipment_group") if name in names]
        if len(aliases) != 1:
            raise InputError(
                f"{self.loader.source}: provide exactly one shifting_code column "
                "(legacy equipment_group is also accepted)."
            )
        columns["shifting_code"] = names[aliases[0]]
        return columns

    @staticmethod
    def _count(value, field, location):
        value = value.strip()
        if not value:
            return None
        try:
            number = int(value)
        except ValueError as error:
            raise InputError(
                f"{location}: {field} must be a non-negative integer."
            ) from error
        if number < 0:
            raise InputError(f"{location}: {field} cannot be negative.")
        return number

    def read_summaries(self, cy_name: str) -> list[ShiftingSummary]:
        cy_name = cy_name.strip()
        if not cy_name:
            raise InputError("A non-empty cy_name is required.")

        result = []
        for location, row in self._iter_rows():
            if row["cy_name"].strip().casefold() != cy_name.casefold():
                continue
            row = {key.strip().casefold(): value for key, value in row.items()}
            if row.get("week_number", "").strip().upper() == "TOTAL":
                continue

            shifting_code = row["shifting_code"].strip()
            if not shifting_code:
                raise InputError(f"{location}: shifting_code is required.")

            lifting = self._count(row["lifting_count"], "lifting_count", location)
            shifting = self._count(row["shifting_count"], "shifting_count", location)
            if (lifting is None) != (shifting is None):
                raise InputError(
                    f"{location}: provide both counts or leave both blank."
                )

            result.append(ShiftingSummary(
                cy_name=cy_name,
                shifting_code=shifting_code,
                lifting_count=lifting,
                shifting_count=shifting,
                report_month=row.get("report_month", "").strip() or None,
                week_number=row.get("week_number", "").strip() or None,
            ))

        if not result:
            raise InputError(f"{self.loader.source}: no records for CY {cy_name!r}.")
        return result


def validate_shifting_blocks(observations, block_ids):
    unknown = {row.block_id for row in observations} - set(block_ids)
    if unknown:
        raise InputError(f"Shifting observations reference blocks outside the loaded yard: {unknown}.")


def load_shifting_summary(file_path, cy_name, mapping_path, block_ids):
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    unknown = set(mapping.values()) - set(block_ids)
    if unknown:
        raise ConfigurationError(
            f"{mapping_path}: mapped block IDs are absent from the yard: {sorted(unknown)}."
        )
    observations = ShiftingRepository(CSVLoader(file_path)).read_summaries(cy_name)
    result = []
    for row in observations:
        key = row.shifting_code.casefold()
        if key not in mapping:
            raise InputError(
                f"{file_path}: unmapped shifting code {row.shifting_code!r} for {cy_name!r}."
            )
        result.append(replace(row, block_id=mapping[key]))
    return result

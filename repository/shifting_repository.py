"""Optional shifting summaries for analysis, scoped to one configured CY."""

from dataclasses import dataclass

from .loader import InputError
from .repository import Repository


@dataclass(frozen=True)
class ShiftingSummary:
    cy_name: str
    equipment_group: str
    lifting_count: int | None
    shifting_count: int | None
    report_month: str | None = None
    week_number: str | None = None

    @property
    def shifting_ratio(self) -> float | None:
        if self.lifting_count in (None, 0) or self.shifting_count is None:
            return None
        return self.shifting_count / self.lifting_count


class ShiftingRepository(Repository):
    required_fields = (
        "cy_name", "equipment_group",
        "lifting_count", "shifting_count",
    )

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

            equipment = row["equipment_group"].strip()
            if not equipment:
                raise InputError(f"{location}: equipment_group is required.")

            lifting = self._count(row["lifting_count"], "lifting_count", location)
            shifting = self._count(row["shifting_count"], "shifting_count", location)
            if (lifting is None) != (shifting is None):
                raise InputError(
                    f"{location}: provide both counts or leave both blank."
                )

            result.append(ShiftingSummary(
                cy_name=cy_name,
                equipment_group=equipment,
                lifting_count=lifting,
                shifting_count=shifting,
                report_month=row.get("report_month", "").strip() or None,
                week_number=row.get("week_number", "").strip() or None,
            ))

        if not result:
            raise InputError(f"{self.loader.source}: no records for CY {cy_name!r}.")
        return result

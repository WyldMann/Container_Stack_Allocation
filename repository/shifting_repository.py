"""Optional shifting summaries for analysis, scoped to one configured CY."""

from dataclasses import dataclass, replace
import re
import warnings

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
    period_start: int | None = None
    period_end: int | None = None

    @property
    def shifting_ratio(self) -> float | None:
        if self.lifting_count is None or self.shifting_count is None:
            return None
        total = self.lifting_count + self.shifting_count
        return self.shifting_count / total if total else None

    @property
    def shifting_percentage(self) -> float | None:
        ratio = self.shifting_ratio
        return ratio * 100 if ratio is not None else None


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

    def read_summaries(self, cy_name: str, *, latest_only=False) -> list[ShiftingSummary]:
        cy_name = cy_name.strip()
        if not cy_name:
            raise InputError("A non-empty cy_name is required.")

        rows = []
        for location, row in self._iter_rows():
            if row["cy_name"].strip().casefold() != cy_name.casefold():
                continue
            row = {key.strip().casefold(): value for key, value in row.items()}
            if row.get("week_number", "").strip().upper() == "TOTAL":
                continue
            rows.append((location, row))

        if not rows:
            raise InputError(f"{self.loader.source}: no records for CY {cy_name!r}.")

        if latest_only:
            validate_report_years(row.get("report_month", "") for _, row in rows)
            weeks = [report_week(row.get("week_number"), location) for location, row in rows]
            latest_week = max(weeks)
            rows = [row for row, week in zip(rows, weeks) if week == latest_week]

        result = []
        for location, row in rows:
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

        return result


def validate_shifting_blocks(observations, block_ids, *, skipped=None):
    """Keep observations for present blocks and report excluded assignments."""
    block_ids = set(block_ids)
    accepted = []
    rejected = []
    for row in observations:
        (accepted if row.block_id in block_ids else rejected).append(row)
    if rejected:
        if skipped is not None:
            skipped.extend(rejected)
        assignments = sorted({f"{row.shifting_code} -> {row.block_id}" for row in rejected})
        warnings.warn(
            f"Skipped {len(rejected)} shifting observations for blocks absent "
            f"from the loaded yard: {', '.join(assignments)}.",
            UserWarning, stacklevel=2,
        )
    return accepted


def validate_report_years(report_months):
    years = {
        match.group(1)
        for month in report_months
        if (match := re.fullmatch(r"(\d{4})-(?:0[1-9]|1[0-2])", month or ""))
    }
    if len(years) > 1:
        raise InputError("A shifting-week benchmark applies to one report year; split multi-year data.")


def report_week(value, source):
    try:
        week = int(value or "")
    except ValueError as error:
        raise InputError(f"{source}: week_number is required for weekly recording.") from error
    if not 1 <= week <= 53:
        raise InputError(f"{source}: week_number must be 1 through 53.")
    return week


def assign_shifting_periods(observations, period_settings):
    validate_report_years(row.report_month for row in observations)
    result = []
    for row in observations:
        week = report_week(row.week_number, row.shifting_code)
        start, end = period_settings.boundaries(week)
        result.append(replace(row, period_start=start, period_end=end))
    return result


def load_shifting_summary(
    file_path, cy_name, mapping_path, block_ids, *, skipped=None, period_settings=None,
    latest_only=False,
):
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    observations = ShiftingRepository(CSVLoader(file_path)).read_summaries(
        cy_name, latest_only=latest_only,
    )
    result = []
    for row in observations:
        key = row.shifting_code.casefold()
        if key not in mapping:
            raise InputError(
                f"{file_path}: unmapped shifting code {row.shifting_code!r} for {cy_name!r}."
            )
        result.append(replace(row, block_id=mapping[key]))
    result = validate_shifting_blocks(result, block_ids, skipped=skipped)
    return assign_shifting_periods(result, period_settings) if period_settings is not None else result

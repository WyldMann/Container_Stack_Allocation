"""Optional shifting summaries for analysis, scoped to one configured CY."""

from dataclasses import dataclass, replace
import re
import warnings

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import CSVLoader
from .loader import InputError
from .repository import Repository
from .shifting_csv_export import refresh_shifting_csv
from .shifting_dates import daily_boundaries, report_date, today_wib


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
    report_date: str | None = None

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

    def read_summaries(self, cy_name: str, *, latest_only=False, today=None, required_codes=None) -> list[ShiftingSummary]:
        if not cy_name.strip():
            raise InputError("A non-empty cy_name is required.")

        rows = []
        for location, row in self._iter_rows():
            if row["cy_name"].upper() != cy_name.upper():
                continue
            row = {key.strip().casefold(): value for key, value in row.items()}
            if any(row.get(field, "").strip().upper() == "TOTAL" for field in ("week_number", "report_date")):
                continue
            rows.append((location, row))

        if not rows:
            raise InputError(f"{self.loader.source}: no records for CY {cy_name!r}.")

        daily = "report_date" in rows[0][1]
        if daily:
            rows = self._latest_complete_day(rows, today or today_wib(), required_codes)
        elif latest_only:
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
            if not daily and (lifting is None) != (shifting is None):
                raise InputError(
                    f"{location}: provide both counts or leave both blank."
                )

            day = report_date(row["report_date"]) if daily else None
            start, end = daily_boundaries(day) if daily else (None, None)
            if daily:
                for field, expected in (("period_start", start), ("period_end", end)):
                    value = row.get(field, "").strip()
                    if value and value != str(expected):
                        raise InputError(f"{location}: {field} must match midnight WIB for report_date.")
            result.append(ShiftingSummary(
                cy_name=cy_name,
                shifting_code=shifting_code,
                lifting_count=lifting,
                shifting_count=shifting,
                report_month=day.strftime("%Y-%m") if day else row.get("report_month", "").strip() or None,
                week_number=row.get("week_number", "").strip() or None,
                report_date=day.isoformat() if day else None,
                period_start=start, period_end=end,
            ))

        return result

    def _latest_complete_day(self, rows, today, required_codes):
        """Only closed calendar days with all required counts can be recorded."""
        by_day = {}
        for location, row in rows:
            day = report_date(row["report_date"])
            if day < today:
                by_day.setdefault(day, []).append((location, row))
        required = (
            {code.casefold() for code in required_codes} if required_codes is not None
            else {row["shifting_code"].strip().casefold() for _, row in rows}
        )
        for day in sorted(by_day, reverse=True):
            observations = by_day[day]
            codes = {}
            for location, row in observations:
                code = row["shifting_code"].strip().casefold()
                if code in codes:
                    raise InputError(f"{location}: duplicate daily shifting code {row['shifting_code']!r} for {day}.")
                codes[code] = row
            if not required or not required.issubset(codes):
                continue
            if any(not codes[code][field].strip() for code in required
                   for field in ("lifting_count", "shifting_count")):
                continue
            # Validate counts only for this candidate; older partial days cannot block it.
            for location, row in observations:
                if row["shifting_code"].strip().casefold() in required:
                    for field in ("lifting_count", "shifting_count"):
                        self._count(row[field], field, location)
            return observations
        raise InputError(
            f"{self.loader.source}: no complete daily shifting data before {today.isoformat()} "
            "for codes mapped to the loaded yard blocks."
        )


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
    workbook_path=None, workbook_sheet="Per Alat Weekly",
    today=None,
):
    if workbook_path is not None:
        refresh_shifting_csv(workbook_path, file_path, workbook_sheet)
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    block_ids = set(block_ids)
    observations = ShiftingRepository(CSVLoader(file_path)).read_summaries(
        cy_name, latest_only=latest_only, today=today,
        required_codes={code for code, block in mapping.items() if block in block_ids},
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
    if any(row.report_date is not None for row in observations):
        return result
    if latest_only and period_settings is None:
        raise ConfigurationError("Configure [shifting_period] before recording legacy weekly metrics.")
    return assign_shifting_periods(result, period_settings) if period_settings is not None else result

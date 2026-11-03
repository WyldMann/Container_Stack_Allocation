"""Aggregate a flat activity export using the SQL operations counting rules."""

from collections import Counter
from datetime import datetime

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import CSVLoader
from .loader import InputError
from .repository import Repository
from .shifting_dates import WIB
from .shifting_repository import ShiftingSummary, resolve_shifting_blocks


class OperationsRepository(Repository):
    required_fields = (
        "DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT",
    )

    def _iter_operations(self, active):
        """Read dated, countable operations for equipment in the loaded yard."""
        for location, row in self._iter_rows():
            code = row["ALAT"].strip().casefold()
            if code not in active:
                continue
            # COUNT(DTL_ID) excludes null identifiers. Empty CSV cells represent nulls.
            if not row["DTL_ID"].strip():
                continue
            activity_time = row["ACTIVITY_DATE_TIME"].strip()
            if not activity_time:
                continue
            try:
                timestamp = int(datetime.strptime(
                    activity_time.replace("/", "-"), "%d-%m-%Y %H:%M",
                ).replace(tzinfo=WIB).timestamp())
            except ValueError as error:
                raise InputError(
                    f"{location}: ACTIVITY_DATE_TIME must be DD-MM-YYYY HH:MM "
                    "or DD/MM/YYYY HH:MM in WIB."
                ) from error
            yield timestamp, code, row["ACTIVITY"]

    def read_summaries(self, cy_name, mapping, blocks, activities, *,
                       period_granularity="daily", diagnostics=None):
        if period_granularity not in ("daily", "weekly"):
            raise ConfigurationError("shifting.period_granularity must be 'daily' or 'weekly'.")
        mapping = resolve_shifting_blocks(mapping, blocks)
        active = {code: block for code, block in mapping.items() if block is not None}
        # The export has no ordering guarantee. Find its latest timestamp before counting;
        # two streaming passes avoid retaining the full activity history in memory.
        period_end = max((timestamp for timestamp, _, _ in self._iter_operations(active)), default=None)
        if diagnostics is not None:
            diagnostics["excluded_activities"] = {}
        if period_end is None:
            return []
        duration = 86400 if period_granularity == "daily" else 7 * 86400
        period_start = period_end - duration
        counts = {code: Counter() for code in active}
        categories = {activity: kind for kind, names in activities.items() for activity in names}
        excluded = Counter()
        for timestamp, code, activity in self._iter_operations(active):
            # Include the newest activity; exclude the exact trailing-window cutoff.
            if not period_start < timestamp <= period_end:
                continue
            # Match SQL's exact activity comparison; equipment codes ignore case/whitespace.
            kind = categories.get(activity)
            if kind is None:
                excluded[activity] += 1
            else:
                counts[code][kind] += 1
        if diagnostics is not None:
            diagnostics["excluded_activities"] = dict(sorted(excluded.items()))
        return [
            ShiftingSummary(
                cy_name=cy_name, shifting_code=code.upper(), block_id=block,
                lifting_count=counts[code]["lifting"], shifting_count=counts[code]["shifting"],
                period_start=period_start, period_end=period_end,
            )
            for code, block in active.items()
        ]


def load_csv_shifting_summary(path, activities, cy_name, branch_code, mapping_path, blocks, *,
                              period_granularity="daily", diagnostics=None):
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    loader = CSVLoader(path, branch_column="KODE_CABANG", branch_codes=(branch_code,))
    return OperationsRepository(loader).read_summaries(
        cy_name, mapping, blocks, activities,
        period_granularity=period_granularity, diagnostics=diagnostics,
    )

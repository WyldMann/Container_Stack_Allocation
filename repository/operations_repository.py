"""Aggregate a flat activity export using the SQL operations counting rules."""

from collections import Counter
from datetime import datetime

from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import CSVLoader
from .loader import InputError
from .repository import Repository
from .shifting_dates import WIB, operations_period_boundaries
from .shifting_repository import ShiftingSummary


class OperationsRepository(Repository):
    required_fields = (
        "DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT",
    )

    def read_summaries(self, cy_name, mapping, block_ids, activities, *,
                       period_start, period_end, diagnostics=None):
        block_ids = set(block_ids)
        active = {code: block for code, block in mapping.items() if block in block_ids}
        counts = {code: Counter() for code in active}
        categories = {activity: kind for kind, names in activities.items() for activity in names}
        excluded = Counter()
        for location, row in self._iter_rows():
            code = row["ALAT"].strip().casefold()
            if code not in active:
                continue
            # COUNT(DTL_ID) excludes null identifiers. Empty CSV cells represent nulls.
            if not row["DTL_ID"].strip():
                continue
            try:
                timestamp = int(datetime.strptime(
                    row["ACTIVITY_DATE_TIME"].strip(), "%d-%m-%Y %H:%M",
                ).replace(tzinfo=WIB).timestamp())
            except ValueError as error:
                raise InputError(
                    f"{location}: ACTIVITY_DATE_TIME must be DD-MM-YYYY HH:MM in WIB."
                ) from error
            if not period_start <= timestamp < period_end:
                continue
            # Match SQL's exact activity comparison; equipment codes ignore case/whitespace.
            activity = row["ACTIVITY"]
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


def load_csv_shifting_summary(path, activities, cy_name, branch_code, mapping_path, block_ids, *,
                              period_granularity="daily", recorded_at=None, diagnostics=None):
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    start, end = operations_period_boundaries(period_granularity, recorded_at)
    loader = CSVLoader(path, branch_column="KODE_CABANG", branch_codes=(branch_code,))
    return OperationsRepository(loader).read_summaries(
        cy_name, mapping, block_ids, activities,
        period_start=start, period_end=end, diagnostics=diagnostics,
    )

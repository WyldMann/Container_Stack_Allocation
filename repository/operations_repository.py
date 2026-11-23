"""Aggregate a flat activity export using the SQL operations counting rules."""

from collections import Counter
from datetime import datetime

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import CSVLoader
from .loader import InputError
from .operations_blacklist import load_operations_blacklist, operation_key
from .repository import Repository
from .shifting_dates import WIB
from .shifting_repository import ShiftingSummary, resolve_shifting_blocks


class OperationsRepository(Repository):
    required_fields = (
        "DTL_ID", "DOC_ID", "ACTIVITY", "ACTIVITY_DATE_TIME", "KODE_CABANG", "ALAT",
    )

    def _iter_operations(self, active, branch_code=None, *, blacklist=None, blacklisted=None):
        """Read dated, countable operations for equipment in the loaded yard."""
        for location, row in self._iter_rows():
            if branch_code is not None and row["KODE_CABANG"].strip().upper() != branch_code.strip().upper():
                continue
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
            if blacklist:
                key = operation_key(row["KODE_CABANG"], row["DOC_ID"], row["DTL_ID"],
                                    code, row["ACTIVITY"], timestamp)
                if key in blacklist:
                    if blacklisted is not None:
                        blacklisted.append({"source": location, "branch_code": key[0],
                                            "document_id": key[1], "detail_id": key[2],
                                            "equipment_code": row["ALAT"].strip().upper(),
                                            "activity": row["ACTIVITY"],
                                            "activity_time": activity_time,
                                            "reason": blacklist[key]})
                    continue
            yield timestamp, code, row["ACTIVITY"]

    def read_summaries(self, cy_name, mapping, blocks, activities, *,
                       period_granularity="daily", diagnostics=None, branch_code=None,
                       blacklist=None):
        if period_granularity not in ("daily", "weekly"):
            raise ConfigurationError("shifting.period_granularity must be 'daily' or 'weekly'.")
        mapping = resolve_shifting_blocks(mapping, blocks)
        active = {code: ids for code, ids in mapping.items() if ids}
        blacklisted = [] if blacklist and diagnostics is not None else None
        if diagnostics is not None:
            diagnostics["excluded_activities"] = {}
            if blacklisted is not None:
                diagnostics["blacklisted_operations"] = blacklisted
            else:
                diagnostics.pop("blacklisted_operations", None)
        # The export has no ordering guarantee. Find its latest timestamp before counting;
        # two streaming passes avoid retaining the full activity history in memory.
        period_end = max((timestamp for timestamp, _, _ in self._iter_operations(
            active, branch_code, blacklist=blacklist, blacklisted=blacklisted,
        )), default=None)
        if period_end is None:
            return []
        duration = 86400 if period_granularity == "daily" else 7 * 86400
        period_start = period_end - duration
        counts = {code: Counter() for code in active}
        categories = {activity.upper(): kind for kind, names in activities.items() for activity in names}
        excluded = Counter()
        for timestamp, code, activity in self._iter_operations(active, branch_code, blacklist=blacklist):
            # Include the newest activity; exclude the exact trailing-window cutoff.
            if not period_start < timestamp <= period_end:
                continue
            # Use the same case-insensitive activity comparison as the SQL source.
            kind = categories.get(activity.upper())
            if kind is None:
                excluded[activity] += 1
            else:
                counts[code][kind] += 1
        if diagnostics is not None:
            diagnostics["excluded_activities"] = dict(sorted(excluded.items()))
        return [
            ShiftingSummary(
                cy_name=cy_name, shifting_code=code.upper(), block_id=ids[0], block_ids=ids,
                branch_code=branch_code.strip().upper() if branch_code else None,
                lifting_count=counts[code]["lifting"], shifting_count=counts[code]["shifting"],
                period_start=period_start, period_end=period_end,
            )
            for code, ids in active.items()
        ]


def load_csv_shifting_summary(path, activities, cy_name, branch_code, mapping_path, blocks, *,
                              period_granularity="daily", diagnostics=None, blacklist_path=None):
    mapping = load_shifting_block_mapping(mapping_path, cy_name, branch_code)
    blacklist = load_operations_blacklist(blacklist_path)
    loader = CSVLoader(path, branch_column="KODE_CABANG", branch_codes=(branch_code,))
    return OperationsRepository(loader).read_summaries(
        cy_name, mapping, blocks, activities,
        period_granularity=period_granularity, diagnostics=diagnostics, branch_code=branch_code,
        blacklist=blacklist,
    )

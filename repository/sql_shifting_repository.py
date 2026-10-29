"""Count lifting and shifting operations over a rolling SQL reporting window."""

from time import time

from config import ConfigurationError
from config.csv_import.shifting_block_mapping import load_shifting_block_mapping

from .csvloader import BRANCH_WHITESPACE
from .loader import InputError
from .shifting_repository import ShiftingSummary
from .sqlloader import SQLLoader


def operations_count_query(definition):
    """Compose identifiers only; all branch, equipment, activity and date values bind."""
    from psycopg import sql

    detail = definition["detail_columns"]
    header = definition["header_columns"]
    fields = {
        "detail_relation": sql.Identifier(definition["schema"], definition["detail_relation"]),
        "header_relation": sql.Identifier(definition["schema"], definition["header_relation"]),
        **{"a_" + name: sql.Identifier("a", column) for name, column in detail.items()},
        **{"b_" + name: sql.Identifier("b", column) for name, column in header.items()},
    }
    return sql.SQL("""
SELECT COUNT({a_operation_id}) AS operation_count
FROM {detail_relation} a
WHERE EXISTS (
    SELECT 1 FROM {header_relation} b
    WHERE {b_document_id} = {a_document_id}
      AND {b_branch_code} = %(branch_code)s
      AND UPPER(BTRIM({b_equipment_code}::text, %(whitespace)s)) = %(equipment_code)s
)
AND {a_activity} = ANY(%(activities)s::text[])
AND TO_TIMESTAMP({a_activity_time} || %(utc_offset)s, %(datetime_format)s)
    >= TO_TIMESTAMP(%(period_start)s::double precision)
AND TO_TIMESTAMP({a_activity_time} || %(utc_offset)s, %(datetime_format)s)
    < TO_TIMESTAMP(%(period_end)s::double precision)
""").format(**fields)


def sql_period_boundaries(period_granularity, recorded_at=None):
    if period_granularity not in ("daily", "weekly"):
        raise ConfigurationError("shifting.period_granularity must be 'daily' or 'weekly'.")
    end = int(time() if recorded_at is None else recorded_at)
    duration = 86400 if period_granularity == "daily" else 7 * 86400
    return end - duration, end


def load_sql_shifting_summary(
    connection, definition, activities, cy_name, branch_code, mapping_path, block_ids, *,
    period_granularity="daily", recorded_at=None,
):
    mapping = load_shifting_block_mapping(mapping_path, cy_name)
    block_ids = set(block_ids)
    active = {code: block for code, block in mapping.items() if block in block_ids}
    if not active:
        return []
    start, end = sql_period_boundaries(period_granularity, recorded_at)
    query = operations_count_query(definition)
    result = []
    for code, block_id in active.items():
        counts = {}
        for kind in ("lifting", "shifting"):
            source = f"SQL {kind} operations for {cy_name!r}, equipment {code.upper()!r}, Unix period [{start}, {end})"
            parameters = {
                "branch_code": branch_code,
                "equipment_code": code.upper(),
                "whitespace": BRANCH_WHITESPACE,
                "activities": list(activities[kind]),
                "utc_offset": " +07:00",
                "datetime_format": definition["datetime_format"] + " TZH:TZM",
                "period_start": start,
                "period_end": end,
            }
            loader = SQLLoader(connection, query, parameters=parameters, source=source)
            with loader.open() as (headers, rows):
                values = list(rows)
            if headers != ["operation_count"] or len(values) != 1:
                raise InputError(f"{source}: expected exactly one operation_count result.")
            count = values[0][1]["operation_count"]
            if type(count) is not int or count < 0:
                raise InputError(f"{source}: operation_count must be a non-negative integer.")
            counts[kind] = count
        result.append(ShiftingSummary(
            cy_name=cy_name, shifting_code=code.upper(), block_id=block_id,
            lifting_count=counts["lifting"], shifting_count=counts["shifting"],
            period_start=start, period_end=end,
        ))
    return result

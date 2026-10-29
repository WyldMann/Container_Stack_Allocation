"""Dispatch operations to the explicitly selected source without fallbacks."""

from config import ConfigurationError

from .shifting_repository import load_shifting_summary
from .sql_connection import input_connection
from .sql_shifting_repository import load_sql_shifting_summary


def load_operations(settings, branches, block_ids, *, connection=None, latest_only=False,
                    today=None, recorded_at=None):
    cy_name = branches.cy_name()
    source = settings.get("shifting_source", "csv")
    if source == "sql":
        if connection is None:
            with input_connection(settings) as connection:
                return load_operations(settings, branches, block_ids, connection=connection,
                                       recorded_at=recorded_at)
        return load_sql_shifting_summary(
            connection, settings["sql_shifting"], settings["shifting_activities"],
            cy_name, branches.records[0]["branch_code"],
            settings["shifting_block_mapping_file"], block_ids,
            period_granularity=settings.get("shifting_granularity", "daily"), recorded_at=recorded_at,
        )
    if source != "csv":
        raise ConfigurationError(f"Unknown operations source: {source!r}.")
    if "shifting_summary_file" not in settings:
        raise ConfigurationError("csv.shifting_summary_file is required for operations recording.")
    return load_shifting_summary(
        settings["shifting_summary_file"], cy_name,
        settings["shifting_block_mapping_file"], block_ids,
        period_settings=settings.get("shifting_period"), latest_only=latest_only,
        workbook_path=settings.get("shifting_workbook_file"),
        workbook_sheet=settings.get("shifting_workbook_sheet", "Per Alat Weekly"), today=today,
    )

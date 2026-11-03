"""Dispatch operations to the explicitly selected source without fallbacks."""

from config import ConfigurationError

from .shifting_repository import load_shifting_summary
from .operations_repository import load_csv_shifting_summary
from .shifting_xlsx_loader import ShiftingXLSXLoader
from .sql_connection import input_connection
from .sql_shifting_repository import load_sql_shifting_summary


def load_operations(settings, branches, blocks, *, connection=None, latest_only=False,
                    today=None, recorded_at=None, diagnostics=None):
    """Load operations using yard records containing block_code and block_id."""
    cy_name = branches.cy_name()
    source = settings.get("shifting_source", "xlsx")
    if source == "csv":
        return load_csv_shifting_summary(
            settings["csv_files"]["shifting_summary"], settings["shifting_activities"],
            cy_name, branches.records[0]["branch_code"],
            settings["shifting_block_mapping_file"], blocks,
            period_granularity=settings.get("shifting_granularity", "daily"),
            diagnostics=diagnostics,
        )
    if source == "sql":
        if connection is None:
            with input_connection(settings) as connection:
                return load_operations(settings, branches, blocks, connection=connection,
                                       recorded_at=recorded_at)
        return load_sql_shifting_summary(
            connection, settings["sql_shifting"], settings["shifting_activities"],
            cy_name, branches.records[0]["branch_code"],
            settings["shifting_block_mapping_file"], blocks,
            period_granularity=settings.get("shifting_granularity", "daily"), recorded_at=recorded_at,
        )
    if source != "xlsx":
        raise ConfigurationError(f"Unknown operations source: {source!r}.")
    if "shifting_workbook_file" not in settings:
        raise ConfigurationError("csv.shifting_workbook_file is required for operations recording.")
    return load_shifting_summary(
        ShiftingXLSXLoader(
            settings["shifting_workbook_file"],
            settings.get("shifting_workbook_sheet", "Per Alat Weekly"),
        ), cy_name,
        settings["shifting_block_mapping_file"], blocks,
        period_settings=settings.get("shifting_period"), latest_only=latest_only,
        today=today,
    )

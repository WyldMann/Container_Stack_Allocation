"""Load all configured datasets before interactive yard processing begins."""

import os

from config import ConfigurationError
from config.application.input_filters import active_filters, mapped_filters
from config.csv_import.mapping_loader import load_mapping

from .csvloader import CSVLoader
from .sqlloader import SQLLoader
from .shifting_repository import load_shifting_summary
from .repository import (
    Repository, ContainerRepository, RemovedSlotsRepository,
    YardPlanningRepository, EquipmentMoveRepository,
)


def _read_datasets(make_loader, profiles, *, datasets=None):
    readers = {
        "yard_blocks": (Repository, "read_records"),
        "yard_planning": (YardPlanningRepository, "read_grouped"),
        "removed_slots": (RemovedSlotsRepository, "read_tuples"),
        "parameters": (Repository, "read_records"),
        "existing_containers": (ContainerRepository, "read_records"),
        "inbound_containers": (ContainerRepository, "read_records"),
        "master_equipment": (Repository, "read_records"),
        "equipment_history": (EquipmentMoveRepository, "read_locations"),
    }
    if datasets is not None:
        unknown = set(datasets) - set(readers)
        if unknown:
            raise ConfigurationError(f"Unknown input datasets: {sorted(unknown)}")
        readers = {name: reader for name, reader in readers.items() if name in datasets}
    missing = set(readers) - set(profiles)
    if missing:
        raise ConfigurationError(f"Missing mapping profiles: {sorted(missing)}")
    return {
        name: getattr(repository(make_loader(name), profiles[name]), method)()
        for name, (repository, method) in readers.items()
    }


def _sql_loader(connection, name, definition):
    from psycopg import sql

    query = sql.SQL("SELECT * FROM {}").format(
        sql.Identifier(definition["schema"], definition["relation"])
    )
    filters = active_filters(definition["filters"])
    if filters:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(
            sql.SQL("{} = %s").format(sql.Identifier(column))
            for column in filters
        )
    if definition["order_by"]:
        query += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(
            sql.Identifier(column) for column in definition["order_by"]
        )
    return SQLLoader(connection, query, parameters=tuple(filters.values()), source=name)


def load_yard_inputs(settings, *, include_shifting=True):
    """Load selected sources; SQL errors propagate without a CSV fallback."""
    sources = settings["sources"]
    profiles_by_source = {
        source: load_mapping(path, source=source)
        for source, path in settings["mapping_files"].items()
    }
    profiles = {}
    for name, source in sources.items():
        if name not in profiles_by_source[source]:
            raise ConfigurationError(
                f"Missing {source.upper()} mapping profile: {name!r}."
            )
        profiles[name] = profiles_by_source[source][name]

    def read_inputs(connection=None):
        def make_loader(name):
            if sources[name] == "csv":
                return CSVLoader(settings["csv_files"][name], filters=mapped_filters(
                    settings.get("filters", {}), profiles[name].filter_columns,
                ))
            return _sql_loader(connection, name, settings["sql_datasets"][name])

        inputs = _read_datasets(make_loader, profiles, datasets=sources)
        if settings.get("filters"):
            _scope_to_yard_blocks(inputs)
        shifting_file = settings.get("shifting_summary_file")
        if include_shifting and shifting_file is not None:
            skipped = []
            inputs["shifting_summary"] = load_shifting_summary(
                shifting_file, settings["cy_name"],
                settings["shifting_block_mapping_file"],
                {row["block_id"] for row in inputs["yard_blocks"]},
                skipped=skipped,
                period_settings=settings.get("shifting_period"),
                workbook_path=settings.get("shifting_workbook_file"),
                workbook_sheet=settings.get("shifting_workbook_sheet", "Per Alat Weekly"),
            )
            if skipped:
                inputs["skipped_shifting_summary"] = skipped
        return inputs

    if "sql" not in sources.values():
        return read_inputs()

    try:
        import psycopg
    except ImportError as error:
        raise ConfigurationError(
            "SQL input requires Psycopg 3. Install requirements-sql.txt."
        ) from error

    connection_options = dict(settings["connection"])
    password_env = settings["password_env"]
    if password_env:
        password = os.environ.get(password_env)
        if password is None:
            raise ConfigurationError(f"SQL password environment variable {password_env!r} is not set.")
        connection_options["password"] = password

    with psycopg.connect(**connection_options) as connection:
        connection.read_only = True
        connection.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if settings["consistent_snapshot"]
            else psycopg.IsolationLevel.READ_COMMITTED
        )
        return read_inputs(connection)


def _scope_to_yard_blocks(inputs):
    """Scope files without terminal/branch columns through their yard blocks."""
    blocks = inputs.get("yard_blocks", [])
    block_ids = {row["block_id"] for row in blocks}
    coordinates = {(row["branch_id"], row["block_code"]) for row in blocks}
    if "existing_containers" in inputs:
        inputs["existing_containers"] = [
            row for row in inputs["existing_containers"]
            if (row["branch_id"], row["block_code"]) in coordinates
        ]
    if "removed_slots" in inputs:
        inputs["removed_slots"] = [row for row in inputs["removed_slots"] if row[0] in block_ids]
    if "yard_planning" in inputs:
        inputs["yard_planning"] = {
            parameter: [location for location in locations if location[0] in block_ids]
            for parameter, locations in inputs["yard_planning"].items()
        }
    if "equipment_history" in inputs:
        inputs["equipment_history"] = {
            code: location for code, location in inputs["equipment_history"].items()
            if location[:2] in coordinates
        }

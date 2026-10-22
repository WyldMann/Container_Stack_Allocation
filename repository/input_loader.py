"""Load all configured datasets before interactive yard processing begins."""

import os

from config import ConfigurationError
from config.csv_import.mapping_loader import load_mapping

from .csvloader import CSVLoader
from .sqlloader import SQLLoader
from .repository import (
    Repository, ContainerRepository, RemovedSlotsRepository,
    YardPlanningRepository, EquipmentMoveRepository,
)


def _read_datasets(make_loader, profiles):
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
    filters = definition["filters"]
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


def load_yard_inputs(settings):
    profiles = load_mapping(
        settings["mapping_file"], source=settings["source"]
    )
    if settings["source"] == "csv":
        return _read_datasets(
            lambda name: CSVLoader(settings["csv_files"][name]), profiles
        )

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
        return _read_datasets(
            lambda name: _sql_loader(connection, name, settings["sql_datasets"][name]),
            profiles,
        )

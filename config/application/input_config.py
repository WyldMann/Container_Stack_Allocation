"""Read source selection and locations without opening any data sources."""

import os
from pathlib import Path

from .config_loader import ConfigurationError, _read_document, _read_section
from .input_filters import FILTER_NAMES, active_filters, mapped_filters, read_filter_columns
from .shifting_period import parse_shifting_period
from ..csv_import.mapping_settings import SCHEMAS


DATASETS = tuple(SCHEMAS)


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string.")
    return value


def _dataset_names(definitions, name, required=DATASETS):
    if not isinstance(definitions, dict):
        raise ConfigurationError(f"{name} must be a table.")
    missing = set(required) - set(definitions)
    unknown = set(definitions) - set(DATASETS)
    if missing or unknown:
        raise ConfigurationError(
            f"Invalid {name}: missing datasets {sorted(missing)}; "
            f"unknown datasets {sorted(unknown)}."
        )


def load_input_config(path: str | Path, *, datasets=DATASETS) -> dict:
    """Validate source settings for the datasets used by an entrypoint."""
    datasets = tuple(datasets)
    if not datasets or set(datasets) - set(DATASETS):
        raise ConfigurationError("Select at least one known input dataset.")
    config_path = Path(path).resolve()
    document = _read_document(config_path)
    unknown = set(document) - {"input", "csv", "sql", "output", "shifting_period"}
    if unknown:
        raise ConfigurationError(f"Unknown input configuration sections: {sorted(unknown)}")
    section = _read_section(document, "input", {"sources", "cy_name", "filters"})
    filters = active_filters(_read_section(section, "filters", FILTER_NAMES), "input.filters")
    for name, value in filters.items():
        if type(value) not in (str, int):
            raise ConfigurationError(f"input.filters.{name} must be a string or integer.")
    cy_name = section.get("cy_name")
    if cy_name is not None:
        cy_name = _string(cy_name, "input.cy_name").strip()
    sources = section.get("sources")
    _dataset_names(sources, "input.sources", required=datasets)
    sources = {name: source for name, source in sources.items() if name in datasets}
    for name, source in sources.items():
        if source not in ("csv", "sql"):
            raise ConfigurationError(
                f"input.sources.{name} must be 'csv' or 'sql'."
            )
    csv_names = {name for name, source in sources.items() if source == "csv"}
    sql_names = {name for name, source in sources.items() if source == "sql"}

    def resolve(value, name):
        return (config_path.parent / _string(value, name)).resolve()

    output = _read_section(document, "output", {"containers_file"})
    settings = {
        "sources": dict(sources),
        "filters": filters,
        "mapping_files": {},
        "output_file": resolve(output.get("containers_file", "../output/result.csv"),
                               "output.containers_file"),
    }

    settings["cy_name"] = cy_name
    period_settings = parse_shifting_period(document)
    if period_settings is not None:
        settings["shifting_period"] = period_settings
    csv = _read_section(document, "csv", {
        "files", "mapping_file", "shifting_summary_file", "shifting_block_mapping_file",
        "shifting_workbook_file", "shifting_workbook_sheet",
    })
    shifting_file = csv.get("shifting_summary_file")
    workbook_file = csv.get("shifting_workbook_file")
    if workbook_file is not None:
        if shifting_file is None:
            raise ConfigurationError("csv.shifting_workbook_file requires csv.shifting_summary_file.")
        settings["shifting_workbook_file"] = resolve(workbook_file, "csv.shifting_workbook_file")
        settings["shifting_workbook_sheet"] = _string(
            csv.get("shifting_workbook_sheet", "Per Alat Weekly"), "csv.shifting_workbook_sheet"
        ).strip()
    if shifting_file is not None:
        if cy_name is None:
            raise ConfigurationError(
                "input.cy_name is required when csv.shifting_summary_file is set."
            )
        settings["shifting_summary_file"] = resolve(
            shifting_file, "csv.shifting_summary_file"
        )
        settings["shifting_block_mapping_file"] = resolve(
            csv.get("shifting_block_mapping_file", "shifting_block_mapping.toml"),
            "csv.shifting_block_mapping_file",
        )

    # Require locations only for datasets using the corresponding source.
    if csv_names:
        settings["mapping_files"]["csv"] = resolve(
            csv.get("mapping_file", "csv_mapping.toml"), "csv.mapping_file"
        )
        files = csv.get("files")
        _dataset_names(files, "csv.files", required=csv_names)
        settings["csv_files"] = {
            name: resolve(value, f"csv.files.{name}")
            for name, value in files.items()
            if name in csv_names
        }

    if not sql_names:
        return settings

    sql = _read_section(document, "sql", {
        "host_env", "port", "dbname_env", "user_env",
        "password_env", "connect_timeout",
        "sslmode", "schema", "consistent_snapshot", "mapping_file",
    })
    connection = {}
    for name in ("host", "dbname", "user"):
        setting = f"{name}_env"
        env_name = _string(sql.get(setting), f"sql.{setting}")
        connection[name] = _string(
            os.environ.get(env_name),
            f"Environment variable {env_name!r} for sql.{setting}",
        )
    for name, default, maximum in (("port", 5432, 65535), ("connect_timeout", 10, None)):
        value = sql.get(name, default)
        if type(value) is not int or value <= 0 or (maximum and value > maximum):
            raise ConfigurationError(f"sql.{name} must be a positive integer"
                                     + (f" no greater than {maximum}." if maximum else "."))
        connection[name] = value
    sslmode = sql.get("sslmode", "prefer")
    if sslmode not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
        raise ConfigurationError("Invalid sql.sslmode.")
    connection["sslmode"] = sslmode
    password_env = sql.get("password_env")
    if password_env is not None:
        _string(password_env, "sql.password_env")
    snapshot = sql.get("consistent_snapshot", True)
    if type(snapshot) is not bool:
        raise ConfigurationError("sql.consistent_snapshot must be true or false.")
    schema = _string(sql.get("schema", "public"), "sql.schema")
    mapping_path = resolve(
        sql.get("mapping_file", "sql_mapping.toml"), "sql.mapping_file"
    )
    mapping_document = _read_document(mapping_path)
    if set(mapping_document) - {"sql"}:
        raise ConfigurationError(
            "Only the 'sql' section is allowed in SQL mappings."
        )
    datasets = _read_section(mapping_document, "sql", set(DATASETS))
    _dataset_names(datasets, "sql", required=sql_names)
    validated = {}
    for name, definition in datasets.items():
        if name not in sql_names:
            continue
        label = f"sql.{name}"
        if not isinstance(definition, dict) or set(definition) - {
            "schema", "relation", "filters", "filter_columns", "order_by", "columns",
        }:
            raise ConfigurationError(f"Invalid {label} settings.")
        filters = active_filters(definition.get("filters", {}), f"{label}.filters")
        columns = read_filter_columns(definition.get("filter_columns", {}), f"{label}.filter_columns")
        for column, value in mapped_filters(settings["filters"], columns).items():
            if column in filters and filters[column] != value:
                raise ConfigurationError(f"Conflicting filter values for {label}.{column}.")
            filters[column] = value
        order = definition.get("order_by", [])
        if not isinstance(order, list):
            raise ConfigurationError(f"{label}.order_by must be a list of column names.")
        for column in order:
            _string(column, f"{label}.order_by column")
        validated[name] = {
            "schema": _string(definition.get("schema", schema), f"{label}.schema"),
            "relation": _string(definition.get("relation"), f"{label}.relation"),
            "filters": filters,
            "order_by": order,
        }
    settings["mapping_files"]["sql"] = mapping_path
    settings.update(connection=connection, password_env=password_env,
                    consistent_snapshot=snapshot, sql_datasets=validated)
    return settings

"""Read source selection and locations without opening any data sources."""

from pathlib import Path

from .config_loader import ConfigurationError, _read_document, _read_section
from ..csv_import.mapping_settings import SCHEMAS


DATASETS = tuple(SCHEMAS)


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string.")
    return value


def _dataset_names(definitions, name):
    if not isinstance(definitions, dict):
        raise ConfigurationError(f"{name} must be a table.")
    missing = set(DATASETS) - set(definitions)
    unknown = set(definitions) - set(DATASETS)
    if missing or unknown:
        raise ConfigurationError(
            f"Invalid {name}: missing datasets {sorted(missing)}; "
            f"unknown datasets {sorted(unknown)}."
        )


def load_input_config(path: str | Path) -> dict:
    config_path = Path(path).resolve()
    document = _read_document(config_path)
    unknown = set(document) - {"input", "csv", "sql", "output"}
    if unknown:
        raise ConfigurationError(f"Unknown input configuration sections: {sorted(unknown)}")
    section = _read_section(document, "input", {"source", "mapping_file"})
    source = section.get("source")
    if source not in ("csv", "sql"):
        raise ConfigurationError("input.source must be 'csv' or 'sql'.")

    def resolve(value, name):
        return (config_path.parent / _string(value, name)).resolve()

    output = _read_section(document, "output", {"containers_file"})
    settings = {
        "source": source,
        "mapping_file": resolve(section.get("mapping_file", "csv_mapping.toml"),
                                "input.mapping_file"),
        "output_file": resolve(output.get("containers_file", "../output/result.csv"),
                               "output.containers_file"),
    }

    # Validate the selected source only, so CSV requires no SQL configuration.
    if source == "csv":
        csv = _read_section(document, "csv", {"files"})
        files = csv.get("files")
        _dataset_names(files, "csv.files")
        settings["csv_files"] = {
            name: resolve(value, f"csv.files.{name}")
            for name, value in files.items()
        }
        return settings

    sql = _read_section(document, "sql", {
        "host", "port", "dbname", "user", "password_env", "connect_timeout",
        "sslmode", "schema", "consistent_snapshot", "datasets",
    })
    connection = {
        name: _string(sql.get(name), f"sql.{name}")
        for name in ("host", "dbname", "user")
    }
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
    datasets = sql.get("datasets")
    _dataset_names(datasets, "sql.datasets")
    validated = {}
    for name, definition in datasets.items():
        label = f"sql.datasets.{name}"
        if not isinstance(definition, dict) or set(definition) - {
            "schema", "relation", "filters", "order_by",
        }:
            raise ConfigurationError(f"Invalid {label} settings.")
        filters = definition.get("filters", {})
        if not isinstance(filters, dict):
            raise ConfigurationError(f"{label}.filters must be a table.")
        for column, value in filters.items():
            _string(column, f"{label}.filters column")
            if isinstance(value, (dict, list)):
                raise ConfigurationError(f"{label}.filters values must be scalar values.")
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
    settings.update(connection=connection, password_env=password_env,
                    consistent_snapshot=snapshot, sql_datasets=validated)
    return settings

from pathlib import Path
from types import MappingProxyType
import tomllib

from ..application import ConfigurationError
from ..application.input_filters import read_filter_columns
from .mapping_settings import CSVMappingProfile, SCHEMAS


def load_csv_mapping(path: str | Path) -> dict[str, CSVMappingProfile]:
    return load_mapping(path, source="csv")


def load_mapping(
    path: str | Path, *, source: str,
) -> dict[str, CSVMappingProfile]:
    if source not in ("csv", "sql"):
        raise ConfigurationError("Mapping source must be 'csv' or 'sql'.")

    mapping_path = Path(path)
    label = source.upper()
    try:
        with mapping_path.open("rb") as file:
            document = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(
            f"Cannot load {label} mappings from {mapping_path}: {error}"
        ) from error

    if set(document) - {source}:
        raise ConfigurationError(f"Only the '{source}' section is allowed.")

    definitions = document.get(source)
    if not isinstance(definitions, dict) or not definitions:
        raise ConfigurationError(f"'{source}' must contain at least one profile.")

    allowed = {"columns", "filter_columns", "branch_kind"}
    if source == "sql":
        allowed |= {"schema", "relation", "filters", "order_by"}

    profiles = {}
    for name, definition in definitions.items():
        if source == "sql" and name == "shifting_summary":
            # Aggregate queries have a dedicated mapping, validated by input_config.
            continue
        if name not in SCHEMAS:
            raise ConfigurationError(f"Unknown {label} profile: {name!r}.")
        if not isinstance(definition, dict) or set(definition) - allowed:
            raise ConfigurationError(f"Invalid {source}.{name} settings.")

        columns = definition.get("columns", {})
        if not isinstance(columns, dict):
            raise ConfigurationError(f"{source}.{name}.columns must be a table.")

        schema = SCHEMAS[name]
        unknown_fields = set(columns) - set(schema.fields)
        if unknown_fields:
            raise ConfigurationError(
                f"Unknown fields in {source}.{name}.columns: "
                + ", ".join(sorted(unknown_fields))
            )

        sources = {}
        for field in schema.fields:
            column = columns.get(field, field)
            if not isinstance(column, str) or not column.strip():
                raise ConfigurationError(
                    f"{source}.{name}.columns.{field} must be a non-empty string."
                )

            normalized = column.strip().casefold()
            if normalized in sources:
                raise ConfigurationError(
                    f"{source}.{name}: {sources[normalized]} and {field} "
                    f"both map to {label} column {column!r}."
                )
            sources[normalized] = field

        branch_kind = definition.get("branch_kind", "id")
        if branch_kind not in ("id", "code"):
            raise ConfigurationError(f"{source}.{name}.branch_kind must be 'id' or 'code'.")
        if branch_kind == "code" and name not in {"existing_containers", "inbound_containers", "equipment_history"}:
            raise ConfigurationError(f"{source}.{name}: branch codes are supported for containers and equipment history only.")
        if branch_kind == "code" and definition.get("filter_columns"):
            raise ConfigurationError(f"{source}.{name}: branch codes are scoped through terminal_branches.")
        profiles[name] = CSVMappingProfile(
            name=name,
            branch_kind=branch_kind,
            schema=schema,
            columns=MappingProxyType(dict(columns)),
            filter_columns=MappingProxyType(read_filter_columns(
                definition.get("filter_columns", {}), f"{source}.{name}.filter_columns",
            )),
        )

    return profiles

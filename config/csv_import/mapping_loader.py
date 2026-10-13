from pathlib import Path
from types import MappingProxyType
import tomllib

from ..application import ConfigurationError
from .mapping_settings import CSVMappingProfile, SCHEMAS


def load_csv_mapping(path: str | Path) -> dict[str, CSVMappingProfile]:
    mapping_path = Path(path)
    try:
        with mapping_path.open("rb") as file:
            document = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(
            f"Cannot load CSV mappings from {mapping_path}: {error}"
        ) from error

    if set(document) - {"csv"}:
        raise ConfigurationError("Only the 'csv' section is allowed.")

    definitions = document.get("csv")
    if not isinstance(definitions, dict) or not definitions:
        raise ConfigurationError("'csv' must contain at least one profile.")

    profiles = {}
    for name, definition in definitions.items():
        if name not in SCHEMAS:
            raise ConfigurationError(f"Unknown CSV profile: {name!r}.")
        if not isinstance(definition, dict) or set(definition) - {"columns"}:
            raise ConfigurationError(
                f"csv.{name} must contain only a 'columns' table."
            )

        columns = definition.get("columns", {})
        if not isinstance(columns, dict):
            raise ConfigurationError(f"csv.{name}.columns must be a table.")

        schema = SCHEMAS[name]
        unknown_fields = set(columns) - set(schema.fields)
        if unknown_fields:
            raise ConfigurationError(
                f"Unknown fields in csv.{name}.columns: "
                + ", ".join(sorted(unknown_fields))
            )

        sources = {}
        for field in schema.fields:
            source = columns.get(field, field)
            if not isinstance(source, str) or not source.strip():
                raise ConfigurationError(
                    f"csv.{name}.columns.{field} must be a non-empty string."
                )

            normalized = source.strip().casefold()
            if normalized in sources:
                raise ConfigurationError(
                    f"csv.{name}: {sources[normalized]} and {field} "
                    f"both map to CSV header {source!r}."
                )
            sources[normalized] = field

        profiles[name] = CSVMappingProfile(
            name=name,
            schema=schema,
            columns=MappingProxyType(dict(columns)),
        )

    return profiles

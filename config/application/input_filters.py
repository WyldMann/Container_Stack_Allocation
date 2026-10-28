"""Shared optional filters and their source-column mappings."""

from .config_loader import ConfigurationError


FILTER_NAMES = {"terminal_id", "branch_id"}


def active_filters(filters, label="filters"):
    """Blank and omitted values disable filters; zero and false remain active."""
    if not isinstance(filters, dict):
        raise ConfigurationError(f"{label} must be a table.")
    result = {}
    for column, value in filters.items():
        if not isinstance(column, str) or not column.strip():
            raise ConfigurationError(f"{label} column must be a non-empty string.")
        if isinstance(value, (dict, list)):
            raise ConfigurationError(f"{label} values must be scalar values.")
        if value is None or isinstance(value, str) and not value.strip():
            continue
        result[column] = value
    return result


def read_filter_columns(columns, label):
    if not isinstance(columns, dict) or set(columns) - FILTER_NAMES:
        raise ConfigurationError(f"{label} must map terminal_id or branch_id to source columns.")
    for column in columns.values():
        if not isinstance(column, str) or not column.strip():
            raise ConfigurationError(f"{label} source columns must be non-empty strings.")
    names = [column.strip().casefold() for column in columns.values()]
    if len(names) != len(set(names)):
        raise ConfigurationError(f"{label} must use a different source column for each filter.")
    return dict(columns)


def mapped_filters(values, columns):
    return {columns[name]: value for name, value in values.items() if name in columns}

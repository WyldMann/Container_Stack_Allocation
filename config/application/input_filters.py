"""Shared optional filters and their source-column mappings."""

from .config_loader import ConfigurationError


FILTER_NAMES = {"branch_code"}
# Source files may store numeric IDs, resolved internally from terminal_branches.
SOURCE_FILTER_NAMES = FILTER_NAMES | {"terminal_id", "branch_id"}


def input_filters(filters):
    """Normalize the branch selection; source-level filters remain scalar."""
    result = {}
    for name, value in filters.items():
        if isinstance(value, list):
            if not value or any(not isinstance(code, str) or not code.strip() for code in value):
                raise ConfigurationError(f"input.filters.{name} must be a non-empty array of non-empty strings.")
            codes = [code.strip().upper() for code in value]
            if len(codes) != len(set(codes)):
                raise ConfigurationError(f"input.filters.{name} must not contain duplicate branch codes.")
            result[name] = codes
        elif isinstance(value, str):
            if value.strip():
                result[name] = value.strip().upper()
        else:
            raise ConfigurationError(f"input.filters.{name} must be a string or an array of strings.")
    return result


def branch_input_settings(settings):
    """Yield independent single-branch settings in configured order."""
    filters = settings.get("filters", {})
    codes = filters.get("branch_code")
    if not isinstance(codes, list):
        codes = [codes]
    for code in codes:
        scoped_filters = dict(filters)
        if code is not None:
            scoped_filters["branch_code"] = code
        yield {**settings, "filters": scoped_filters}


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
    if not isinstance(columns, dict) or set(columns) - SOURCE_FILTER_NAMES:
        raise ConfigurationError(f"{label} must map branch_code, terminal_id or branch_id to source columns.")
    for column in columns.values():
        if not isinstance(column, str) or not column.strip():
            raise ConfigurationError(f"{label} source columns must be non-empty strings.")
    names = [column.strip().casefold() for column in columns.values()]
    if len(names) != len(set(names)):
        raise ConfigurationError(f"{label} must use a different source column for each filter.")
    return dict(columns)


def mapped_filters(values, columns):
    return {columns[name]: value for name, value in values.items() if name in columns}

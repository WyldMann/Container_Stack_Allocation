"""Validate shared operations settings and the reporting SQL mapping."""

from .config_loader import ConfigurationError, _read_section


def shifting_settings(document, *, sql_required=False):
    section = _read_section(document, "shifting", {
        "block_mapping_file", "period_granularity", "timezone", "activities",
    })
    if section.get("period_granularity", "daily") not in ("daily", "weekly"):
        raise ConfigurationError("shifting.period_granularity must be 'daily' or 'weekly'.")
    if section.get("timezone", "Asia/Jakarta") != "Asia/Jakarta":
        raise ConfigurationError("shifting.timezone must be 'Asia/Jakarta' (WIB).")
    activities = _read_section(section, "activities", {"lifting", "shifting"})
    result = {}
    for kind in ("lifting", "shifting"):
        values = activities.get(kind)
        if values is None and not sql_required:
            continue
        if (not isinstance(values, list) or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
                or len(set(values)) != len(values)):
            raise ConfigurationError(f"shifting.activities.{kind} must be a non-empty list of unique activity names.")
        result[kind] = tuple(values)
    if set(result.get("lifting", ())) & set(result.get("shifting", ())):
        raise ConfigurationError("Lifting and shifting activity lists must not overlap.")
    return section, result


def sql_shifting_settings(definition):
    label = "sql.shifting_summary"
    if not isinstance(definition, dict):
        raise ConfigurationError(f"{label} mapping is required for SQL operations.")
    allowed = {"schema", "detail_relation", "header_relation", "datetime_format",
               "detail_columns", "header_columns"}
    unknown = set(definition) - allowed
    if unknown:
        raise ConfigurationError(f"Unknown {label} options: {sorted(unknown)}")
    result = {}
    for name in ("schema", "detail_relation", "header_relation", "datetime_format"):
        value = definition.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{label}.{name} must be a non-empty string.")
        result[name] = value
    for group, required in (
        ("detail_columns", {"operation_id", "document_id", "activity", "activity_time"}),
        ("header_columns", {"document_id", "branch_code", "equipment_code"}),
    ):
        columns = definition.get(group)
        if not isinstance(columns, dict) or set(columns) != required:
            raise ConfigurationError(f"{label}.{group} must define exactly {sorted(required)}.")
        if any(not isinstance(value, str) or not value.strip() for value in columns.values()):
            raise ConfigurationError(f"{label}.{group} column names must be non-empty strings.")
        if len({value.strip().casefold() for value in columns.values()}) != len(columns):
            raise ConfigurationError(f"{label}.{group} column names must be distinct.")
        result[group] = dict(columns)
    return result

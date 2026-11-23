"""Load explicit CSV operation exclusions without changing source exports."""

from datetime import datetime

from config import ConfigurationError
from config.application.config_loader import _read_document

from .shifting_dates import WIB


def operation_key(branch_code, document_id, detail_id, equipment_code, activity, timestamp):
    """Match an operation by content, independently of CSV row order."""
    return (branch_code.strip().upper(), document_id.strip(), detail_id.strip(),
            equipment_code.strip().casefold(), activity.strip().upper(), timestamp)


def load_operations_blacklist(path):
    """Return normalized identities and reasons; reject invalid or duplicate rules."""
    if path is None:
        return {}
    document = _read_document(path)
    if set(document) != {"operations"} or not isinstance(document["operations"], list):
        raise ConfigurationError(f"{path}: define an operations array using [[operations]].")
    fields = {"branch_code", "document_id", "detail_id", "equipment_code",
              "activity", "activity_time", "reason"}
    result = {}
    for index, entry in enumerate(document["operations"], 1):
        label = f"{path}: operations[{index}]"
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ConfigurationError(f"{label} must define exactly {sorted(fields)}.")
        for field in fields:
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ConfigurationError(f"{label}.{field} must be a non-empty string.")
        try:
            timestamp = int(datetime.strptime(
                entry["activity_time"].strip().replace("/", "-"), "%d-%m-%Y %H:%M",
            ).replace(tzinfo=WIB).timestamp())
        except ValueError as error:
            raise ConfigurationError(
                f"{label}.activity_time must be DD-MM-YYYY HH:MM or DD/MM/YYYY HH:MM in WIB."
            ) from error
        key = operation_key(entry["branch_code"], entry["document_id"], entry["detail_id"],
                            entry["equipment_code"], entry["activity"], timestamp)
        if key in result:
            raise ConfigurationError(f"{label}: duplicate blacklisted operation.")
        result[key] = entry["reason"].strip()
    return result

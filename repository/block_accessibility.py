"""Validate and serialize block border access and stacking-start preferences."""

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Literal

from config.application.heuristic_settings import StackingStartPreference
from config.csv_import.mapping_settings import BLOCK_ACCESSIBILITY_SCHEMA
from entities.feasibility.equipment_access import BlockBorderAccessPolicy
from utils import strGeneralize

SIDES = BLOCK_ACCESSIBILITY_SCHEMA.required[1:]
HEADERS = tuple(field.upper() for field in BLOCK_ACCESSIBILITY_SCHEMA.required)
STACKING_START_HEADERS = tuple(field.upper() for field in BLOCK_ACCESSIBILITY_SCHEMA.optional)


@dataclass(frozen=True)
class BlockSettings:
    border_access: BlockBorderAccessPolicy
    # A missing value lets legacy TOML supply the override. Inherit explicitly clears it.
    stacking_start: StackingStartPreference | Literal["inherit"] | None = None


def block_settings(records):
    settings = {}
    for row in records:
        block_id = strGeneralize(str(row.get("block_id", "")).strip())
        if not block_id:
            raise ValueError("Block accessibility requires a block ID.")
        if block_id in settings:
            raise ValueError(f"Duplicate block accessibility for block {block_id}.")
        values = {}
        for side in SIDES:
            value = row.get(side)
            if type(value) is bool:
                values[side] = value
            elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
                values[side] = value.strip().lower() == "true"
            else:
                raise ValueError(f"Block {block_id}: {side.upper()} must be TRUE or FALSE.")
        axis, position, half_distance, enabled_text = (
            "" if row.get(field) is None else str(row[field]).strip()
            for field in BLOCK_ACCESSIBILITY_SCHEMA.optional
        )
        try:
            enabled_value = enabled_text.lower()
            if enabled_value not in ("", "true", "false"):
                raise ValueError("STACKING_START_ENABLED must be TRUE or FALSE.")
            enabled = enabled_value == "true"
            if axis.lower() in ("", "inherit") and not position and not half_distance and not enabled:
                preference = "inherit" if axis or enabled_text else None
            else:
                preference = StackingStartPreference(
                    axis.lower(), int(position) if position else None,
                    float(half_distance) if half_distance else None,
                    enabled=enabled,
                )
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"Block {block_id}: invalid stacking start ({error}).") from error
        settings[block_id] = BlockSettings(BlockBorderAccessPolicy(**values), preference)
    return settings


def access_policies(records):
    return {block_id: settings.border_access for block_id, settings in block_settings(records).items()}


def stacking_start_overrides(settings, legacy=None):
    overrides = dict(legacy or {})
    for block_id, block in settings.items():
        if block.stacking_start == "inherit":
            overrides.pop(block_id, None)
        elif block.stacking_start is not None:
            overrides[block_id] = block.stacking_start
    return overrides


def policies_csv(policies):
    return block_settings_csv({block_id: BlockSettings(policy) for block_id, policy in policies.items()})


def block_settings_csv(settings):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    include_start = any(block.stacking_start is not None for block in settings.values())
    writer.writerow(HEADERS + (STACKING_START_HEADERS if include_start else ()))
    for block_id, block in sorted(settings.items()):
        row = [block_id, *(str(getattr(block.border_access, side)).upper() for side in SIDES)]
        if include_start:
            preference = block.stacking_start
            if isinstance(preference, StackingStartPreference):
                row.extend((preference.axis, preference.position, preference.half_distance, str(preference.enabled).upper()))
            else:
                row.extend((preference, None, None, None))
        writer.writerow(row)
    return stream.getvalue()


def read_policies(text):
    return {block_id: settings.border_access for block_id, settings in read_block_settings(text).items()}


def read_block_settings(text):
    if not isinstance(text, str):
        raise ValueError("Block accessibility must be CSV text.")
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    headers = reader.fieldnames or []
    if (len(set(headers)) != len(headers) or not set(HEADERS) <= set(headers)
            or set(headers) - set(HEADERS + STACKING_START_HEADERS)):
        raise ValueError("Block accessibility CSV requires BLOCK_ID,ABOVE,BELOW,LEFT,RIGHT headers.")
    records = []
    for row in reader:
        if None in row or None in row.values():
            raise ValueError("Block accessibility CSV rows must have as many values as headers.")
        records.append({key.lower(): value for key, value in row.items()})
    return block_settings(records)

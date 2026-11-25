"""Validate and serialize block border access policies."""

import csv
from dataclasses import asdict
from io import StringIO

from entities.feasibility.equipment_access import BlockBorderAccessPolicy
from utils import strGeneralize

SIDES = ("above", "below", "left", "right")
HEADERS = ("BLOCK_ID", *(side.upper() for side in SIDES))


def access_policies(records):
    policies = {}
    for row in records:
        block_id = strGeneralize(str(row.get("block_id", "")).strip())
        if not block_id:
            raise ValueError("Block accessibility requires a block ID.")
        if block_id in policies:
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
        policies[block_id] = BlockBorderAccessPolicy(**values)
    return policies


def policies_csv(policies):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    for block_id, policy in sorted(policies.items()):
        writer.writerow([block_id, *(str(value).upper() for value in asdict(policy).values())])
    return stream.getvalue()


def read_policies(text):
    if not isinstance(text, str):
        raise ValueError("Block accessibility must be CSV text.")
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames != list(HEADERS):
        raise ValueError("Block accessibility CSV requires BLOCK_ID,ABOVE,BELOW,LEFT,RIGHT headers.")
    records = []
    for row in reader:
        if None in row:
            raise ValueError("Block accessibility CSV has more values than headers.")
        records.append({key.lower(): value for key, value in row.items()})
    return access_policies(records)

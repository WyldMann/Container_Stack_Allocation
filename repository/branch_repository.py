"""Resolve source branch codes to the IDs used by yard coordinates."""

import re

from config import ConfigurationError
from .repository import Repository
from .loader import InputError


class BranchRepository(Repository):
    def read_records(self):
        # Preserve the display name; ordinary yard records normalize text to uppercase.
        return [{key: value.strip() for key, value in row.items()}
                for _, row in self._iter_rows()]


class BranchDirectory:
    def __init__(self, records):
        if not records:
            raise InputError("terminal_branches: no branches match the configured filters.")
        self.records = records
        self.by_code = {}
        self.by_id = {}
        for row in records:
            if any(not value for value in row.values()):
                raise InputError("terminal_branches: branch IDs, code and name must be non-empty.")
            code = row["branch_code"].upper()
            branch_id = row["branch_id"]
            if code in self.by_code or branch_id in self.by_id:
                raise InputError(
                    "terminal_branches: ambiguous branch code or ID; narrow terminal_id/branch_id filters."
                )
            self.by_code[code] = row
            self.by_id[branch_id] = row

    @property
    def codes_by_id(self):
        return {key: row["branch_code"] for key, row in self.by_id.items()}

    def cy_name(self):
        if len(self.records) != 1:
            raise ConfigurationError(
                "Shifting reports require exactly one branch; set terminal_id/branch_id filters."
            )
        name = self.records[0]["branch_name"]
        match = re.match(r"CY\s*(\d+)\b", name, re.IGNORECASE)
        if not match:
            raise ConfigurationError(f"Cannot derive a CY report key from BRANCH_NAME {name!r}.")
        return "CY" + match.group(1)

    def normalize_containers(self, records, *, scoped=False):
        result = []
        for row in records:
            code = row["branch_id"].strip().upper()
            # Inbound records may have no coordinates until assigned to the yard.
            if not code:
                result.append(row)
                continue
            branch = self.by_code.get(code)
            if branch is None:
                if scoped:
                    continue
                raise InputError(f"Container {row['container_id']}: unknown BRANCH code {code!r}.")
            result.append(row | {"branch_id": branch["branch_id"]})
        return result

"""Resolve report labels using explicit initial-block assignments."""

from ..application.config_loader import ConfigurationError, _read_document


def load_shifting_block_mapping(path, cy_name, branch_code=None):
    document = _read_document(path)
    branch_sections = [
        value for name, value in document.items()
        if branch_code is not None and name.strip().upper() == branch_code.strip().upper()
    ]
    selected = branch_sections or [
        value for name, value in document.items()
        if name.upper() == cy_name.upper()
    ]
    if len(selected) != 1:
        raise ConfigurationError(
            f"{path}: expected exactly one mapping section for CY {cy_name!r}"
            f" (branch_code {branch_code!r})."
        )
    definitions = selected[0]
    if not isinstance(definitions, dict) or not definitions:
        raise ConfigurationError(
            f"{path}: fill in shifting-code to block_code assignments for {cy_name!r}."
        )

    mapping = {}
    for code, block_code in definitions.items():
        key = code.strip().casefold()
        if not key or key in mapping:
            raise ConfigurationError(f"{path}: blank or ambiguous shifting code {code!r}.")
        if not isinstance(block_code, str) or not block_code.strip():
            raise ConfigurationError(
                f"{path}: {code!r} must map to one non-empty block_code string."
            )
        mapping[key] = block_code.strip()
    return mapping

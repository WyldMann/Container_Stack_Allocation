"""Resolve report labels using explicit initial-block assignments."""

from ..application.config_loader import ConfigurationError, _read_document


def load_shifting_block_mapping(path, cy_name):
    document = _read_document(path)
    selected = [
        value for name, value in document.items()
        if name.upper() == cy_name.upper()
    ]
    if len(selected) != 1:
        raise ConfigurationError(
            f"{path}: expected exactly one mapping section for CY {cy_name!r}."
        )
    definitions = selected[0]
    if not isinstance(definitions, dict) or not definitions:
        raise ConfigurationError(
            f"{path}: fill in shifting-code to block_id assignments for {cy_name!r}."
        )

    mapping = {}
    for code, block_id in definitions.items():
        key = code.strip().casefold()
        if not key or key in mapping:
            raise ConfigurationError(f"{path}: blank or ambiguous shifting code {code!r}.")
        if not isinstance(block_id, str) or not block_id.strip():
            raise ConfigurationError(
                f"{path}: {code!r} must map to one non-empty block_id string."
            )
        mapping[key] = block_id.strip()
    return mapping

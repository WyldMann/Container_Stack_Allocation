from dataclasses import fields
from pathlib import Path
import tomllib

from .feasibility_settings import FeasibilitySettings
from .application_settings import ApplicationSettings
from .heuristic_settings import HeuristicSettings, StackingStartPreference


class ConfigurationError(ValueError):
    """The configuration file contains invalid settings."""


_FEASIBILITY_ALIASES = {
    "loader_access": "equipment_access",
    "loader_access_mode": "equipment_access_mode",
    "loader_destination_access_mode": "destination_access_mode",
    "preserve_occupied_loader_access_mode": "preserve_occupied_access_mode",
    "preserve_future_loader_access": "preserve_future_access",
    "preserve_future_loader_access_mode": "preserve_future_access_mode",
    "ignore_full_stacks_for_loader_access": "ignore_stacks_without_legal_next_tier",
}
_HEURISTIC_ALIASES = {
    "loader_inaccessible_destination_multiplier": "unreachable_destination_multiplier",
    "loader_occupied_access_loss_weight": "occupied_access_loss_weight",
    "loader_future_access_loss_weight": "future_access_loss_weight",
}


def _read_document(path: str | Path) -> dict:
    config_path = Path(path)

    try:
        with config_path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(
            f"Invalid TOML in {config_path}: {error}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Cannot read configuration file {config_path}: {error}"
        ) from error

def _read_section(
    document: dict, name: str, allowed_options: set[str], aliases: dict[str, str] | None = None,
) -> dict:
    section = document.get(name, {})
    if not isinstance(section, dict):
        raise ConfigurationError(f"'{name}' must be a TOML table.")

    aliases = aliases or {}
    unknown_options = set(section) - allowed_options - aliases.keys()
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ConfigurationError(f"Unknown {name} options: {names}")
    for previous, option in aliases.items():
        if previous in section and option in section:
            raise ConfigurationError(f"Set either {name}.{previous} or {name}.{option}.")
    return {aliases.get(key, key): value for key, value in section.items()}


def _parse_feasibility(document: dict) -> FeasibilitySettings:
    section = _read_section(
        document, "feasibility", {field.name for field in fields(FeasibilitySettings)}, _FEASIBILITY_ALIASES,
    )

    for name in ("stacking_safety", "equipment_access", "preserve_future_access"):
        if name in section and name + "_mode" in section:
            raise ConfigurationError(
                f"Set either feasibility.{name} or feasibility.{name}_mode."
            )
    try:
        return FeasibilitySettings(**section)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"Invalid feasibility settings: {error}") from error


def _parse_heuristic(document: dict) -> HeuristicSettings:
    section = _read_section(
        document, "heuristic", {field.name for field in fields(HeuristicSettings)}, _HEURISTIC_ALIASES,
    )
    try:
        return HeuristicSettings(**section)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"Invalid heuristic settings: {error}") from error


def load_config(path: str | Path) -> ApplicationSettings:
    return parse_config(_read_document(path))


def _parse_stacking_start_by_block(document: dict) -> dict[str, dict[str, StackingStartPreference]]:
    section = document.get("stacking_start_by_block", {})
    if not isinstance(section, dict):
        raise ConfigurationError("'stacking_start_by_block' must be a table of branches.")
    preferences = {}
    for branch, blocks in section.items():
        if not isinstance(branch, str) or not branch.strip() or not isinstance(blocks, dict):
            raise ConfigurationError("Each stacking start branch must have a name and a table of blocks.")
        code = branch.strip().upper()
        if code in preferences:
            raise ConfigurationError(f"Duplicate stacking start branch: {code}.")
        preferences[code] = {}
        for block_id, settings in blocks.items():
            if not isinstance(block_id, str) or not block_id.strip() or not isinstance(settings, dict):
                raise ConfigurationError(f"Each stacking start block in {code} must have an ID and settings.")
            try:
                preferences[code][block_id] = StackingStartPreference(**settings)
            except (TypeError, ValueError, OverflowError) as error:
                raise ConfigurationError(f"Invalid stacking start for block {block_id} in {code}: {error}") from error
    return {branch: blocks for branch, blocks in preferences.items() if blocks}


def parse_config(document: dict) -> ApplicationSettings:
    """Validate settings from TOML or an interface using the same rules."""
    if not isinstance(document, dict):
        raise ConfigurationError("Stacking configuration must be a table.")
    unknown = set(document) - {"feasibility", "heuristic", "stacking_start_by_block"}
    if unknown:
        raise ConfigurationError(f"Unknown stacking configuration sections: {sorted(unknown)}")
    return ApplicationSettings(
        feasibility=_parse_feasibility(document),
        heuristic=_parse_heuristic(document),
        stacking_start_by_block=_parse_stacking_start_by_block(document),
    )


def load_feasibility_settings(path: str | Path) -> FeasibilitySettings:
    return _parse_feasibility(_read_document(path))


def load_heuristic_settings(path: str | Path) -> HeuristicSettings:
    return _parse_heuristic(_read_document(path))

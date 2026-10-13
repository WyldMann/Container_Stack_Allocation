from dataclasses import fields
from pathlib import Path
import tomllib

from .feasibility_settings import FeasibilitySettings
from .application_settings import ApplicationSettings
from .heuristic_settings import HeuristicSettings


class ConfigurationError(ValueError):
    """The configuration file contains invalid settings."""


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

def _read_section(document: dict, name: str, allowed_options: set[str]) -> dict:
    section = document.get(name, {})
    if not isinstance(section, dict):
        raise ConfigurationError(f"'{name}' must be a TOML table.")

    unknown_options = set(section) - allowed_options
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ConfigurationError(f"Unknown {name} options: {names}")
    return section


def _parse_feasibility(document: dict) -> FeasibilitySettings:
    section = _read_section(
        document, "feasibility", {"stacking_safety", "loader_access"}
    )

    for name, value in section.items():
        if type(value) is not bool:
            raise ConfigurationError(
                f"feasibility.{name} must be true or false."
            )

    return FeasibilitySettings(**section)


def _parse_heuristic(document: dict) -> HeuristicSettings:
    section = _read_section(
        document, "heuristic", {field.name for field in fields(HeuristicSettings)}
    )
    try:
        return HeuristicSettings(**section)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"Invalid heuristic settings: {error}") from error


def load_config(path: str | Path) -> ApplicationSettings:
    document = _read_document(path)
    return ApplicationSettings(
        feasibility=_parse_feasibility(document),
        heuristic=_parse_heuristic(document),
    )


def load_feasibility_settings(path: str | Path) -> FeasibilitySettings:
    return _parse_feasibility(_read_document(path))


def load_heuristic_settings(path: str | Path) -> HeuristicSettings:
    return _parse_heuristic(_read_document(path))

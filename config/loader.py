from pathlib import Path
import tomllib

from .feasibility_settings import FeasibilitySettings


class ConfigurationError(ValueError):
    """The configuration file contains invalid settings."""


def load_feasibility_settings(path: str | Path) -> FeasibilitySettings:
    config_path = Path(path)

    try:
        with config_path.open("rb") as file:
            document = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(
            f"Invalid TOML in {config_path}: {error}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Cannot read configuration file {config_path}: {error}"
        ) from error

    section = document.get("feasibility", {})
    if not isinstance(section, dict):
        raise ConfigurationError("'feasibility' must be a TOML table.")

    allowed_options = {"stacking_safety", "loader_access"}
    unknown_options = set(section) - allowed_options
    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ConfigurationError(f"Unknown feasibility options: {names}")

    for name, value in section.items():
        if type(value) is not bool:
            raise ConfigurationError(
                f"feasibility.{name} must be true or false."
            )

    return FeasibilitySettings(**section)

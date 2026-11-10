"""Configuration and CSV sources for offline stacking drafts."""

from dataclasses import asdict
import csv
import io
import json
import math
from pathlib import Path
import tomllib

from config import DEFAULT_CONFIG_FILE, DEFAULT_CSV_MAPPING_FILE, DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.config_loader import ConfigurationError, parse_config
from config.application.input_config import parse_input_config
from config.csv_import.mapping_loader import parse_mapping
from config.csv_import.mapping_settings import SCHEMAS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOML_FILES = {
    "config_toml": DEFAULT_CONFIG_FILE,
    "input_toml": DEFAULT_STACKING_INPUT_CONFIG_FILE,
    "mapping_toml": DEFAULT_CSV_MAPPING_FILE,
}


def read_toml(text, label):
    if not isinstance(text, str):
        raise ConfigurationError(f"{label} must be TOML text.")
    try:
        return tomllib.loads(text.lstrip("\ufeff"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"{label}: {error}") from error


def dump_toml(document):
    """Serialize this application's scalar/list/table configuration subset."""
    def scalar(value):
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if type(value) is bool:
            return "true" if value else "false"
        if type(value) in (int, float) and math.isfinite(value):
            return str(value)
        if isinstance(value, list):
            return "[" + ", ".join(scalar(item) for item in value) + "]"
        raise ConfigurationError(f"Unsupported TOML value: {type(value).__name__}.")

    lines = []

    def table(values, path):
        if path:
            lines.append("[" + ".".join(json.dumps(key) for key in path) + "]")
        for key, value in values.items():
            if not isinstance(value, dict):
                lines.append(f"{json.dumps(key)} = {scalar(value)}")
        lines.append("")
        for key, value in values.items():
            if isinstance(value, dict):
                table(value, (*path, key))

    table(document, ())
    return "\n".join(lines).strip() + "\n"


def portable_input(document):
    """Require CSV sources and bind each dataset to its portable filename."""
    if set(document) - {"input", "csv", "sql", "output"}:
        raise ConfigurationError("Use a container-stacking input TOML, without shifting settings.")
    section = document.get("input", {})
    if not isinstance(section, dict) or set(section) - {"sources", "filters"}:
        raise ConfigurationError("input must be a table with optional sources and filters.")
    sources = section.get("sources", dict.fromkeys(SCHEMAS, "csv"))
    if not isinstance(sources, dict) or set(sources) != set(SCHEMAS):
        raise ConfigurationError("input.sources must name all nine stacking datasets.")
    if any(source != "csv" for source in sources.values()):
        raise ConfigurationError("This import interface accepts CSV sources only.")
    return {
        "input": {**section, "sources": sources},
        "csv": {"mapping_file": "csv_mapping.toml",
                "files": {name: f"{name}.csv" for name in SCHEMAS}},
        "output": {"containers_file": "result.csv"},
    }


def configuration(payload):
    def document(key, label, default_path):
        text = payload.get(key)
        if text is None:
            text = default_path.read_text(encoding="utf-8")
        return read_toml(text, label)

    settings = parse_config(document("config_toml", "Stacking settings", DEFAULT_CONFIG_FILE))
    mapping = document("mapping_toml", "CSV mapping", DEFAULT_CSV_MAPPING_FILE)
    profiles = parse_mapping(mapping)
    if set(profiles) != set(SCHEMAS):
        raise ConfigurationError("CSV mapping must define all nine stacking datasets.")
    input_document = document("input_toml", "Stacking inputs", DEFAULT_STACKING_INPUT_CONFIG_FILE)
    if payload.get("branch_codes") is not None:
        section = input_document.get("input")
        if not isinstance(section, dict) or not isinstance(section.get("filters", {}), dict):
            raise ConfigurationError("input and input.filters must be TOML tables.")
        section.setdefault("filters", {})["branch_code"] = payload["branch_codes"]
    # Older drafts contain the selected files and have no explicit source mode.
    source = payload.get("file_source", "upload")
    if source not in ("folder", "upload"):
        raise ConfigurationError("file_source must be 'folder' or 'upload'.")
    portable = portable_input(input_document)
    inputs = portable
    if source == "folder":
        inputs = {key: value for key, value in input_document.items() if key != "sql"}
        inputs["input"] = portable["input"]
    return settings, mapping, profiles, inputs


def empty_csv_templates(profiles):
    empty_csv = {}
    for name, profile in profiles.items():
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerow(list(dict.fromkeys([
            *(profile.columns.get(field, field) for field in profile.schema.fields),
            *profile.filter_columns.values(),
        ])))
        empty_csv[name] = buffer.getvalue()
    return empty_csv


def draft_files(payload, profiles, input_document):
    """Read the selected CSV source and fill explicitly empty datasets."""
    selected = payload.get("files", {})
    if not isinstance(selected, dict) or set(selected) - set(profiles):
        raise ConfigurationError("files must contain only known stacking datasets.")
    templates = empty_csv_templates(profiles)
    folder_paths = {}
    if payload.get("file_source") == "folder":
        settings = parse_input_config(input_document, base_dir=DEFAULT_STACKING_INPUT_CONFIG_FILE.parent)
        folder_paths = settings["csv_files"]

    files = {}
    for name in profiles:
        upload = selected.get(name)
        if isinstance(upload, dict) and upload.get("empty") is True:
            files[name] = {"name": name + ".csv", "content": templates[name]}
        elif name in folder_paths:
            path = folder_paths[name]
            display_path = input_document["csv"]["files"][name]
            if not path.is_relative_to(PROJECT_ROOT) or path.suffix.casefold() != ".csv":
                files[name] = {"error": f"Choose a CSV inside the project folder for {name}: {display_path}"}
                continue
            try:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    files[name] = {"name": path.name, "content": stream.read()}
            except FileNotFoundError:
                files[name] = {"error": f"Configured CSV file not found: {display_path}"}
            except (OSError, UnicodeError):
                files[name] = {"error": f"Cannot read the configured UTF-8 CSV: {display_path}"}
        elif name in selected:
            files[name] = upload
    return files


def write_browser_defaults():
    """Refresh the TOML text bundled with the file-based browser page."""
    documents = {key: path.read_text(encoding="utf-8-sig") for key, path in TOML_FILES.items()}
    path = Path(__file__).with_name("static") / "defaults.js"
    script = "// Generated by python -m stacking_ui --refresh-defaults.\n"
    script += "const TOML_DEFAULTS = " + json.dumps(documents, indent=2) + ";\n"
    path.write_text(script, encoding="utf-8")
    return path


def defaults():
    config_text = DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")
    mapping_text = DEFAULT_CSV_MAPPING_FILE.read_text(encoding="utf-8")
    profiles = parse_mapping(read_toml(mapping_text, "CSV mapping"))
    return {
        "version": 1,
        "config_toml": config_text,
        "settings": asdict(parse_config(read_toml(config_text, "Stacking settings"))),
        "mapping_toml": mapping_text,
        "input_toml": dump_toml(portable_input(read_toml(
            DEFAULT_STACKING_INPUT_CONFIG_FILE.read_text(encoding="utf-8"), "Stacking inputs"))),
        "datasets": list(SCHEMAS),
        "empty_csv": empty_csv_templates(profiles),
    }

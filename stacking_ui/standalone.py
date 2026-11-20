"""Build the shareable, browser-only stacking simulator."""

import argparse
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import parse_input_config
from config.csv_import.mapping_loader import parse_mapping
from repository import CSVLoader, Repository
from repository.branch_repository import BranchRepository
from utils import strGeneralize
from repository.block_accessibility import policies_csv

from .configuration import PROJECT_ROOT, TOML_FILES, dump_toml, portable_input, read_project_tomls, read_toml


RUNTIME_VERSION = "0.27.7"
RUNTIME_FILES = {
    "pyodide.js": "text/javascript",
    "pyodide.asm.js": "text/javascript",
    "pyodide.asm.wasm": "application/wasm",
    "pyodide-lock.json": "application/json",
    "python_stdlib.zip": "application/zip",
}
STATIC = Path(__file__).with_name("static")
ENTRY_PAGE = "container-stacking-simulator.html"


def project_snapshot(*, branch_code=None, data_dir=None):
    documents = read_project_tomls()
    input_text = documents["input_toml"]
    inputs = read_toml(input_text, "Stacking inputs")
    portable_input(inputs)  # Validate that every source is CSV.
    inputs.pop("sql", None)
    input_text = re.sub(r"(?ms)^[ \t]*\[sql(?:\.[^\]\n]+)?\][^\n]*\n.*?(?=^[ \t]*\[|\Z)", "", input_text)
    if branch_code is not None:
        inputs.setdefault("input", {}).setdefault("filters", {})["branch_code"] = [branch_code]
    base = DEFAULT_STACKING_INPUT_CONFIG_FILE.parent
    settings = parse_input_config(inputs, base_dir=base)
    files = settings["csv_files"]
    empty_accessibility = {}
    if data_dir is not None:
        directory = Path(data_dir).resolve()
        files = {name: directory / path.name for name, path in files.items()}
    for name, path in files.items():
        if not path.is_relative_to(PROJECT_ROOT) or path.suffix.casefold() != ".csv":
            raise ValueError(f"{name} must be a CSV path inside the project.")
        if not path.is_file():
            if name == "block_accessibility":
                empty_accessibility[path] = policies_csv({})
            else:
                raise FileNotFoundError(f"Missing CSV for {name}: {path}")
        inputs["csv"]["files"][name] = Path(os.path.relpath(path, base)).as_posix()
    # Preserve the editor comments whenever the source already uses portable paths.
    documents["input_toml"] = input_text if read_toml(input_text, "Stacking inputs") == inputs else dump_toml(inputs)

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for package in ("config", "entities", "repository", "stacking_ui", "utils"):
            for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
                archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())
        archive.write(PROJECT_ROOT / "filewriter.py", "filewriter.py")
        for key, path in TOML_FILES.items():
            archive.writestr(path.relative_to(PROJECT_ROOT).as_posix(), documents[key])
        for path in sorted(set(files.values())):
            if path.is_file():
                archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())
            elif path in empty_accessibility:
                archive.writestr(path.relative_to(PROJECT_ROOT).as_posix(), empty_accessibility[path])
    return documents, buffer.getvalue()


def bundled_yard_branches(documents):
    """List branches with yard blocks in the packaged CSVs."""
    inputs = read_toml(documents["input_toml"], "Stacking inputs")
    settings = parse_input_config(inputs, base_dir=DEFAULT_STACKING_INPUT_CONFIG_FILE.parent)
    files = settings["csv_files"]
    profiles = parse_mapping(read_toml(documents["mapping_toml"], "CSV mapping"))
    blocks = Repository(CSVLoader(files["yard_blocks"]), profiles["yard_blocks"])
    branches = BranchRepository(CSVLoader(files["terminal_branches"]), profiles["terminal_branches"])
    yard_ids = {strGeneralize(row["branch_id"].strip()) for _, row in blocks.read_source_records()
                if row["branch_id"].strip()}
    choices = sorted(
        [{"code": row["branch_code"].upper(), "name": row["branch_name"].strip()}
         for row in branches.read_records()
         if row["branch_code"] and strGeneralize(row["branch_id"]) in yard_ids],
        key=lambda branch: branch["code"],
    )
    configured = settings["filters"].get("branch_code", [])
    if isinstance(configured, str):
        configured = [configured]
    available = {branch["code"] for branch in choices}
    default_code = next((code for code in configured if code in available), None)
    return {"branches": choices, "default_code": default_code}


def build(runtime, destination, *, branch_code=None, data_dir=None):
    manifest = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "pyodide" or manifest.get("version") != RUNTIME_VERSION:
        raise ValueError(f"Use the Pyodide {RUNTIME_VERSION} npm package.")
    assets = {
        name: [mime, base64.b64encode((runtime / name).read_bytes()).decode("ascii")]
        for name, mime in RUNTIME_FILES.items()
    }
    licenses = {name: (runtime / name).read_bytes() for name in ("LICENSE", "LICENSE-Python")}
    documents, snapshot = project_snapshot(branch_code=branch_code, data_dir=data_dir)
    yard_branches = bundled_yard_branches(documents)
    assets["project.zip"] = ["application/zip", base64.b64encode(snapshot).decode("ascii")]

    csv_snapshot = BytesIO()
    with ZipFile(BytesIO(snapshot)) as project, ZipFile(csv_snapshot, "w", ZIP_DEFLATED) as csv_archive:
        for name in project.namelist():
            if name.casefold().endswith(".csv"):
                csv_archive.writestr(name, project.read(name))

    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace(
        "script-src 'self' file:; style-src 'self' file:; connect-src 'none';",
        "script-src 'self' file: blob: 'wasm-unsafe-eval'; style-src 'self' file:; "
        "worker-src blob:; connect-src blob:;",
    )
    page = page.replace(
        '<script src="./defaults.js" defer></script>',
        '<script src="./defaults.js" defer></script>\n'
        '  <script src="./runtime-assets.js" defer></script>\n'
        '  <script src="./standalone.js" defer></script>',
    )
    page = page.replace("Use files in the project folder (default)", "Use bundled CSVs (default)")
    page = page.replace("Choose files in the browser", "Replace selected CSVs")

    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr(ENTRY_PAGE, page)
        archive.writestr("bundled-csvs.zip", csv_snapshot.getvalue())
        bundle_id = hashlib.sha256(snapshot).hexdigest()[:16]
        archive.writestr("defaults.js", "const STACKING_BUNDLE_ID = " + json.dumps(bundle_id) + ";\n"
                         "const TOML_DEFAULTS = " + json.dumps(documents) + ";\n"
                         "const STACKING_YARD_BRANCHES = " + json.dumps(yard_branches) + ";\n")
        archive.writestr("runtime-assets.js", "let STACKING_RUNTIME = " + json.dumps(assets) + ";\n")
        for name in ("style.css", "yard-map.css", "yard-map.js", "yard-comparison-map.js",
                     "simulation.js", "placement-graphs.js", "app.js", "standalone.js"):
            archive.write(STATIC / name, name)
        for name, content in licenses.items():
            archive.writestr("licenses/" + name, content)
        archive.writestr("README.txt", f"Extract all files and open {ENTRY_PAGE} in Chrome or Microsoft Edge.\n"
                         "The package includes a copy of the CSVs and TOMLs from build time.\n"
                         "When using bundled CSVs, choose a yard branch from the dropdown.\n"
                         "Set the four loader access switches around each block before starting its branch.\n"
                         "Each block's Save block access settings button enables only for changed borders and saves that block in this browser.\n"
                         "Download bundled CSVs (ZIP) includes the saved block_accessibility.csv and all branches.\n"
                         "Use Replace selected CSVs or Load from TOML to use newer data.\n"
                         "Save settings remembers a TOML in this browser for this page.\n"
                         "Save as TOML and Save yard CSV download files through the browser.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path, help=f"Extracted Pyodide {RUNTIME_VERSION} npm package directory")
    parser.add_argument("output", type=Path, help="Destination ZIP file")
    parser.add_argument("--branch-code", help="Branch filter to bundle instead of the project default")
    parser.add_argument("--data-dir", type=Path, help="Directory containing the stacking CSVs to bundle")
    args = parser.parse_args()
    try:
        build(args.runtime, args.output, branch_code=args.branch_code, data_dir=args.data_dir)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(f"Standalone simulator saved to {args.output}")


if __name__ == "__main__":
    main()

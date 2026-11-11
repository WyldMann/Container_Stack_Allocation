"""Build the shareable, browser-only stacking simulator."""

import argparse
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import parse_input_config

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


def project_snapshot():
    documents = read_project_tomls()
    input_text = documents["input_toml"]
    inputs = read_toml(input_text, "Stacking inputs")
    portable_input(inputs)  # Validate that every source is CSV.
    inputs.pop("sql", None)
    input_text = re.sub(r"(?ms)^[ \t]*\[sql(?:\.[^\]\n]+)?\][^\n]*\n.*?(?=^[ \t]*\[|\Z)", "", input_text)
    base = DEFAULT_STACKING_INPUT_CONFIG_FILE.parent
    settings = parse_input_config(inputs, base_dir=base)
    files = settings["csv_files"]
    for name, path in files.items():
        if not path.is_relative_to(PROJECT_ROOT) or path.suffix.casefold() != ".csv":
            raise ValueError(f"{name} must be a CSV path inside the project.")
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
    return documents, buffer.getvalue()


def build(runtime, destination):
    manifest = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "pyodide" or manifest.get("version") != RUNTIME_VERSION:
        raise ValueError(f"Use the Pyodide {RUNTIME_VERSION} npm package.")
    assets = {
        name: [mime, base64.b64encode((runtime / name).read_bytes()).decode("ascii")]
        for name, mime in RUNTIME_FILES.items()
    }
    licenses = {name: (runtime / name).read_bytes() for name in ("LICENSE", "LICENSE-Python")}
    documents, snapshot = project_snapshot()
    assets["project.zip"] = ["application/zip", base64.b64encode(snapshot).decode("ascii")]

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
        archive.writestr("index.html", page)
        archive.writestr("defaults.js", "const TOML_DEFAULTS = " + json.dumps(documents) + ";\n")
        archive.writestr("runtime-assets.js", "let STACKING_RUNTIME = " + json.dumps(assets) + ";\n")
        for name in ("style.css", "yard-map.css", "yard-map.js", "simulation.js", "app.js", "standalone.js"):
            archive.write(STATIC / name, name)
        for name, content in licenses.items():
            archive.writestr("licenses/" + name, content)
        archive.writestr("README.txt", "Extract all files and open index.html in Chrome or Microsoft Edge.\n"
                         "The package includes a copy of the CSVs and TOMLs from build time.\n"
                         "Use Replace selected CSVs or Load from TOML to use newer data.\n"
                         "Set default remembers a TOML in this browser for this page.\n"
                         "Save as TOML and Save yard CSV download files through the browser.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path, help=f"Extracted Pyodide {RUNTIME_VERSION} npm package directory")
    parser.add_argument("output", type=Path, help="Destination ZIP file")
    args = parser.parse_args()
    try:
        build(args.runtime, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(f"Standalone simulator saved to {args.output}")


if __name__ == "__main__":
    main()

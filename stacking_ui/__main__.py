"""Open the setup page or validate a saved stacking draft."""

import argparse
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import zipfile

from config.application.config_loader import ConfigurationError
from config.application.input_config import parse_input_config

from .configuration import configuration, draft_files, dump_toml, portable_input, write_browser_defaults
from .session import SimulationSession, prepare_draft, preview_document


def open_setup():
    page = Path(__file__).with_name("static") / "index.html"
    runtime = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node"
    node = shutil.which("node")
    if node is None:
        bundled_node = runtime / "bin" / "node.exe"
        if not bundled_node.is_file():
            raise OSError("The setup launcher requires Node.js.")
        node = str(bundled_node)

    env = os.environ.copy()
    modules = runtime / "node_modules"
    if (modules / "playwright-core").is_dir():
        env["NODE_PATH"] = os.pathsep.join(filter(None, (env.get("NODE_PATH"), str(modules))))
    launcher = Path(__file__).with_name("browser.cjs")
    result = subprocess.run([node, launcher, sys.executable, page.as_uri()], env=env, check=False)
    if result.returncode:
        raise OSError("The setup window could not be opened.")


def build_preview(draft):
    return preview_document(prepare_draft(draft))


def serve_simulation():
    session = SimulationSession()
    for line in sys.stdin.buffer:
        print(session.handle_json(line), flush=True)


def export_bundle(payload, path):
    settings, mapping, profiles, inputs = configuration(payload)
    portable = portable_input(inputs)
    validated = parse_input_config(portable, base_dir=path.parent)
    if not validated["filters"].get("branch_code"):
        raise ConfigurationError("Select at least one branch code.")

    files = draft_files(payload, profiles, inputs)
    contents = {
        "config.toml": dump_toml(settings.to_document()),
        "csv_mapping.toml": dump_toml(mapping),
        "container_stacking_input.toml": dump_toml(portable),
    }
    for dataset in portable["input"]["sources"]:
        upload = files.get(dataset)
        if isinstance(upload, dict) and upload.get("error"):
            raise ConfigurationError(upload["error"])
        if not isinstance(upload, dict) or not isinstance(upload.get("content"), str):
            raise ConfigurationError(f"Select a CSV for {dataset} before exporting a bundle.")
        contents[dataset + ".csv"] = upload["content"].lstrip("\ufeff")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path, nargs="?", help="Path to the saved scenario draft JSON.")
    parser.add_argument("--bundle", action="store_true", help="Also export the draft's CSVs and TOML as a ZIP.")
    parser.add_argument("--refresh-defaults", action="store_true", help="Refresh the page's prefilled TOML from the project files.")
    worker = parser.add_mutually_exclusive_group()
    worker.add_argument("--preview-stdin", action="store_true", help=argparse.SUPPRESS)
    worker.add_argument("--simulation-stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        if args.simulation_stdin:
            if args.draft is not None or args.bundle or args.refresh_defaults:
                parser.error("--simulation-stdin runs on its own.")
            serve_simulation()
            return
        if args.preview_stdin:
            if args.draft is not None or args.bundle or args.refresh_defaults:
                parser.error("--preview-stdin runs on its own.")
            preview = build_preview(json.load(sys.stdin.buffer))
            print(json.dumps(preview, allow_nan=False))
            return
        if args.refresh_defaults:
            if args.draft is not None or args.bundle:
                parser.error("--refresh-defaults runs on its own.")
            print(f"Refreshed browser defaults: {write_browser_defaults()}")
            return
        if args.draft is None:
            if args.bundle:
                parser.error("--bundle requires a draft")
            open_setup()
            return
        draft = json.loads(args.draft.read_text(encoding="utf-8-sig"))
        preview = build_preview(draft)
        path = args.draft.with_suffix(".preview.json")
        path.write_text(json.dumps(preview, allow_nan=False, ensure_ascii=False), encoding="utf-8")
        print(f"Preview saved to {path}")
        if args.bundle:
            bundle = args.draft.with_suffix(".zip")
            export_bundle(draft, bundle)
            print(f"Exported CSV and TOML bundle: {bundle}")
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()

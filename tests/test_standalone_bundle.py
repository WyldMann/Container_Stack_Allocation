"""Checks for choosing a standalone snapshot's bundled CSV directory."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import parse_input_config
from stacking_ui.configuration import PROJECT_ROOT, read_toml
from stacking_ui.standalone import project_snapshot


class StandaloneBundleTest(unittest.TestCase):
    def test_data_directory_is_embedded_and_selected(self):
        original = read_toml(DEFAULT_STACKING_INPUT_CONFIG_FILE.read_text(encoding="utf-8"), "input")
        configured = parse_input_config(original, base_dir=DEFAULT_STACKING_INPUT_CONFIG_FILE.parent)["csv_files"]
        with TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            directory = Path(temporary)
            for name, path in configured.items():
                (directory / path.name).write_bytes(f"dataset,{name}\n".encode())

            documents, snapshot = project_snapshot(data_dir=directory, branch_code="JKT64")
            input_document = read_toml(documents["input_toml"], "bundled input")
            self.assertEqual(input_document["input"]["filters"]["branch_code"], ["JKT64"])
            with ZipFile(BytesIO(snapshot)) as archive:
                for name, path in configured.items():
                    relative = (directory / path.name).relative_to(PROJECT_ROOT).as_posix()
                    self.assertEqual(archive.read(relative), f"dataset,{name}\n".encode())
                    self.assertEqual(
                        (DEFAULT_STACKING_INPUT_CONFIG_FILE.parent / input_document["csv"]["files"][name]).resolve(),
                        directory / path.name,
                    )


if __name__ == "__main__":
    unittest.main()

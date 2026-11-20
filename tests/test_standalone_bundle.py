"""Checks for choosing a standalone snapshot's bundled CSV directory."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from config import DEFAULT_STACKING_INPUT_CONFIG_FILE
from config.application.input_config import parse_input_config
from stacking_ui.configuration import PROJECT_ROOT, read_toml
from stacking_ui.standalone import bundled_yard_branches, project_snapshot


class StandaloneBundleTest(unittest.TestCase):
    def test_missing_optional_accessibility_is_bundled_as_empty(self):
        original = read_toml(DEFAULT_STACKING_INPUT_CONFIG_FILE.read_text(encoding="utf-8"), "input")
        configured = parse_input_config(original, base_dir=DEFAULT_STACKING_INPUT_CONFIG_FILE.parent)["csv_files"]
        with TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            directory = Path(temporary)
            for name, path in configured.items():
                if name != "block_accessibility":
                    (directory / path.name).touch()
            _, snapshot = project_snapshot(data_dir=directory)
            with ZipFile(BytesIO(snapshot)) as archive:
                name = (directory / configured["block_accessibility"].name).relative_to(PROJECT_ROOT).as_posix()
                self.assertEqual(archive.read(name).decode(), "BLOCK_ID,ABOVE,BELOW,LEFT,RIGHT\r\n")
            self.assertFalse((directory / configured["block_accessibility"].name).exists())

    def test_yard_branch_choices_require_bundled_blocks(self):
        original = read_toml(DEFAULT_STACKING_INPUT_CONFIG_FILE.read_text(encoding="utf-8"), "input")
        configured = parse_input_config(original, base_dir=DEFAULT_STACKING_INPUT_CONFIG_FILE.parent)["csv_files"]
        with TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            directory = Path(temporary)
            for path in configured.values():
                (directory / path.name).touch()
            (directory / configured["terminal_branches"].name).write_text(
                "BRANCH_ID,TERMINAL_ID,BRANCH_CODE,BRANCH_NAME\n"
                "1,7,Z,Yard Z\n2,7,a,Yard A\n3,7,N,No blocks\n",
                encoding="utf-8",
            )
            (directory / configured["yard_blocks"].name).write_text(
                "BLOCK_ID,BRANCH_ID,BLOCK_CODE,ROW_COUNT,SLOT_COUNT,MAX_TIER,POS_X,POS_Y\n"
                "7,01,X,3,2,2,0,0\n8,2,Y,3,2,2,0,0\n",
                encoding="utf-8",
            )
            documents, _ = project_snapshot(data_dir=directory, branch_code="z")
            self.assertEqual(bundled_yard_branches(documents), {
                "branches": [{"code": "A", "name": "Yard A"}, {"code": "Z", "name": "Yard Z"}],
                "default_code": "Z",
            })

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

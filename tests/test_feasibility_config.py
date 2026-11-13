import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from config import (
    ConfigurationError,
    FeasibilitySettings,
    load_feasibility_settings,
)
from config.application.config_loader import parse_config


class FeasibilityConfigurationTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(text, encoding="utf-8")
            return load_feasibility_settings(path)

    def test_empty_file_uses_defaults(self):
        self.assertEqual(self.load_text(""), FeasibilitySettings())

    def test_explicit_options_are_loaded(self):
        settings = self.load_text(
            """
[feasibility]
stacking_safety = false
loader_access = true
preserve_future_loader_access = false
ignore_full_stacks_for_loader_access = true
"""
        )
        self.assertFalse(settings.stacking_safety)
        self.assertTrue(settings.loader_access)
        self.assertFalse(settings.preserve_future_loader_access)
        self.assertTrue(settings.ignore_full_stacks_for_loader_access)

    def test_omitted_option_uses_default(self):
        settings = self.load_text(
            """
[feasibility]
loader_access = false
"""
        )
        self.assertTrue(settings.stacking_safety)
        self.assertFalse(settings.loader_access)
        self.assertTrue(settings.preserve_future_loader_access)
        self.assertFalse(settings.ignore_full_stacks_for_loader_access)

    def test_unknown_option_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            self.load_text(
                """
[feasibility]
loader_acess = false
"""
            )

    def test_loader_mode_strength_is_validated_for_all_pairs(self):
        modes = ("off", "heuristic", "feasibility")
        for current_rank, current in enumerate(modes):
            for future_rank, future in enumerate(modes):
                with self.subTest(current=current, future=future):
                    options = dict(loader_access_mode=current, preserve_future_loader_access_mode=future)
                    if future_rank > current_rank:
                        with self.assertRaisesRegex(ValueError, "exceeds"):
                            FeasibilitySettings(**options)
                        with self.assertRaisesRegex(ConfigurationError, "exceeds"):
                            parse_config({"feasibility": options})
                    else:
                        parsed = parse_config({"feasibility": options})
                        self.assertEqual(parsed.feasibility.effective_loader_access_mode, current)
                        self.assertEqual(parsed.feasibility.effective_future_loader_access_mode, future)

    def test_loader_modes_roundtrip_and_legacy_settings_keep_effective_behavior(self):
        for options, current, future in (
            ({"loader_access": False, "preserve_future_loader_access": True}, "off", "off"),
            ({"loader_access": True, "preserve_future_loader_access": False}, "feasibility", "off"),
            ({"loader_access_mode": "heuristic"}, "heuristic", "heuristic"),
        ):
            with self.subTest(options=options):
                document = parse_config({"feasibility": options}).to_document()
                self.assertEqual(document["feasibility"]["loader_access_mode"], current)
                self.assertEqual(document["feasibility"]["preserve_future_loader_access_mode"], future)
                self.assertEqual(parse_config(document).to_document(), document)

    def test_invalid_or_conflicting_loader_mode_settings_are_rejected(self):
        for key in ("loader_access", "preserve_future_loader_access"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ConfigurationError, "Set either"):
                    parse_config({"feasibility": {key: True, key + "_mode": "feasibility"}})
                for value in (False, "invalid", 1, []):
                    with self.assertRaisesRegex(ConfigurationError, key + "_mode"):
                        parse_config({"feasibility": {key + "_mode": value}})

    def test_stacking_safety_mode_round_trips_and_accepts_legacy_booleans(self):
        for options, mode in (
            ({"stacking_safety": True}, "feasibility"),
            ({"stacking_safety": False}, "off"),
            ({"stacking_safety_mode": "heuristic"}, "heuristic"),
        ):
            with self.subTest(options=options):
                settings = parse_config({"feasibility": options})
                self.assertEqual(settings.feasibility.effective_stacking_safety_mode, mode)
                document = settings.to_document()
                self.assertEqual(document["feasibility"]["stacking_safety_mode"], mode)
                self.assertEqual(parse_config(document).to_document(), document)
        with self.assertRaisesRegex(ConfigurationError, "stacking_safety_mode"):
            parse_config({"feasibility": {"stacking_safety_mode": "invalid"}})
        with self.assertRaisesRegex(ConfigurationError, "Set either"):
            parse_config({"feasibility": {"stacking_safety": True, "stacking_safety_mode": "off"}})

    def test_non_boolean_options_are_rejected(self):
        for option in (
            "stacking_safety", "loader_access", "preserve_future_loader_access",
            "ignore_full_stacks_for_loader_access",
        ):
            for value in ('"false"', "0", "1", "[]"):
                with self.subTest(option=option, value=value):
                    with self.assertRaises(ConfigurationError):
                        self.load_text(
                            f"[feasibility]\n{option} = {value}\n"
                        )

    def test_invalid_section_type_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            self.load_text("feasibility = false\n")

    def test_invalid_toml_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            self.load_text("[feasibility\n")

    def test_missing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.toml"
            with self.assertRaises(ConfigurationError):
                load_feasibility_settings(path)

    def test_other_application_sections_are_permitted(self):
        settings = self.load_text(
            """
[application]
name = "Yard Management"

[feasibility]
loader_access = false
"""
        )
        self.assertFalse(settings.loader_access)

    def test_direct_settings_require_booleans(self):
        for option in (
            "stacking_safety", "loader_access", "preserve_future_loader_access",
            "ignore_full_stacks_for_loader_access",
        ):
            with self.subTest(option=option):
                with self.assertRaises(TypeError):
                    FeasibilitySettings(**{option: "false"})

    def test_settings_are_immutable(self):
        settings = FeasibilitySettings()
        with self.assertRaises(FrozenInstanceError):
            settings.loader_access = False


if __name__ == "__main__":
    unittest.main()

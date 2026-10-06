import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from config import (
    ConfigurationError,
    FeasibilitySettings,
    load_feasibility_settings,
)


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
"""
        )
        self.assertFalse(settings.stacking_safety)
        self.assertTrue(settings.loader_access)

    def test_omitted_option_uses_default(self):
        settings = self.load_text(
            """
[feasibility]
loader_access = false
"""
        )
        self.assertTrue(settings.stacking_safety)
        self.assertFalse(settings.loader_access)

    def test_unknown_option_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            self.load_text(
                """
[feasibility]
loader_acess = false
"""
            )

    def test_non_boolean_options_are_rejected(self):
        for option in ("stacking_safety", "loader_access"):
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
        for option in ("stacking_safety", "loader_access"):
            with self.subTest(option=option):
                with self.assertRaises(TypeError):
                    FeasibilitySettings(**{option: "false"})

    def test_settings_are_immutable(self):
        settings = FeasibilitySettings()
        with self.assertRaises(FrozenInstanceError):
            settings.loader_access = False


if __name__ == "__main__":
    unittest.main()

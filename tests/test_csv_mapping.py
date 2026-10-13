import tempfile
import unittest
from pathlib import Path

from config import (
    ConfigurationError,
    CSVMappingProfile,
    DEFAULT_CSV_MAPPING_FILE,
    load_csv_mapping,
)
from config.csv_import.mapping_settings import SCHEMAS
from entities import Container, Yard
from filereader import (
    ContainerFileReader,
    CSVInputError,
    EquipmentMoveFileReader,
    FileReader,
    RemovedSlotsFileReader,
    YardPlanningFileReader,
)


class CSVMappingLoaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "csv_mapping.toml"

    def load_text(self, text):
        self.path.write_text(text, encoding="utf-8")
        return load_csv_mapping(self.path)

    def test_default_file_contains_all_application_profiles(self):
        profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
        self.assertEqual(set(profiles), {
            "yard_blocks", "removed_slots", "parameters", "yard_planning",
            "existing_containers", "inbound_containers",
            "master_equipment", "equipment_history",
        })
        with self.assertRaises(TypeError):
            profiles["removed_slots"].columns["BLOCK_ID"] = "Changed"

    def test_partial_mapping_keeps_unmapped_fields_available(self):
        profiles = self.load_text(
            '[csv.master_equipment.columns]\nEQUIPMENT_CODE = "Code"\n'
        )
        csv_path = self.path.with_suffix(".csv")
        csv_path.write_text("Code,EQUIPMENT_TYPE\nrtg01,rtg\n", encoding="utf-8")
        self.assertEqual(
            FileReader(csv_path, profiles["master_equipment"]).readCSV(),
            [{"EQUIPMENT_CODE": "RTG01", "EQUIPMENT_TYPE": "RTG"}],
        )

    def test_invalid_definitions_are_rejected(self):
        cases = [
            "",
            "[csv]",
            '[csv.removed_slots.columns]\nBOCK_ID = "Block"\n',
            '[csv.removed_slots.columns]\nBLOCK_ID = ""\n',
            '[csv.removed_slots.columns]\nBLOCK_ID = 1\n',
            '[csv.unknown.columns]\nA = "a"\n',
            '[csv.removed_slots]\nunknown = 1\n',
            '[csv.removed_slots.columns\n',
            '[csv.removed_slots.columns]\nBLOCK_ID = "Block"\n'
            '[other]\nx = 1\n',
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_conflicts_include_identity_and_normalized_header_names(self):
        cases = [
            '[csv.removed_slots.columns]\nBLOCK_ID = "ROW_NO"\n',
            '[csv.removed_slots.columns]\nBLOCK_ID = "Location"\n'
            'ROW_NO = " location "\n',
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ConfigurationError, "both map"):
                    self.load_text(text)

    def test_missing_mapping_file_is_reported(self):
        with self.assertRaisesRegex(ConfigurationError, "Cannot load"):
            load_csv_mapping(self.path)


class CSVReaderMappingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "input.csv"

    def read_text(self, reader_type, text, profile_name=None, columns=None,
                  method="readCSV"):
        self.path.write_text(text, encoding="utf-8")
        profile = None
        if profile_name is not None:
            profile = CSVMappingProfile(
                profile_name, SCHEMAS[profile_name], columns or {},
            )
        return getattr(reader_type(self.path, profile), method)()

    def test_legacy_call_preserves_values_and_unnamed_column(self):
        self.assertEqual(
            self.read_text(FileReader, "ID,,VALUE\n0001,,abc\n"),
            [{"ID": "1", "": "", "VALUE": "ABC"}],
        )

    def test_renamed_reordered_headers_ignore_case_spaces_and_bom(self):
        self.assertEqual(
            self.read_text(
                RemovedSlotsFileReader,
                "\ufeff bay ,row NUMBER,Yard BLOCK\n4,2,000A\n",
                "removed_slots",
                {"BLOCK_ID": "Yard Block", "ROW_NO": "Row Number",
                 "SLOT_NO": "Bay"},
                "readCSVTuple",
            ),
            [("A", 1, 3)],
        )

    def test_configured_source_wins_over_unrelated_canonical_column(self):
        self.assertEqual(
            self.read_text(
                FileReader,
                "EQUIPMENT_CODE,Equipment Code,Type\nWRONG,rtg01,rtg\n",
                "master_equipment",
                {"EQUIPMENT_CODE": "Equipment Code", "EQUIPMENT_TYPE": "Type"},
            ),
            [{"EQUIPMENT_CODE": "RTG01", "EQUIPMENT_TYPE": "RTG"}],
        )

    def test_missing_optional_headers_still_construct_a_container(self):
        rows = self.read_text(
            ContainerFileReader,
            "CONTNO,PRINCIPAL,DMG_FLAG,FULLMT,CONT_GRADE,POL,POD,"
            "VESSEL,VOYAGE,WEIGHT,MOVE_TIME\n"
            "c001,ONE,AV,F,PG,JKT,SGR,MKL,V1,1000,\n",
            "inbound_containers",
        )
        container = Container(**rows[0])
        self.assertEqual(container.getId(), "C001")
        self.assertEqual(container.getContSize(), "")
        self.assertEqual(container.getWeight(), 1000)
        self.assertEqual(container.getCoordsStr(), ["", "", "", "", ""])
        self.assertEqual(container.operation_type, "")

    def test_present_empty_cell_is_allowed_for_a_required_column(self):
        self.assertEqual(
            self.read_text(
                FileReader, "Code,EQUIPMENT_TYPE\n,RTG\n",
                "master_equipment", {"EQUIPMENT_CODE": "Code"},
            ),
            [{"EQUIPMENT_CODE": "", "EQUIPMENT_TYPE": "RTG"}],
        )

    def test_missing_required_column_names_internal_and_source_fields(self):
        with self.assertRaisesRegex(CSVInputError, "BLOCK_ID.*Yard Block"):
            self.read_text(
                RemovedSlotsFileReader, "ROW_NO,SLOT_NO\n1,1\n",
                "removed_slots", {"BLOCK_ID": "Yard Block"}, "readCSVTuple",
            )

    def test_ambiguous_headers_are_rejected(self):
        with self.assertRaisesRegex(CSVInputError, "ambiguous"):
            self.read_text(FileReader, "BLOCK_ID, block_id \n1,2\n")

    def test_empty_file_and_malformed_rows_are_rejected(self):
        for text in ("", "a,b\n1\n", "a,b\n1,2,3\n"):
            with self.subTest(text=text):
                with self.assertRaises(CSVInputError):
                    self.read_text(FileReader, text)

    def test_invalid_coordinate_has_line_context(self):
        with self.assertRaisesRegex(CSVInputError, "line 2.*ROW_NO"):
            self.read_text(
                RemovedSlotsFileReader,
                "BLOCK_ID,ROW_NO,SLOT_NO\nA,invalid,1\n",
                "removed_slots", method="readCSVTuple",
            )

    def test_yard_planning_mapping_and_grouping(self):
        self.assertEqual(
            self.read_text(
                YardPlanningFileReader,
                "rule,block,slot,row\n001,000A,4,2\n001,000A,5,2\n",
                "yard_planning",
                {"PARAM_ID": "rule", "BLOCK_ID": "block",
                 "SLOT": "slot", "ROW": "row"},
                "readCSVDictTuple",
            ),
            {"1": [("A", 1, 3), ("A", 1, 4)]},
        )

    def test_equipment_latest_timestamp_and_first_record_on_a_tie(self):
        text = (
            "equipment,terminal,block,row,slot,time\n"
            "rtg01,001,a,1,2,2/8/2026 14:27\n"
            "rtg01,001,a,4,5,2/8/2026 14:26\n"
            "rtg01,001,a,3,4,2/8/2026 14:27\n"
        )
        columns = {
            "ALAT": "equipment", "BRANCH": "terminal", "BLOK": "block",
            "ROW": "row", "SLOT": "slot", "MOVE_DATE": "time",
        }
        self.assertEqual(
            self.read_text(EquipmentMoveFileReader, text,
                           "equipment_history", columns, "readCSVDict"),
            {"rtg01": ("001", "a", 0, 1)},
        )
        self.assertEqual(
            self.read_text(
                EquipmentMoveFileReader,
                text + "rtg01,001,a,2,3,2/8/2026 14:28\n",
                "equipment_history", columns, "readCSVDict",
            ),
            {"rtg01": ("001", "a", 1, 2)},
        )

    def test_incompatible_profile_is_rejected(self):
        with self.assertRaisesRegex(CSVInputError, "does not define"):
            self.read_text(
                RemovedSlotsFileReader,
                "PARAM_ID,BLOCK_ID,ROW,SLOT\n1,A,1,1\n",
                "yard_planning", method="readCSVTuple",
            )

    def test_default_profiles_load_sample_inputs_into_yard(self):
        data = Path(__file__).resolve().parents[1] / "test_data"
        profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
        yard = Yard(
            yard_block_input=FileReader(
                data / "yard_block.csv", profiles["yard_blocks"],
            ).readCSV(),
            removed_slots_input=RemovedSlotsFileReader(
                data / "removed_slots.csv", profiles["removed_slots"],
            ).readCSVTuple(),
            parameters_input=FileReader(
                data / "parameters2.csv", profiles["parameters"],
            ).readCSV(),
            yard_planning_input=YardPlanningFileReader(
                data / "yard_planning.csv", profiles["yard_planning"],
            ).readCSVDictTuple(),
            container_input=ContainerFileReader(
                data / "containers.csv", profiles["existing_containers"],
            ).readCSV(),
            master_equipment=FileReader(
                data / "master_equipment.csv", profiles["master_equipment"],
            ).readCSV(),
            equipment_history=EquipmentMoveFileReader(
                data / "equipment_history.csv", profiles["equipment_history"],
            ).readCSVDict(),
        )
        self.assertTrue(yard.blocks_by_id)
        self.assertTrue(yard.params)
        self.assertTrue(yard.containers)
        self.assertTrue(ContainerFileReader(
            data / "inbound.csv", profiles["inbound_containers"],
        ).readCSV())


if __name__ == "__main__":
    unittest.main()

import ast
import inspect
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
from entities import Block, Container, Parameter, Yard
from filewriter import ContainerFileWriter
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
            profiles["removed_slots"].columns["block_id"] = "Changed"

    def test_partial_mapping_keeps_unmapped_fields_available(self):
        profiles = self.load_text(
            '[csv.master_equipment.columns]\nequipment_code = "Code"\n'
        )
        csv_path = self.path.with_suffix(".csv")
        csv_path.write_text("Code,EQUIPMENT_TYPE\nrtg01,rtg\n", encoding="utf-8")
        self.assertEqual(
            FileReader(csv_path, profiles["master_equipment"]).readCSV(),
            [{"equipment_code": "RTG01", "equipment_type": "RTG"}],
        )

    def test_invalid_definitions_are_rejected(self):
        cases = [
            "",
            "[csv]",
            '[csv.removed_slots.columns]\nBOCK_ID = "Block"\n',
            '[csv.removed_slots.columns]\nblock_id = ""\n',
            '[csv.removed_slots.columns]\nblock_id = 1\n',
            '[csv.unknown.columns]\nA = "a"\n',
            '[csv.removed_slots]\nunknown = 1\n',
            '[csv.removed_slots.columns\n',
            '[csv.removed_slots.columns]\nblock_id = "Block"\n[other]\nx = 1\n',
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(ConfigurationError):
                    self.load_text(text)

    def test_conflicts_include_identity_and_normalized_header_names(self):
        cases = [
            '[csv.removed_slots.columns]\nblock_id = "ROW_NO"\n',
            '[csv.removed_slots.columns]\nblock_id = "Location"\nrow_no = " location "\n',
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ConfigurationError, "both map"):
                    self.load_text(text)

    def test_missing_mapping_file_is_reported(self):
        with self.assertRaisesRegex(ConfigurationError, "Cannot load"):
            load_csv_mapping(self.path)

    def test_entity_schemas_match_constructor_keyword_arguments(self):
        for entity, name in (
            (Block, "yard_blocks"),
            (Parameter, "parameters"),
            (Container, "existing_containers"),
            (Container, "inbound_containers"),
        ):
            with self.subTest(profile=name):
                parameters = inspect.signature(entity).parameters
                required = {
                    name for name, parameter in parameters.items()
                    if parameter.default is inspect.Parameter.empty
                    and parameter.kind not in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    )
                }
                fields = set(SCHEMAS[name].fields)
                self.assertLessEqual(fields, set(parameters))
                self.assertLessEqual(required, fields)


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
            mapping = dict(load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)[profile_name].columns)
            mapping.update(columns or {})
            profile = CSVMappingProfile(
                profile_name, SCHEMAS[profile_name], mapping,
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
                {"block_id": "Yard Block", "row_no": "Row Number",
                 "slot_no": "Bay"},
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
                {"equipment_code": "Equipment Code", "equipment_type": "Type"},
            ),
            [{"equipment_code": "RTG01", "equipment_type": "RTG"}],
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
                "master_equipment", {"equipment_code": "Code"},
            ),
            [{"equipment_code": "", "equipment_type": "RTG"}],
        )

    def test_parameter_operation_type_columns_are_optional_and_mapped(self):
        headers = (
            "PARAM_ID,PARAM_NAME,PRINCIPAL,PRINCIPAL_SCORE,CONT_CONDITION,"
            "CONT_CONDITION_SCORE,CONT_FILL,CONT_FILL_SCORE,CONT_SIZE,"
            "CONT_SIZE_SCORE,CONT_GRADE,CONT_GRADE_SCORE,POL,POD,ROUTE_SCORE,"
            "VESSEL,VOYAGE,VESSEL_VOYAGE_SCORE,WEIGHT_START,WEIGHT_END,"
            "WEIGHT_RANGE_SCORE"
        )
        row = ",".join(["P1", "Operation"] + [""] * 19)
        for extra_headers, extra_values, expected_type, expected_score in (
            ("", "", "", 0),
            (",OPERATION_TYPE,OPERATION_TYPE_SCORE", ",d,5", "D", 5),
            (",OPERATION_TYPE,OPERATION_TYPE_SCORE", ",,", "", 0),
            (",OPERATION_TYPE", ",d", "D", 0),
            (",OPERATION_TYPE_SCORE", ",5", "", 5),
        ):
            with self.subTest(headers=extra_headers, values=extra_values):
                record = self.read_text(
                    FileReader,
                    headers + extra_headers + "\n" + row + extra_values + "\n",
                    "parameters",
                )[0]
                self.assertEqual(record["operation_type"], expected_type)
                self.assertEqual(
                    record["operation_type_score"],
                    str(expected_score) if expected_score else "",
                )
                parameter = Parameter(**record)
                self.assertEqual(parameter.getOpType(), expected_type)
                self.assertEqual(parameter.getOpTypeScore(), expected_score)

    def container_record(self):
        return self.read_text(
            ContainerFileReader,
            "CONTNO,PRINCIPAL,DMG_FLAG,FULLMT,CONT_GRADE,POL,POD,"
            "VESSEL,VOYAGE,WEIGHT,MOVE_TIME,CONTSIZE,BRANCH,BLOK,ROW,SLOT,TIER,"
            "OPERATION_TYPE,POT,VESSEL_OPERATOR\n"
            "C1,ONE,AV,F,PG,JKT,SGR,MKL,V1,1000,,20,BR,A,2,4,3,D,PTL,OPR\n",
            "existing_containers",
        )[0]

    def test_csv_coordinate_numbers_and_internal_indices_remain_distinct(self):
        record = self.container_record()
        self.assertEqual(
            (record["row_no"], record["slot_no"], record["tier_no"]),
            ("2", "4", "3"),
        )
        container = Container(**record)
        self.assertEqual(container.getCoordsInt(), ("BR", "A", 1, 3, 2))
        container.setCoordsStr(
            branch_id="BR", block_code="A", row_no="3", slot_no="5", tier_no="2",
        )
        self.assertEqual(container.getCoordsInt(), ("BR", "A", 2, 4, 1))
        container.setCoordsInt(("BR", "A", 0, 1, 0))
        self.assertEqual(container.getCoordsStr(), ["BR", "A", "1", "2", "1"])

    def test_canonical_entity_fields_export_under_existing_csv_headers(self):
        yard = Yard(
            yard_blocks_input=[dict(
                block_id="1", branch_id="BR", block_code="A",
                row_count="3", slot_count="6", max_tier="3",
                pos_x="0", pos_y="0",
            )],
            containers_input=[self.container_record()],
        )
        writer = ContainerFileWriter(self.path)
        rows = writer.buildRows(yard)
        self.assertEqual(writer.FIELDNAMES, (
            "CONTNO", "BRANCH", "BLOK", "BLOK_ID", "SLOT", "ROW", "TIER",
            "PRINCIPAL", "DMG_FLAG", "FULLMT", "OPERATION_TYPE",
            "CONTSIZE", "CONT_GRADE", "POL", "POT", "POD",
            "VESSEL_OPERATOR", "VESSEL", "VOYAGE", "WEIGHT", "MOVE_TIME",
        ))
        self.assertEqual(set(rows[0]), set(writer.FIELDNAMES))
        self.assertEqual(
            {name: rows[0][name] for name in (
                "CONTNO", "BLOK", "BLOK_ID", "ROW", "SLOT", "TIER",
                "OPERATION_TYPE", "POT", "VESSEL_OPERATOR",
            )},
            {
                "CONTNO": "C1", "BLOK": "A", "BLOK_ID": "1",
                "ROW": "2", "SLOT": "4", "TIER": "3",
                "OPERATION_TYPE": "D", "POT": "PTL", "VESSEL_OPERATOR": "OPR",
            },
        )

    def test_missing_required_column_names_internal_and_source_fields(self):
        with self.assertRaisesRegex(CSVInputError, "block_id.*Yard Block"):
            self.read_text(
                RemovedSlotsFileReader, "ROW_NO,SLOT_NO\n1,1\n",
                "removed_slots", {"block_id": "Yard Block"}, "readCSVTuple",
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
        with self.assertRaisesRegex(CSVInputError, "line 2.*row_no"):
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
                {"parameter_id": "rule", "block_id": "block",
                 "slot_no": "slot", "row_no": "row"},
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
            "equipment_code": "equipment", "branch_id": "terminal", "block_code": "block",
            "row_no": "row", "slot_no": "slot", "move_time": "time",
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
                "EQUIPMENT_CODE,EQUIPMENT_TYPE\nRTG01,RTG\n",
                "master_equipment", method="readCSVTuple",
            )

    def test_default_profiles_load_sample_inputs_into_yard(self):
        data = Path(__file__).resolve().parents[1] / "test_data"
        profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
        yard = Yard(
            yard_blocks_input=FileReader(
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
            containers_input=ContainerFileReader(
                data / "containers.csv", profiles["existing_containers"],
            ).readCSV(),
            equipment_input=FileReader(
                data / "master_equipment.csv", profiles["master_equipment"],
            ).readCSV(),
            equipment_locations_input=EquipmentMoveFileReader(
                data / "equipment_history.csv", profiles["equipment_history"],
            ).readCSVDict(),
        )
        self.assertTrue(yard.blocks_by_id)
        self.assertTrue(yard.parameters)
        self.assertTrue(yard.containers)
        self.assertTrue(ContainerFileReader(
            data / "inbound.csv", profiles["inbound_containers"],
        ).readCSV())

    def test_application_startup_loads_profiles_and_builds_yard(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        startup = []
        for statement in tree.body:
            startup.append(statement)
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "yard"
                for target in statement.targets
            ):
                break
        else:
            self.fail("The application must initialize a yard.")

        # Exercise initialization without entering the interactive placement
        # loop or writing the output CSV.
        namespace = {"__file__": str(main_path), "__name__": "__main__"}
        exec(compile(ast.Module(body=startup, type_ignores=[]), str(main_path), "exec"), namespace)
        self.assertTrue(namespace["yard"].blocks_by_id)
        self.assertTrue(namespace["yard"].containers)


if __name__ == "__main__":
    unittest.main()

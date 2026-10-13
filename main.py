from pathlib import Path

from filewriter import ContainerFileWriter

from config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_CSV_MAPPING_FILE,
    load_config,
    load_csv_mapping,
)

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader, EquipmentMoveFileReader
from entities import Yard, Container
from entities.bad_yard_data import PlacementRejected
from presenter import YardPresenter, BadDataPresenter

settings = load_config(DEFAULT_CONFIG_FILE)
csv_profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)

blockFile = Path(__file__).parent / "test_data" / "yard_block.csv"
ypFile = Path(__file__).parent / "test_data" / "yard_planning.csv"
removedFile = Path(__file__).parent / "test_data" / "removed_slots.csv"
parameterFile = Path(__file__).parent / "test_data" / "parameters2.csv"
containerFile = Path(__file__).parent / "test_data" / "containers.csv"
inboundContFile = Path(__file__).parent / "test_data" / "inbound.csv"
masterEquipmentFile = Path(__file__).parent / "test_data" / "master_equipment.csv"
equipmentHistoryFile = Path(__file__).parent / "test_data" / "equipment_history.csv"

block_repo = FileReader(
    blockFile,
    profile=csv_profiles["yard_blocks"],
).readCSV()

removed_repo = RemovedSlotsFileReader(
    removedFile,
    profile=csv_profiles["removed_slots"],
).readCSVTuple()

parameter_repo = FileReader(
    parameterFile,
    profile=csv_profiles["parameters"],
).readCSV()

yp_repo = YardPlanningFileReader(
    ypFile,
    profile=csv_profiles["yard_planning"],
).readCSVDictTuple()

containerRepo = ContainerFileReader(
    containerFile,
    profile=csv_profiles["existing_containers"],
).readCSV()

inboundContRepo = ContainerFileReader(
    inboundContFile,
    profile=csv_profiles["inbound_containers"],
).readCSV()

masterEquipmentRepo = FileReader(
    masterEquipmentFile,
    profile=csv_profiles["master_equipment"],
).readCSV()

equipmentHistoryFile = EquipmentMoveFileReader(
    equipmentHistoryFile,
    profile=csv_profiles["equipment_history"],
).readCSVDict()

yard = Yard(
    yard_block_input=block_repo,
    removed_slots_input=removed_repo,
    parameters_input=parameter_repo,
    yard_planning_input=yp_repo,
    container_input=containerRepo,
    master_equipment=masterEquipmentRepo,
    equipment_history=equipmentHistoryFile,
    feasibility_settings=settings.feasibility,
    heuristic_settings=settings.heuristic,
)
yardPresenter = YardPresenter()
yardPresenter.outYard(yard)

if yard.bad_data.anyBadData():
    BadDataPresenter().print(yard.bad_data)
    BadDataPresenter().printStats(yard.bad_data)
else: print("All good.")

skip = False
for x in inboundContRepo:
    print("\n Press Enter to continue. Anything else to skip.")
    if not skip:
        inp = input()
        if inp != "":
            skip = True
    newContainer = Container(**({"CONTSIZE": ""} | x))

    try:
        result = yard.assign_and_place(newContainer)
    except PlacementRejected as error:
        print(f"Container {newContainer.getId()} was not placed: {error}")
        continue

    yardPresenter.outAssignResult(result)
    yardPresenter.outYard(yard)

BadDataPresenter().printInbound(yard.bad_data)

container_writer = ContainerFileWriter(
    Path(__file__).parent / "output" / "result.csv"
)
container_writer.writeCSV(yard)

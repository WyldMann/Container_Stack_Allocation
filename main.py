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

yard_blocks_file = Path(__file__).parent / "test_data" / "yard_block.csv"
yard_planning_file = Path(__file__).parent / "test_data" / "yard_planning.csv"
removed_slots_file = Path(__file__).parent / "test_data" / "removed_slots.csv"
parameters_file = Path(__file__).parent / "test_data" / "parameters2.csv"
containers_file = Path(__file__).parent / "test_data" / "containers.csv"
inbound_containers_file = Path(__file__).parent / "test_data" / "inbound.csv"
equipment_file = Path(__file__).parent / "test_data" / "master_equipment.csv"
equipment_history_file = Path(__file__).parent / "test_data" / "equipment_history.csv"

yard_block_records = FileReader(
    yard_blocks_file,
    profile=csv_profiles["yard_blocks"],
).readCSV()

removed_slots = RemovedSlotsFileReader(
    removed_slots_file,
    profile=csv_profiles["removed_slots"],
).readCSVTuple()

parameter_records = FileReader(
    parameters_file,
    profile=csv_profiles["parameters"],
).readCSV()

yard_planning = YardPlanningFileReader(
    yard_planning_file,
    profile=csv_profiles["yard_planning"],
).readCSVDictTuple()

container_records = ContainerFileReader(
    containers_file,
    profile=csv_profiles["existing_containers"],
).readCSV()

inbound_container_records = ContainerFileReader(
    inbound_containers_file,
    profile=csv_profiles["inbound_containers"],
).readCSV()

equipment_records = FileReader(
    equipment_file,
    profile=csv_profiles["master_equipment"],
).readCSV()

equipment_locations = EquipmentMoveFileReader(
    equipment_history_file,
    profile=csv_profiles["equipment_history"],
).readCSVDict()

yard = Yard(
    yard_blocks_input=yard_block_records,
    removed_slots_input=removed_slots,
    parameters_input=parameter_records,
    yard_planning_input=yard_planning,
    containers_input=container_records,
    equipment_input=equipment_records,
    equipment_locations_input=equipment_locations,
    feasibility_settings=settings.feasibility,
    heuristic_settings=settings.heuristic,
)
yard_presenter = YardPresenter()
yard_presenter.outYard(yard)

if yard.bad_data.anyBadData():
    BadDataPresenter().print(yard.bad_data)
    BadDataPresenter().printStats(yard.bad_data)
else: print("All good.")

skip = False
for x in inbound_container_records:
    print("\n Press Enter to continue. Anything else to skip.")
    if not skip:
        inp = input()
        if inp != "":
            skip = True
    new_container = Container(**({"container_size": ""} | x))

    try:
        result = yard.assign_and_place(new_container)
    except PlacementRejected as error:
        print(f"Container {new_container.getId()} was not placed: {error}")
        continue

    yard_presenter.outAssignResult(result)
    yard_presenter.outYard(yard)

BadDataPresenter().printInbound(yard.bad_data)

container_writer = ContainerFileWriter(
    Path(__file__).parent / "output" / "result.csv"
)
container_writer.writeCSV(yard)

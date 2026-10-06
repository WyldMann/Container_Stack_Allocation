from pathlib import Path

from config import load_config

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader, EquipmentMoveFileReader
from entities import Yard, Container
from presenter import YardPresenter, BadDataPresenter

config_file = Path(__file__).resolve().parent / "config.toml"
settings = load_config(config_file)

blockFile = Path(__file__).parent / "test_data" / "yard_block.csv"
ypFile = Path(__file__).parent / "test_data" / "yard_planning.csv"
removedFile = Path(__file__).parent / "test_data" / "removed_slots.csv"
parameterFile = Path(__file__).parent / "test_data" / "parameters.csv"
containerFile = Path(__file__).parent / "test_data" / "containers.csv"
inboundContFile = Path(__file__).parent / "test_data" / "inbound.csv"
masterEquipmentFile = Path(__file__).parent / "test_data" / "master_equipment.csv"
equipmentHistoryFile = Path(__file__).parent / "test_data" / "equipment_history.csv"

block_repo = FileReader(blockFile).readCSV()
removed_repo = RemovedSlotsFileReader(removedFile).readCSVTuple()
parameter_repo = FileReader(parameterFile).readCSV()
yp_repo = YardPlanningFileReader(ypFile).readCSVDictTuple()
containerRepo = ContainerFileReader(containerFile).readCSV()
inboundContRepo = ContainerFileReader(inboundContFile).readCSV()
masterEquipmentRepo = FileReader(masterEquipmentFile).readCSV()
equipmentHistoryFile = EquipmentMoveFileReader(equipmentHistoryFile).readCSVDict()

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
    newContainer = Container(**x)
    yardPresenter.outAssignResult(yard.assign_and_place(newContainer))
    yardPresenter.outYard(yard)

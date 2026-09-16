from pathlib import Path

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader, EquipmentMoveFileReader
from entities import Yard, Container

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

yard = Yard(block_repo, removed_repo, parameter_repo, yp_repo,containerRepo,masterEquipmentRepo,equipmentHistoryFile)

yard.print()

yard.getBadData().print()
for x in inboundContRepo:
    print("\n Press Enter to continue")
    #input()
    newContainer = Container(**x)
    yard.assignContainer(newContainer)
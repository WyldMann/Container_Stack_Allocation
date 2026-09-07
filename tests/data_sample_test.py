from pathlib import Path

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader
from entities import Yard, Container

blockFile = Path(__file__).parent / "test_data" / "yard_block.csv"
ypFile = Path(__file__).parent / "test_data" / "yard_planning.csv"
removedFile = Path(__file__).parent / "test_data" / "removed_slots.csv"
parameterFile = Path(__file__).parent / "test_data" / "parameters.csv"
containerFile = Path(__file__).parent / "test_data" / "containers.csv"

block_repo = FileReader(blockFile).readCSV()
removed_repo = RemovedSlotsFileReader(removedFile).readCSVTuple()
parameter_repo = FileReader(parameterFile).readCSV()
yp_repo = YardPlanningFileReader(ypFile).readCSVDictTuple()
containerRepo = ContainerFileReader(containerFile).readCSV()
yard = Yard(block_repo, removed_repo, parameter_repo, yp_repo)

print(containerRepo[0])
container = Container(**containerRepo[0])
print(yard.assignContainer(container))
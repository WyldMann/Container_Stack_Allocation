from pathlib import Path

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader
from entities import Yard

yardfile = Path(__file__).parent.parent / "data"/ "_TRM_MST_YARD_BLOCK__202609030901.csv"
removed_slot_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv"
parameter_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_PARAMETER__202608271123.csv"
yard_planning_input_file =  Path(__file__).parent.parent / "data" / "_TRM_TRS_YARD_PLANNING_ITEM__202608271125.csv"
container_file = Path(__file__).parent.parent / "data" / "_TRM_TRS_TARGET_CONTAINER.csv"
prod_container_file = Path(__file__).parent.parent / "data" / "rpt-terminalapp-010926.csv"

yard_repo = FileReader(yardfile).readCSV()
removed_slot = RemovedSlotsFileReader(removed_slot_file).readCSVTuple()
parameter_input = FileReader(parameter_file).readCSV()
yard_planning_input = YardPlanningFileReader(yard_planning_input_file).readCSVDictTuple()
container_repo = ContainerFileReader(prod_container_file).readCSV()

yard = Yard(yard_repo,removed_slot,parameter_input,yard_planning_input,container_repo)

yard.getBadData().print()
from pathlib import Path

from repository import Repository, RemovedSlotsRepository, YardPlanningRepository
from entities import Container, Parameter, Yard, Block, Stack

yardfile = Path(__file__).parent.parent / "data"/ "_TRM_MST_YARD_BLOCK__202608271123.csv"
removed_slot_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv"
parameter_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_PARAMETER__202608271123.csv"
yard_planning_input_file =  Path(__file__).parent.parent / "data" / "_TRM_TRS_YARD_PLANNING_ITEM__202608271125.csv"

yard_repo = Repository(yardfile).readCSV()
removed_slot = RemovedSlotsRepository(removed_slot_file).readCSVTuple()
parameter_input = Repository(parameter_file).readCSV()
yard_planning_input = YardPlanningRepository(yard_planning_input_file).readCSVDictTuple()

yard = Yard(yard_repo,removed_slot,parameter_input)

yard.print()
from pathlib import Path
from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping

from filereader import FileReader, RemovedSlotsFileReader, YardPlanningFileReader, ContainerFileReader
from entities import Yard

import matplotlib as plt
import pandas as pd

yardfile = Path(__file__).parent.parent / "data"/ "_TRM_MST_YARD_BLOCK__202609030901.csv"
removed_slot_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv"
parameter_file = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_PARAMETER__202608271123.csv"
yard_planning_input_file =  Path(__file__).parent.parent / "data" / "_TRM_TRS_YARD_PLANNING_ITEM__202608271125.csv"
container_file = Path(__file__).parent.parent / "data" / "_TRM_TRS_TARGET_CONTAINER.csv"
prod_container_file = Path(__file__).parent.parent / "data" / "rpt-terminalapp-010926.csv"

csv_profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
yard_repo = FileReader(yardfile, profile=csv_profiles["yard_blocks"]).readCSV()
removed_slot = RemovedSlotsFileReader(removed_slot_file, profile=csv_profiles["removed_slots"]).readCSVTuple()
parameter_input = FileReader(parameter_file, profile=csv_profiles["parameters"]).readCSV()
yard_planning_input = YardPlanningFileReader(yard_planning_input_file, profile=csv_profiles["yard_planning"]).readCSVDictTuple()
container_repo = ContainerFileReader(prod_container_file, profile=csv_profiles["existing_containers"]).readCSV()

yard = Yard(yard_repo,removed_slot,parameter_input,yard_planning_input,container_repo)

#yard.print()
#yard.getBadData().print()
yard.fillDummyContainer()
yard.dummy.printCoordsList()


baddata = yard.getBadData()
baddata.printStats()

usable_containers = len(yard.containers)
print("\nUsable container data:",usable_containers)

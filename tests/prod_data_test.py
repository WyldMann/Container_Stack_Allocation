from pathlib import Path
from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping

from repository import CSVLoader
from repository import Repository, RemovedSlotsRepository, YardPlanningRepository, ContainerRepository
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
yard_repo = Repository(CSVLoader(yardfile), profile=csv_profiles["yard_blocks"]).read_records()
removed_slot = RemovedSlotsRepository(CSVLoader(removed_slot_file), profile=csv_profiles["removed_slots"]).read_tuples()
parameter_input = Repository(CSVLoader(parameter_file), profile=csv_profiles["parameters"]).read_records()
yard_planning_input = YardPlanningRepository(CSVLoader(yard_planning_input_file), profile=csv_profiles["yard_planning"]).read_grouped()
container_repo = ContainerRepository(CSVLoader(prod_container_file), profile=csv_profiles["existing_containers"]).read_records()

yard = Yard(yard_repo,removed_slot,parameter_input,yard_planning_input,container_repo)

#yard.print()
#yard.getBadData().print()
# Disabled anomaly-repair demonstration.
# yard.fillDummyContainer()
# yard.dummy.printCoordsList()


baddata = yard.getBadData()
baddata.printStats()

usable_containers = len(yard.containers)
print("\nUsable container data:",usable_containers)

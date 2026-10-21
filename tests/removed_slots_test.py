from pathlib import Path
from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping

from repository import CSVLoader
from repository import RemovedSlotsRepository


path = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv"
csv_profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
for x in RemovedSlotsRepository(CSVLoader(path), profile=csv_profiles["removed_slots"]).read_tuples():
    print(x)

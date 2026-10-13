import csv
from pathlib import Path
from config import DEFAULT_CSV_MAPPING_FILE, load_csv_mapping
from entities import Parameter
from filereader import FileReader

# data
parameters: list[Parameter] = []
csv_profiles = load_csv_mapping(DEFAULT_CSV_MAPPING_FILE)
parameter_repository = FileReader(Path(__file__).parent.parent
                                  / "data" / "_TRM_MST_YARD_PARAMETER__202608271123.csv",
                                  profile=csv_profiles["parameters"]).readCSV()
for x in parameter_repository:
    parameters.append(Parameter(**x))

print([x.getId() for x in parameters])


import csv
from pathlib import Path
from entities import Parameter
from filereader import FileReader

# data
parameters: list[Parameter] = []
parameter_repository = FileReader(Path(__file__).parent.parent
                                  / "data" / "_TRM_MST_YARD_PARAMETER__202608271123.csv").readCSV()
for x in parameter_repository:
    parameters.append(Parameter(**x))

print([x.getId() for x in parameters])


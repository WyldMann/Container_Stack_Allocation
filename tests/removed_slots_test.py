from pathlib import Path

from filereader import RemovedSlotsFileReader


path = Path(__file__).parent.parent / "data" / "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv"
for x in RemovedSlotsFileReader(path).readCSVTuple():
    print(x)
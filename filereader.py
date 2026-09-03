import csv
from typing import Any
from utils import strGeneralize


class FileReader:
    def __init__(self, file_path):
        self.file_path = file_path

    def readCSV(self) -> list[dict[str,str]]:
        data = []
        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                data.append({key:strGeneralize(value) for key, value in row.items()})
        return data

    # group list into a dict with first element as key
    @staticmethod
    def group_rows(data):
        result = {}

        for row in data:
            key = row[0]
            values = tuple(row[1:])

            result.setdefault(key, []).append(values)

        return result

    # meant to be overridden
    def readCSVTuple(self) -> list[Any]:
        raise NotImplementedError("Subclasses must override readCSVTuple()")

    def readCSVDictTuple(self):
        return self.group_rows(self.readCSVTuple())

class ContainerFileReader(FileReader):
    def readCSV(self) -> list[dict[str,str]]:
        data = []
        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:

                #stopgap data sampling fix
                if row["BRANCH"] == "JKT64": row["BRANCH"] = "1"
                elif row["BRANCH"] == "JKT74": row["BRANCH"] = "2"
                elif row["BRANCH"] == "JKT56": row["BRANCH"] = "3"

                data.append({key:strGeneralize(value) for key, value in row.items()})

        return data

class RemovedSlotsFileReader(FileReader):

    #[(block_id, row_no, slot_no),....]
    def readCSVTuple(self) -> list[tuple[str,int,int]]:
        data = []

        # required field names as they appear in the csv
        block_id = "BLOCK_ID"
        row_no = "ROW_NO"
        slot_no = "SLOT_NO"

        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for line in reader:
                data.append((strGeneralize(line[block_id]), int(line[row_no]) - 1, int(line[slot_no]) - 1))
        return data

class YardPlanningFileReader(FileReader):

    #[(param_id, block_id, slot, row), ... ]
    # readCSVTuple().grouprows() {param_id:
    def readCSVTuple(self) -> list[tuple[str,str,int,int]]:
        data = []

        param_id = "PARAM_ID"
        block_id = "BLOCK_ID"
        row = "ROW"
        slot = "SLOT"

        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for line in reader:
                data.append((strGeneralize(line[param_id]), strGeneralize(line[block_id]), int(line[row]) - 1, int(line[slot]) - 1))
        return data
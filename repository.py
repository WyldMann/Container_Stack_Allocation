import csv

#todo overhaul repository usage for all classes

class Repository:
    def __init__(self, file_path):
        self.file_path = file_path

    def readCSV(self) -> list[dict[str,str]]:
        data = []
        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                data.append(row)
        return data

class RemovedSlotsRepository(Repository):

    #[(block_id, row_no, slot_no),....]
    def readCSVTuple(self) -> list[tuple[str,str,int,int]]:
        data = []

        # required field names as they appear in the csv
        block_id = "BLOCK_ID"
        block_code = "BLOCK_CODE"
        row_no = "ROW_NO"
        slot_no = "SLOT_NO"

        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for line in reader:
                data.append((line[block_id], line[block_code], int(line[row_no]), int(line[slot_no])))
        return data

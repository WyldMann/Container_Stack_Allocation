import csv

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
    def readCSV(self) -> list[dict[str,str]]:
        data = []

        # required field names as they appear in the csv

        block_id = "BLOCK_ID"
        row_id = "ROW_ID"
        slot_no = "SLOT_NO"

        with open(self.file_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for line in reader:
                data.append({block_id:line[block_id],row_id:line[row_id],slot_no:line[slot_no]})
        return data


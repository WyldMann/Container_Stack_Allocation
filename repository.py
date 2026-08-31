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

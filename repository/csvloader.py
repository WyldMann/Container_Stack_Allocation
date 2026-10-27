import csv
from contextlib import contextmanager
from pathlib import Path

from .loader import InputError


class CSVLoader:
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        if self.file_path.suffix.casefold() in {".xlsx", ".xls", ".xlsm", ".xlsb"}:
            raise InputError(
                f"{self.file_path}: expected a UTF-8 CSV file, received an Excel workbook. "
                "Convert the report to a flat CSV and configure the CSV path; "
                "renaming the Excel file is not sufficient."
            )

    @property
    def source(self) -> str:
        return str(self.file_path)

    @contextmanager
    def open(self):
        with self.file_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)

            def iter_rows():
                for record in reader:
                    location = f"{self.source}, line {reader.line_num}"
                    if None in record:
                        raise InputError(f"{location}: too many values.")
                    if any(value is None for value in record.values()):
                        raise InputError(f"{location}: too few values.")
                    yield location, record

            yield reader.fieldnames, iter_rows()

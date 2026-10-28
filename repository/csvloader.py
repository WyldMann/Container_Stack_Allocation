import csv
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from config.application.input_filters import active_filters
from .loader import InputError


class CSVLoader:
    def __init__(self, file_path: str | Path, *, filters=None):
        self.file_path = Path(file_path)
        self.filters = active_filters({} if filters is None else filters)
        if self.file_path.suffix.casefold() in {".xlsx", ".xls", ".xlsm", ".xlsb"}:
            raise InputError(
                f"{self.file_path}: expected a UTF-8 CSV file, received an Excel workbook. "
                "Convert the report to a flat CSV and configure the CSV path; "
                "renaming the Excel file is not sufficient."
            )

    @property
    def source(self) -> str:
        return str(self.file_path)

    @staticmethod
    def _matches(value, expected):
        if type(expected) is int:
            try:
                return Decimal(value.strip()) == expected
            except InvalidOperation:
                return False
        return value == str(expected)

    @contextmanager
    def open(self):
        with self.file_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            headers = {name.strip().casefold(): name for name in reader.fieldnames or []}
            filters = {}
            for column, value in self.filters.items():
                header = headers.get(column.strip().casefold())
                if header is None:
                    raise InputError(f"{self.source}: missing filter column {column!r}.")
                filters[header] = value

            def iter_rows():
                for record in reader:
                    location = f"{self.source}, line {reader.line_num}"
                    if None in record:
                        raise InputError(f"{location}: too many values.")
                    if any(value is None for value in record.values()):
                        raise InputError(f"{location}: too few values.")
                    if any(not self._matches(record[column], value) for column, value in filters.items()):
                        continue
                    yield location, record

            yield reader.fieldnames, iter_rows()

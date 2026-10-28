"""Refresh the flat shifting CSV from the supplied weekly XLSX report template."""

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .loader import InputError


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_HEADERS = ("cy_name", "shifting_code", "lifting_count", "shifting_count",
            "report_month", "week_number")


def _column(reference):
    result = 0
    for letter in re.match(r"[A-Z]+", reference).group():
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def _count_text(value):
    """Preserve blanks and invalid source values for the CSV reader to validate."""
    if value is None or not str(value).strip():
        return ""
    text = str(value).strip()
    try:
        number = Decimal(text)
        if number.is_finite() and number >= 0 and number == number.to_integral_value():
            return str(int(number))
    except InvalidOperation:
        pass
    return text


def _report_month(value):
    text = str(value or "").strip()
    for pattern in ("%b-%y", "%b-%Y", "%Y-%m"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m")
        except ValueError:
            pass
    try:
        return date.fromisoformat(text).strftime("%Y-%m")
    except ValueError as error:
        raise InputError("Report cell E3 must contain a month such as Oct-26 or 2026-10.") from error


def _read_report(workbook_path, sheet_name):
    with ZipFile(workbook_path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(node.text or "" for node in item.findall(".//m:t", _NS))
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", _NS)
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall("m:sheets/m:sheet", _NS)
        sheet = next((item for item in sheets if item.get("name") == sheet_name), None)
        if sheet is None:
            raise InputError(f"Missing shifting worksheet {sheet_name!r}.")
        relations = {
            item.get("Id"): item for item in
            ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        relation = relations[sheet.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )]
        if relation.get("TargetMode") == "External":
            raise InputError("The shifting worksheet must be stored inside the workbook.")
        target = relation.get("Target")
        if not target:
            raise InputError("The shifting worksheet relationship has no target.")
        target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join("xl", target)
        )
        root = ET.fromstring(archive.read(target))
        cells = {}
        for cell in root.findall("m:sheetData/m:row/m:c", _NS):
            value = cell.find("m:v", _NS)
            if cell.get("t") == "inlineStr":
                cells[cell.get("r")] = "".join(
                    node.text or "" for node in cell.findall(".//m:t", _NS)
                )
            elif value is not None and value.text is not None:
                cells[cell.get("r")] = (
                    strings[int(value.text)] if cell.get("t") == "s" else value.text
                )

        month = _report_month(cells.get("E3"))
        cy_columns = {}
        for merged in root.findall("m:mergeCells/m:mergeCell", _NS):
            start, end = merged.get("ref").split(":")
            if not re.fullmatch(r"[A-Z]+7", start):
                continue
            name = cells.get(start, "")
            if name.strip():
                for column in range(_column(start), _column(end) + 1):
                    cy_columns[column] = name

        metrics = {
            _column(address): value.strip().upper()
            for address, value in cells.items() if re.fullmatch(r"[A-Z]+9", address)
        }
        groups = []
        seen = set()
        for address, value in cells.items():
            if not re.fullmatch(r"[A-Z]+8", address) or not value.strip():
                continue
            column = _column(address)
            cy = cy_columns.get(column)
            if cy is None or metrics.get(column) != "LIFTING" or metrics.get(column + 1) != "SHIFTING":
                raise InputError(f"Unexpected shifting header layout at {address}.")
            code = value.strip()
            key = (cy, code.casefold())
            if key in seen:
                raise InputError(f"Duplicate shifting header {cy}/{code}.")
            seen.add(key)
            groups.append((column, cy, code))
        if not groups:
            raise InputError("No CY/code groups found in report header rows 7-9.")

        output = []
        for row in root.findall("m:sheetData/m:row", _NS):
            number = int(row.get("r"))
            if number < 10:
                continue
            label = cells.get(f"A{number}", "").strip()
            if not label or label.upper() == "TOTAL":
                continue
            match = re.fullmatch(r"(?:WEEK\s*)?(\d+)", label, re.IGNORECASE)
            if match is None or not 1 <= int(match.group(1)) <= 53:
                raise InputError(f"Invalid weekly period label {label!r} in A{number}.")
            values = {_column(cell.get("r")): cells.get(cell.get("r"))
                      for cell in row.findall("m:c", _NS)}
            for column, cy, code in sorted(groups):
                output.append((
                    cy, code, _count_text(values.get(column)),
                    _count_text(values.get(column + 1)), month, int(match.group(1)),
                ))
        if not output:
            raise InputError("The shifting worksheet has no weekly detail rows.")
        return output


def refresh_shifting_csv(workbook_path, csv_path, sheet_name="Per Alat Weekly"):
    """Always re-read the workbook and atomically replace the generated CSV."""
    workbook_path, csv_path = Path(workbook_path), Path(csv_path)
    if workbook_path.resolve() == csv_path.resolve() or csv_path.suffix.casefold() != ".csv":
        raise InputError("The generated shifting CSV must have a separate .csv output path.")
    temporary = None
    try:
        rows = _read_report(workbook_path, sheet_name)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", delete=False,
            dir=csv_path.parent, prefix=csv_path.name + ".", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(_HEADERS)
            writer.writerows(rows)
        os.replace(temporary, csv_path)
    except InputError:
        raise
    except (OSError, BadZipFile, ET.ParseError, KeyError, IndexError, ValueError) as error:
        raise InputError(f"Cannot refresh shifting CSV from {workbook_path}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(rows)

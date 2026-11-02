"""Small report workbooks shared by shifting input and entrypoint tests."""

from collections import defaultdict
import xml.etree.ElementTree as ET
from zipfile import ZipFile


NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def column(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_report(path, records, *, daily=False, sheet_name=None):
    """Records contain (CY, code, lifting, shifting, month, period label)."""
    records = list(records)
    groups = list(dict.fromkeys((row[0], row[1]) for row in records))
    occurrences = defaultdict(int)
    periods = {}
    for cy, code, lifting, shifting, month, period in records:
        key = (cy, code, period)
        index = occurrences[key]
        occurrences[key] += 1
        periods.setdefault((period, index), {})[(cy, code)] = (lifting, shifting)
    values = {3: {"E": records[0][4]}, 5: {"E": "Daily" if daily else "Weekly"},
              7: {}, 8: {}, 9: {}}
    merges = []
    for index, (cy, code) in enumerate(groups):
        left, right = column(2 + index * 3), column(4 + index * 3)
        values[7][left] = cy
        values[8][left] = code
        values[9].update({left: "LIFTING", column(3 + index * 3): "SHIFTING"})
        merges.extend((f"{left}7:{right}7", f"{left}8:{right}8"))
    for number, ((period, _), observations) in enumerate(periods.items(), start=10):
        values[number] = {"A": period if daily else "WEEK " + str(period)}
        for index, group in enumerate(groups):
            lifting, shifting = observations.get(group, (None, None))
            values[number].update({column(2 + index * 3): lifting,
                                   column(3 + index * 3): shifting})
    values[max(values) + 1] = {"A": "TOTAL"}
    sheet = ET.Element("{" + NS + "}worksheet")
    data = ET.SubElement(sheet, "{" + NS + "}sheetData")
    for number, cells in sorted(values.items()):
        row = ET.SubElement(data, "{" + NS + "}row", r=str(number))
        for name, value in cells.items():
            if value is None or value == "":
                continue
            cell = ET.SubElement(row, "{" + NS + "}c", r=name + str(number))
            if isinstance(value, str):
                cell.set("t", "inlineStr")
                ET.SubElement(ET.SubElement(cell, "{" + NS + "}is"), "{" + NS + "}t").text = value
            else:
                ET.SubElement(cell, "{" + NS + "}v").text = str(value)
    merged = ET.SubElement(sheet, "{" + NS + "}mergeCells")
    for reference in merges:
        ET.SubElement(merged, "{" + NS + "}mergeCell", ref=reference)
    sheet_name = sheet_name or ("Per Alat Daily" if daily else "Per Alat Weekly")
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml",
            '<workbook xmlns="' + NS + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="' + sheet_name + '" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))

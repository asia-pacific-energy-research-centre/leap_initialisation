"""Create USA-derived provisional LEAP export templates for missing economies.

The copies retain every source workbook component and change only the readable
``Region`` cells on the ``Export`` sheet. They are intentionally named with
``_COMP_GEN`` so the resolver marks downstream baseline seeds as provisional.
"""

from __future__ import annotations

import argparse
from copy import copy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TEMPLATES_ROOT = REPO_ROOT / "data" / "leap_export_templates"
EXPORT_SHEET_NAME = "Export"
XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NAMESPACES = {"main": XML_NS, "rel": REL_NS, "pkg": PKG_REL_NS}


def _column_label(column_index: int) -> str:
    """Return an Excel column label for a zero-based index."""
    label = ""
    value = column_index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _export_sheet_archive_path(workbook_path: Path) -> str:
    """Return the ZIP member containing the named worksheet's XML."""
    with ZipFile(workbook_path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(
            (
                element
                for element in workbook.findall("main:sheets/main:sheet", NAMESPACES)
                if element.attrib.get("name") == EXPORT_SHEET_NAME
            ),
            None,
        )
        if sheet is None:
            raise ValueError(f"{workbook_path.name} has no {EXPORT_SHEET_NAME!r} worksheet.")
        relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            (
                element.attrib["Target"]
                for element in relationships.findall("pkg:Relationship", NAMESPACES)
                if element.attrib.get("Id") == relationship_id
            ),
            None,
        )
    if target is None:
        raise ValueError(f"{workbook_path.name} has no relationship for {EXPORT_SHEET_NAME!r}.")
    return f"xl/{target.lstrip('/')}"


def _replace_region_cells(source_path: Path, output_path: Path, region: str) -> int:
    """Copy a workbook and replace only populated data-row Region cells."""
    sheet_member = _export_sheet_archive_path(source_path)
    headers = pd.read_excel(
        source_path,
        sheet_name=EXPORT_SHEET_NAME,
        header=2,
        nrows=0,
    ).columns.tolist()
    if "Region" not in headers:
        raise ValueError(f"{source_path.name} has no Region column on Excel row 3.")
    region_column = _column_label(headers.index("Region"))
    source_rows = pd.read_excel(
        source_path,
        sheet_name=EXPORT_SHEET_NAME,
        header=2,
        usecols=["Branch Path"],
        dtype=object,
    )
    branch_paths = source_rows["Branch Path"].fillna("").astype(str).str.strip()
    populated_excel_rows = {
        int(index) + 4
        for index, branch_path in branch_paths.items()
        if branch_path
    }
    with ZipFile(source_path) as source:
        sheet_root = ET.fromstring(source.read(sheet_member))
        rows = sheet_root.findall("main:sheetData/main:row", NAMESPACES)

        changed = 0
        for row in rows:
            row_number = int(row.attrib.get("r", "0"))
            if row_number not in populated_excel_rows:
                continue
            cell = next(
                (
                    candidate
                    for candidate in row.findall("main:c", NAMESPACES)
                    if "".join(filter(str.isalpha, candidate.attrib.get("r", "")))
                    == region_column
                ),
                None,
            )
            if cell is None:
                continue
            cell.attrib["t"] = "inlineStr"
            for child in list(cell):
                cell.remove(child)
            inline_string = ET.SubElement(cell, f"{{{XML_NS}}}is")
            ET.SubElement(inline_string, f"{{{XML_NS}}}t").text = region
            changed += 1

        if not changed:
            raise ValueError(f"{source_path.name} contains no data-row Region cells.")
        updated_sheet_xml = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)

        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as output:
            for item in source.infolist():
                payload = updated_sheet_xml if item.filename == sheet_member else source.read(item.filename)
                output.writestr(copy(item), payload)
    return changed


def _verify_copy(source_path: Path, output_path: Path, region: str) -> None:
    """Prove that IDs are unchanged and only the expected Region label changed."""
    source = pd.read_excel(source_path, sheet_name=EXPORT_SHEET_NAME, header=2, dtype=object)
    output = pd.read_excel(output_path, sheet_name=EXPORT_SHEET_NAME, header=2, dtype=object)
    required = ["BranchID", "VariableID", "ScenarioID", "RegionID", "Region"]
    missing = [column for column in required if column not in output.columns]
    if missing:
        raise ValueError(f"{output_path.name} is missing required columns: {missing}")
    if len(source) != len(output):
        raise ValueError(f"{output_path.name} row count changed: {len(source)} -> {len(output)}")
    for column in required[:-1]:
        if not source[column].equals(output[column]):
            raise ValueError(f"{output_path.name} unexpectedly changed {column}.")
    if set(output["Region"].dropna().astype(str)) != {region}:
        raise ValueError(f"{output_path.name} does not contain only Region={region!r}.")


def main(overwrite: bool = False) -> None:
    """Create a template for every configured economy currently missing one."""
    from codebase.functions.supply_data_pipeline import get_region_for_economy
    from codebase.utilities.leap_export_template_resolver import (
        KNOWN_ECONOMIES,
        available_template_economies,
        resolve_leap_export_template,
    )

    source_path = resolve_leap_export_template("20_USA", warn_on_provisional=False)
    missing_economies = sorted(set(KNOWN_ECONOMIES) - set(available_template_economies()))
    if not missing_economies:
        print("No missing economy templates found; nothing to create.")
        return

    for economy in missing_economies:
        output_path = TEMPLATES_ROOT / f"leap_export_template {economy}_COMP_GEN.xlsx"
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing template: {output_path}")
        region = get_region_for_economy(economy)
        with TemporaryDirectory(dir=TEMPLATES_ROOT) as temp_dir:
            temporary_path = Path(temp_dir) / output_path.name
            changed = _replace_region_cells(source_path, temporary_path, region)
            _verify_copy(source_path, temporary_path, region)
            temporary_path.replace(output_path)
        print(f"Created {output_path.name}: {changed} Region cells -> {region}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Replace existing COMP_GEN copies.")
    arguments = parser.parse_args()
    main(overwrite=arguments.overwrite)

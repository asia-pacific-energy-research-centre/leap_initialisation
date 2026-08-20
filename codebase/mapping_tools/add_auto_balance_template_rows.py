#%%
"""Migrate existing transfer AUTO BALANCE template rows to BranchID 100.

Every active template already contains the same validated 72 transfer AUTO
BALANCE rows.  BranchID 100 is the explicit placeholder convention; it is not
a LEAP branch ID.  This module deliberately edits only those 72 XML values and
re-packs the XLSX archive, avoiding an expensive full-workbook rebuild.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "data" / "leap_export_templates"
TARGET_ECONOMIES = [
    "AUS", "BD", "PRC", "MAS", "MEX", "NZ", "PNG", "PHL", "THA", "USA", "VN",
]
AUTO_BALANCE_LABEL = "AUTO BALANCE"
AUTO_BALANCE_PLACEHOLDER_BRANCH_ID = 100
SHEET_XML_PATH = "xl/worksheets/sheet1.xml"
NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
AUTO_BALANCE_TRANSFER_ROOTS = (
    "Transformation\\Transfers unallocated\\",
    "Transformation\\Refinery and blending transfers\\",
    "Transformation\\Upstream liquids transfers\\",
)


def _find_target_template(economy: str) -> Path:
    """Resolve exactly one active template by its economy letter token."""
    candidates = sorted(TEMPLATE_ROOT.glob(f"*{economy}*.xlsx"))
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one {economy} template, found: {candidates}")
    return candidates[0]


def _cell_value(cell) -> str:
    """Return a cell's inline string or numerical value from the sheet XML."""
    return "".join(cell.itertext())


def _column_name(cell) -> str:
    """Extract the Excel column letters from a cell reference such as ``AZ11252``."""
    match = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
    return match.group(0) if match is not None else ""


def _auto_balance_rows(template_path: Path) -> list[tuple[int, str]]:
    """Return (row number, BranchID) for the existing AUTO BALANCE rows."""
    with ZipFile(template_path) as archive:
        root = ElementTree.fromstring(archive.read(SHEET_XML_PATH))
    rows = []
    for row in root.iter(f"{NAMESPACE}row"):
        cells = {_column_name(cell): cell for cell in row}
        path = _cell_value(cells.get("E")) if cells.get("E") is not None else ""
        if path.endswith(AUTO_BALANCE_LABEL):
            row_number = int(row.attrib["r"])
            branch_id = _cell_value(cells.get("A")) if cells.get("A") is not None else ""
            rows.append((row_number, branch_id))
    return rows


def _validate_auto_balance_structure(template_path: Path) -> None:
    """Require the expected transfer-only set and populated non-branch IDs."""
    with ZipFile(template_path) as archive:
        root = ElementTree.fromstring(archive.read(SHEET_XML_PATH))
    rows = []
    for row in root.iter(f"{NAMESPACE}row"):
        cells = {_column_name(cell): cell for cell in row}
        path = _cell_value(cells.get("E")) if cells.get("E") is not None else ""
        if path.endswith(AUTO_BALANCE_LABEL):
            rows.append(
                {
                    "path": path,
                    "variable": _cell_value(cells.get("F")) if cells.get("F") is not None else "",
                    "scenario": _cell_value(cells.get("G")) if cells.get("G") is not None else "",
                    "region": _cell_value(cells.get("H")) if cells.get("H") is not None else "",
                    "variable_id": _cell_value(cells.get("B")) if cells.get("B") is not None else "",
                    "scenario_id": _cell_value(cells.get("C")) if cells.get("C") is not None else "",
                    "region_id": _cell_value(cells.get("D")) if cells.get("D") is not None else "",
                }
            )
    if len(rows) != 72:
        raise ValueError(f"{template_path.name} has {len(rows)} AUTO BALANCE rows, expected 72")
    if len({(row["path"], row["variable"], row["scenario"], row["region"]) for row in rows}) != 72:
        raise ValueError(f"{template_path.name} has duplicate AUTO BALANCE keys")
    if any(not row[key] for row in rows for key in ("variable_id", "scenario_id", "region_id")):
        raise ValueError(f"{template_path.name} has an AUTO BALANCE row without a non-branch ID")
    if any(not row["path"].startswith(AUTO_BALANCE_TRANSFER_ROOTS) for row in rows):
        raise ValueError(f"{template_path.name} has an AUTO BALANCE row outside the approved transfer branches")


def _migrate_existing_rows(template_path: Path, apply_changes: bool) -> dict[str, object]:
    """Change only approved -1 placeholders to 100, using an atomic archive replace."""
    _validate_auto_balance_structure(template_path)
    rows = _auto_balance_rows(template_path)
    if len(rows) != 72:
        raise ValueError(f"{template_path.name} has {len(rows)} AUTO BALANCE rows, expected 72")
    ids = {branch_id for _, branch_id in rows}
    if not ids.issubset({"-1", "#N/A", str(AUTO_BALANCE_PLACEHOLDER_BRANCH_ID)}):
        raise ValueError(f"{template_path.name} has unexpected AUTO BALANCE BranchIDs: {sorted(ids)}")
    target_rows = [
        row_number
        for row_number, branch_id in rows
        if branch_id in {"-1", "#N/A"}
    ]
    if apply_changes and target_rows:
        with ZipFile(template_path) as source_archive:
            sheet_xml = source_archive.read(SHEET_XML_PATH).decode("utf-8")
            for row_number in target_rows:
                pattern = rf'(<c r="A{row_number}"[^>]*><v>)(?:-1|#N/A)(</v></c>)'
                sheet_xml, substitutions = re.subn(
                    pattern,
                    rf"\g<1>{AUTO_BALANCE_PLACEHOLDER_BRANCH_ID}\g<2>",
                    sheet_xml,
                    count=1,
                )
                if substitutions != 1:
                    raise ValueError(f"Could not safely update BranchID at A{row_number} in {template_path.name}")
            temporary_path = template_path.with_suffix(".tmp.xlsx")
            with ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive:
                for item in source_archive.infolist():
                    content = sheet_xml.encode("utf-8") if item.filename == SHEET_XML_PATH else source_archive.read(item.filename)
                    destination_archive.writestr(item, content)
        os.replace(temporary_path, template_path)
    return {"template": template_path.name, "rows_migrated": len(target_rows)}


def validate_auto_balance_rows(template_path: Path) -> None:
    """Confirm the added set is complete, key-unique, and explicitly unresolved."""
    _validate_auto_balance_structure(template_path)
    rows = _auto_balance_rows(template_path)
    if len(rows) != 72:
        raise ValueError(f"{template_path.name} has {len(rows)} AUTO BALANCE rows, expected 72")
    if {branch_id for _, branch_id in rows} != {str(AUTO_BALANCE_PLACEHOLDER_BRANCH_ID)}:
        raise ValueError(f"{template_path.name} AUTO BALANCE rows must keep BranchID=100")


def update_all_templates(apply_changes: bool = False) -> list[dict[str, object]]:
    """Dry-run or migrate the complete existing set in every active template."""
    results = []
    for economy in TARGET_ECONOMIES:
        template_path = _find_target_template(economy)
        result = _migrate_existing_rows(template_path, apply_changes=apply_changes)
        if apply_changes or result["rows_migrated"] == 0:
            validate_auto_balance_rows(template_path)
        results.append(result)
        print(result)
    return results


#%%
# Toggle from a Jupyter cell or run this module with the chosen value below.
APPLY_CHANGES = False

if __name__ == "__main__":
    update_all_templates(apply_changes=APPLY_CHANGES)

#%%

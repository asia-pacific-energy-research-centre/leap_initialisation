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
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "data" / "leap_export_templates"
TARGET_ECONOMIES = [
    "AUS", "BD", "PRC", "MAS", "MEX", "NZ", "PNG", "PHL", "RUS", "THA", "USA", "VN",
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
AUTO_BALANCE_VARIABLES = {
    "Output Fuels": {
        "Shortfall Rule",
        "Surplus Rule",
        "Usage Rule",
        "Priority Output",
        "Output Share",
        "Import Target",
        "Export Target",
    },
    "Feedstock Fuels": {"Feedstock Fuel Share"},
}


def _find_target_template(economy: str) -> Path:
    """Resolve exactly one active template by its economy letter token."""
    candidates = sorted(TEMPLATE_ROOT.glob(f"*{economy}*.xlsx"))
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one {economy} template, found: {candidates}")
    return candidates[0]


def _cell_value(cell) -> str:
    """Return an inline/numeric cell value; shared strings are resolved by caller."""
    return "".join(cell.itertext())


def _column_name(cell) -> str:
    """Extract the Excel column letters from a cell reference such as ``AZ11252``."""
    match = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
    return match.group(0) if match is not None else ""


def _read_template_xml(template_path: Path):
    """Read sheet XML plus the workbook's optional shared-string table."""
    with ZipFile(template_path) as archive:
        root = ElementTree.fromstring(archive.read(SHEET_XML_PATH))
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(item.itertext())
                for item in shared_root.iter(f"{NAMESPACE}si")
            ]
    return root, shared_strings


def _resolved_cell_value(cell, shared_strings: list[str]) -> str:
    """Return a cell value, including a value stored through sharedStrings.xml."""
    if cell is None:
        return ""
    value_node = cell.find(f"{NAMESPACE}v")
    if cell.attrib.get("t") == "s" and value_node is not None:
        return shared_strings[int(value_node.text)]
    return _cell_value(cell)


def _auto_balance_rows(template_path: Path) -> list[tuple[int, str]]:
    """Return (row number, BranchID) for the existing AUTO BALANCE rows."""
    root, shared_strings = _read_template_xml(template_path)
    rows = []
    for row in root.iter(f"{NAMESPACE}row"):
        cells = {_column_name(cell): cell for cell in row}
        path = _resolved_cell_value(cells.get("E"), shared_strings)
        if path.endswith(AUTO_BALANCE_LABEL):
            row_number = int(row.attrib["r"])
            branch_id = _resolved_cell_value(cells.get("A"), shared_strings)
            rows.append((row_number, branch_id))
    return rows


def _validate_auto_balance_structure(template_path: Path) -> None:
    """Require the expected transfer-only set and populated non-branch IDs."""
    root, shared_strings = _read_template_xml(template_path)
    rows = []
    for row in root.iter(f"{NAMESPACE}row"):
        cells = {_column_name(cell): cell for cell in row}
        path = _resolved_cell_value(cells.get("E"), shared_strings)
        if path.endswith(AUTO_BALANCE_LABEL):
            rows.append(
                {
                    "path": path,
                    "variable": _resolved_cell_value(cells.get("F"), shared_strings),
                    "scenario": _resolved_cell_value(cells.get("G"), shared_strings),
                    "region": _resolved_cell_value(cells.get("H"), shared_strings),
                    "variable_id": _resolved_cell_value(cells.get("B"), shared_strings),
                    "scenario_id": _resolved_cell_value(cells.get("C"), shared_strings),
                    "region_id": _resolved_cell_value(cells.get("D"), shared_strings),
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


def _header_columns(root, shared_strings: list[str]) -> dict[str, str]:
    """Return workbook header names keyed to their Excel column letters."""
    for row in root.iter(f"{NAMESPACE}row"):
        cells = {_column_name(cell): cell for cell in row}
        values = {
            _resolved_cell_value(cell, shared_strings): column
            for column, cell in cells.items()
        }
        if "Branch Path" in values and "Variable" in values:
            return values
    raise ValueError("Could not locate the LEAP export header row")


def _set_inline_string(cell, value: str) -> None:
    """Set one XML cell to an inline string without extending sharedStrings.xml."""
    cell.attrib["t"] = "inlineStr"
    for child in list(cell):
        cell.remove(child)
    inline = ElementTree.SubElement(cell, f"{NAMESPACE}is")
    text = ElementTree.SubElement(inline, f"{NAMESPACE}t")
    text.text = value


def _set_numeric_value(cell, value: int) -> None:
    """Set one XML cell to a numeric placeholder value."""
    cell.attrib.pop("t", None)
    for child in list(cell):
        cell.remove(child)
    numeric = ElementTree.SubElement(cell, f"{NAMESPACE}v")
    numeric.text = str(value)


def _new_auto_balance_paths() -> list[str]:
    """Return the six reviewed transfer AUTO BALANCE paths."""
    paths = []
    for root in AUTO_BALANCE_TRANSFER_ROOTS:
        sector_name = root.rstrip("\\").split("\\")[-1]
        paths.extend(
            [
                f"{root}Output Fuels\\{AUTO_BALANCE_LABEL}",
                f"{root}Processes\\{sector_name}\\Feedstock Fuels\\{AUTO_BALANCE_LABEL}",
            ]
        )
    return paths


def _insert_missing_auto_balance_rows(template_path: Path, apply_changes: bool) -> dict[str, object]:
    """Add the standard 72 local-placeholder rows where a template has none.

    Each new row clones its own area's matching transfer fuel row, retaining its
    VariableID, ScenarioID, RegionID, formats, and surrounding metadata.  Only
    the leaf path and the deliberately non-real BranchID=100 are changed.
    """
    root, shared_strings = _read_template_xml(template_path)
    existing_rows = _auto_balance_rows(template_path)
    if existing_rows:
        validate_auto_balance_rows(template_path)
        return {"template": template_path.name, "rows_added": 0}

    headers = _header_columns(root, shared_strings)
    required_headers = {"BranchID", "Branch Path", "Variable", "Scenario", "Region"}
    if not required_headers.issubset(headers):
        raise ValueError(f"{template_path.name} lacks required LEAP export columns")

    sheet_data = root.find(f"{NAMESPACE}sheetData")
    if sheet_data is None:
        raise ValueError(f"{template_path.name} has no sheet data")
    template_rows = list(sheet_data)
    next_row = max(int(row.attrib["r"]) for row in template_rows) + 1
    rows_to_add = []
    for target_path in _new_auto_balance_paths():
        branch_kind = "Output Fuels" if "\\Output Fuels\\" in target_path else "Feedstock Fuels"
        prefix = target_path.rsplit("\\", 1)[0] + "\\"
        candidates = []
        for row in template_rows:
            cells = {_column_name(cell): cell for cell in row}
            source_path = _resolved_cell_value(cells.get(headers["Branch Path"]), shared_strings)
            variable = _resolved_cell_value(cells.get(headers["Variable"]), shared_strings)
            if source_path.startswith(prefix) and variable in AUTO_BALANCE_VARIABLES[branch_kind]:
                candidates.append(row)
        expected_count = 21 if branch_kind == "Output Fuels" else 3
        if len(candidates) < expected_count:
            raise ValueError(
                f"{template_path.name} has only {len(candidates)} suitable rows for {target_path}; "
                f"expected at least {expected_count}"
            )
        source_leaf = _resolved_cell_value(
            {_column_name(cell): cell for cell in candidates[0]}.get(headers["Branch Path"]),
            shared_strings,
        )
        matching_leaf_rows = []
        for row in candidates:
            cells = {_column_name(cell): cell for cell in row}
            source_path = _resolved_cell_value(cells.get(headers["Branch Path"]), shared_strings)
            if source_path == source_leaf:
                matching_leaf_rows.append(row)
        if len(matching_leaf_rows) != expected_count:
            raise ValueError(f"{template_path.name} does not have one complete source leaf for {target_path}")
        rows_to_add.extend((row, target_path) for row in matching_leaf_rows)

    if len(rows_to_add) != 72:
        raise ValueError(f"{template_path.name} would add {len(rows_to_add)} rows, expected 72")
    if apply_changes:
        for source_row, target_path in rows_to_add:
            new_row = deepcopy(source_row)
            new_row.attrib["r"] = str(next_row)
            cells = {_column_name(cell): cell for cell in new_row}
            for column, cell in cells.items():
                cell.attrib["r"] = f"{column}{next_row}"
            _set_numeric_value(cells[headers["BranchID"]], AUTO_BALANCE_PLACEHOLDER_BRANCH_ID)
            _set_inline_string(cells[headers["Branch Path"]], target_path)
            for index, part in enumerate(target_path.split("\\"), start=1):
                level_column = headers.get(f"Level {index}")
                if level_column in cells:
                    _set_inline_string(cells[level_column], part)
            sheet_data.append(new_row)
            next_row += 1
        temporary_path = template_path.with_suffix(".tmp.xlsx")
        with ZipFile(template_path) as source_archive, ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive:
            updated_xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            for item in source_archive.infolist():
                content = updated_xml if item.filename == SHEET_XML_PATH else source_archive.read(item.filename)
                destination_archive.writestr(item, content)
        os.replace(temporary_path, template_path)
        validate_auto_balance_rows(template_path)
    return {"template": template_path.name, "rows_added": len(rows_to_add)}


def validate_auto_balance_rows(template_path: Path) -> None:
    """Confirm the added set is complete, key-unique, and explicitly unresolved."""
    _validate_auto_balance_structure(template_path)
    rows = _auto_balance_rows(template_path)
    if len(rows) != 72:
        raise ValueError(f"{template_path.name} has {len(rows)} AUTO BALANCE rows, expected 72")
    if {branch_id for _, branch_id in rows} != {str(AUTO_BALANCE_PLACEHOLDER_BRANCH_ID)}:
        raise ValueError(f"{template_path.name} AUTO BALANCE rows must keep BranchID=100")


def update_all_templates(apply_changes: bool = False) -> list[dict[str, object]]:
    """Dry-run or add/migrate the complete set in every active template."""
    results = []
    for economy in TARGET_ECONOMIES:
        template_path = _find_target_template(economy)
        added = _insert_missing_auto_balance_rows(template_path, apply_changes=apply_changes)
        result = _migrate_existing_rows(template_path, apply_changes=apply_changes)
        result.update(added)
        if apply_changes or (result["rows_migrated"] == 0 and result["rows_added"] == 0):
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

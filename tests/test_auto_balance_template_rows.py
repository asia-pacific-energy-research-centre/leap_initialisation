"""Tests for the narrow AUTO BALANCE placeholder XML migration."""

from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from codebase.mapping_tools.add_auto_balance_template_rows import (
    SHEET_XML_PATH,
    _auto_balance_rows,
    _insert_missing_auto_balance_rows,
    _migrate_existing_rows,
    validate_auto_balance_rows,
)


def _write_template(path, branch_id: int = -1) -> None:
    rows = "".join(
        '<row r="{row}"><c r="A{row}" t="n"><v>{branch_id}</v></c>'
        '<c r="B{row}" t="n"><v>2</v></c><c r="C{row}" t="n"><v>3</v></c>'
        '<c r="D{row}" t="n"><v>4</v></c>'
        '<c r="E{row}" t="inlineStr"><is><t>'
        'Transformation\\Transfers unallocated\\Output Fuels\\AUTO BALANCE'
        '</t></is></c><c r="F{row}" t="inlineStr"><is><t>Value {row}</t></is></c>'
        '<c r="G{row}" t="inlineStr"><is><t>Target</t></is></c>'
        '<c r="H{row}" t="inlineStr"><is><t>AUS</t></is></c></row>'.format(
            row=row,
            branch_id=branch_id,
        )
        for row in range(4, 76)
    )
    xml = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{rows}</sheetData></worksheet>'
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(SHEET_XML_PATH, xml)


def test_migrate_existing_rows_updates_only_the_72_placeholder_ids(tmp_path):
    template_path = tmp_path / "template.xlsx"
    _write_template(template_path)

    result = _migrate_existing_rows(template_path, apply_changes=True)

    assert result["rows_migrated"] == 72
    assert {branch_id for _, branch_id in _auto_balance_rows(template_path)} == {"100"}
    validate_auto_balance_rows(template_path)


def test_migrate_existing_rows_refuses_an_unexpected_branch_id(tmp_path):
    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, branch_id=7)

    with pytest.raises(ValueError, match="unexpected AUTO BALANCE BranchIDs"):
        _migrate_existing_rows(template_path, apply_changes=True)


def _write_transfer_template_without_auto_balance(path) -> None:
    """Write the six local transfer leaf structures from which rows are cloned."""
    headers = (
        '<row r="3"><c r="A3" t="inlineStr"><is><t>BranchID</t></is></c>'
        '<c r="E3" t="inlineStr"><is><t>Branch Path</t></is></c>'
        '<c r="F3" t="inlineStr"><is><t>Variable</t></is></c>'
        '<c r="G3" t="inlineStr"><is><t>Scenario</t></is></c>'
        '<c r="H3" t="inlineStr"><is><t>Region</t></is></c></row>'
    )
    output_variables = [
        "Shortfall Rule", "Surplus Rule", "Usage Rule", "Priority Output",
        "Output Share", "Import Target", "Export Target",
    ]
    scenarios = [("Current Accounts", 1), ("Reference", 2), ("Target", 3)]
    transfer_roots = [
        "Transfers unallocated", "Refinery and blending transfers", "Upstream liquids transfers",
    ]
    row_number = 4
    rows = []
    for transfer_root in transfer_roots:
        for variable in output_variables:
            for scenario, scenario_id in scenarios:
                path_value = f"Transformation\\{transfer_root}\\Output Fuels\\Aviation gasoline"
                rows.append(
                    '<row r="{row}"><c r="A{row}" t="n"><v>1200</v></c>'
                    '<c r="B{row}" t="n"><v>2</v></c><c r="C{row}" t="n"><v>{scenario_id}</v></c>'
                    '<c r="D{row}" t="n"><v>1</v></c><c r="E{row}" t="inlineStr"><is><t>{path}</t></is></c>'
                    '<c r="F{row}" t="inlineStr"><is><t>{variable}</t></is></c>'
                    '<c r="G{row}" t="inlineStr"><is><t>{scenario}</t></is></c>'
                    '<c r="H{row}" t="inlineStr"><is><t>Russia</t></is></c></row>'.format(
                        row=row_number, scenario_id=scenario_id, path=path_value,
                        variable=variable, scenario=scenario,
                    )
                )
                row_number += 1
        for scenario, scenario_id in scenarios:
            path_value = (
                f"Transformation\\{transfer_root}\\Processes\\{transfer_root}"
                "\\Feedstock Fuels\\Aviation gasoline"
            )
            rows.append(
                '<row r="{row}"><c r="A{row}" t="n"><v>1201</v></c>'
                '<c r="B{row}" t="n"><v>1036</v></c><c r="C{row}" t="n"><v>{scenario_id}</v></c>'
                '<c r="D{row}" t="n"><v>1</v></c><c r="E{row}" t="inlineStr"><is><t>{path}</t></is></c>'
                '<c r="F{row}" t="inlineStr"><is><t>Feedstock Fuel Share</t></is></c>'
                '<c r="G{row}" t="inlineStr"><is><t>{scenario}</t></is></c>'
                '<c r="H{row}" t="inlineStr"><is><t>Russia</t></is></c></row>'.format(
                    row=row_number, scenario_id=scenario_id, path=path_value, scenario=scenario,
                )
            )
            row_number += 1
    xml = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{headers}{"".join(rows)}</sheetData></worksheet>'
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(SHEET_XML_PATH, xml)


def test_insert_missing_rows_clones_local_transfer_metadata(tmp_path):
    template_path = tmp_path / "rus_template.xlsx"
    _write_transfer_template_without_auto_balance(template_path)

    result = _insert_missing_auto_balance_rows(template_path, apply_changes=True)

    assert result == {"template": "rus_template.xlsx", "rows_added": 72}
    assert {branch_id for _, branch_id in _auto_balance_rows(template_path)} == {"100"}
    validate_auto_balance_rows(template_path)

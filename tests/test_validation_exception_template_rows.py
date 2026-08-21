from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from codebase.mapping_tools.add_validation_exception_template_rows import (
    PLACEHOLDER_BRANCH_ID,
    SHEET_XML_PATH,
    insert_missing_exception_rows,
    validate_exception_placeholder_rows,
)


def _write_template(path, sibling_profiles: dict[str, list[tuple[str, str, str]]]) -> None:
    headers = (
        '<row r="3"><c r="A3" t="inlineStr"><is><t>BranchID</t></is></c>'
        '<c r="E3" t="inlineStr"><is><t>Branch Path</t></is></c>'
        '<c r="F3" t="inlineStr"><is><t>Variable</t></is></c>'
        '<c r="G3" t="inlineStr"><is><t>Scenario</t></is></c>'
        '<c r="H3" t="inlineStr"><is><t>Region</t></is></c>'
        '<c r="I3" t="inlineStr"><is><t>Level 1</t></is></c>'
        '<c r="J3" t="inlineStr"><is><t>Level 2</t></is></c>'
        '<c r="K3" t="inlineStr"><is><t>Level 3</t></is></c></row>'
    )
    rows = []
    row_number = 4
    for branch_path, profile in sibling_profiles.items():
        for variable, scenario, region in profile:
            levels = branch_path.split("\\")
            rows.append(
                '<row r="{row}"><c r="A{row}" t="n"><v>1200</v></c>'
                '<c r="E{row}" t="inlineStr"><is><t>{path}</t></is></c>'
                '<c r="F{row}" t="inlineStr"><is><t>{variable}</t></is></c>'
                '<c r="G{row}" t="inlineStr"><is><t>{scenario}</t></is></c>'
                '<c r="H{row}" t="inlineStr"><is><t>{region}</t></is></c>'
                '<c r="I{row}" t="inlineStr"><is><t>{level1}</t></is></c>'
                '<c r="J{row}" t="inlineStr"><is><t>{level2}</t></is></c>'
                '<c r="K{row}" t="inlineStr"><is><t>{level3}</t></is></c></row>'.format(
                    row=row_number, path=branch_path, variable=variable, scenario=scenario,
                    region=region, level1=levels[0], level2=levels[1], level3=levels[2],
                )
            )
            row_number += 1
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{}</sheetData></worksheet>'.format(headers + "".join(rows))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(SHEET_XML_PATH, xml)


def test_inserts_complete_largest_sibling_profile_with_branch_id_99(tmp_path):
    template_path = tmp_path / "template.xlsx"
    target_path = r"Demand\Other\Missing fuel"
    profile = [("Activity Level", "Reference", "Test"), ("Activity Level", "Target", "Test")]
    _write_template(template_path, {
        r"Demand\Other\Existing fuel": profile,
        r"Demand\Other\Sparse fuel": profile[:1],
    })

    result = insert_missing_exception_rows(template_path, {target_path}, apply_changes=True)

    assert result == {"template": "template.xlsx", "rows_added": 2}
    validate_exception_placeholder_rows(template_path, {target_path})
    with ZipFile(template_path) as archive:
        xml = archive.read(SHEET_XML_PATH).decode("utf-8")
    assert xml.count(target_path) == 2
    assert f">{PLACEHOLDER_BRANCH_ID}<" in xml


def test_refuses_ambiguous_largest_sibling_profiles(tmp_path):
    template_path = tmp_path / "template.xlsx"
    _write_template(template_path, {
        r"Demand\Other\Existing fuel": [("Activity Level", "Reference", "Test")],
        r"Demand\Other\Different fuel": [("Energy Intensity", "Reference", "Test")],
    })

    with pytest.raises(ValueError, match="Ambiguous sibling profiles"):
        insert_missing_exception_rows(template_path, {r"Demand\Other\Missing fuel"})

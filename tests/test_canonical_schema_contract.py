"""Schema contracts for canonical mapping sheets consumed by initialisation."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.mappings import canonical_loaders as cl


def _write_workbook(path: Path, sheet_name: str, columns: tuple[str, ...]) -> None:
    pd.DataFrame(columns=list(columns)).to_excel(path, sheet_name=sheet_name, index=False)


@pytest.mark.parametrize("sheet_name", sorted(cl.CANONICAL_SHEET_CONTRACT))
def test_every_declared_contract_loads_from_real_canonical_workbook(sheet_name: str) -> None:
    if not cl.CANONICAL_WORKBOOK_PATH.exists():
        pytest.skip("canonical workbook not present in this environment")
    frame = cl.load_canonical_contract_sheet(sheet_name)
    assert set(cl.CANONICAL_SHEET_CONTRACT[sheet_name]).issubset(frame.columns)


@pytest.mark.parametrize("sheet_name", sorted(cl.CANONICAL_SHEET_CONTRACT))
def test_declared_contract_rejects_a_renamed_consumed_column(tmp_path: Path, sheet_name: str) -> None:
    required = cl.CANONICAL_SHEET_CONTRACT[sheet_name]
    renamed = (f"renamed_{required[0]}", *required[1:])
    workbook = tmp_path / "canonical.xlsx"
    _write_workbook(workbook, sheet_name, renamed)

    with pytest.raises(cl.CanonicalMappingError, match=rf"{sheet_name}.*{required[0]}"):
        cl.load_canonical_contract_sheet(sheet_name, workbook=workbook)


def test_undeclared_sheet_cannot_bypass_the_schema_contract(tmp_path: Path) -> None:
    workbook = tmp_path / "canonical.xlsx"
    _write_workbook(workbook, "unowned_sheet", ("any_column",))

    with pytest.raises(cl.CanonicalMappingError, match="no declared initialisation contract"):
        cl.load_canonical_contract_sheet("unowned_sheet", workbook=workbook)


def test_rollup_schema_break_is_not_silently_converted_to_empty_rules(tmp_path: Path) -> None:
    sheet_name = cl.SHEET_LEAP_ROLLUP_RULES
    required = cl.CANONICAL_SHEET_CONTRACT[sheet_name]
    workbook = tmp_path / "canonical.xlsx"
    _write_workbook(workbook, sheet_name, ("renamed_include", *[c for c in required if c != "include"]))

    with pytest.raises(cl.CanonicalMappingError, match=r"leap_rollup_rules.*include"):
        cl.load_canonical_contract_sheet(sheet_name, workbook=workbook)

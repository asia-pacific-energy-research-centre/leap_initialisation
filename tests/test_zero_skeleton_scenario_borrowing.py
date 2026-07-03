#%%
"""Cross-scenario borrowing for all-zero share groups and zero-skeleton records."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import complete_canonical_share_groups
from codebase.functions.transformation_record_builder import (
    _is_excluded_transformation_record,
    borrow_zero_skeleton_measures,
    build_process_record,
    build_zero_skeleton_record,
)


def test_excluded_zero_skeleton_is_identified_before_name_resolution() -> None:
    record = {"sector_title": "09.10 Biofuels processing", "is_zero_skeleton": True}
    assert _is_excluded_transformation_record(record)


def _row(path: str, variable: str, expression: str, *, scenario: str = "Reference") -> dict[str, object]:
    return {
        "BranchID": 1,
        "VariableID": 2,
        "ScenarioID": 3,
        "RegionID": 1,
        "Branch Path": path,
        "Variable": variable,
        "Scenario": scenario,
        "Region": "United States",
        "Scale": "",
        "Units": "Percent" if "Share" in variable else "Gigajoules/Year",
        "Per...": "",
        "Expression": expression,
        "source_workflow": "test_producer",
        "source_file": "test.xlsx",
    }


def _write_template(path: Path, rows: list[dict[str, object]]) -> None:
    canonical = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item.update({"BranchID": index, "VariableID": 100 + index, "ScenarioID": 2, "RegionID": 1})
        item["Region"] = "United States of America"
        canonical.append(item)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(canonical).to_excel(writer, sheet_name="Export", index=False, startrow=2)


def _values(expression: str) -> dict[int, float]:
    tokens = expression.removeprefix("Data(").removesuffix(")").split(",")
    return {int(tokens[index]): float(tokens[index + 1]) for index in range(0, len(tokens), 2)}


def test_all_zero_group_borrows_profile_from_other_scenario(tmp_path: Path) -> None:
    parent = "Transformation\\Plant\\Processes"
    ref_a = _row(f"{parent}\\A", "Process Share", "Data(2023,30,2024,30)")
    ref_b = _row(f"{parent}\\B", "Process Share", "Data(2023,70,2024,70)")
    tgt_a = _row(f"{parent}\\A", "Process Share", "Data(2023,0,2024,0)", scenario="Target")
    tgt_b = _row(f"{parent}\\B", "Process Share", "Data(2023,0,2024,0)", scenario="Target")
    tgt_cap_a = _row(f"{parent}\\A", "Exogenous Capacity", "Data(2023,0,2024,0)", scenario="Target")
    tgt_cap_b = _row(f"{parent}\\B", "Exogenous Capacity", "Data(2023,0,2024,0)", scenario="Target")
    template = tmp_path / "template.xlsx"
    _write_template(template, [ref_a, ref_b, tgt_a, tgt_b, tgt_cap_a, tgt_cap_b])

    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([ref_a, ref_b, tgt_a, tgt_b, tgt_cap_a, tgt_cap_b]),
        template_path=template,
        required_years_by_scenario={"Reference": [2023, 2024], "Target": [2023, 2024]},
    )

    target_rows = completed[
        completed["Scenario"].eq("Target") & completed["Variable"].eq("Process Share")
    ]
    values = {
        row["Branch Path"].rsplit("\\", 1)[-1]: _values(row["Expression"])
        for _, row in target_rows.iterrows()
    }
    assert values["A"] == pytest.approx({2023: 30.0, 2024: 30.0})
    assert values["B"] == pytest.approx({2023: 70.0, 2024: 70.0})
    assert diagnostics["message"].str.contains("Borrowed normalized share profile").any()
    # Reference keeps its genuine profile untouched.
    reference_rows = completed[
        completed["Scenario"].eq("Reference") & completed["Variable"].eq("Process Share")
    ]
    ref_values = {
        row["Branch Path"].rsplit("\\", 1)[-1]: _values(row["Expression"])
        for _, row in reference_rows.iterrows()
    }
    assert ref_values["A"] == pytest.approx({2023: 30.0, 2024: 30.0})
    assert ref_values["B"] == pytest.approx({2023: 70.0, 2024: 70.0})


def test_all_zero_group_without_donor_uses_synthetic_anchor(tmp_path: Path) -> None:
    parent = "Transformation\\Plant\\Processes"
    tgt_a = _row(f"{parent}\\A", "Process Share", "Data(2023,0)", scenario="Target")
    tgt_b = _row(f"{parent}\\B", "Process Share", "Data(2023,0)", scenario="Target")
    tgt_cap_a = _row(f"{parent}\\A", "Exogenous Capacity", "Data(2023,0)", scenario="Target")
    tgt_cap_b = _row(f"{parent}\\B", "Exogenous Capacity", "Data(2023,0)", scenario="Target")
    template = tmp_path / "template.xlsx"
    _write_template(template, [tgt_a, tgt_b, tgt_cap_a, tgt_cap_b])

    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([tgt_a, tgt_b, tgt_cap_a, tgt_cap_b]),
        template_path=template,
        required_years_by_scenario={"Target": [2023]},
    )
    target_rows = completed[
        completed["Scenario"].eq("Target") & completed["Variable"].eq("Process Share")
    ]
    values = {
        row["Branch Path"].rsplit("\\", 1)[-1]: _values(row["Expression"])
        for _, row in target_rows.iterrows()
    }
    assert values["A"] == {2023: 100.0}
    assert values["B"] == {2023: 0.0}
    assert diagnostics["message"].str.contains("synthetic share anchor").any()


def test_borrow_zero_skeleton_measures_copies_inert_values() -> None:
    skeleton = build_zero_skeleton_record(
        "20_USA", "Hydrogen transformation", "SMR with CCS", ["h2"], 2022, 2024,
    )
    genuine = build_process_record(
        economy="20_USA",
        sector_title="Hydrogen transformation",
        process_name="SMR with CCS",
        output_values={"h2": {2022: 5.0}},
        feedstock_values={},
        efficiency=45.9,
        auxiliary_ratios={"gas": 0.1},
        loss_values={},
        loss_total=0.0,
    )
    records = {"Target": [skeleton], "Reference": [genuine]}
    borrowed = borrow_zero_skeleton_measures(records)
    assert borrowed == 1
    assert skeleton["efficiency"] == 45.9
    assert skeleton["auxiliary_ratios"] == {"gas": 0.1}
    assert skeleton["borrowed_measures_from_scenario"] == "Reference"
    # Genuine record untouched; skeleton without donor keeps its placeholder.
    assert genuine.get("borrowed_measures_from_scenario") is None
    lone = build_zero_skeleton_record(
        "20_USA", "Hydrogen transformation", "Electrolysers", ["h2"], 2022, 2024,
    )
    assert borrow_zero_skeleton_measures({"Target": [lone]}) == 0
    assert lone["efficiency"] == 1.0

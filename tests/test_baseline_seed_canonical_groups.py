#%%
"""Canonical share completion, fallback-capacity, and atomic-patch tests."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import (
    complete_canonical_share_groups,
    validate_seed_rows,
)
from codebase.functions.patch_baseline_seeds import _assert_atomic_canonical_share_groups


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


def test_output_share_completion_normalizes_and_uses_nearest_profile(tmp_path: Path) -> None:
    parent = "Transformation\\Transfers unallocated\\Output Fuels"
    output_a = _row(f"{parent}\\Additives and oxygenates", "Output Share", "Data(2022,0,2023,20,2024,80)")
    output_b = _row(f"{parent}\\LPG", "Output Share", "Data(2022,0,2023,30,2024,120)")
    output_c = _row(f"{parent}\\Naphtha", "Output Share", "Data(2022,0,2023,0,2024,0)")
    template = tmp_path / "template.xlsx"
    _write_template(template, [output_a, output_b, output_c])

    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([output_a, output_b]),
        template_path=template,
        required_years_by_scenario={"Reference": [2022, 2023, 2024]},
    )

    assert set(completed["Branch Path"]) == {output_a["Branch Path"], output_b["Branch Path"], output_c["Branch Path"]}
    by_leaf = {
        path.rsplit("\\", 1)[-1]: _values(expression)
        for path, expression in zip(completed["Branch Path"], completed["Expression"])
    }
    assert by_leaf["Additives and oxygenates"] == pytest.approx({2022: 40, 2023: 40, 2024: 40})
    assert by_leaf["LPG"] == pytest.approx({2022: 60, 2023: 60, 2024: 60})
    assert by_leaf["Naphtha"] == pytest.approx({2022: 0, 2023: 0, 2024: 0})
    assert diagnostics["message"].str.contains("explicit zero").any()
    assert diagnostics["message"].str.contains("nearest genuine").any()


@pytest.mark.parametrize(
    ("variable", "parent", "capacity_path"),
    [
        ("Process Share", "Transformation\\Plant\\Processes", "Transformation\\Plant\\Processes\\A"),
        ("Feedstock Fuel Share", "Transformation\\Plant\\Processes\\A\\Feedstock Fuels", "Transformation\\Plant\\Processes\\A"),
    ],
)
def test_zero_capacity_allows_deterministic_complete_share_fallback(
    tmp_path: Path,
    variable: str,
    parent: str,
    capacity_path: str,
) -> None:
    rows = [
        _row(f"{parent}\\B", variable, "Data(2023,0,2024,0)"),
        _row(f"{parent}\\A", variable, "Data(2023,0,2024,0)"),
    ]
    capacity = _row(capacity_path, "Exogenous Capacity", "Data(2023,0,2024,0)")
    template = tmp_path / "template.xlsx"
    _write_template(template, [*rows, capacity])
    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([*reversed(rows), capacity]),
        template_path=template,
        required_years_by_scenario={"Reference": [2023, 2024]},
    )
    share_rows = completed[completed["Variable"].eq(variable)]
    values = {row["Branch Path"].rsplit("\\", 1)[-1]: _values(row["Expression"]) for _, row in share_rows.iterrows()}
    assert values["A"] == {2023: 100.0, 2024: 100.0}
    assert values["B"] == {2023: 0.0, 2024: 0.0}
    assert diagnostics["message"].str.contains("synthetic share anchor").any()


def test_explicitly_nonzero_capacity_blocks_fallback(tmp_path: Path) -> None:
    parent = "Transformation\\Plant\\Processes\\A\\Feedstock Fuels"
    share = _row(f"{parent}\\Gas", "Feedstock Fuel Share", "Data(2023,0)")
    capacity = _row("Transformation\\Plant\\Processes\\A", "Exogenous Capacity", "Data(2023,1)")
    template_rows = [share, capacity]
    template = tmp_path / "template.xlsx"
    _write_template(template, template_rows)
    _, diagnostics = complete_canonical_share_groups(
        pd.DataFrame(template_rows),
        template_path=template,
        required_years_by_scenario={"Reference": [2023]},
    )
    assert diagnostics["blocking"].fillna(False).any()
    assert diagnostics["message"].str.contains("fallback is blocked").any()


@pytest.mark.parametrize("efficiency_expression", [None, "", "not parseable"])
def test_nonzero_capacity_requires_usable_process_efficiency(
    efficiency_expression: str | None,
) -> None:
    process = "Transformation\\Plant\\Processes\\A"
    capacity = _row(process, "Exogenous Capacity", "Data(2023,1)")
    rows = [capacity]
    if efficiency_expression is not None:
        rows.append(_row(process, "Process Efficiency", efficiency_expression))

    validation = validate_seed_rows(pd.DataFrame(rows))
    findings = validation.findings[validation.findings["rule_id"].eq("SEED-013")]

    assert len(findings) == 1
    assert findings.iloc[0]["blocking"]
    assert "no usable Process Efficiency" in findings.iloc[0]["message"]


def test_nonzero_capacity_accepts_explicit_process_efficiency() -> None:
    process = "Transformation\\Plant\\Processes\\A"
    rows = [
        _row(process, "Exogenous Capacity", "Data(2023,1)"),
        _row(process, "Process Efficiency", "Data(2023,0)"),
    ]

    validation = validate_seed_rows(pd.DataFrame(rows))
    findings = validation.findings[validation.findings["rule_id"].eq("SEED-013")]

    assert len(findings) == 1
    assert findings.iloc[0]["status"] == "pass"


def test_process_efficiency_must_match_capacity_scenario_and_region() -> None:
    process = "Transformation\\Plant\\Processes\\A"
    capacity = _row(process, "Exogenous Capacity", "Data(2023,1)", scenario="Target")
    efficiency = _row(process, "Process Efficiency", "Data(2023,100)")
    efficiency["Region"] = "Canada"

    validation = validate_seed_rows(pd.DataFrame([capacity, efficiency]))
    findings = validation.findings[validation.findings["rule_id"].eq("SEED-013")]

    assert len(findings) == 1
    assert findings.iloc[0]["blocking"]


def test_zero_or_nonprocess_capacity_does_not_require_efficiency() -> None:
    rows = [
        _row("Transformation\\Plant\\Processes\\A", "Exogenous Capacity", "Data(2023,0)"),
        _row("Resources\\Gas", "Exogenous Capacity", "Data(2023,1)"),
    ]

    validation = validate_seed_rows(pd.DataFrame(rows))

    assert validation.findings.empty or not validation.findings["rule_id"].eq("SEED-013").any()


@pytest.mark.parametrize("capacity_expression", ["", "not parseable"])
def test_unavailable_capacity_still_gets_deterministic_fallback(
    tmp_path: Path,
    capacity_expression: str,
) -> None:
    """When no owning capacity data exists at all, share activity is the only
    signal available. An inactive share group with unavailable capacity must
    still resolve to a valid, importable profile rather than blocking forever
    on a fact the generator never had a chance to record."""
    parent = "Transformation\\Plant\\Processes\\A\\Feedstock Fuels"
    share = _row(f"{parent}\\Gas", "Feedstock Fuel Share", "Data(2023,0)")
    template_rows = [share]
    candidate_rows = [share]
    if capacity_expression:
        capacity = _row("Transformation\\Plant\\Processes\\A", "Exogenous Capacity", capacity_expression)
        template_rows.append(capacity)
        candidate_rows.append(capacity)
    template = tmp_path / "template.xlsx"
    _write_template(template, template_rows)
    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame(candidate_rows),
        template_path=template,
        required_years_by_scenario={"Reference": [2023]},
    )
    assert not diagnostics["blocking"].fillna(False).any()
    assert diagnostics["message"].str.contains("synthetic share anchor").any()
    share_row = completed[completed["Variable"].eq("Feedstock Fuel Share")].iloc[0]
    assert _values(share_row["Expression"]) == {2023: 100.0}


def test_noncanonical_sibling_is_removed_and_remaining_group_sums_to_100(tmp_path: Path) -> None:
    """A generated sibling absent from the full-model export (e.g. a fuel that
    was never a valid input to this process, or a label mangled by a mapping
    bug) has no valid LEAP branch to import into. It must be dropped from the
    exported group -- not left in place diluting the canonical siblings'
    shares -- and the canonical siblings must still sum to 100."""
    parent = "Transformation\\Gas works plants\\Processes\\Gas works plants\\Feedstock Fuels"
    canonical_a = _row(f"{parent}\\Natural gas", "Feedstock Fuel Share", "Data(2023,60)")
    canonical_b = _row(f"{parent}\\Coal tar", "Feedstock Fuel Share", "Data(2023,40)")
    noncanonical = _row(f"{parent}\\PetProd nonspecified", "Feedstock Fuel Share", "Data(2023,25)")
    template = tmp_path / "template.xlsx"
    _write_template(template, [canonical_a, canonical_b])

    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([canonical_a, canonical_b, noncanonical]),
        template_path=template,
        required_years_by_scenario={"Reference": [2023]},
    )

    assert set(completed["Branch Path"]) == {canonical_a["Branch Path"], canonical_b["Branch Path"]}
    by_leaf = {
        path.rsplit("\\", 1)[-1]: _values(expression)
        for path, expression in zip(completed["Branch Path"], completed["Expression"])
    }
    assert sum(by_leaf["Natural gas"].values()) + sum(by_leaf["Coal tar"].values()) == pytest.approx(100.0)
    assert diagnostics["message"].str.contains("noncanonical sibling").any()

    validation = validate_seed_rows(completed, template_path=template)
    assert not validation.blocking_findings["rule_id"].isin({"SEED-006", "SEED-007", "SEED-008"}).any()


def test_partial_group_validation_and_patch_both_block(tmp_path: Path) -> None:
    parent = "Transformation\\Plant\\Output Fuels"
    rows = [
        _row(f"{parent}\\A", "Output Share", "Data(2023,100)"),
        _row(f"{parent}\\B", "Output Share", "Data(2023,0)"),
    ]
    template = tmp_path / "template.xlsx"
    _write_template(template, rows)
    partial = pd.DataFrame(rows[:1])

    validation = validate_seed_rows(partial, template_path=template)
    assert validation.blocking_findings["message"].str.contains("partial or noncanonical").any()
    with pytest.raises(ValueError, match="Partial canonical share-group patch"):
        _assert_atomic_canonical_share_groups(partial, template)


def test_ignored_full_model_export_leaf_is_skipped_in_canonical_share_checks(tmp_path: Path) -> None:
    parent = "Transformation\\Transfers unallocated\\Output Fuels"
    canonical_a = _row(f"{parent}\\Additives and oxygenates", "Output Share", "Data(2023,55)")
    canonical_b = _row(f"{parent}\\LPG", "Output Share", "Data(2023,45)")
    ignored = _row(f"{parent}\\ABC DO NOT USE", "Output Share", "Data(2023,0)")
    template = tmp_path / "template.xlsx"
    _write_template(template, [canonical_a, canonical_b, ignored])

    completed, diagnostics = complete_canonical_share_groups(
        pd.DataFrame([canonical_a, canonical_b]),
        template_path=template,
        required_years_by_scenario={"Reference": [2023]},
    )

    assert set(completed["Branch Path"]) == {canonical_a["Branch Path"], canonical_b["Branch Path"]}
    assert not diagnostics["message"].str.contains("partial or noncanonical", case=False).any()
    _assert_atomic_canonical_share_groups(pd.DataFrame([canonical_a, canonical_b]), template)


def test_ignored_full_model_export_branch_is_skipped_in_presence_validation(tmp_path: Path) -> None:
    ignored = _row("Transformation\\Transfers unallocated\\Output Fuels\\ABC DO NOT USE", "Output Share", "Data(2023,0)")
    template = tmp_path / "template.xlsx"
    _write_template(template, [_row("Resources\\Primary\\Gas", "Imports", "Data(2023,1)")])

    validation = validate_seed_rows(pd.DataFrame([ignored]), template_path=template)
    assert not validation.findings["rule_id"].eq("SEED-011").any()


#%%

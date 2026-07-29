#%%
"""Focused tests for opt-in final baseline-seed expression overrides."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from codebase.functions import supply_leap_io
from codebase.functions.baseline_seed_postprocess import (
    apply_postprocess_rules,
    load_postprocess_excluded_branch_paths,
    load_postprocess_rules,
    validate_postprocess_rule,
)


PROCESS_PATH = r"Transformation\Oil Refining\Processes\Oil Refining"
COAL_CHP_PATH = r"Transformation\CHP plants\Processes\Coal CHP"


def _template_rows(*, target_value: float = 90.0) -> pd.DataFrame:
    rows = []
    for scenario, scenario_id, value in (
        ("Reference", 2, 100.0),
        ("Target", 3, target_value),
    ):
        rows.append(
            {
                "BranchID": 10,
                "VariableID": 20,
                "ScenarioID": scenario_id,
                "RegionID": 1,
                "Branch Path": PROCESS_PATH,
                "Variable": "Maximum Availability",
                "Scenario": scenario,
                "Region": "United States of America",
                "Scale": "",
                "Units": "Percent",
                "Per...": "",
                2023: value,
                2024: value,
            }
        )
    return pd.DataFrame(rows)


def _rule(**updates) -> dict[str, object]:
    rule: dict[str, object] = {
        "rule_id": "oil_refining_availability",
        "enabled": True,
        "economies": ["20_USA"],
        "branch_path_equals": PROCESS_PATH,
        "variable_equals": "Maximum Availability",
        "scenarios": ["Target"],
        "template_value_not_equal_to": 100,
        "replacement_expression": "100",
    }
    rule.update(updates)
    return rule


def test_rule_inserts_only_triggering_template_row() -> None:
    seed = pd.DataFrame(
        [
            {
                "Branch Path": r"Resources\Primary\Crude oil",
                "Variable": "Production",
                "Scenario": "Target",
                "Region": "United States of America",
                "Expression": "Data(2023,1)",
            }
        ]
    )

    result, audit = apply_postprocess_rules(
        seed,
        _template_rows(),
        [_rule()],
        economy="20_USA",
        config_path="rules.json",
    )

    inserted = result[result["Variable"].eq("Maximum Availability")]
    assert len(inserted) == 1
    assert inserted.iloc[0]["Scenario"] == "Target"
    assert inserted.iloc[0]["Expression"] == "100"
    assert pd.isna(inserted.iloc[0][2023])
    assert audit.iloc[0]["action"] == "insert"
    assert json.loads(audit.iloc[0]["template_differing_year_values"]) == {
        "2023": 90.0,
        "2024": 90.0,
    }


def test_rule_replaces_existing_logical_key() -> None:
    existing = _template_rows().iloc[[1]].copy()
    existing["Expression"] = "Data(2023,90)"

    result, audit = apply_postprocess_rules(
        existing,
        _template_rows(),
        [_rule()],
        economy="20_USA",
        config_path="rules.json",
    )

    matching = result[
        result["Branch Path"].eq(PROCESS_PATH)
        & result["Variable"].eq("Maximum Availability")
        & result["Scenario"].eq("Target")
    ]
    assert len(matching) == 1
    assert matching.iloc[0]["Expression"] == "100"
    assert audit.iloc[0]["action"] == "replace"
    assert audit.iloc[0]["previous_expression"] == "Data(2023,90)"


def test_rule_does_not_insert_when_template_already_has_expected_value() -> None:
    result, audit = apply_postprocess_rules(
        pd.DataFrame(columns=["Branch Path", "Variable", "Scenario", "Region"]),
        _template_rows(target_value=100.0),
        [_rule()],
        economy="20_USA",
        config_path="rules.json",
    )

    assert result.empty
    assert audit.empty


def test_branch_substring_and_variable_can_select_without_exact_path() -> None:
    substring_rule = _rule(
        branch_path_equals=[],
        branch_path_contains=[r"Transformation\Oil Refining", "\\Processes\\"],
    )
    result, audit = apply_postprocess_rules(
        pd.DataFrame(columns=["Branch Path", "Variable", "Scenario", "Region"]),
        _template_rows(),
        [substring_rule],
        economy="20_USA",
        config_path="rules.json",
    )

    assert len(result) == 1
    assert len(audit) == 1


def test_economy_filter_prevents_cross_economy_override() -> None:
    result, audit = apply_postprocess_rules(
        pd.DataFrame(columns=["Branch Path", "Variable", "Scenario", "Region"]),
        _template_rows(),
        [_rule(require_match=True)],
        economy="01_AUS",
        config_path="rules.json",
    )

    assert result.empty
    assert audit.empty


def test_excluded_branch_path_prevents_automatic_override() -> None:
    template = _template_rows()
    template.loc[:, "Branch Path"] = COAL_CHP_PATH
    broad_rule = _rule(
        branch_path_equals=[],
        branch_path_contains=r"Transformation\CHP plants\Processes",
    )

    result, audit = apply_postprocess_rules(
        pd.DataFrame(columns=["Branch Path", "Variable", "Scenario", "Region"]),
        template,
        [broad_rule],
        economy="20_USA",
        config_path="rules.json",
        excluded_branch_paths=[COAL_CHP_PATH],
    )

    assert result.empty
    assert audit.empty


def test_load_rules_and_reject_ambiguous_rule(tmp_path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"version": 1, "rules": [_rule()]}),
        encoding="utf-8",
    )

    loaded = load_postprocess_rules(path)
    assert loaded[0]["rule_id"] == "oil_refining_availability"

    with pytest.raises(ValueError, match="must constrain"):
        validate_postprocess_rule(
            {
                "rule_id": "unsafe_global",
                "replacement_expression": "100",
            }
        )


def test_load_excluded_branch_paths_from_configured_workbook(tmp_path) -> None:
    workbook_path = tmp_path / "new leap rows.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            {"Branch Path": [COAL_CHP_PATH, r"Transformation\CHP plants"]}
        ).to_excel(writer, sheet_name="power", index=False)

    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "excluded_branch_path_workbooks": [
                    {
                        "path": workbook_path.name,
                        "sheets": ["power"],
                        "branch_path_column": "Branch Path",
                    }
                ],
                "rules": [],
            }
        ),
        encoding="utf-8",
    )

    excluded = load_postprocess_excluded_branch_paths(path)

    assert excluded == {
        COAL_CHP_PATH,
        r"Transformation\CHP plants",
    }


def test_final_seed_writer_applies_enabled_postprocess_rule(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_row = {
        "BranchID": -1,
        "VariableID": -1,
        "ScenarioID": -1,
        "RegionID": -1,
        "Branch Path": r"Resources\Primary\Natural gas",
        "Variable": "Imports",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "",
        "Expression": "Data(2023,1)",
    }
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    source_columns = list(source_row)
    preamble = {column: pd.NA for column in source_columns}
    preamble["Branch Path"] = "Area:"
    preamble["Scenario"] = "Ver:"
    preamble["Region"] = "2"
    source_frame = pd.concat(
        [
            pd.DataFrame([preamble]),
            pd.DataFrame([{column: pd.NA for column in source_columns}]),
            pd.DataFrame([source_columns], columns=source_columns),
            pd.DataFrame([source_row]),
        ],
        ignore_index=True,
    )
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        source_frame.to_excel(writer, sheet_name="LEAP", index=False, header=False)

    template_rows = _template_rows()
    canonical_source = dict(source_row)
    canonical_source.update(
        {
            "BranchID": 101,
            "VariableID": 201,
            "ScenarioID": 2,
            "RegionID": 1,
            2023: 1.0,
            2024: 1.0,
        }
    )
    template = tmp_path / "USA template.xlsx"
    with pd.ExcelWriter(template, engine="openpyxl") as writer:
        pd.concat(
            [pd.DataFrame([canonical_source]), template_rows],
            ignore_index=True,
            sort=False,
        ).to_excel(writer, sheet_name="Export", index=False, startrow=2)

    config_path = tmp_path / "postprocess.json"
    config_path.write_text(
        json.dumps({"version": 1, "rules": [_rule()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(supply_leap_io, "APPLY_BASELINE_SEED_POSTPROCESS_RULES", True)
    monkeypatch.setattr(
        supply_leap_io,
        "BASELINE_SEED_POSTPROCESS_RULES_PATH",
        config_path,
    )
    monkeypatch.setattr(
        supply_leap_io,
        "_load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        supply_leap_io,
        "run_export_readiness",
        lambda *args, **kwargs: type(
            "Readiness",
            (),
            {"blocking_failures": 0, "findings": pd.DataFrame()},
        )(),
    )

    written = supply_leap_io.write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        required_years_by_scenario={"Reference": [2023], "Target": [2023]},
    )

    assert len(written) == 1
    final = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    override = final[
        final["Branch Path"].eq(PROCESS_PATH)
        & final["Variable"].eq("Maximum Availability")
        & final["Scenario"].eq("Target")
    ]
    assert len(override) == 1
    assert str(override.iloc[0]["Expression"]) == "100"
    audit_paths = list(
        (tmp_path / "output" / "supporting_files" / "baseline_seed_validation").glob(
            "*_postprocess_overrides.csv"
        )
    )
    assert len(audit_paths) == 1
    assert pd.read_csv(audit_paths[0]).iloc[0]["action"] == "insert"


#%%

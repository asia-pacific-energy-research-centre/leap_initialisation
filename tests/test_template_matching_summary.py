"""[19] docs/work_queue.md: consolidated, filtered template-matching diagnostics.

Pure-function tests for
``codebase.functions.supply_results_saver.filter_actionable_mapping_config_mismatches``
and ``build_template_matching_summary``. Neither reads production ESTO/9th
data or acquires an economy run lock; safe alongside a live run.
"""
from __future__ import annotations

import pandas as pd

from codebase.functions.supply_results_saver import (
    build_template_matching_summary,
    filter_actionable_mapping_config_mismatches,
)


def _mapping_mismatch_row(**overrides: object) -> dict[str, object]:
    row = {
        "match_scope": "branch_variable",
        "branch_path": "Resources\\Primary\\Crude Oil",
        "variable": "Maximum Production",
        "field": "units",
        "config_value": "Gigajoule",
        "reference_values": "Petajoule",
        "issue": "config_reference_mismatch",
    }
    row.update(overrides)
    return row


def test_no_reference_value_rows_are_filtered() -> None:
    rows = pd.DataFrame(
        [
            _mapping_mismatch_row(),
            _mapping_mismatch_row(
                branch_path="Key\\Macro\\GDP",
                variable="Activity Level",
                config_value="Dollars",
                reference_values="",
                issue="reference_value_missing",
            ),
        ]
    )
    filtered = filter_actionable_mapping_config_mismatches(rows)
    assert list(filtered["issue"]) == ["config_reference_mismatch"]


def test_excluded_variable_rows_are_filtered() -> None:
    rows = pd.DataFrame(
        [
            _mapping_mismatch_row(),
            _mapping_mismatch_row(
                variable="Endogenous Capacity",
                issue="config_reference_mismatch",
            ),
        ]
    )
    filtered = filter_actionable_mapping_config_mismatches(rows)
    assert list(filtered["variable"]) == ["Maximum Production"]


def test_excluded_variable_match_is_case_and_whitespace_insensitive() -> None:
    rows = pd.DataFrame([_mapping_mismatch_row(variable="  endogenous capacity  ")])
    filtered = filter_actionable_mapping_config_mismatches(rows)
    assert filtered.empty


def test_populated_reference_workflow_owned_row_is_retained() -> None:
    rows = pd.DataFrame([_mapping_mismatch_row()])
    filtered = filter_actionable_mapping_config_mismatches(rows)
    assert len(filtered) == 1
    assert filtered.iloc[0]["branch_path"] == "Resources\\Primary\\Crude Oil"


def test_filter_accepts_custom_excluded_variables() -> None:
    rows = pd.DataFrame([_mapping_mismatch_row(variable="Custom Unowned Variable")])
    filtered = filter_actionable_mapping_config_mismatches(
        rows, excluded_variables=("Custom Unowned Variable",)
    )
    assert filtered.empty


def test_filter_handles_empty_and_non_dataframe_input() -> None:
    assert filter_actionable_mapping_config_mismatches(pd.DataFrame()).empty
    assert filter_actionable_mapping_config_mismatches(None).empty


def test_summary_concatenates_all_three_sources_with_provenance() -> None:
    unmatched_id_rows = pd.DataFrame(
        [
            {
                "Branch Path": "Transformation\\Coke ovens\\...\\Coke oven gas",
                "Variable": "Feedstock Fuel Share",
                "Scenario": "Target",
                "Region": "Brunei Darussalam",
                "reason": "no_verification_export_id_match",
            }
        ]
    )
    metadata_mismatch_rows = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Other loss and own use\\...\\Electricity",
                "Variable": "Activity Level",
                "Scenario": "Reference",
                "Region": "United States",
                "column": "Units",
                "generated_value": "Unspecified Unit",
                "reference_value": "Share",
            }
        ]
    )
    mapping_config_mismatch_rows = pd.DataFrame(
        [
            _mapping_mismatch_row(),
            _mapping_mismatch_row(
                variable="Endogenous Capacity", issue="config_reference_mismatch"
            ),
            _mapping_mismatch_row(
                branch_path="Key\\Macro\\GDP",
                variable="Activity Level",
                reference_values="",
                issue="reference_value_missing",
            ),
        ]
    )

    summary = build_template_matching_summary(
        unmatched_id_rows=unmatched_id_rows,
        metadata_mismatch_rows=metadata_mismatch_rows,
        mapping_config_mismatch_rows=mapping_config_mismatch_rows,
    )

    # 1 unmatched-id + 1 metadata-mismatch + 1 surviving config-mismatch row
    # (the excluded-variable and no-reference rows must not appear).
    assert len(summary) == 3
    assert set(summary["source_check"]) == {
        "unmatched_id",
        "metadata_mismatch",
        "config_mapping_mismatch",
    }
    assert "Endogenous Capacity" not in set(summary["variable"])
    assert "reference_value_missing" not in set(summary["issue"])
    # Every row is traceable back to its detailed source file's category.
    by_source = dict(zip(summary["source_check"], summary["branch_path"]))
    assert by_source["unmatched_id"].startswith("Transformation")
    assert by_source["metadata_mismatch"].startswith("Demand")
    assert by_source["config_mapping_mismatch"].startswith("Resources")


def test_summary_is_empty_when_all_sources_are_empty() -> None:
    summary = build_template_matching_summary(
        unmatched_id_rows=pd.DataFrame(),
        metadata_mismatch_rows=pd.DataFrame(),
        mapping_config_mismatch_rows=pd.DataFrame(),
    )
    assert summary.empty
    assert list(summary.columns) == [
        "source_check",
        "branch_path",
        "variable",
        "scenario",
        "region",
        "field",
        "value",
        "reference_value",
        "issue",
    ]

#%%
"""Focused tests for validation at the final baseline-seed workbook writer."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import (
    BaselineSeedValidationError,
    build_branch_issue_summary,
    build_validation_issue_groups,
    filter_actionable_findings,
    prepare_seed_rows_for_write,
    validate_seed_rows,
)
from codebase.supply_reconciliation.leap_io import (
    _baseline_seed_filename,
    _format_blocking_summary,
    save_combined_supply_transformation_export,
    write_per_economy_combined_workbooks,
)
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.configuration.workflow_config import get_baseline_seed_validation_years


def test_baseline_seed_filename_marks_comp_gen_templates() -> None:
    assert _baseline_seed_filename(
        "02_BD",
        "20260721",
        Path("leap_export_template 02_BD_COMP_GEN.xlsx"),
    ) == "leap_import_baseline_seed_02_BD_PRELIM_20260721.xlsx"
    assert _baseline_seed_filename(
        "01_AUS",
        "20260721",
        Path("leap_export_template 01_AUS.xlsx"),
    ) == "leap_import_baseline_seed_01_AUS_20260721.xlsx"


def test_blocking_summary_uses_missing_branch_group_once() -> None:
    blocking = pd.DataFrame(
        [
            {"rule_id": "SEED-003"},
            {"rule_id": "SEED-004"},
            {"rule_id": "SEED-011"},
        ]
    )
    issue_groups = pd.DataFrame(
        [
            {
                "issue_group_type": "missing_branch",
                "member_rule_ids": "SEED-003|SEED-004|SEED-011",
            }
        ]
    )

    summary = _format_blocking_summary(
        blocking=blocking,
        issue_groups=issue_groups,
    )

    assert summary == "groups: missing_branch=1"


def _row(expression: str) -> dict[str, object]:
    return {
        "BranchID": -1,
        "VariableID": -1,
        "ScenarioID": -1,
        "RegionID": -1,
        "Branch Path": "Resources\\Primary\\Natural gas",
        "Variable": "Imports",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "",
        "Expression": expression,
    }


def _write_leap_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    columns = list(rows[0])
    preamble = {column: pd.NA for column in columns}
    preamble["Branch Path"] = "Area:"
    preamble["Scenario"] = "Ver:"
    preamble["Region"] = "2"
    full = pd.concat(
        [
            pd.DataFrame([preamble]),
            pd.DataFrame([{column: pd.NA for column in columns}]),
            pd.DataFrame([columns], columns=columns),
            pd.DataFrame(rows),
        ],
        ignore_index=True,
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        full.to_excel(writer, sheet_name="LEAP", index=False, header=False)


def test_persisted_findings_keep_only_actionable_statuses() -> None:
    findings = pd.DataFrame([
        {"rule_id": "SEED-006", "status": "info", "severity": "error", "blocking": False},
        {"rule_id": "SEED-006", "status": "pass", "severity": "error", "blocking": False},
        {"rule_id": "SEED-009", "status": "warn", "severity": "warning", "blocking": False},
        {"rule_id": "SEED-003", "status": "fail", "severity": "error", "blocking": True},
    ])

    actionable = filter_actionable_findings(findings)

    assert actionable["rule_id"].tolist() == ["SEED-009", "SEED-003"]


def test_unlimited_expression_is_not_a_year_coverage_failure() -> None:
    data = pd.DataFrame([{
        "Branch Path": "Resources\\Primary\\Geothermal",
        "Variable": "Maximum Production",
        "Scenario": "Reference",
        "Region": "Australia",
        "Expression": "Unlimited",
    }])

    result = validate_seed_rows(
        data,
        required_years_by_scenario={"Reference": list(range(2023, 2061))},
    )

    assert not result.findings["rule_id"].eq("SEED-009").any()


@pytest.mark.parametrize(
    "branch_path,variable",
    [
        ("Stock Changes\\Primary\\Natural gas", "Stock Changes"),
        (
            "Statistical Differences\\Primary\\Natural gas",
            "Statistical Differences",
        ),
    ],
)
def test_nonzero_balance_roots_missing_from_template_are_blocking(
    tmp_path: Path,
    branch_path: str,
    variable: str,
) -> None:
    template = tmp_path / "template.xlsx"
    _write_template(template)
    row = _row("1.5")
    row.update({"Branch Path": branch_path, "Variable": variable})

    result = validate_seed_rows(pd.DataFrame([row]), template_path=template)
    findings = result.findings[
        result.findings["rule_id"].isin(["SEED-003", "SEED-004", "SEED-011"])
    ]

    assert set(findings["status"]) == {"fail"}
    assert findings["blocking"].all()


@pytest.mark.parametrize(
    "branch_path,variable",
    [
        ("Resources\\Primary\\Unused fuel", "Imports"),
        ("Stock Changes\\Primary\\Unused fuel", "Stock Change"),
        (
            "Statistical Differences\\Primary\\Unused fuel",
            "Statistical Differences",
        ),
        (
            "Transformation\\CHP interim\\Processes\\CHP interim\\Feedstock Fuels\\Petroleum coke",
            "Feedstock Fuel Share",
        ),
        (
            "Transformation\\Electricity interim\\Processes\\Electricity interim\\Feedstock Fuels\\Sub bituminous coal",
            "Feedstock Fuel Share",
        ),
    ],
)
def test_all_zero_optional_roots_do_not_require_template_branches(
    tmp_path: Path,
    branch_path: str,
    variable: str,
) -> None:
    template = tmp_path / "template.xlsx"
    _write_template(template)
    row = _row("Data(2023,0)")
    row.update({"Branch Path": branch_path, "Variable": variable})

    result = prepare_seed_rows_for_write(
        pd.DataFrame([row]),
        template_path=template,
        diagnostics_dir=tmp_path / "diagnostics",
        diagnostic_stem="optional_zero",
        required_years_by_scenario={"Reference": [2023]},
    )

    assert result.resolved_rows.empty
    assert result.findings.empty


def test_all_zero_optional_root_ignores_years_outside_scenario_payload(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template.xlsx"
    _write_template(template)
    row = _row("")
    row.update({
        "Branch Path": "Stock Changes\\Primary\\Unused fuel",
        "Variable": "Stock Change",
        2022: 0.0,
        2023: pd.NA,
        2024: pd.NA,
    })

    result = prepare_seed_rows_for_write(
        pd.DataFrame([row]),
        template_path=template,
        diagnostics_dir=tmp_path / "diagnostics",
        diagnostic_stem="optional_zero_partial_horizon",
        required_years_by_scenario={"Reference": [2022]},
    )

    assert result.resolved_rows.empty
    assert result.findings.empty


def _write_template(path: Path, *, variable_id: int = 420) -> None:
    row = _row("")
    row.update({"BranchID": 101, "VariableID": variable_id, "ScenarioID": 2, "RegionID": 1})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([row]).to_excel(
            writer, sheet_name="Export", index=False, startrow=2
        )


def _write_template_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(
            writer, sheet_name="Export", index=False, startrow=2
        )


def test_default_scenario_windows_use_2022_base_and_2060_final_year() -> None:
    windows = get_baseline_seed_validation_years(
        ["Current Accounts", "Reference", "Target"]
    )
    assert windows["Current Accounts"] == [2022]
    assert windows["Reference"][0] == 2023
    assert windows["Reference"][-1] == 2060
    assert windows["Target"] == windows["Reference"]


def test_wide_year_expression_builder_matches_float_excel_headers() -> None:
    row = pd.Series({2022.0: -11.077893, 2023.0: 0.0})

    assert build_data_expression_from_row(row, [2022]) == "Data(2022,-11.077893)"


def test_final_writer_collapses_exact_duplicates_and_populates_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference_a.xlsx"
    duplicate_source = tmp_path / "supply_leap_imports_20_USA_reference_b.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    _write_leap_workbook(duplicate_source, [_row("Data(2023, 1.0)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source, duplicate_source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    data = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert len(data) == 1
    assert data[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [101, 420, 2, 1]


def test_final_writer_runs_combined_export_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    seen: list[dict[str, object]] = []

    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    def fake_readiness(*args, **kwargs):
        kwargs["workbook_path"] = args[0]
        seen.append(kwargs)
        return type("Readiness", (), {"blocking_failures": 0, "findings": pd.DataFrame()})()

    monkeypatch.setattr("codebase.supply_reconciliation.leap_io.run_export_readiness", fake_readiness)

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    assert len(seen) == 1
    assert seen[0]["economy"] == "20_USA"
    assert seen[0]["producer"] == "per_economy_combined_workbook"
    assert seen[0]["expected_region"] == "United States"


def test_final_writer_consolidates_proxy_seed_fallback_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "other_loss_own_use_proxy_20_USA_Reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    pd.DataFrame([{
        "rule_id": "SEED-014",
        "status": "warn",
        "severity": "warning",
        "blocking": False,
        "violated_rule_expectation": "Proxy fallbacks are explicit and usable.",
        "scope": "other-loss and own-use proxy process/fuel series",
        "message": "Base-year target is unavailable; direct Ninth values are retained.",
        "evidence": "target_fallback_reason=ninth_exact_no_base_target",
        "documentation_reference": "docs/special_rules_and_design_decisions.md#init-014-other-loss-and-own-use-proxy-source-fallbacks",
        "economy": "20_USA",
        "process_key": "transmission_and_distribution_losses",
        "process_label": "Transmission and distribution losses",
        "fuel_branch_label": "Heat",
        "source_workflow": "other_loss_own_use_proxy_workflow",
        "source_file": "proxy_activity_intensity_detail.csv",
    }]).to_csv(tmp_path / "proxy_seed_rule_findings.csv", index=False)
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.run_export_readiness",
        lambda *args, **kwargs: type(
            "Readiness", (), {"blocking_failures": 0, "findings": pd.DataFrame()}
        )(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=output_dir,
        id_lookup_path=template,
        source_workbooks_by_workflow={"other_loss_own_use_proxy_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    consolidated = pd.read_csv(next(diagnostics.glob("*_consolidated_rule_findings.csv")))
    proxy = consolidated[consolidated["rule_id"].eq("SEED-014")]
    assert len(proxy) == 1
    assert proxy["status"].iloc[0] == "warn"
    assert proxy["economy"].iloc[0] == "20_USA"


def test_final_writer_runs_central_artifact_gate_after_physical_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    def fake_artifact_gate(**kwargs):
        candidate = Path(kwargs["candidate_workbooks"]["20_USA"])
        assert candidate.exists()
        seen.append(kwargs)
        return type(
            "ArtifactAudit",
            (),
            {
                "shadow_status": "SHADOW_PASS",
                "manifest_path": tmp_path / "artifact_manifest.json",
            },
        )()

    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.run_baseline_seed_artifact_validation",
        fake_artifact_gate,
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    assert len(seen) == 1
    assert seen[0]["expected_economies"] == ["20_USA"]
    assert set(seen[0]["enforcement_by_check"].values()) == {"audit"}
    assert "20_USA" in seen[0]["source_rows_by_economy"]


def test_final_writer_retains_workbook_on_combined_readiness_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.run_export_readiness",
        lambda *args, **kwargs: type(
            "Readiness", (), {"blocking_failures": 1, "findings": pd.DataFrame()}
        )(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    assert written[0].exists()


def test_final_writer_writes_diagnostics_before_conflict_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)"), _row("Data(2023,2)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS",
        False,
    )

    with pytest.raises(BaselineSeedValidationError):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={"supply_workflow": [source]},
        )

    assert not list(output_dir.glob("leap_import_baseline_seed_*.xlsx"))
    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    assert list(diagnostics.glob("*_rule_findings.csv"))
    assert list(diagnostics.glob("*_duplicate_groups.csv"))


def test_final_writer_writes_grouped_missing_branch_issue_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "electricity_heat_interim_20_USA_Target_Reference_Current_Accounts.xlsx"
    _write_leap_workbook(source, [{
        "BranchID": -1,
        "VariableID": -1,
        "ScenarioID": -1,
        "RegionID": -1,
        "Branch Path": "Transformation\\CHP interim\\Processes\\CHP interim\\Feedstock Fuels\\Petroleum coke",
        "Variable": "Imports",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "",
        "Expression": "Data(2023,1)",
    }])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr("codebase.utilities.workflow_common.THROW_ERROR_AFTER_RUN", True)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.run_export_readiness",
        lambda *args, **kwargs: type(
            "Readiness", (), {"blocking_failures": 0, "findings": pd.DataFrame()}
        )(),
    )

    write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=output_dir,
        id_lookup_path=template,
        source_workbooks_by_workflow={"electricity_heat_interim_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    issue_groups = next(diagnostics.glob("*_issue_groups.csv"))
    grouped = pd.read_csv(issue_groups)
    assert len(grouped) == 1
    assert grouped["primary_rule_id"].iloc[0] == "SEED-011"
    assert grouped["member_rule_ids"].iloc[0] == "SEED-003|SEED-004|SEED-011"
    assert "missing from the selected economy's LEAP template" in grouped["summary"].iloc[0]
    consolidated = pd.read_csv(next(diagnostics.glob("*_consolidated_rule_findings.csv")))
    standalone = consolidated[
        consolidated["source_file"].eq(str(source))
        & consolidated["Branch Path"].eq(
            "Transformation\\CHP interim\\Processes\\CHP interim\\Feedstock Fuels\\Petroleum coke"
        )
    ]
    assert set(standalone["rule_id"]) == {"SEED-003", "SEED-004", "SEED-011"}
    assert standalone["blocking"].any()
    assert set(standalone["source_workflow"]) == {"electricity_heat_interim_workflow"}


def test_missing_branch_issue_group_collapses_variables_and_scenarios() -> None:
    branch = r"Demand\All demand aggregated\International transport\Ammonia"
    findings = pd.DataFrame([
        {
            "economy": "01_AUS",
            "rule_id": rule_id,
            "blocking": False,
            "Branch Path": branch,
            "Variable": variable,
            "Scenario": scenario,
            "Region": "Australia",
            "source_workflow": "aggregated_demand_workflow",
            "source_file": "aggregated_demand_01_AUS.xlsx",
            "evidence": evidence,
        }
        for rule_id, variable, scenario, evidence in [
            ("SEED-003", "Activity Level", "Current Accounts", "BranchID"),
            ("SEED-004", "Activity Level", "Target", "nonzero"),
            ("SEED-010", "Final Energy Intensity", "", "Reference"),
            ("SEED-011", "Final Energy Intensity", "Reference", "template.xlsx"),
        ]
    ])

    grouped = build_validation_issue_groups(findings)

    assert len(grouped) == 1
    issue = grouped.iloc[0]
    assert issue["issue_group_type"] == "missing_branch"
    assert issue["Branch Path"] == branch
    assert issue["Variable"] == "Activity Level|Final Energy Intensity"
    assert issue["Scenario"] == "Current Accounts|Reference|Target"
    assert issue["member_rule_ids"] == "SEED-003|SEED-004|SEED-010|SEED-011"
    assert issue["member_count"] == 4
    assert "Code generated this branch" in issue["summary"]


def test_grouped_share_issues_collapse_to_one_issue_per_share_group() -> None:
    findings = pd.DataFrame([
        {
            "economy": "20_USA",
            "rule_id": "SEED-007",
            "blocking": True,
            "Branch Path": "Transformation\\Plant",
            "Variable": "Process Share",
            "Scenario": "Reference",
            "Region": "United States",
            "year": 2023,
            "source_workflow": "transformation_workflow",
            "source_file": "transformation_20_USA.xlsx",
            "evidence": "sum=80",
        },
        {
            "economy": "20_USA",
            "rule_id": "SEED-007",
            "blocking": True,
            "Branch Path": "Transformation\\Plant",
            "Variable": "Process Share",
            "Scenario": "Reference",
            "Region": "United States",
            "year": 2024,
            "source_workflow": "transformation_workflow",
            "source_file": "transformation_20_USA.xlsx",
            "evidence": "sum=75",
        },
    ])

    grouped = build_validation_issue_groups(findings)
    share = grouped[grouped["issue_group_type"].eq("share_group")]
    assert len(share) == 1
    assert share["primary_rule_id"].iloc[0] == "SEED-007"
    assert share["member_count"].iloc[0] == 2
    assert share["year_min"].iloc[0] == 2023
    assert share["year_max"].iloc[0] == 2024


def test_branch_issue_summary_collapses_rules_variables_and_scenarios() -> None:
    branch = r"Demand\All demand aggregated\Road\Wind"
    standalone_coverage_branch = r"Demand\All demand aggregated\Road\Solar"
    findings = pd.DataFrame([
        {
            "economy": economy,
            "rule_id": rule_id,
            "blocking": blocking,
            "Branch Path": path,
            "Variable": variable,
            "Scenario": scenario,
            "Region": "United States",
            "year": year,
            "source_workflow": "aggregated_demand_workflow",
            "source_file": f"aggregated_demand_{economy}.xlsx",
        }
        for economy, rule_id, blocking, path, variable, scenario, year in [
            ("20_USA", "SEED-003", False, branch, "Activity Level", "Reference", 2023),
            ("20_USA", "SEED-004", True, branch, "Activity Level", "Target", 2024),
            ("20_USA", "SEED-011", True, branch, "Final Energy Intensity", "Reference", 2023),
            ("20_USA", "SEED-009", True, branch, "Activity Level", "Reference", 2025),
            (
                "20_USA",
                "SEED-009",
                True,
                standalone_coverage_branch,
                "Activity Level",
                "Reference",
                2026,
            ),
            ("05_PRC", "SEED-003", True, branch, "Activity Level", "Reference", 2023),
        ]
    ])

    summary = build_branch_issue_summary(findings)

    assert len(summary) == 3
    usa_missing = summary[
        summary["economy"].eq("20_USA")
        & summary["issue_family"].eq("missing_branch_or_id")
    ].iloc[0]
    assert usa_missing["member_rule_ids"] == "SEED-003|SEED-004|SEED-009|SEED-011"
    assert usa_missing["variables"] == "Activity Level|Final Energy Intensity"
    assert usa_missing["scenarios"] == "Reference|Target"
    assert usa_missing["years"] == "2023|2024|2025"
    assert usa_missing["finding_count"] == 4
    assert usa_missing["blocking_count"] == 3
    assert usa_missing["blocking_status"] == "blocking"
    assert (
        summary[
            summary["economy"].eq("20_USA")
            & summary["issue_family"].eq("series_coverage")
            & summary["Branch Path"].eq(standalone_coverage_branch)
        ].shape[0]
        == 1
    )
    assert (
        summary[
            summary["economy"].eq("05_PRC")
            & summary["issue_family"].eq("missing_branch_or_id")
        ].shape[0]
        == 1
    )


def test_final_writer_exposes_key_scoped_zero_reset_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    expression = "Data(" + ",".join(
        token for year in range(2023, 2061) for token in (str(year), "0")
    ) + ")"
    _write_leap_workbook(source, [_row(expression)])
    template = tmp_path / "full model export.xlsx"
    _write_template(template, variable_id=-1)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        validation_exceptions=[{
            "exception_id": "TEST-ZERO-RESET",
            "rule_id": "SEED-003",
            "Variable": "Imports",
            "Branch Path": "Resources\\Primary\\Natural gas",
            "reason": "Test-only explicit exception.",
        }],
    )

    assert len(written) == 1
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert output["VariableID"].iloc[0] == -1


def test_final_writer_preserves_non_branch_ids_for_warning_only_aggregated_demand_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "aggregated_demand_20_USA_reference.xlsx"
    _write_leap_workbook(source, [{
        "BranchID": -1,
        "VariableID": 2040,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": "Demand\\All demand aggregated\\Black liquor",
        "Variable": "Final Energy Intensity",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "Million households",
        "Expression": "1",
    }])
    template = tmp_path / "full model export.xlsx"
    _write_template_rows(template, [{
        "BranchID": 500,
        "VariableID": 900,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": "Demand\\All demand aggregated\\Electricity",
        "Variable": "Final Energy Intensity",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "Million households",
        "Expression": "1",
    }])
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"aggregated_demand_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    row = output.loc[
        output["Branch Path"].eq("Demand\\All demand aggregated\\Black liquor")
        & output["Variable"].eq("Final Energy Intensity")
    ].iloc[0]
    assert row["BranchID"] == -1
    assert row["VariableID"] == 2040

    consolidated = next(
        (tmp_path / "output" / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    aggregate_findings = findings[
        findings["rule_id"].isin(["SEED-003", "SEED-004", "SEED-011"])
    ]
    assert set(aggregate_findings["status"]) == {"warn"}
    assert not aggregate_findings["blocking"].any()


def test_default_reference_validation_window_requires_2023_through_2060(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1,2060,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS",
        False,
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-009"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={"supply_workflow": [source]},
        )
    assert not list(output_dir.glob("leap_import_baseline_seed_*.xlsx"))


def test_missing_configured_producer_for_economy_blocks_final_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("1")])
    other_economy_source = tmp_path / "transformation_leap_imports_05_PRC_reference.xlsx"
    _write_leap_workbook(other_economy_source, [_row("1")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-012"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={
                "supply_workflow": [source],
                "transformation_workflow": [other_economy_source],
            },
        )
    consolidated = next(
        (output_dir / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    coverage = findings[findings["rule_id"].eq("SEED-012")]
    assert coverage["source_workflow"].tolist() == ["transformation_workflow"]
    # The finding must explain why the probe rejected each configured path:
    # here the transformation workbook exists but is named for another economy.
    message = str(coverage["message"].iloc[0])
    assert "1 configured workbook(s) exist only for other economies" in message


def test_missing_producer_finding_names_nonexistent_workbook_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("1")])
    absent_source = tmp_path / "transformation_leap_imports_20_USA_reference.xlsx"
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-012"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={
                "supply_workflow": [source],
                "transformation_workflow": [absent_source],
            },
        )
    consolidated = next(
        (output_dir / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    coverage = findings[findings["rule_id"].eq("SEED-012")]
    assert coverage["source_workflow"].tolist() == ["transformation_workflow"]
    message = str(coverage["message"].iloc[0])
    assert "1 expected workbook(s) do not exist on disk" in message
    # The concrete missing path is carried on the finding itself.
    assert str(absent_source) in str(coverage["source_file"].iloc[0])


def test_final_writer_can_skip_validation_for_side_combines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._load_reference_export_data",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        source_workbooks_by_workflow={"supply_workflow": [source]},
        enforce_validation=False,
    )

    assert len(written) == 1
    assert written[0].exists()
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert output["Branch Path"].iloc[0] == "Resources\\Primary\\Natural gas"


def _write_leap_and_viewing_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    """Like _write_leap_workbook, but also adds the FOR_VIEWING sheet that
    save_combined_supply_transformation_export reads unconditionally."""
    columns = list(rows[0])
    preamble = {column: pd.NA for column in columns}
    preamble["Branch Path"] = "Area:"
    preamble["Scenario"] = "Ver:"
    preamble["Region"] = "2"
    full = pd.concat(
        [
            pd.DataFrame([preamble]),
            pd.DataFrame([{column: pd.NA for column in columns}]),
            pd.DataFrame([columns], columns=columns),
            pd.DataFrame(rows),
        ],
        ignore_index=True,
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        full.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        full.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)


def test_combined_export_blocks_by_default_on_conflicting_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """save_combined_supply_transformation_export must still block on genuine
    blocking findings when BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS
    is False, matching write_per_economy_combined_workbooks' default behavior."""
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_and_viewing_workbook(source, [_row("Data(2023,1)"), _row("Data(2023,2)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.RESULTS_VERIFICATION_EXPORT_PATH", template
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_FINAL_YEAR",
        2023,
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.transformation_workflow.core.EXPORT_FINAL_YEAR",
        2023,
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS",
        False,
    )
    output_dir = tmp_path / "output"

    with pytest.raises(BaselineSeedValidationError):
        save_combined_supply_transformation_export(
            supply_export_paths=[source],
            transformation_export_paths=[],
            transfer_export_paths=[],
            output_dir=output_dir,
            economy_label="20_USA",
            scenarios=["Reference"],
            # Pin the fixture template: this test is about validation, not
            # routing, and the default would load the real 20_USA template from
            # data/. Routing is covered by
            # test_combined_export_resolves_template_from_economy_label.
            template_path=template,
        )


def test_combined_export_never_blanket_downgrades_nonmigration_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retired broad flag cannot hide duplicates or coverage failures."""
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_and_viewing_workbook(source, [_row("Data(2023,1)"), _row("Data(2023,2)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.RESULTS_VERIFICATION_EXPORT_PATH", template
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS",
        True,
    )
    output_dir = tmp_path / "output"

    with pytest.raises(BaselineSeedValidationError, match="SEED-001"):
        save_combined_supply_transformation_export(
            supply_export_paths=[source],
            transformation_export_paths=[],
            transfer_export_paths=[],
            output_dir=output_dir,
            economy_label="20_USA",
            scenarios=["Reference"],
            template_path=template,  # pin the fixture; see the test above
        )


def test_combined_export_resolves_template_from_economy_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must resolve each economy's own template, not a pinned path.

    Regression test for the recorded bypass: a pinned id_lookup/template applies
    one area's BranchIDs to every economy, and tests that pin the template
    themselves exercise the override branch and so cannot catch it. This test
    therefore asserts the *default* (template_path=None) path specifically.
    """
    source = tmp_path / "supply_leap_imports_12_NZ_reference.xlsx"
    _write_leap_and_viewing_workbook(source, [_row("Data(2023,1,2060,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.RESULTS_VERIFICATION_EXPORT_PATH", template
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_FINAL_YEAR",
        2023,
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.transformation_workflow.core.EXPORT_FINAL_YEAR",
        2023,
    )

    seen: list[object] = []

    def _fake_resolver(economy: object) -> Path:
        seen.append(economy)
        return template

    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._leap_export_template_for_economy",
        _fake_resolver,
    )

    save_combined_supply_transformation_export(
        supply_export_paths=[source],
        transformation_export_paths=[],
        transfer_export_paths=[],
        output_dir=tmp_path / "output",
        economy_label="12_NZ",
        scenarios=["Reference"],
    )

    assert seen == ["12_NZ"], (
        "template must be resolved from economy_label when template_path is None; "
        f"resolver saw {seen!r}"
    )


def test_combined_export_explicit_template_bypasses_the_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit template_path is honoured without consulting the resolver."""
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_and_viewing_workbook(source, [_row("Data(2023,1,2060,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)

    def _explode(economy: object) -> Path:
        raise AssertionError(f"resolver must not be consulted; got {economy!r}")

    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io._leap_export_template_for_economy",
        _explode,
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.workflow_cfg.BASELINE_SEED_VALIDATION_FINAL_YEAR",
        2023,
    )
    monkeypatch.setattr(
        "codebase.supply_reconciliation.leap_io.transformation_workflow.core.EXPORT_FINAL_YEAR",
        2023,
    )

    written = save_combined_supply_transformation_export(
        supply_export_paths=[source],
        transformation_export_paths=[],
        transfer_export_paths=[],
        output_dir=tmp_path / "output",
        economy_label="20_USA",
        scenarios=["Reference"],
        template_path=template,
    )

    assert written is not None


#%%

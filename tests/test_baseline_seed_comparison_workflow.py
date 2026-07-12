"""Focused tests for baseline seed comparison and share-total auditing."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.baseline_seed_comparison_workflow import (
    build_share_sum_checks,
    compare_seed_tables,
    read_seed_workbook,
)
from codebase.functions.baseline_seed_validation import (
    BaselineSeedValidationError,
    enrich_seed_ids_from_template,
    prepare_seed_rows_for_write,
    resolve_logical_duplicates,
    validate_seed_rows,
)
from codebase.functions.patch_baseline_seeds import MODULE_REGISTRY
from codebase.functions import patch_baseline_seeds


def _row(branch: str, variable: str, expression: object, *, branch_id: int = 1) -> dict[str, object]:
    return {
        "BranchID": branch_id,
        "VariableID": 10,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": branch,
        "Variable": variable,
        "Scenario": "Reference",
        "Region": "Australia",
        "Units": "Share",
        "Expression": expression,
    }


def _with_excel_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    data = pd.DataFrame(rows)
    data["source_excel_row"] = range(4, 4 + len(data))
    return data


def test_semantic_expression_comparison_reports_only_changed_year() -> None:
    reference = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2023,50)")]
    )
    candidate = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40.0, 2023,55)")]
    )

    row_diff, expression_diff, summary = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert row_diff["status"].tolist() == ["expression_changed"]
    assert expression_diff["year"].tolist() == [2023]
    assert expression_diff["difference"].tolist() == [5.0]
    assert summary["expression_changed_rows"] == 1


def test_data_and_interp_are_not_treated_as_equivalent() -> None:
    reference = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2030,60)")]
    )
    candidate = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Interp(2022,40, 2030,60)")]
    )

    row_diff, expression_diff, _ = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert row_diff["status"].tolist() == ["expression_changed"]
    assert expression_diff["status"].tolist() == ["expression_kind_changed"]


def test_added_and_removed_rows_are_reported() -> None:
    reference = _with_excel_rows([_row("Resources\\Primary\\Gas", "Imports", "Data(2022,1)")])
    candidate = _with_excel_rows([_row("Resources\\Primary\\Coal", "Imports", "Data(2022,1)")])

    row_diff, _, summary = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert set(row_diff["status"]) == {"reference_only", "candidate_only"}
    assert summary["reference_only_rows"] == 1
    assert summary["candidate_only_rows"] == 1


def test_share_sum_check_groups_sibling_fuel_leaves() -> None:
    data = _with_excel_rows(
        [
            _row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2023,50)"),
            _row("Transformation\\Plant\\Output Fuels\\Oil", "Output Share", "Data(2022,60, 2023,40)"),
        ]
    )

    checks = build_share_sum_checks(
        data,
        economy="01_AUS",
        source="candidate",
        file_path=Path("candidate.xlsx"),
        tolerance=1e-9,
    )

    assert checks.loc[checks["year"] == 2022, "status"].item() == "pass"
    assert checks.loc[checks["year"] == 2023, "status"].item() == "fail_not_100"
    assert checks.loc[checks["year"] == 2023, "share_sum"].item() == 90.0


def test_share_sum_check_flags_conflicting_duplicate_key() -> None:
    branch = "Transformation\\Plant\\Output Fuels\\Gas"
    data = _with_excel_rows(
        [
            _row(branch, "Output Share", "Data(2022,100)", branch_id=1),
            _row(branch, "Output Share", "Data(2022,90)", branch_id=-1),
        ]
    )

    checks = build_share_sum_checks(
        data,
        economy="01_AUS",
        source="candidate",
        file_path=Path("candidate.xlsx"),
        tolerance=1e-9,
    )

    assert checks["status"].tolist() == ["blocked_by_conflicting_duplicate"]
    assert checks["share_sum"].tolist() == [100.0]
    assert checks["blocking_duplicate_logical_key_count"].tolist() == [1]


def test_duplicate_resolution_prefers_only_valid_id_row_without_row_order() -> None:
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    rows = [
        _row(branch, "Process Share", "Data(2022,0)", branch_id=-1),
        _row(branch, "Process Share", "Data(2022,100)", branch_id=2450),
        _row(branch, "Process Share", "Data(2022,100)", branch_id=-1),
    ]
    rows[0]["VariableID"] = rows[0]["ScenarioID"] = -1
    rows[2]["VariableID"] = rows[2]["ScenarioID"] = -1
    data = _with_excel_rows(rows).sample(frac=1, random_state=7)

    resolved, duplicates = resolve_logical_duplicates(data)

    assert resolved["BranchID"].tolist() == [2450]
    assert resolved["Expression"].tolist() == ["Data(2022,100)"]
    assert duplicates["classification"].tolist() == ["conflicting_expression_one_valid_id_row"]
    assert duplicates["blocking"].tolist() == [True]


def test_duplicate_classification_exact_and_multiple_valid_rows() -> None:
    exact = _with_excel_rows([
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
    ])
    _, exact_groups = resolve_logical_duplicates(exact)
    assert exact_groups["classification"].item() == "exact_duplicate_same_ids_and_expression"
    assert not exact_groups["blocking"].item()

    conflicting = _with_excel_rows([
        _row("Resources\\Gas", "Imports", "1", branch_id=1),
        _row("Resources\\Gas", "Imports", "2", branch_id=2),
    ])
    _, conflicting_groups = resolve_logical_duplicates(conflicting)
    assert conflicting_groups["classification"].item() == "conflicting_expression_multiple_valid_id_rows"
    assert conflicting_groups["blocking"].item()


def test_duplicate_resolution_accepts_mixed_type_column_labels() -> None:
    data = _with_excel_rows([
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
    ])
    data[2022.0] = 0.0

    resolved, duplicates = resolve_logical_duplicates(data)

    assert len(resolved) == 1
    assert duplicates["classification"].item() == "exact_duplicate_same_ids_and_expression"


def test_validator_checks_all_ids_and_distinguishes_zero_reset() -> None:
    rows = [
        _row("Resources\\Gas", "Imports", "Data(2022,5)"),
        _row("Resources\\Coal", "Imports", "Data(2022,0)"),
    ]
    rows[0]["VariableID"] = -1
    rows[1]["ScenarioID"] = -1
    result = validate_seed_rows(_with_excel_rows(rows))

    assert len(result.findings[result.findings["rule_id"] == "SEED-003"]) == 2
    assert len(result.findings[result.findings["rule_id"] == "SEED-004"]) == 1
    zero_findings = result.findings[result.findings["rule_id"] == "SEED-005"]
    assert len(zero_findings) == 1
    assert not zero_findings["blocking"].item()


def test_missing_aggregated_demand_branch_is_warning_only(tmp_path: Path) -> None:
    row = _row(
        "Demand\\All demand aggregated\\Black liquor",
        "Final Energy Intensity",
        "1",
        branch_id=-1,
    )
    row["source_workflow"] = "aggregated_demand_workflow"
    template = tmp_path / "template.xlsx"
    canonical = pd.DataFrame([
        _row("Demand\\All demand aggregated\\Electricity", "Final Energy Intensity", "1")
    ])
    with pd.ExcelWriter(template, engine="openpyxl") as writer:
        canonical.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    result = validate_seed_rows(pd.DataFrame([row]), template_path=template)

    findings = result.findings[result.findings["rule_id"].isin(["SEED-003", "SEED-004", "SEED-011"])]
    assert set(findings["rule_id"]) == {"SEED-003", "SEED-004", "SEED-011"}
    assert findings["status"].eq("warn").all()
    assert not findings["blocking"].any()


def test_aggregated_demand_patch_scope_does_not_strip_entire_demand_tree() -> None:
    assert MODULE_REGISTRY["aggregated_demand"].strip_prefixes == [
        "Demand\\All demand aggregated\\"
    ]


def test_losses_own_use_patch_scope_strips_managed_subtree() -> None:
    assert MODULE_REGISTRY["losses_own_use"].strip_prefixes == [
        "Demand\\Other loss and own use\\"
    ]


def test_aggregated_demand_patch_threads_reconciliation_config(monkeypatch, tmp_path: Path) -> None:
    import codebase.aggregated_demand_workflow as aggregated_demand_workflow
    import codebase.functions.transformation_analysis_utils as transformation_core
    import codebase.supply_reconciliation_config as reconciliation_config

    captured: dict[str, object] = {}

    monkeypatch.setattr(transformation_core, "prepare_transformation_assets", lambda: None)
    monkeypatch.setattr(
        transformation_core,
        "ninth_data",
        pd.DataFrame({"economy": ["20_USA", "00_APEC"]}),
    )
    monkeypatch.setattr(patch_baseline_seeds, "WORKBOOKS_DIR", tmp_path)
    monkeypatch.setattr(
        reconciliation_config,
        "AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES",
        True,
    )
    monkeypatch.setattr(
        reconciliation_config,
        "AGGREGATED_DEMAND_EXCLUDED_SECTORS",
        ["15_02_road"],
    )
    monkeypatch.setattr(
        reconciliation_config,
        "AGGREGATED_DEMAND_USE_SECTOR_BRANCHES",
        True,
    )

    def fake_save_aggregated_demand_as_leap_workbook(**kwargs):
        captured.update(kwargs)
        output_path = Path(kwargs["output_path"])
        output_path.write_text("placeholder")
        return output_path

    monkeypatch.setattr(
        aggregated_demand_workflow,
        "save_aggregated_demand_as_leap_workbook",
        fake_save_aggregated_demand_as_leap_workbook,
    )

    written = patch_baseline_seeds._run_source_workflow(
        "aggregated_demand",
        ["20_USA"],
    )

    assert written == [tmp_path / "aggregated_demand_20_USA.xlsx"]
    assert captured["exclude_own_use_td_losses"] is True
    assert captured["excluded_sectors"] == ["15_02_road"]
    assert captured["use_sector_branches"] is True


def test_losses_own_use_patch_generates_exact_fresh_workbook_paths(monkeypatch, tmp_path: Path) -> None:
    import codebase.other_loss_own_use_proxy_workflow as proxy_workflow
    import codebase.functions.transformation_analysis_utils as transformation_core
    import codebase.supply_reconciliation_config as reconciliation_config

    captured: dict[str, object] = {}

    monkeypatch.setattr(transformation_core, "prepare_transformation_assets", lambda: None)
    monkeypatch.setattr(
        transformation_core,
        "ninth_data",
        pd.DataFrame({"economy": ["20_USA", "00_APEC"]}),
    )
    monkeypatch.setattr(reconciliation_config, "OTHER_LOSS_OWN_USE_PROXY_STAGE", "first")
    monkeypatch.setattr(reconciliation_config, "CAPACITY_UNMET_PASS_MODE", "baseline_seed")

    def fake_assemble_proxy_workbook(**kwargs):
        captured.update(kwargs)
        return tmp_path / f"other_loss_own_use_proxy_{kwargs['economy']}_Reference_Target_Current_Accounts.xlsx"

    monkeypatch.setattr(
        proxy_workflow,
        "assemble_proxy_workbook",
        fake_assemble_proxy_workbook,
    )

    written = patch_baseline_seeds._run_source_workflow(
        "losses_own_use",
        ["20_USA"],
    )

    assert written == [
        tmp_path / "other_loss_own_use_proxy_20_USA_Reference_Target_Current_Accounts.xlsx"
    ]
    assert captured["activity_source_mode"] == "esto_ninth"
    assert captured["include_leap_import"] is False
    assert captured["strict_proxy_activity_target_consistency"] is False
    assert captured["write_proxy_activity_target_consistency_issues"] is True


@pytest.mark.parametrize("module", ["oil_refineries", "lng", "transformation"])
def test_transformation_auto_regen_modules_are_gated(module: str) -> None:
    with pytest.raises(NotImplementedError, match="not safely patchable"):
        patch_baseline_seeds.run_patch(module, economies=["20_USA"], run_workflow=True)


def test_transfers_patch_scope_covers_every_transfer_process_title() -> None:
    # strip_prefixes must cover every sector title the transfers workflow can
    # produce, otherwise a patch leaves stale rows behind (and drops new rows,
    # since _patch_one also filters incoming rows to the active prefixes).
    from codebase.transfers_workflow import get_transfer_sector_titles

    resolved = MODULE_REGISTRY["transfers"].resolve_strip_prefixes()
    expected = {f"Transformation\\{title}" for title in get_transfer_sector_titles()}
    assert expected == set(resolved)
    # The static display list must not drift from the runtime source either.
    assert set(MODULE_REGISTRY["transfers"].strip_prefixes) == expected


def test_missing_id_zero_exception_requires_rule_and_key_scope() -> None:
    row = _row("Resources\\Coal", "Imports", "Data(2022,0)")
    row["VariableID"] = -1
    result = validate_seed_rows(
        _with_excel_rows([row]),
        exceptions=[{
            "exception_id": "TEST-ZERO-RESET",
            "rule_id": "SEED-003",
            "Variable": "Imports",
            "Branch Path": "Resources\\Coal",
            "reason": "Explicit test-only reset exception.",
        }],
    )
    missing_id = result.findings[result.findings["rule_id"].eq("SEED-003")].iloc[0]
    assert missing_id["status"] == "excepted"
    assert not missing_id["blocking"]

    with pytest.raises(ValueError, match="measure/key"):
        validate_seed_rows(
            _with_excel_rows([row]),
            exceptions=[{"rule_id": "SEED-003"}],
        )


def test_validator_handles_inactive_shares_and_configured_coverage() -> None:
    rows = [
        _row("Transformation\\Plant\\Processes\\A", "Process Share", "Data(2022,0, 2023,0)"),
        _row("Transformation\\Plant\\Processes\\B", "Process Share", "Data(2022,0, 2023,0)"),
    ]
    result = validate_seed_rows(
        _with_excel_rows(rows),
        required_years=[2022, 2023, 2024],
        required_scenarios=["Reference", "Target"],
    )

    process_findings = result.findings[result.findings["rule_id"] == "SEED-007"]
    assert set(process_findings["status"]) == {"fail"}
    assert len(result.findings[result.findings["rule_id"] == "SEED-009"]) == 2
    assert len(result.findings[result.findings["rule_id"] == "SEED-010"]) == 2


def test_validator_branch_existence_and_explicit_exception(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    template = pd.DataFrame([_row("Resources\\Gas", "Imports", "0")])
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)
    candidate = _with_excel_rows([_row("Resources\\Unknown", "Imports", "0")])

    result = validate_seed_rows(candidate, template_path=template_path)
    assert result.findings[result.findings["rule_id"] == "SEED-011"]["blocking"].item()

    excepted = validate_seed_rows(
        candidate,
        template_path=template_path,
        exceptions=[{"rule_id": "SEED-011", "Branch Path": "Resources\\Unknown"}],
    )
    finding = excepted.findings[excepted.findings["rule_id"] == "SEED-011"].iloc[0]
    assert finding["status"] == "excepted"
    assert not finding["blocking"]


def test_june_usa_fixture_heat_interim_duplicate_is_resolved_to_valid_row() -> None:
    fixture_dir = Path("data/backup_tgt_ref_ca_20260625")
    files = sorted(fixture_dir.glob("leap_import_baseline_seed_20_USA_*.xlsx"))
    if not files:
        return
    data = read_seed_workbook(files[0])
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    focused = data[
        data["Branch Path"].eq(branch)
        & data["Variable"].eq("Process Share")
        & data["Scenario"].eq("Current Accounts")
    ]

    resolved, duplicates = resolve_logical_duplicates(focused)

    assert len(focused) == 3
    assert resolved["BranchID"].tolist() == [2450]
    assert resolved["Expression"].tolist() == ["Data(2022,100.0)"]
    assert duplicates["classification"].tolist() == ["conflicting_expression_one_valid_id_row"]


def _write_template(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Export", index=False, startrow=2)


def test_production_preparation_enriches_all_ids_and_collapses_exact_duplicates(
    tmp_path: Path,
) -> None:
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Process Share", "")
    template_row.update({"BranchID": 2450, "VariableID": 418, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])

    rows = [
        _row(branch, "Process Share", "Data(2023,100)", branch_id=-1),
        _row(branch, "Process Share", "Data(2023, 100.0)", branch_id=2450),
    ]
    for row in rows:
        row.update({"VariableID": -1, "ScenarioID": -1, "RegionID": -1})
    result = prepare_seed_rows_for_write(
        _with_excel_rows(rows).sample(frac=1, random_state=3),
        template_path=template_path,
        diagnostics_dir=tmp_path / "diagnostics",
        diagnostic_stem="heat",
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(result.resolved_rows) == 1
    assert result.resolved_rows[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [2450, 418, 2, 1]
    assert result.duplicate_groups["classification"].tolist() == [
        "exact_duplicate_same_ids_and_expression"
    ]


def test_zero_reset_is_enriched_with_real_ids(tmp_path: Path) -> None:
    branch = "Resources\\Primary\\Gas"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Imports", "")
    template_row.update({"BranchID": 20, "VariableID": 30, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])
    candidate = _with_excel_rows([_row(branch, "Imports", "Data(2023,0)", branch_id=-1)])

    enriched = enrich_seed_ids_from_template(candidate, template_path)
    result = validate_seed_rows(enriched, template_path=template_path)

    assert enriched[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [20, 30, 2, 1]
    assert result.findings.empty


def test_known_leap_label_exception_rescues_branch_and_variable_id(tmp_path: Path) -> None:
    # The mapping sheets spell the fuel "Black liquor"; the live LEAP model (and
    # therefore the seed row's branch path) uses the typo "Black liqour". Without
    # the KNOWN_LEAP_LABEL_EXCEPTIONS rescue the row would stay -1 and block.
    template_branch = "Demand\\Industry\\Black liquor"
    seed_branch = "Demand\\Industry\\Black liqour"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(template_branch, "Activity Level", "")
    template_row.update({"BranchID": 555, "VariableID": 77, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])

    candidate = _with_excel_rows([_row(seed_branch, "Activity Level", "Data(2023,1)", branch_id=-1)])
    candidate["VariableID"] = -1

    enriched = enrich_seed_ids_from_template(candidate, template_path)

    assert int(enriched["BranchID"].iloc[0]) == 555
    assert int(enriched["VariableID"].iloc[0]) == 77
    # Branch Path is rewritten to the canonical (template) spelling on rescue.
    assert enriched["Branch Path"].iloc[0] == template_branch


def test_genuinely_unmatched_branch_stays_minus_one(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    template_row = _row("Demand\\Industry\\Black liquor", "Activity Level", "")
    template_row.update({"BranchID": 555, "VariableID": 77, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])

    candidate = _with_excel_rows(
        [_row("Resources\\Primary\\Unobtanium", "Activity Level", "Data(2023,1)", branch_id=-1)]
    )
    candidate["VariableID"] = -1

    enriched = enrich_seed_ids_from_template(candidate, template_path)

    assert int(enriched["BranchID"].iloc[0]) == -1
    assert int(enriched["VariableID"].iloc[0]) == -1


def test_share_validation_uses_resolved_rows_not_duplicate_physical_rows() -> None:
    gas = _row(
        "Transformation\\Plant\\Output Fuels\\Gas",
        "Output Share",
        "Data(2023,40)",
    )
    oil = _row(
        "Transformation\\Plant\\Output Fuels\\Oil",
        "Output Share",
        "Data(2023,60)",
    )
    result = validate_seed_rows(
        _with_excel_rows([gas, dict(gas), oil]),
        allow_exact_duplicate_resolution=True,
    )

    share_findings = result.findings[result.findings["rule_id"] == "SEED-006"]
    assert share_findings["status"].tolist() == ["pass"]
    assert share_findings["evidence"].tolist() == ["sum=100"]


def test_scenario_specific_year_and_source_coverage_block_when_incomplete() -> None:
    row = _row("Resources\\Primary\\Gas", "Imports", "Data(2023,1)")
    row["source_workflow"] = "supply_workflow"
    result = validate_seed_rows(
        _with_excel_rows([row]),
        required_years_by_scenario={"Reference": [2023, 2024]},
        required_scenarios_by_source={
            "supply_workflow": ["Reference", "Target"]
        },
    )

    assert result.findings[result.findings["rule_id"] == "SEED-009"]["blocking"].all()
    assert result.findings[result.findings["rule_id"] == "SEED-010"]["blocking"].all()


def test_conflicting_valid_rows_write_diagnostics_before_raising(tmp_path: Path) -> None:
    branch = "Resources\\Primary\\Gas"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Imports", "")
    _write_template(template_path, [template_row])
    candidate = _with_excel_rows([
        _row(branch, "Imports", "Data(2023,1)"),
        _row(branch, "Imports", "Data(2023,2)"),
    ])
    diagnostics_dir = tmp_path / "diagnostics"

    try:
        prepare_seed_rows_for_write(
            candidate,
            template_path=template_path,
            diagnostics_dir=diagnostics_dir,
            diagnostic_stem="conflict",
        )
    except BaselineSeedValidationError:
        pass
    else:
        raise AssertionError("Conflicting valid rows must block workbook preparation")

    findings_path = diagnostics_dir / "conflict_rule_findings.csv"
    duplicates_path = diagnostics_dir / "conflict_duplicate_groups.csv"
    assert findings_path.exists()
    assert duplicates_path.exists()
    duplicates = pd.read_csv(duplicates_path)
    assert duplicates["blocking"].tolist() == [True]


#%%

from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

import codebase.functions.baseline_seed_balance_diagnostics as diagnostics


def _comparison_rows(
    *,
    scenario: str,
    year: int,
    leap_value: float | None,
    source: str,
    source_value: float | None,
) -> pd.DataFrame:
    rows = []
    for source_name, value in [("leap", leap_value), (source, source_value)]:
        rows.append(
            {
                "economy": "20_USA",
                "scenario": scenario,
                "sheet": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "source": source_name,
                "year": year,
                "value": value,
            }
        )
    return pd.DataFrame(rows)


def _mapping_status(*, ninth_pairs: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sheet": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                "sector_code_9th": sector,
                "ninth_fuel_code": fuel,
            }
            for sector, fuel in ninth_pairs
        ]
    )


def _leap_long(*, components: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sheet_name": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "leap_sector_name": sector,
                "leap_fuel_name": fuel,
            }
            for sector, fuel in components
        ]
    )


def _write_balance_workbook(
    path: Path,
    *,
    scenario: str = "Reference",
    year: int = 2022,
    units: str = "Petajoule",
    include_level2: bool = True,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Energy Balance"
    sheet.append(['Energy Balance for Area "Test"', None])
    sheet.append([f"Scenario: {scenario}, Year: {year}, Units: {units}", None])
    sheet.append([None, "Electricity"])
    sheet.append(["Production", 1.0])
    if include_level2:
        sheet.append(["  Child production", 1.0])
    workbook.save(path)


def test_projection_difference_marks_cardinality_and_correction() -> None:
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=_comparison_rows(
            scenario="Reference",
            year=2023,
            leap_value=12.0,
            source="projection",
            source_value=10.0,
        ),
        mapping_status=_mapping_status(
            ninth_pairs=[
                ("09_06_gas_processing_plants", "08_01_natural_gas"),
                ("09_06_gas_processing_plants", "08_02_lng"),
            ]
        ),
        leap_long=_leap_long(
            components=[
                ("Gas processing/Input", "Natural gas"),
                ("Gas processing/Output", "Natural gas"),
            ]
        ),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    assert len(table) == 1
    row = table.iloc[0]
    assert row["reference_source"] == "9th Outlook"
    assert row["difference_pj"] == pytest.approx(2.0)
    assert row["correction_to_match_source_pj"] == pytest.approx(-2.0)
    assert row["difference_percent"] == pytest.approx(20.0)
    assert row["status"] == "value_mismatch"
    assert bool(row["is_mismatch"]) is True
    assert row["leap_component_count"] == 2
    assert row["ninth_pair_count"] == 2
    assert row["ninth_pair_max_esto_claimants"] == 1
    assert row["comparison_grain"] == "aggregate_many_leap_to_many_ninth"
    assert bool(row["update_allocation_required"]) is True
    assert row["update_allocation_reason"] == (
        "multiple_leap_components_share_the_esto_pair;"
        "esto_pair_sums_multiple_ninth_pairs"
    )


def test_base_year_uses_esto_and_matches_across_economy_code_formats() -> None:
    comparison = _comparison_rows(
        scenario="Target",
        year=2022,
        leap_value=5.0,
        source="base",
        source_value=5.0,
    )
    comparison.loc[comparison["source"].eq("base"), "economy"] = "20USA"
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=_mapping_status(
            ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
        ),
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2022],
        scenarios=["Target"],
    )

    row = table.iloc[0]
    assert row["reference_source"] == "ESTO"
    assert row["status"] == "match"
    assert row["comparison_grain"] == "direct_leap_to_esto_pair"
    assert bool(row["update_allocation_required"]) is False


def test_oil_refining_base_comparator_adds_only_configured_own_use_flow() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=-8.0,
        source="base",
        source_value=-5.0,
    )
    comparison["sheet"] = "09.07 Oil refineries"
    comparison["fuel_label"] = "08.01 Natural gas"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "09.07 Oil refineries",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "esto_flow": "09.07 Oil refineries",
                "esto_product": "08.01 Natural gas",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            }
        ]
    )
    base_df = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "10.01.11 Oil refineries",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                "2022": -3.0,
            },
            {
                "economy": "01AUS",
                "flows": "10.01.12 Petrochemical industry",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                "2022": -99.0,
            },
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        base_df=base_df,
        economy="01_AUS",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(-8.0)
    assert row["difference_pj"] == pytest.approx(0.0)
    assert row["status"] == "match"


def test_shared_ninth_pair_across_esto_rows_requires_allocation() -> None:
    mapping_status = _mapping_status(
        ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
    )
    shared = mapping_status.iloc[0].copy()
    shared["sheet"] = "02 Imports"
    shared["fuel_label"] = "06.08 Other hydrocarbons"
    shared["esto_flow"] = "02 Imports"
    shared["esto_product"] = "06.08 Other hydrocarbons"
    mapping_status = pd.concat(
        [mapping_status, shared.to_frame().T],
        ignore_index=True,
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=_comparison_rows(
            scenario="Reference",
            year=2023,
            leap_value=12.0,
            source="projection",
            source_value=10.0,
        ),
        mapping_status=mapping_status,
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["ninth_pair_count"] == 1
    assert row["ninth_pair_max_esto_claimants"] == 2
    assert row["comparison_grain"] == "aggregate_shared_ninth_pair_across_esto_rows"
    assert bool(row["update_allocation_required"]) is True
    assert row["update_allocation_reason"] == (
        "ninth_pair_is_shared_by_multiple_esto_pairs"
    )


def test_canonical_projection_allocation_resolves_shared_ninth_pair() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=42.0,
        source="projection",
        source_value=100.0,
    )
    mapping_status = _mapping_status(
        ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
    )
    shared = mapping_status.iloc[0].copy()
    shared["sheet"] = "02 Imports"
    shared["fuel_label"] = "06.08 Other hydrocarbons"
    shared["esto_flow"] = "02 Imports"
    shared["esto_product"] = "06.08 Other hydrocarbons"
    mapping_status = pd.concat(
        [mapping_status, shared.to_frame().T],
        ignore_index=True,
    )
    projection_tables = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "economy_key": "20USA",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                2023: 40.0,
            },
            {
                "scenario": "Reference",
                "economy_key": "20USA",
                "esto_flow": "02 Imports",
                "esto_product": "06.08 Other hydrocarbons",
                2023: 60.0,
            },
        ]
    )
    provenance = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "year": 2023,
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                "allocation_method": "proportional_esto_base_year",
                "share_source": "economy",
            }
        ]
    )

    allocated, allocation_status = (
        diagnostics.apply_canonical_projection_comparators(
            comparison_long=comparison,
            mapping_status=mapping_status,
            projection_tables=projection_tables,
            allocation_provenance=provenance,
        )
    )
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=allocated,
        mapping_status=mapping_status,
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        projection_allocation_status=allocation_status,
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(40.0)
    assert row["difference_pj"] == pytest.approx(2.0)
    assert bool(row["projection_allocation_complete"]) is True
    assert row["projection_target_pair_count"] == 1
    assert row["projection_matched_pair_count"] == 1
    assert row["projection_allocation_methods"] == (
        "proportional_esto_base_year"
    )
    assert row["comparison_grain"] == "canonical_allocated_ninth_to_esto_pair"
    assert bool(row["update_allocation_required"]) is False
    assert row["update_allocation_reason"] == ""


def test_missing_reference_is_visible_but_not_called_a_mismatch() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=4.0,
        source="projection",
        source_value=None,
    )
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=_mapping_status(ninth_pairs=[]),
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["status"] == "reference_unavailable"
    assert bool(row["is_mismatch"]) is False
    assert pd.isna(row["difference_pj"])


def test_pre_base_historical_years_are_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="Pre-base historical years"):
        diagnostics._validate_years([2021, 2022], base_year=2022)


def test_economy_diagnostic_rejects_level1_before_conversion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    level1_path = tmp_path / "level1.xlsx"
    _write_balance_workbook(level1_path, include_level2=False)
    monkeypatch.setattr(
        diagnostics,
        "_load_optional_json",
        lambda path: pytest.fail("conversion setup ran before detail validation"),
    )

    with pytest.raises(ValueError, match="at least Level 2 detail"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=level1_path,
        )


def test_direct_reference_workbook_uses_metadata_without_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(direct_path)
    calls: dict[str, object] = {}

    def _fake_convert(**kwargs):
        calls.update(kwargs)
        return {
            "leap_long": pd.DataFrame(),
            "mapping_status": pd.DataFrame(),
            "issues": pd.DataFrame(),
            "total_balance_checks": pd.DataFrame(),
            "matching_diagnostics": pd.DataFrame(),
        }

    def _fake_build(**kwargs):
        return {"comparison_long": pd.DataFrame(), "mapping_status": pd.DataFrame()}

    @contextmanager
    def _fake_runtime_paths(**kwargs):
        yield _fake_build, _fake_convert

    monkeypatch.setattr(diagnostics, "_temporary_balance_runtime_paths", _fake_runtime_paths)
    monkeypatch.setattr(
        diagnostics,
        "_write_esto_axis_extraction_mapping_workbook",
        lambda **kwargs: kwargs["output_path"],
    )
    monkeypatch.setattr(
        diagnostics,
        "build_leap_source_difference_table",
        lambda **kwargs: pd.DataFrame(columns=diagnostics.DIFFERENCE_OUTPUT_COLUMNS),
    )

    result = diagnostics.run_economy_balance_diagnostic(
        economy="01_AUS",
        years=None,
        scenarios=None,
        workbook_path=direct_path,
    )

    assert result["years"] == [2022]
    assert result["scenarios"] == ["Reference"]
    assert result["ref_workbook_path"] == direct_path
    assert result["tgt_workbook_path"] is None
    assert calls["ref_workbook_path"] == direct_path
    assert calls["tgt_workbook_path"] is None


def test_direct_workbook_metadata_accepts_thousand_petajoule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(
        direct_path,
        scenario="Target",
        units="Thousand Petajoule",
    )

    monkeypatch.setattr(
        diagnostics,
        "require_level2_balance_export_detail",
        lambda paths: list(paths),
    )

    def stop_after_preflight(
        *,
        codebook_path: Path,
        sheet_map_path: Path,
        exports_root: Path,
    ):
        raise RuntimeError("preflight passed")

    monkeypatch.setattr(
        diagnostics,
        "_temporary_balance_runtime_paths",
        stop_after_preflight,
    )

    with pytest.raises(RuntimeError, match="preflight passed"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=direct_path,
        )


def test_direct_workbook_metadata_rejects_unsupported_units(tmp_path: Path) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(direct_path, units="Terajoule")

    with pytest.raises(ValueError, match="Petajoule"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=direct_path,
        )


def test_review_table_flags_non_comparable_total_final_energy_boundary() -> None:
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "esto_flow": "13 Total final energy consumption",
            "esto_product": "17 Electricity",
            "leap_sector_names": "Total final energy consumption",
            "leap_fuel_names": "Electricity",
            "absolute_difference_pj": 175.0,
            "status": "value_mismatch",
        }
    )

    review = diagnostics.build_balance_review_table(pd.DataFrame([row]))

    assert review.loc[0, "primary_classification"] == "diagnostic_bug"
    assert review.loc[0, "preliminary_owner"] == "mapping_or_diagnostic"
    assert bool(review.loc[0, "material_for_review"]) is True


def test_review_table_uses_imports_as_error_signal_and_protects_other_flows() -> None:
    rows = []
    for flow, sector in [
        ("02 Imports", "Imports"),
        ("01 Production", "Production"),
        ("03 Exports", "Exports"),
        ("07 Total primary energy supply", "Total Primary Supply"),
    ]:
        row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
        row.update(
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": flow,
                "esto_product": "01.04 Anthracite",
                "leap_sector_names": sector,
                "absolute_difference_pj": 10.0,
                "status": "value_mismatch",
                "update_allocation_required": False,
            }
        )
        rows.append(row)

    review = diagnostics.build_balance_review_table(pd.DataFrame(rows))
    indexed = review.set_index("esto_flow")

    imports = indexed.loc["02 Imports"]
    assert imports["balance_variable_role"] == "error_signal"
    assert bool(imports["allowed_to_change"]) is True
    assert imports["error_signal_name"] == "imports_gap"
    assert bool(imports["update_signal_eligible"]) is True
    assert bool(imports["requires_issue_review"]) is False

    for flow in ["01 Production", "03 Exports"]:
        protected = indexed.loc[flow]
        assert protected["balance_variable_role"] == "protected"
        assert protected["balance_contract_issue"] == "protected_flow_difference"
        assert bool(protected["update_signal_eligible"]) is False
        assert bool(protected["requires_issue_review"]) is True

    total = indexed.loc["07 Total primary energy supply"]
    assert total["balance_variable_role"] == "derived_check"
    assert total["balance_contract_issue"] == "derived_balance_difference"
    assert bool(total["requires_issue_review"]) is True


def test_placeholder_scope_is_visible_but_not_silently_excluded() -> None:
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "economy": "01_AUS",
            "scenario": "Reference",
            "year": 2022,
            "esto_flow": "09.01.01,09.02.01 Electricity plants",
            "esto_product": "01.04 Anthracite",
            "leap_sector_names": "Electricity interim/Electricity interim",
            "absolute_difference_pj": 10.0,
            "status": "value_mismatch",
            "update_allocation_required": False,
        }
    )

    review = diagnostics.build_balance_review_table(pd.DataFrame([row]))

    assert bool(review.loc[0, "placeholder_scope"]) is True
    assert review.loc[0, "balance_contract_issue"] == "protected_flow_difference"
    assert bool(review.loc[0, "requires_issue_review"]) is True
    assert "not automatically excluded" in review.loc[0, "placeholder_scope_reason"]


def test_more_specific_rule_can_allow_a_non_import_error_signal() -> None:
    rules = diagnostics.load_balance_variable_rules()
    rules = pd.concat(
        [
            rules,
            pd.DataFrame(
                [
                    {
                        "economy": "01_AUS",
                        "scenario": "Reference",
                        "esto_product": "17 Electricity",
                        "esto_flow": "03 Exports",
                        "balance_variable_role": "error_signal",
                        "error_signal_name": "exports_gap",
                        "reason": "Reviewed product-specific exception.",
                        "enabled": True,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "economy": "01_AUS",
            "scenario": "Reference",
            "year": 2022,
            "esto_flow": "03 Exports",
            "esto_product": "17 Electricity",
            "absolute_difference_pj": 10.0,
            "status": "value_mismatch",
            "update_allocation_required": False,
        }
    )

    review = diagnostics.build_balance_review_table(
        pd.DataFrame([row]),
        balance_variable_rules=rules,
    )

    assert review.loc[0, "balance_variable_role"] == "error_signal"
    assert review.loc[0, "error_signal_name"] == "exports_gap"
    assert bool(review.loc[0, "update_signal_eligible"]) is True


def test_diagnostic_counts_keep_missing_unmapped_and_total_failures_separate() -> None:
    differences = pd.DataFrame(
        [
            {
                "status": "value_mismatch",
                "comparison_grain": "direct_leap_to_esto_pair",
                "update_allocation_required": False,
            },
            {
                "status": "reference_unavailable",
                "comparison_grain": "direct_leap_to_esto_pair",
                "update_allocation_required": True,
            },
        ]
    )
    issues = pd.DataFrame(
        [
            {"reason": "missing_esto_pair", "severity": ""},
            {"reason": "total_balance_mapping_check", "severity": "error"},
        ]
    )

    counts = diagnostics.build_balance_diagnostic_counts(differences, issues)

    assert counts == {
        "value_mismatches": 1,
        "rows_missing_from_leap": 0,
        "rows_missing_from_comparator": 1,
        "unmapped_rows": 1,
        "total_balance_check_failures": 1,
        "direct_one_to_one_comparisons": 2,
        "aggregate_or_shared_unsafe_comparisons": 1,
    }


def test_supporting_issues_are_scoped_to_selected_years_and_scenarios() -> None:
    issues = pd.DataFrame(
        [
            {"scenario": "Reference", "year": 2023, "reason": "keep"},
            {"scenario": "Reference", "year": 2060, "reason": "wrong_year"},
            {"scenario": "Target", "year": 2023, "reason": "wrong_scenario"},
        ]
    )
    scoped = diagnostics._scope_rows_to_diagnostic_window(
        issues,
        years=[2023],
        scenarios=["Reference"],
    )

    assert scoped["reason"].tolist() == ["keep"]


def test_multi_economy_runner_writes_one_combined_table(monkeypatch, tmp_path: Path) -> None:
    def _fake_run_economy_balance_diagnostic(**kwargs):
        economy = kwargs["economy"]
        row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
        row.update(
            {
                "economy": economy,
                "scenario": "Reference",
                "year": 2023,
                "leap_value_pj": 2.0,
                "source_value_pj": 1.0,
                "difference_pj": 1.0,
                "absolute_difference_pj": 1.0,
                "correction_to_match_source_pj": -1.0,
                "status": "value_mismatch",
                "is_mismatch": True,
                "update_allocation_required": False,
            }
        )
        return {
            "difference_table": pd.DataFrame([row]),
            "mapping_issues": pd.DataFrame(),
        }

    monkeypatch.setattr(
        diagnostics,
        "run_economy_balance_diagnostic",
        _fake_run_economy_balance_diagnostic,
    )
    result = diagnostics.run_baseline_seed_balance_diagnostics(
        economies=["01_AUS", "20_USA"],
        years=[2023],
        output_dir=tmp_path,
    )

    output = pd.read_csv(result["differences_path"])
    assert output["economy"].tolist() == ["01_AUS", "20_USA"]
    assert result["summary"]["comparison_rows"] == 2
    assert result["summary"]["mismatch_rows"] == 2
    assert result["mapping_issues_path"] is None
    assert result["review_path"].exists()

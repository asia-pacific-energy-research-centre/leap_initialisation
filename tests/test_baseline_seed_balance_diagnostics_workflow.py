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
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Energy Balance"
    sheet.append(['Energy Balance for Area "Test"', None])
    sheet.append(["Scenario: Reference, Year: 2022, Units: Petajoule", None])
    sheet.append([None, "Electricity"])
    sheet.append(["Production", 1.0])
    workbook.save(level1_path)

    monkeypatch.setattr(
        diagnostics,
        "resolve_balance_export_workbook",
        lambda **kwargs: level1_path,
    )
    monkeypatch.setattr(
        diagnostics,
        "_load_optional_json",
        lambda path: pytest.fail("conversion setup ran before detail validation"),
    )

    with pytest.raises(ValueError, match="at least Level 2 detail"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=[2022],
        )


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

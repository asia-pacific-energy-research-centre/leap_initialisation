"""Focused tests for the independent balance-demand conservation diagnostic."""

#%%

import pandas as pd
import pytest

from codebase.functions.balance_demand_conservation import (
    build_balance_demand_conservation_breakdown,
    build_raw_demand_conservation_reference,
    build_balance_demand_conservation_diagnostics,
    build_balance_demand_conservation_lineage,
    prepare_aggregated_demand_reference,
    prepare_reconciliation_demand_totals,
)


def _rows(value_column: str, values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "Reference",
                "sector_context": "Industry",
                "esto_product": product,
                "year": 2030,
                value_column: value,
            }
            for product, value in zip(["07.01 Motor gasoline", "08.01 Natural gas"], values)
        ]
    )


def test_conservation_diagnostic_passes_equal_independent_totals():
    diagnostics = build_balance_demand_conservation_diagnostics(
        reference_rows=_rows("reference_total", [10.0, 20.0]),
        resolved_rows=_rows("resolved_total", [10.0, 20.0]),
    )

    assert not diagnostics["is_mismatch"].any()
    assert diagnostics["difference"].tolist() == pytest.approx([0.0, 0.0])


def test_conservation_diagnostic_catches_value_and_missing_row_mismatches():
    reference = _rows("reference_total", [10.0, 20.0])
    resolved = _rows("resolved_total", [9.0, 20.0]).iloc[[0]].copy()

    diagnostics = build_balance_demand_conservation_diagnostics(reference, resolved)
    statuses = diagnostics.set_index("esto_product")["status"].to_dict()

    assert statuses == {
        "07.01 Motor gasoline": "value_mismatch",
        "08.01 Natural gas": "missing_resolved",
    }


def test_conservation_diagnostic_aggregates_mapping_augmentation_duplicates():
    reference = _rows("reference_total", [10.0, 20.0]).iloc[[0]].copy()
    resolved = pd.concat(
        [
            _rows("resolved_total", [4.0, 0.0]).iloc[[0]],
            _rows("resolved_total", [6.0, 0.0]).iloc[[0]],
        ],
        ignore_index=True,
    )

    diagnostics = build_balance_demand_conservation_diagnostics(reference, resolved)

    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(10.0)
    assert diagnostics.loc[0, "status"] == "match"


def test_conservation_diagnostic_rejects_negative_tolerance():
    with pytest.raises(ValueError, match="non-negative"):
        build_balance_demand_conservation_diagnostics(
            _rows("reference_total", [10.0, 20.0]),
            _rows("resolved_total", [10.0, 20.0]),
            tolerance_pj=-1.0,
        )


def test_optional_adapter_can_combine_placeholder_and_detailed_sectors():
    reference_source = pd.DataFrame(
        [{"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 100.0}]
    )
    placeholder = reference_source.copy()
    placeholder["demand_value"] = 60.0
    detailed = reference_source.copy()
    detailed["demand_value"] = 40.0

    diagnostics = build_balance_demand_conservation_diagnostics(
        prepare_aggregated_demand_reference(reference_source),
        prepare_reconciliation_demand_totals(
            placeholder,
            detailed_sector_demand=detailed,
            include_detailed_sectors=True,
        ),
    )

    assert diagnostics.loc[0, "status"] == "match"
    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(100.0)


def test_results_update_excludes_detailed_leap_sector_rows_from_both_sides():
    residual_reference = pd.DataFrame(
        [{"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 60.0}]
    )
    detailed_leap = residual_reference.copy()
    detailed_leap["demand_value"] = 250.0

    diagnostics = build_balance_demand_conservation_diagnostics(
        prepare_aggregated_demand_reference(residual_reference),
        prepare_reconciliation_demand_totals(
            residual_reference,
            detailed_sector_demand=detailed_leap,
            include_detailed_sectors=False,
        ),
    )

    assert diagnostics.loc[0, "status"] == "match"
    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(60.0)


def test_total_energy_surface_detects_mapping_loss_across_fuels():
    reference = pd.DataFrame(
        [
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 40.0},
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "p2", "year": 2030, "demand_value": 60.0},
        ]
    )
    resolved = reference.iloc[[0]].copy()

    diagnostics = build_balance_demand_conservation_diagnostics(
        prepare_aggregated_demand_reference(reference, collapse_products=True),
        prepare_reconciliation_demand_totals(resolved, collapse_products=True),
    )

    assert diagnostics.loc[0, "reference_total"] == pytest.approx(100.0)
    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(40.0)
    assert diagnostics.loc[0, "status"] == "value_mismatch"


def test_raw_reference_is_built_before_fuel_mapping(monkeypatch):
    import codebase.aggregated_demand_workflow as aggregated

    base = pd.DataFrame(
        [{"economy": "20_USA", "fuel_code": "base", "year": 2022, "value": 10.0}]
    )
    projection = pd.DataFrame(
        [
            {"economy": "20_USA", "fuel_code": "unmapped_a", "year": 2023, "value": 30.0},
            {"economy": "20_USA", "fuel_code": "unmapped_b", "year": 2023, "value": 70.0},
        ]
    )
    monkeypatch.setattr(aggregated, "_load_esto_base_csv", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(aggregated, "_load_demand_csv", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(aggregated, "_extract_base_year", lambda *args, **kwargs: base.copy())
    monkeypatch.setattr(aggregated, "_extract_projection_years", lambda *args, **kwargs: projection.copy())

    reference = build_raw_demand_conservation_reference(
        economy="20_USA",
        scenarios=["Reference"],
        base_year=2022,
        final_year=2023,
        data_path="unused.csv",
        esto_data_path="unused.csv",
    )
    totals = reference.groupby("year")["reference_total"].sum().to_dict()

    assert totals == pytest.approx({2022: 10.0, 2023: 100.0})
    assert reference["esto_product"].eq("__all_fuels__").all()


def test_breakdown_components_add_back_to_existing_total_difference():
    reference = _rows("reference_total", [40.0, 60.0])
    reference["esto_product"] = "__all_fuels__"
    expected = pd.DataFrame(
        [
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 35.0},
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "p2", "year": 2030, "demand_value": 55.0},
        ]
    )
    resolved = prepare_reconciliation_demand_totals(
        pd.DataFrame(
            [
                {"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 50.0},
                {"economy": "20_USA", "scenario": "Reference", "esto_product": "p2", "year": 2030, "demand_value": 70.0},
            ]
        )
    )

    breakdown = build_balance_demand_conservation_breakdown(reference, expected, resolved)

    # Mapping loses 10 PJ; resolution adds 30 PJ. Net resolved-reference is 20 PJ.
    assert breakdown["difference"].sum() == pytest.approx(20.0)
    stage_totals = breakdown.groupby("breakdown_stage")["difference"].sum().to_dict()
    assert stage_totals == pytest.approx(
        {
            "source_to_expected_mapping": -10.0,
            "expected_mapping_to_actual_resolved": 30.0,
        }
    )


def test_lineage_keeps_source_rows_once_and_does_not_invent_links():
    reference = pd.DataFrame(
        [
            {
                "economy": "20_USA", "scenario": "Reference",
                "sector_context": "All demand after detailed-sector exclusions",
                "esto_product": "__all_fuels__", "year": 2030,
                "reference_total": 100.0, "source_system": "NINTH",
                "source_row_id": "source_1", "source_sector_or_flow": "industry",
                "source_fuel_or_product": "gas", "value_classification": "exact_aggregated",
            }
        ]
    )
    expected = pd.DataFrame(
        [
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "gas_a", "year": 2030, "demand_value": 40.0},
            {"economy": "20_USA", "scenario": "Reference", "esto_product": "gas_b", "year": 2030, "demand_value": 60.0},
        ]
    )
    resolved = prepare_reconciliation_demand_totals(expected)

    lineage = build_balance_demand_conservation_lineage(reference, expected, resolved)
    original = lineage[lineage["lineage_stage"].eq("original_source")]
    mapped = lineage[lineage["lineage_stage"].eq("expected_mapped")]

    assert original["value"].sum() == pytest.approx(100.0)
    assert len(original) == 1
    assert mapped["value"].sum() == pytest.approx(100.0)
    assert mapped["linked_source_row_id"].eq("").all()
    assert mapped["mapping_status"].eq("mapped_but_source_link_not_retained").all()


def test_breakdown_labels_direct_proportional_and_estimated_values():
    reference = _rows("reference_total", [100.0, 0.0]).iloc[[0]].copy()
    reference["esto_product"] = "__all_fuels__"
    expected = pd.DataFrame([
        {"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 100.0}
    ])
    resolved = prepare_reconciliation_demand_totals(expected)
    expected_provenance = pd.DataFrame([
        {
            "economy": "20_USA", "scenario": "Reference", "year": 2030,
            "esto_product": "p1", "source_system": "NINTH",
            "source_fuel_or_product": "01_coal", "allocation_method": "proportional_esto_base_year",
            "allocation_share": 0.75,
        }
    ])
    resolved_provenance = pd.DataFrame([
        {
            "economy": "20_USA", "scenario": "Reference", "year": 2030,
            "esto_product": "p1", "source_system": "LEAP_BALANCE",
            "source_fuel_or_product": "Coal", "allocation_method": "equal_split",
            "allocation_share": 0.5,
        }
    ])

    breakdown = build_balance_demand_conservation_breakdown(
        reference, expected, resolved, expected_provenance, resolved_provenance
    )
    row = breakdown[breakdown["component"].eq("p1")].iloc[0]
    assert row["expected_source_system"] == "NINTH"
    assert row["expected_allocation_methods"] == "proportional_esto_base_year"
    assert row["expected_value_quality"] == "allocated"
    assert row["actual_allocation_methods"] == "equal_split"
    assert row["actual_value_quality"] == "estimated"


#%%

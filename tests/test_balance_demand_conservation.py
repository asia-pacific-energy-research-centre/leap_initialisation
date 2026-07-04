"""Focused tests for the independent balance-demand conservation diagnostic."""

#%%

import pandas as pd
import pytest

from codebase.functions.balance_demand_conservation import (
    BREAKDOWN_SCHEMA_VERSION,
    PRODUCED_DEMAND_SYSTEM,
    YEAR_TYPE_ACTUAL,
    YEAR_TYPE_COMPRESSED_PROJECTION,
    build_balance_demand_conservation_breakdown,
    build_raw_demand_conservation_reference,
    build_balance_demand_conservation_diagnostics,
    build_balance_demand_conservation_lineage,
    prepare_aggregated_demand_reference,
    prepare_reconciliation_demand_totals,
    prepare_reconciliation_sector_demand_totals,
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


def test_sector_exclusions_are_applied_to_leap_rows_before_aggregation():
    sector_rows = pd.DataFrame(
        [
            {
                "economy": "20_USA", "scenario": "Reference", "sheet": "Industry",
                "esto_product": "p1", "esto_flow": "14.03 Manufacturing", "year": 2030,
                "demand_value": 40.0,
            },
            {
                "economy": "20_USA", "scenario": "Reference", "sheet": "Other sector",
                "esto_product": "p1", "esto_flow": "16.02 Agriculture", "year": 2030,
                "demand_value": 60.0,
            },
        ]
    )

    totals, audit = prepare_reconciliation_sector_demand_totals(
        sector_rows,
        excluded_sectors=["14_industry_sector"],
    )

    assert totals["resolved_total"].sum() == pytest.approx(60.0)
    status = audit.set_index("leap_branch")["included"].to_dict()
    assert status == {"Industry": False, "Other sector": True}
    assert (
        audit.set_index("leap_branch").loc["Industry", "exclusion_reason"]
        == "configured_detailed_sector_exclusion"
    )


def test_breakdown_shows_leap_branch_contributions_and_exclusions():
    reference = _rows("reference_total", [60.0, 0.0]).iloc[[0]].copy()
    reference["esto_product"] = "__all_fuels__"
    expected = pd.DataFrame([
        {"economy": "20_USA", "scenario": "Reference", "esto_product": "p1", "year": 2030, "demand_value": 60.0}
    ])
    resolved = prepare_reconciliation_demand_totals(expected)
    branch_audit = pd.DataFrame(
        [
            {
                "economy": "20_USA", "scenario": "Reference", "year": 2030,
                "esto_product": "p1", "esto_flow": "16.02 Agriculture",
                "leap_branch": "Other sector", "branch_contribution_value": 60.0,
                "included": True, "exclusion_reason": "",
            },
            {
                "economy": "20_USA", "scenario": "Reference", "year": 2030,
                "esto_product": "p1", "esto_flow": "14.03 Manufacturing",
                "leap_branch": "Industry", "branch_contribution_value": 40.0,
                "included": False, "exclusion_reason": "configured_detailed_sector_exclusion",
            },
        ]
    )
    source_scope = pd.DataFrame(
        [
            {
                "source_system": "ESTO", "economy": "20_USA", "scenario": "Reference",
                "year": 2030, "source_flow_or_sector": "14 Industry sector",
                "source_fuel_or_product": "p1", "value": 100.0, "included": False,
                "exclusion_reason": "subtotal",
            },
            {
                "source_system": "ESTO", "economy": "20_USA", "scenario": "Reference",
                "year": 2030, "source_flow_or_sector": "10.01 Own Use",
                "source_fuel_or_product": "p1", "value": 5.0, "included": False,
                "exclusion_reason": "handled_by_other_loss_own_use_proxy",
            },
        ]
    )

    breakdown = build_balance_demand_conservation_breakdown(
        reference,
        expected,
        resolved,
        source_scope_audit=source_scope,
        resolved_scope_audit=branch_audit,
    )
    row = breakdown[breakdown["component"].eq("p1")].iloc[0]
    assert row["included_leap_branches"] == "Other sector"
    assert row["excluded_leap_branches"] == "Industry"
    assert row["included_leap_branch_contributions"] == "Other sector=60"
    assert row["excluded_leap_branch_contributions"] == "Industry=40"
    assert row["excluded_source_flows"] == "10.01 Own Use"


# ── Realigned semantics: produced-demand "actual" side (not LEAP readback) ─────


def _produced(products_values: dict[str, float], year: int = 2030) -> pd.DataFrame:
    """Build a produced-demand-shaped frame (build_aggregated_demand_as_dummy)."""
    return pd.DataFrame(
        [
            {
                "economy": "20_USA", "scenario": "Reference",
                "esto_product": product, "year": year, "demand_value": value,
            }
            for product, value in products_values.items()
        ]
    )


def test_conservation_holds_when_produced_demand_matches_reference():
    # The "actual" side is our produced demand; when it equals the ESTO/9th
    # reference the totals reconcile to zero.
    produced = _produced({"07.01 Motor gasoline": 40.0, "08.01 Natural gas": 60.0})

    diagnostics = build_balance_demand_conservation_diagnostics(
        prepare_aggregated_demand_reference(produced, collapse_products=True),
        prepare_reconciliation_demand_totals(produced, collapse_products=True),
    )

    assert diagnostics.loc[0, "status"] == "match"
    assert not diagnostics["is_mismatch"].any()
    assert diagnostics.loc[0, "reference_total"] == pytest.approx(100.0)
    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(100.0)


def test_injected_leak_in_produced_demand_is_caught_and_localized():
    produced_full = _produced({"07.01 Motor gasoline": 40.0, "08.01 Natural gas": 60.0})
    reference = prepare_aggregated_demand_reference(produced_full, collapse_products=True)
    # Drop a produced product row -> a genuine conservation leak of 60 PJ.
    produced_leaked = produced_full.iloc[[0]].copy()

    diagnostics = build_balance_demand_conservation_diagnostics(
        reference,
        prepare_reconciliation_demand_totals(produced_leaked, collapse_products=True),
    )
    assert diagnostics.loc[0, "status"] == "value_mismatch"
    assert diagnostics.loc[0, "reason"] == "produced_demand_differs_from_reference"
    assert diagnostics.loc[0, "difference"] == pytest.approx(-60.0)

    breakdown = build_balance_demand_conservation_breakdown(
        reference_rows=reference,
        expected_mapped_rows=produced_leaked,
        resolved_rows=prepare_reconciliation_demand_totals(produced_leaked),
    )
    mapping_stage = breakdown[breakdown["breakdown_stage"].eq("source_to_expected_mapping")]
    # The mapping bridge localizes the -60 gap to the economy/scenario/year group.
    assert mapping_stage["difference"].sum() == pytest.approx(-60.0)
    assert (mapping_stage["economy"] == "20_USA").all()


def test_lineage_actual_side_is_produced_demand_not_leap_readback():
    reference = pd.DataFrame(
        [
            {
                "economy": "20_USA", "scenario": "Reference",
                "sector_context": "Demand rows included in conservation scope",
                "esto_product": "__all_fuels__", "year": 2030,
                "reference_total": 100.0, "source_system": "NINTH",
                "source_row_id": "source_1", "source_sector_or_flow": "industry",
                "source_fuel_or_product": "gas", "value_classification": "exact_aggregated",
            }
        ]
    )
    produced = _produced({"gas_a": 40.0, "gas_b": 60.0})
    resolved = prepare_reconciliation_demand_totals(produced)

    lineage = build_balance_demand_conservation_lineage(reference, produced, resolved)
    actual = lineage[lineage["lineage_stage"].eq("actual_resolved")]

    assert not actual.empty
    # No LEAP balance anywhere on the actual side.
    assert (actual["source_system"] == PRODUCED_DEMAND_SYSTEM).all()
    assert not lineage["source_system"].eq("LEAP_BALANCE").any()
    assert actual["mapping_status"].eq("produced_demand_source_link_not_retained").all()


def test_diagnostic_flags_compressed_projection_year():
    reference = _rows("reference_total", [10.0, 20.0])
    resolved = _rows("resolved_total", [10.0, 20.0])

    diagnostics = build_balance_demand_conservation_diagnostics(
        reference, resolved, compressed_projection_years={2030}
    )
    assert (diagnostics["year_type"] == YEAR_TYPE_COMPRESSED_PROJECTION).all()

    # Without the flag, a year is a real annual balance.
    plain = build_balance_demand_conservation_diagnostics(reference, resolved)
    assert (plain["year_type"] == YEAR_TYPE_ACTUAL).all()


def test_empty_comparison_is_failure_not_silent_pass():
    empty_reference = pd.DataFrame(
        columns=["economy", "scenario", "sector_context", "esto_product", "year", "reference_total"]
    )
    empty_resolved = pd.DataFrame(
        columns=["economy", "scenario", "sector_context", "esto_product", "year", "resolved_total"]
    )

    diagnostics = build_balance_demand_conservation_diagnostics(empty_reference, empty_resolved)

    assert len(diagnostics) == 1
    assert diagnostics.loc[0, "status"] == "failed_empty"
    assert bool(diagnostics.loc[0, "is_mismatch"]) is True


def test_outputs_carry_schema_version():
    reference = _rows("reference_total", [10.0, 20.0])
    resolved = _rows("resolved_total", [10.0, 20.0])
    diagnostics = build_balance_demand_conservation_diagnostics(reference, resolved)
    assert (diagnostics["schema_version"] == BREAKDOWN_SCHEMA_VERSION).all()

    produced = _produced({"p1": 10.0})
    breakdown = build_balance_demand_conservation_breakdown(
        prepare_aggregated_demand_reference(produced, collapse_products=True),
        produced,
        prepare_reconciliation_demand_totals(produced),
    )
    assert (breakdown["schema_version"] == BREAKDOWN_SCHEMA_VERSION).all()


def test_reference_and_produced_demand_apply_identical_exclusions(monkeypatch):
    # Turning an exclusion on must drop the SAME sector from both the ESTO/9th
    # reference side and the produced-demand actual side, and the remaining
    # totals must still reconcile. Uses Current Accounts so only the ESTO base
    # year is exercised (no projection), with real exclusion logic on both sides.
    import codebase.aggregated_demand_workflow as aggregated
    from codebase.aggregated_demand_workflow import build_aggregated_demand_as_dummy

    esto = pd.DataFrame(
        [
            # Excludable industry sector (14_industry_sector -> all 14 flows).
            {"economy": "20_USA", "flows": "14.03 Manufacturing", "products": "Coal",
             "is_subtotal": False, "2022": 40.0},
            # Kept agriculture sector.
            {"economy": "20_USA", "flows": "16.02 Agriculture", "products": "Gas",
             "is_subtotal": False, "2022": 60.0},
        ]
    )
    monkeypatch.setattr(aggregated, "_load_esto_base_csv", lambda *a, **k: esto.copy())
    monkeypatch.setattr(aggregated, "_load_demand_csv", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(
        aggregated, "load_fuel_mapping",
        lambda *a, **k: {"Coal": "Coal fuel", "Gas": "Gas fuel"},
    )
    monkeypatch.setattr(
        aggregated, "load_active_mapping_sheet",
        lambda *a, **k: pd.DataFrame(
            [
                {"raw_leap_fuel_name": "Coal fuel", "esto_product": "01.01 Coal"},
                {"raw_leap_fuel_name": "Gas fuel", "esto_product": "08.01 Natural gas"},
            ]
        ),
    )

    common = dict(
        economy="20_USA", scenarios=["Current Accounts"],
        base_year=2022, final_year=2022,
        data_path="unused.csv", esto_data_path="unused.csv",
    )
    reference = build_raw_demand_conservation_reference(
        excluded_sectors=["14_industry_sector"], **common
    )
    produced = build_aggregated_demand_as_dummy(
        excluded_sectors=["14_industry_sector"],
        fuel_mappings_path="unused.xlsx", **common
    )

    # The excluded industry/coal energy is absent from BOTH sides.
    assert reference["reference_total"].sum() == pytest.approx(60.0)
    assert produced["demand_value"].sum() == pytest.approx(60.0)
    assert not produced["esto_product"].eq("01.01 Coal").any()

    diagnostics = build_balance_demand_conservation_diagnostics(
        reference,
        prepare_reconciliation_demand_totals(produced, collapse_products=True),
    )
    assert not diagnostics["is_mismatch"].any()


def test_mis_flagged_parent_subtotal_is_excluded_from_reference_and_produced(monkeypatch):
    import codebase.aggregated_demand_workflow as aggregated
    from codebase.aggregated_demand_workflow import build_aggregated_demand_as_dummy

    esto = pd.DataFrame(
        [
            {"economy": "20_USA", "flows": "16.01.99 Services", "products": "15 Solid biomass",
             "is_subtotal": False, "2022": 30.0},
            {"economy": "20_USA", "flows": "16.01.99 Services", "products": "15.01 Fuelwood",
             "is_subtotal": False, "2022": 30.0},
            {"economy": "20_USA", "flows": "16.01.99 Services", "products": "17 Electricity",
             "is_subtotal": False, "2022": 20.0},
        ]
    )
    monkeypatch.setattr(aggregated, "_load_esto_base_csv", lambda *a, **k: esto.copy())
    monkeypatch.setattr(aggregated, "_load_demand_csv", lambda *a, **k: pd.DataFrame())
    # Deliberately leave the parent unmapped, matching the production mapping.
    monkeypatch.setattr(
        aggregated, "load_fuel_mapping",
        lambda *a, **k: {"15.01 Fuelwood": "Fuelwood", "17 Electricity": "Electricity"},
    )
    monkeypatch.setattr(
        aggregated, "load_active_mapping_sheet",
        lambda *a, **k: pd.DataFrame(
            [
                {"raw_leap_fuel_name": "Fuelwood", "esto_product": "15.01 Fuelwood"},
                {"raw_leap_fuel_name": "Electricity", "esto_product": "17 Electricity"},
            ]
        ),
    )
    common = dict(
        economy="20_USA", scenarios=["Current Accounts"], base_year=2022,
        final_year=2022, data_path="unused.csv", esto_data_path="unused.csv",
    )

    reference, scope_audit = build_raw_demand_conservation_reference(
        return_scope_audit=True, **common
    )
    produced = build_aggregated_demand_as_dummy(
        fuel_mappings_path="unused.xlsx", **common
    )

    parent_audit = scope_audit[
        scope_audit["source_fuel_or_product"].eq("15 Solid biomass")
    ]
    assert not parent_audit["included"].any()
    assert parent_audit["exclusion_reason"].eq("mis_flagged_parent_subtotal").all()
    assert not reference["source_fuel_or_product"].eq("15 Solid biomass").any()
    assert not produced["esto_product"].eq("15 Solid biomass").any()
    # Genuine top-level leaves remain, and both independent totals agree.
    assert reference["reference_total"].sum() == pytest.approx(50.0)
    assert produced["demand_value"].sum() == pytest.approx(50.0)
    diagnostics = build_balance_demand_conservation_diagnostics(
        reference,
        prepare_reconciliation_demand_totals(produced, collapse_products=True),
    )
    assert not diagnostics["is_mismatch"].any()


#%%

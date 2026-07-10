"""Focused tests for the balance-demand mapping fixes (INIT-008).

Covers:
* Fix 1 (known LEAP label exceptions): the "Black liqour" LEAP-export spelling
  is aliased to the mapping-sheet "Black liquor" before the leap_combined join.
* Fix 2 (general rollup-resolution fallback): demand rows with no direct ESTO
  pair are resolved through the maintained rollup rules (leap_rollup_rules and
  ninth_rollup_rules), proven via the Road transport case but not scoped to it.
"""

from __future__ import annotations

import pandas as pd

import codebase.functions.supply_demand_mapping as sdm
from codebase.configuration.known_leap_label_exceptions import KNOWN_LEAP_LABEL_EXCEPTIONS


# --- Fix 1: demand-mapping alias -----------------------------------------------


def _patch_direct_demand_sheets(monkeypatch, ninth: pd.DataFrame, esto: pd.DataFrame) -> None:
    def _fake_loader(sheet_name: str) -> pd.DataFrame:
        if sheet_name == sdm.DIRECT_DEMAND_NINTH_MAPPING_SHEET:
            return ninth.copy()
        return esto.copy()

    monkeypatch.setattr(sdm, "_load_active_direct_demand_mapping_sheet", _fake_loader)
    monkeypatch.setattr(sdm, "load_fuel_aliases", lambda *a, **k: {})
    monkeypatch.setattr(sdm, "build_sector_to_esto_flow_lookup", lambda *a, **k: {})


def _direct_demand_fixtures() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Mapping sheets use the correct "Black liquor" spelling.
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Black liquor",
                "ninth_sector": "15_04_industry",
                "ninth_fuel": "15_04_black_liquor",
            }
        ]
    )
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Black liquor",
                "esto_flow": "15.04 Industry",
                "esto_product": "15.04 Black liqour",
            }
        ]
    )
    sheet_map = pd.DataFrame(
        [{"sheet_name": "Industry", "sector_code_9th": "15_04_industry", "sector_name": "Industry"}]
    )
    return ninth, esto, sheet_map


def _run_direct_demand(monkeypatch, leap_fuel_label: str) -> pd.DataFrame:
    ninth, esto, sheet_map = _direct_demand_fixtures()
    _patch_direct_demand_sheets(monkeypatch, ninth, esto)
    leap_long = pd.DataFrame([{"sheet_name": "Industry", "fuel_label": leap_fuel_label}])
    return sdm._build_direct_demand_mapping_status(sheet_map=sheet_map, leap_long=leap_long)


def test_known_label_exception_is_registered() -> None:
    assert KNOWN_LEAP_LABEL_EXCEPTIONS.get("Black liqour") == "Black liquor"


def test_black_liqour_alias_resolves_same_pair_as_black_liquor(monkeypatch) -> None:
    typo = _run_direct_demand(monkeypatch, "Black liqour")  # LEAP-export spelling
    correct = _run_direct_demand(monkeypatch, "Black liquor")  # mapping-sheet spelling

    assert not typo.empty
    assert typo["esto_flow"].iloc[0] == "15.04 Industry"
    assert typo["esto_product"].iloc[0] == "15.04 Black liqour"
    assert typo["ninth_fuel_code"].iloc[0] == "15_04_black_liquor"
    # Aliased typo row resolves to exactly the same pair as the correct spelling.
    assert typo["esto_flow"].iloc[0] == correct["esto_flow"].iloc[0]
    assert typo["esto_product"].iloc[0] == correct["esto_product"].iloc[0]
    assert typo["ninth_fuel_code"].iloc[0] == correct["ninth_fuel_code"].iloc[0]


# --- Fix 2: general rollup-resolution fallback ---------------------------------


def _unresolved(rows: list[dict[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"],
    )


def _empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"])


def test_road_case_resolves_via_leap_rollup() -> None:
    # leap_rollup_rules rolls Freight road -> Road (keeping the fuel); the pre-built
    # "Road" combined-sheet row supplies the ESTO pair, even though no Freight-road
    # ESTO row exists at any level.
    esto_ref = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Road",
                "raw_leap_fuel_name": "Electricity",
                "esto_flow": "15.02 Road",
                "esto_product": "17 Electricity",
            }
        ]
    )
    unresolved = _unresolved(
        [
            {
                "leap_sector_name_full_path": "Freight road/Trucks/BEV heavy",
                "raw_leap_fuel_name": "Electricity",
                "ninth_sector": "15_02_02_freight",
                "ninth_fuel": "17_electricity",
            }
        ]
    )
    out = sdm._resolve_demand_esto_pairs_via_rollups(
        unresolved, esto_reference=esto_ref, canonical=_empty_canonical()
    )
    assert len(out) == 1
    assert out["esto_flow"].iloc[0] == "15.02 Road"
    assert out["esto_product"].iloc[0] == "17 Electricity"
    assert "leap_rollup" in out["Note"].iloc[0]


def test_second_leap_rollup_pattern_is_not_road_specific() -> None:
    # A different maintained leap_rollup pattern: BKB and PB plants -> Coal
    # transformation. Proves the resolver is general, not hard-coded to Road.
    esto_ref = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Coal transformation",
                "raw_leap_fuel_name": "Coal",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "01 Coal",
            }
        ]
    )
    unresolved = _unresolved(
        [
            {
                "leap_sector_name_full_path": "BKB and PB plants",
                "raw_leap_fuel_name": "Coal",
                "ninth_sector": "",
                "ninth_fuel": "",
            }
        ]
    )
    out = sdm._resolve_demand_esto_pairs_via_rollups(
        unresolved, esto_reference=esto_ref, canonical=_empty_canonical()
    )
    assert len(out) == 1
    assert out["esto_flow"].iloc[0] == "09.08 Coal transformation"
    assert "leap_rollup" in out["Note"].iloc[0]


def test_ninth_rollup_sheet_is_consulted() -> None:
    # When the LEAP axis cannot resolve (empty ESTO reference), the resolver must
    # fall back to ninth_rollup_rules + the 9th->ESTO canonical bridge. This proves
    # ninth_rollup_rules is actually consulted, not just loaded.
    canonical = pd.DataFrame(
        [
            {
                "ninth_sector": "09_08_coal_transformation_incl_own_use",
                "ninth_fuel": "01_coal",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "01 Coal",
            }
        ]
    )
    unresolved = _unresolved(
        [
            {
                "leap_sector_name_full_path": "No such leap sector for rollup",
                "raw_leap_fuel_name": "Coal",
                "ninth_sector": "10_01_05_coke_ovens",
                "ninth_fuel": "01_coal",
            }
        ]
    )
    out = sdm._resolve_demand_esto_pairs_via_rollups(
        unresolved,
        esto_reference=pd.DataFrame(
            columns=["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
        ),
        canonical=canonical,
    )
    assert len(out) == 1
    assert out["esto_flow"].iloc[0] == "09.08 Coal transformation"
    assert out["esto_product"].iloc[0] == "01 Coal"
    assert "ninth_rollup" in out["Note"].iloc[0]


def test_esto_rollup_sheet_is_consulted() -> None:
    # Leap axis and ninth-rollup axis both miss; the direct 9th->ESTO bridge yields
    # a leaf ESTO pair that is not itself a combined target, and esto_rollup_rules
    # roll it to the maintained parent target that IS present. Proves esto_rollup
    # is consulted, not just loaded.
    esto_ref = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "09.01-09.02 Power sector",
                "raw_leap_fuel_name": "Coal",
                "esto_flow": "09.01.01,09.02.01 Electricity plants",
                "esto_product": "01 Coal",
            }
        ]
    )
    canonical = pd.DataFrame(
        [
            {
                "ninth_sector": "10_99_99_synthetic",
                "ninth_fuel": "01_coal",
                "esto_flow": "09.01.01 Electricity plants",  # leaf, not a combined target
                "esto_product": "01 Coal",
            }
        ]
    )
    unresolved = _unresolved(
        [
            {
                "leap_sector_name_full_path": "Main activity producer electricity plants",
                "raw_leap_fuel_name": "Coal",
                "ninth_sector": "10_99_99_synthetic",
                "ninth_fuel": "01_coal",
            }
        ]
    )
    out = sdm._resolve_demand_esto_pairs_via_rollups(
        unresolved, esto_reference=esto_ref, canonical=canonical
    )
    assert len(out) == 1
    assert out["esto_flow"].iloc[0] == "09.01.01,09.02.01 Electricity plants"
    assert out["esto_product"].iloc[0] == "01 Coal"
    assert "esto_rollup" in out["Note"].iloc[0]


def test_projection_only_path_sees_rollup_augmented_road_rows() -> None:
    # Critical: baseline_seed always uses _build_projection_only_mapping_status,
    # which does a plain inner join on the augmented workbook and drops unmatched
    # rows silently. The rollup fallback must land in the augmentation layer so the
    # previously-missing Freight/Passenger road demand appears in ITS output, not
    # only in the real-export comparison path.
    workbook = sdm._build_augmented_balance_demand_mapping_workbook()
    status = sdm._build_projection_only_mapping_status(workbook)
    road = status[status["esto_flow"].astype(str).str.strip() == "15.02 Road"]
    assert not road.empty
    # Freight/Passenger road descendant 9th sectors (15_02_01_* / 15_02_02_*),
    # which have no leap_combined_esto row at any level, are present in the
    # projection-only (inner-join) output carrying the pre-built Road ESTO pair —
    # i.e. beyond just the native "15_02_road" sector.
    codes = road["sector_code_9th"].astype(str)
    assert codes.str.startswith(("15_02_01", "15_02_02")).any()


def test_unresolvable_row_is_omitted() -> None:
    unresolved = _unresolved(
        [
            {
                "leap_sector_name_full_path": "Totally unmapped sector",
                "raw_leap_fuel_name": "Unobtanium",
                "ninth_sector": "99_99_nowhere",
                "ninth_fuel": "99_unobtanium",
            }
        ]
    )
    out = sdm._resolve_demand_esto_pairs_via_rollups(
        unresolved,
        esto_reference=pd.DataFrame(
            columns=["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
        ),
        canonical=_empty_canonical(),
    )
    assert out.empty

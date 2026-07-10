import pandas as pd

from codebase.outlook_mapping_maintenance_workflow import (
    _build_crosswalk_target_conflicts,
    _build_implied_missing_crosswalk_pairs,
    _build_missing_between_sheet_conflicts,
    _build_trio_presence_check,
    _refresh_esto_sheet,
    _refresh_ninth_sheet,
)


def test_refresh_sheets_drop_many_to_many_is_ok_but_keep_cardinality() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
            },
            {
                "leap_sector_name_full_path": "Buildings",
                "raw_leap_fuel_name": "Electricity",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
            },
        ]
    )
    esto_lookup = pd.DataFrame(
        [
            {
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "esto_pair_is_subtotal": False,
                "esto_pair_abs_sum": 1.0,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "many_to_many_is_ok": True,
            },
            {
                "leap_sector_name_full_path": "Buildings",
                "raw_leap_fuel_name": "Electricity",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "many_to_many_is_ok": True,
            },
        ]
    )
    ninth_lookup = pd.DataFrame(
        [
            {
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "ninth_pair_is_subtotal": False,
                "ninth_pair_abs_sum": 1.0,
            }
        ]
    )

    refreshed_esto = _refresh_esto_sheet(esto, esto_lookup)
    refreshed_ninth = _refresh_ninth_sheet(ninth, ninth_lookup)

    assert "many_to_many_is_ok" not in refreshed_esto.columns
    assert "many_to_many_is_ok" not in refreshed_ninth.columns
    assert set(refreshed_esto["pair_mapping_cardinality"]) == {"many_to_one"}
    assert set(refreshed_ninth["pair_mapping_cardinality"]) == {"many_to_one"}


def test_missing_between_sheet_conflicts_reports_active_counterpart_gap() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_original": "Industry",
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_original": "Buildings",
                "leap_sector_name_full_path": "Buildings",
                "raw_leap_fuel_name": "Electricity",
                "ninth_sector": "16_other_sector",
                "ninth_fuel": "17_electricity",
            }
        ]
    )

    trio_presence = _build_trio_presence_check(esto, ninth)
    conflicts = _build_missing_between_sheet_conflicts(trio_presence)

    assert set(conflicts["presence_status"]) == {
        "esto_active_ninth_missing",
        "ninth_active_esto_missing",
    }


def test_crosswalk_target_conflicts_reports_different_active_target() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.02 LPG",
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
            }
        ]
    )
    ninth_to_esto_pairs = pd.DataFrame(
        [
            {
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
            }
        ]
    )

    conflicts = _build_crosswalk_target_conflicts(esto, ninth, ninth_to_esto_pairs)

    assert len(conflicts) == 1
    assert conflicts.loc[0, "conflict_type"] == "strict_one_to_one_target_mismatch"
    assert conflicts.loc[0, "active_esto_targets"] == "14 Industry sector || 08.02 LPG"
    assert conflicts.loc[0, "esto_cardinalities"] == "one_to_one"
    assert conflicts.loc[0, "ninth_cardinality"] == "one_to_one"


def test_crosswalk_target_conflicts_labels_non_strict_cardinality_review() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.02 LPG",
            },
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.03 Refinery gas",
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
            }
        ]
    )
    ninth_to_esto_pairs = pd.DataFrame(
        [
            {
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
            }
        ]
    )

    conflicts = _build_crosswalk_target_conflicts(esto, ninth, ninth_to_esto_pairs)

    assert len(conflicts) == 1
    assert conflicts.loc[0, "conflict_type"] == "non_strict_cardinality_target_review"
    assert conflicts.loc[0, "esto_cardinalities"] == "one_to_many"
    assert conflicts.loc[0, "ninth_cardinality"] == "one_to_one"


def test_crosswalk_target_conflicts_labels_rollup_covering_implied_components() -> None:
    # leap_combined_esto maps to the rollup target; ninthpairs_to_esto maps the
    # same 9th pair to the individual component targets. Both representations are
    # equivalent — the rollup covers the components — so the conflict should be
    # labelled as rollup_covers_implied_components rather than a true mismatch.
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "CHP interim/CHP interim",
                "raw_leap_fuel_name": "Black liquor",
                "esto_flow": "09.01.02,09.02.02 CHP plants",
                "esto_product": "15.04 Black liquor",
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "CHP interim/CHP interim",
                "raw_leap_fuel_name": "Black liquor",
                "ninth_sector": "09_02_chp_plants",
                "ninth_fuel": "15_04_black_liquor",
            }
        ]
    )
    ninth_to_esto_pairs = pd.DataFrame(
        [
            {
                "ninth_sector": "09_02_chp_plants",
                "ninth_fuel": "15_04_black_liquor",
                "esto_flow": "09.01.02 CHP plants",
                "esto_product": "15.04 Black liquor",
            },
            {
                "ninth_sector": "09_02_chp_plants",
                "ninth_fuel": "15_04_black_liquor",
                "esto_flow": "09.02.02 CHP plants",
                "esto_product": "15.04 Black liquor",
            },
        ]
    )

    conflicts = _build_crosswalk_target_conflicts(esto, ninth, ninth_to_esto_pairs)

    assert len(conflicts) == 1
    assert conflicts.loc[0, "conflict_type"] == "rollup_covers_implied_components"
    assert conflicts.loc[0, "active_esto_targets"] == "09.01.02,09.02.02 CHP plants || 15.04 Black liquor"


def test_implied_missing_crosswalk_pairs_reports_candidate_to_add() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
            }
        ]
    )
    ninth_to_esto_pairs = pd.DataFrame(
        columns=["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]
    )

    candidates = _build_implied_missing_crosswalk_pairs(esto, ninth, ninth_to_esto_pairs)

    assert len(candidates) == 1
    assert candidates.loc[0, "candidate_status"] == "candidate_to_add"
    assert not bool(candidates.loc[0, "would_create_many_to_many"])
    assert candidates.loc[0, "candidate_crosswalk_cardinality"] == "one_to_one"


def test_implied_missing_crosswalk_pairs_labels_many_to_many_candidate() -> None:
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.02 LPG",
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
            }
        ]
    )
    ninth_to_esto_pairs = pd.DataFrame(
        [
            {
                "ninth_sector": "14_industry_sector",
                "ninth_fuel": "08_gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
            },
            {
                "ninth_sector": "16_other_sector",
                "ninth_fuel": "08_gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.02 LPG",
            },
        ]
    )

    candidates = _build_implied_missing_crosswalk_pairs(esto, ninth, ninth_to_esto_pairs)

    assert len(candidates) == 1
    assert candidates.loc[0, "candidate_status"] == "review_many_to_many_before_adding"
    assert bool(candidates.loc[0, "would_create_many_to_many"])
    assert candidates.loc[0, "candidate_crosswalk_cardinality"] == "many_to_many"

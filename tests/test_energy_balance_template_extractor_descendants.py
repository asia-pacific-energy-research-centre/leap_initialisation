from pathlib import Path

import pandas as pd

from codebase.utilities import energy_balance_template_extractor as extractor_module
from codebase.utilities.energy_balance_template_extractor import TemplateBalanceExtractor


def _make_extractor(
    *,
    explicit_pair_mappings_only: bool,
    allow_descendant_mapping_expansion: bool = True,
    present_child: bool = False,
) -> TemplateBalanceExtractor:
    extractor = TemplateBalanceExtractor(
        template_sheet="EBal|2060",
        mapping_pairs_path=Path("config/leap_mappings.xlsx"),
        codebook_path=Path("config/esto_9th_leap_codebook.xlsx"),
        explicit_pair_mappings_only=explicit_pair_mappings_only,
        allow_descendant_mapping_expansion=allow_descendant_mapping_expansion,
    )

    # Keep this test focused on explicit full-path mappings and descendant reuse.
    extractor._flow_name_to_codes = {}
    extractor._fuel_name_to_codes = {}
    extractor._flow_name_to_esto = {}
    extractor._fuel_name_to_esto = {}
    extractor._canonical_pair_to_esto = {}
    extractor._balance_name_pair_to_esto = {}
    extractor._balance_code_pair_to_esto = {}
    extractor._balance_name_pair_to_ninth = {}
    extractor._flow_code_cache = {}
    extractor._fuel_code_cache = {}
    extractor._flow_esto_cache = {}
    extractor._fuel_esto_cache = {}
    extractor._balance_full_path_pairs_to_remove = set()
    extractor._balance_full_path_pairs_with_removed_rows = set()

    fuel_key = extractor._canonicalize_label("Coal")
    parent_key = extractor._canonicalize_path_key("Transformation")
    child_key = extractor._canonicalize_path_key("Transformation/Electricity plants")

    extractor._balance_full_path_pair_to_esto = {
        (child_key, fuel_key): [
            {
                "esto_flow": "09.01.01 Electricity plants",
                "esto_product": "01 Coal",
                "candidate_leap_sector_name_full_path": "Transformation/Electricity plants",
                "candidate_leap_fuel_name": "Coal",
                "candidate_rule": "test_child_mapping",
                "pair_mapping_cardinality": "one_to_one",
            }
        ]
    }
    extractor._balance_full_path_pair_to_ninth = {
        (child_key, fuel_key): [
            {
                "ninth_sector": "09_01_01_electricity_plants",
                "ninth_fuel": "01_coal",
                "candidate_leap_sector_name_full_path": "Transformation/Electricity plants",
                "candidate_leap_fuel_name": "Coal",
                "candidate_rule": "test_child_mapping",
                "pair_mapping_cardinality": "one_to_one",
            }
        ]
    }

    present_keys = {(parent_key, fuel_key)}
    if present_child:
        present_keys.add((child_key, fuel_key))
    extractor._balance_present_source_keys_by_sheet = {"Balance": present_keys}
    return extractor


def _parent_row() -> pd.Series:
    return pd.Series(
        {
            "source_sheet": "Balance",
            "leap_sector_name": "Transformation",
            "leap_sector_name_full_path": "Transformation",
            "leap_sector_name_original": "Transformation",
            "leap_fuel_name": "Coal",
        }
    )


def test_balance_path_alias_maps_from_stocks_to_stock_changes() -> None:
    extractor = _make_extractor(explicit_pair_mappings_only=True)

    assert extractor._canonicalize_path_key("From Stocks") == (
        extractor._canonicalize_path_key("Stock Changes")
    )
    assert extractor._canonicalize_path_key("Statistical Differences") == (
        "statistical differences"
    )


def test_from_stocks_balance_row_uses_stock_changes_explicit_pair() -> None:
    extractor = _make_extractor(explicit_pair_mappings_only=True)
    stock_key = extractor._canonicalize_path_key("Stock Changes")
    fuel_key = extractor._canonicalize_label("Coal")
    extractor._balance_full_path_pair_to_esto = {
        (stock_key, fuel_key): [
            {
                "esto_flow": "06 Stock changes",
                "esto_product": "01 Coal",
                "candidate_leap_sector_name_full_path": "Stock Changes",
                "candidate_leap_fuel_name": "Coal",
                "candidate_rule": "",
                "pair_mapping_cardinality": "one_to_one",
            }
        ]
    }
    extractor._balance_full_path_pair_to_ninth = {}
    extractor._balance_present_source_keys_by_sheet = {
        "Balance": {(stock_key, fuel_key)}
    }
    row = pd.Series(
        {
            "source_sheet": "Balance",
            "leap_sector_name": "From Stocks",
            "leap_sector_name_full_path": "From Stocks",
            "leap_sector_name_original": "From Stocks",
            "leap_fuel_name": "Coal",
        }
    )

    records = extractor._map_row_records(row)

    assert len(records) == 1
    assert records[0]["mapping_status"] == "partial_full_path_pair"
    assert records[0]["esto_flow"] == "06 Stock changes"
    assert records[0]["esto_product"] == "01 Coal"


def test_non_explicit_mode_uses_absent_child_descendant_mapping_by_default() -> None:
    extractor = _make_extractor(explicit_pair_mappings_only=False, present_child=False)

    records = extractor._map_row_records(_parent_row())

    assert len(records) == 1
    assert records[0]["mapping_status"] == "mapped"
    assert records[0]["mapping_method"] == "module_full_path_pair"
    assert records[0]["match_resolution"] == "module_only"
    assert records[0]["esto_flow"] == "09.01.01 Electricity plants"


def test_descendant_mapping_expansion_switch_disables_absent_child_mapping() -> None:
    extractor = _make_extractor(
        explicit_pair_mappings_only=False,
        allow_descendant_mapping_expansion=False,
        present_child=False,
    )

    records = extractor._map_row_records(_parent_row())

    assert len(records) == 1
    assert records[0]["mapping_status"] == "unmapped"
    assert records[0]["mapping_method"] == ""
    assert records[0]["match_resolution"] == "detailed"
    assert records[0]["esto_flow"] == ""


def test_explicit_pair_mode_blocks_absent_child_descendant_mapping() -> None:
    extractor = _make_extractor(explicit_pair_mappings_only=True, present_child=False)

    records = extractor._map_row_records(_parent_row())

    assert len(records) == 1
    assert records[0]["mapping_status"] == "unmapped"
    assert records[0]["mapping_method"] == ""
    assert records[0]["match_resolution"] == "detailed"
    assert records[0]["esto_flow"] == ""


def test_parent_row_does_not_reuse_descendant_mapping_when_child_source_is_present() -> None:
    extractor = _make_extractor(explicit_pair_mappings_only=False, present_child=True)

    records = extractor._map_row_records(_parent_row())

    assert len(records) == 1
    assert records[0]["mapping_status"] == "unmapped"
    assert records[0]["remove_row"] is True
    assert records[0]["esto_flow"] == ""


def test_load_mappings_reports_non_subtotal_many_to_many_rows(tmp_path: Path) -> None:
    workbook = tmp_path / "mapping_fixture.xlsx"
    codebook = pd.DataFrame(columns=["name", "ninth_label", "ninth_column", "esto_label", "esto_column"])
    esto_leap = pd.DataFrame(columns=["category", "leap_name", "original_label"])
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
                "subtotal_mismatch_is_ok": True,
            },
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "12 Total final consumption",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
                "subtotal_mismatch_is_ok": True,
            },
            {
                "leap_sector_name_full_path": "Buildings",
                "raw_leap_fuel_name": "Electricity",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
                "subtotal_mismatch_is_ok": True,
            },
            {
                "leap_sector_name_full_path": "Buildings",
                "raw_leap_fuel_name": "Electricity",
                "esto_flow": "12 Total final consumption",
                "esto_product": "08.01 Natural gas",
                "many_to_many_is_ok": True,
                "subtotal_mismatch_is_ok": True,
            },
        ]
    )
    ninth = pd.DataFrame(columns=["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"])

    with pd.ExcelWriter(workbook) as writer:
        codebook.to_excel(writer, sheet_name="code_to_name", index=False)
        esto_leap.to_excel(writer, sheet_name="ESTO_LEAP_names", index=False)
        esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)

    extractor = TemplateBalanceExtractor(
        template_sheet="EBal|2060",
        mapping_pairs_path=workbook,
        codebook_path=workbook,
        explicit_pair_mappings_only=True,
    )

    extractor.load_mappings()

    diagnostics = extractor.many_to_many_is_ok_diagnostics
    assert len(diagnostics) == 4
    assert set(diagnostics["_diagnostic_issue"]) == {"non_subtotal_many_to_many_mapping"}
    assert set(diagnostics["_diagnostic_sheet"]) == {"leap_combined_esto"}
    assert set(diagnostics["legacy_many_to_many_is_ok"]) == {True}


def test_load_mappings_warns_and_continues_for_unapproved_subtotal_mismatch(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    workbook = tmp_path / "mapping_fixture.xlsx"
    codebook = pd.DataFrame(columns=["name", "ninth_label", "ninth_column", "esto_label", "esto_column"])
    esto_leap = pd.DataFrame(columns=["category", "leap_name", "original_label"])
    esto = pd.DataFrame(columns=["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"])
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transport non road/Freight non road/Rail",
                "raw_leap_fuel_name": "Hydrogen",
                "ninth_sector": "15_03_rail",
                "ninth_fuel": "16_x_hydrogen",
                "leap_is_subtotal": False,
                "ninth_pair_is_subtotal": True,
                "subtotal_mismatch_is_ok": False,
            }
        ]
    )

    with pd.ExcelWriter(workbook) as writer:
        codebook.to_excel(writer, sheet_name="code_to_name", index=False)
        esto_leap.to_excel(writer, sheet_name="ESTO_LEAP_names", index=False)
        esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)

    diagnostic_dir = tmp_path / "checks"
    monkeypatch.setattr(extractor_module, "SUBTOTAL_FLAG_DIAGNOSTIC_DIR", diagnostic_dir)
    monkeypatch.setattr(extractor_module, "load_subtotal_mismatch_exception_sets", lambda: {})
    monkeypatch.setattr(extractor_module, "load_leap_display_names", lambda: pd.DataFrame())

    extractor = TemplateBalanceExtractor(
        template_sheet="EBal|2060",
        mapping_pairs_path=workbook,
        codebook_path=workbook,
        explicit_pair_mappings_only=True,
    )

    extractor.load_mappings()

    warning_path = diagnostic_dir / "subtotal_flag_mismatch_warnings_leap_combined_ninth.csv"
    warning_rows = pd.read_csv(warning_path)
    output = capsys.readouterr().out

    assert len(warning_rows) == 1
    assert warning_rows.loc[0, "raw_leap_fuel_name"] == "Hydrogen"
    assert "mapping load will continue" in output
    assert (
        extractor._balance_full_path_pair_to_ninth[
            (
                extractor._canonicalize_path_key("Transport non road/Freight non road/Rail"),
                extractor._canonicalize_label("Hydrogen"),
            )
        ][0]["ninth_fuel"]
        == "16_x_hydrogen"
    )

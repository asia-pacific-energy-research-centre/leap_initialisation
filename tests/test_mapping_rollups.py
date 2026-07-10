from pathlib import Path

import pandas as pd

from codebase.mapping_tools.mapping_rollups import (
    build_all_effective_mappings,
    build_individual_mapping_consistency_qa,
    build_original_label_presence_qa,
    build_qa_tables,
    build_relationship_rows,
    build_subtotal_alignment_qa,
    ensure_rollup_sheets,
)
from codebase.mapping_tools.update_mapping_cardinality import build_mapping_balance_coverage_qa


def _write_minimal_workbook(path: Path) -> None:
    leap_esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transfers/Imports",
                "raw_leap_fuel_name": "Gasoline",
                "esto_flow": "08.01 Recycled products",
                "esto_product": "07.01 Motor gasoline",
            },
            {
                "leap_sector_name_full_path": "Transfers/Exports",
                "raw_leap_fuel_name": "Gasoline",
                "esto_flow": "08.02 Interproduct transfers",
                "esto_product": "07.01 Motor gasoline",
            },
        ]
    )
    ninth_esto = pd.DataFrame(
        [
            {
                "ninth_sector": "08_transfers",
                "ninth_fuel": "07_01_motor_gasoline",
                "esto_flow": "08.01 Recycled products",
                "esto_product": "07.01 Motor gasoline",
            }
        ]
    )
    leap_ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transfers/Imports",
                "raw_leap_fuel_name": "Gasoline",
                "ninth_sector": "08_transfers",
                "ninth_fuel": "07_01_motor_gasoline",
            },
            {
                "leap_sector_name_full_path": "Transfers/Exports",
                "raw_leap_fuel_name": "Gasoline",
                "ninth_sector": "08_transfers",
                "ninth_fuel": "07_01_motor_gasoline",
            },
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        leap_esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth_esto.to_excel(writer, sheet_name="ninth_pairs_to_esto_pairs", index=False)
        leap_ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)


def test_ensure_rollup_sheets_adds_editable_headers(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    ensure_rollup_sheets(workbook)

    xl = pd.ExcelFile(workbook)
    assert "leap_rollup_rules" in xl.sheet_names
    assert "esto_rollup_rules" in xl.sheet_names
    assert "ninth_rollup_rules" in xl.sheet_names
    assert "rollup_label_overrides" in xl.sheet_names


def test_rollup_rules_are_applied_before_cardinality(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)
    ensure_rollup_sheets(workbook)

    esto_rollups = pd.DataFrame(
        [
            {
                "rollup_context": "leap_to_esto",
                "input_esto_flow": "08.01 Recycled products",
                "input_esto_product": "",
                "rolled_esto_flow": "08 Transfers",
                "rolled_esto_product": "",
                "rollup_group_id": "08_transfers",
                "rollup_reason": "compare_at_transfer_parent",
                "include": True,
            },
            {
                "rollup_context": "leap_to_esto",
                "input_esto_flow": "08.02 Interproduct transfers",
                "input_esto_product": "",
                "rolled_esto_flow": "08 Transfers",
                "rolled_esto_product": "",
                "rollup_group_id": "08_transfers",
                "rollup_reason": "compare_at_transfer_parent",
                "include": True,
            },
        ]
    )
    leap_rollups = pd.DataFrame(
        [
            {
                "rollup_context": "leap_to_esto",
                "input_leap_sector_name_full_path": "Transfers/Imports",
                "input_raw_leap_fuel_name": "",
                "rolled_leap_sector_name_full_path": "Transfers",
                "rolled_raw_leap_fuel_name": "",
                "rollup_group_id": "transfers",
                "rollup_reason": "compare_at_transfer_parent",
                "include": True,
            },
            {
                "rollup_context": "leap_to_esto",
                "input_leap_sector_name_full_path": "Transfers/Exports",
                "input_raw_leap_fuel_name": "",
                "rolled_leap_sector_name_full_path": "Transfers",
                "rolled_raw_leap_fuel_name": "",
                "rollup_group_id": "transfers",
                "rollup_reason": "compare_at_transfer_parent",
                "include": True,
            },
        ]
    )
    with pd.ExcelWriter(workbook, mode="a", if_sheet_exists="replace", engine="openpyxl") as writer:
        esto_rollups.to_excel(writer, sheet_name="esto_rollup_rules", index=False)
        leap_rollups.to_excel(writer, sheet_name="leap_rollup_rules", index=False)

    effective_tables, rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    leap_esto = effective_tables["leap_to_esto_balance_conversion"]

    assert set(leap_esto["pair_mapping_cardinality_raw"]) == {"one_to_one"}
    assert set(leap_esto["pair_mapping_cardinality_after_rollup"]) == {"one_to_one"}
    assert set(leap_esto["rolled_target_flow"]) == {"08 Transfers"}
    assert len(rollup_qa["rules_used"]) == 4


def test_many_to_many_after_rollup_is_high_severity(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    extra = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transfers/Imports",
                "raw_leap_fuel_name": "Gasoline",
                "esto_flow": "08.02 Interproduct transfers",
                "esto_product": "07.01 Motor gasoline",
            }
        ]
    )
    leap_esto = pd.concat([pd.read_excel(workbook, sheet_name="leap_combined_esto"), extra], ignore_index=True)
    with pd.ExcelWriter(workbook, mode="a", if_sheet_exists="replace", engine="openpyxl") as writer:
        leap_esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)

    effective_tables, rollup_qa = build_all_effective_mappings(workbook, include_reverse=True)
    relationship_df = build_relationship_rows(effective_tables)
    qa = build_qa_tables(effective_tables, relationship_df, rollup_qa)

    assert not qa["qa_many_to_many_after_rollup"].empty
    assert set(qa["qa_many_to_many_after_rollup"]["qa_severity"]) == {"high"}


def test_reverse_ninth_to_leap_cardinality_is_checked_separately(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=True)
    reverse = effective_tables["ninth_to_leap_initialisation"]

    assert set(reverse["pair_mapping_cardinality_after_rollup"]) == {"one_to_many"}


def test_individual_mapping_consistency_flags_product_many_to_many(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    leap_esto = pd.read_excel(workbook, sheet_name="leap_combined_esto")
    leap_esto = pd.concat(
        [
            leap_esto,
            pd.DataFrame(
                [
                    {
                        "leap_sector_name_full_path": "Transfers/Stock changes",
                        "raw_leap_fuel_name": "Gasoline",
                        "esto_flow": "07 Total exports",
                        "esto_product": "07.02 Aviation gasoline",
                    },
                    {
                        "leap_sector_name_full_path": "Transfers/Stock changes",
                        "raw_leap_fuel_name": "Aviation gasoline",
                        "esto_flow": "07 Total exports",
                        "esto_product": "07.01 Motor gasoline",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    with pd.ExcelWriter(workbook, mode="a", if_sheet_exists="replace", engine="openpyxl") as writer:
        leap_esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    qa = build_individual_mapping_consistency_qa(effective_tables)

    leap_to_esto_qa = qa[qa["check_name"].eq("raw_leap_fuel_name_to_esto_product")]
    assert not leap_to_esto_qa.empty
    assert set(leap_to_esto_qa["exception_status"]) == {"unrecorded_exception"}
    assert set(leap_to_esto_qa["qa_severity"]) == {"warning"}


def test_individual_mapping_consistency_marks_recorded_exception(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    leap_esto = pd.read_excel(workbook, sheet_name="leap_combined_esto")
    leap_esto = pd.concat(
        [
            leap_esto,
            pd.DataFrame(
                [
                    {
                        "leap_sector_name_full_path": "Transfers/Stock changes",
                        "raw_leap_fuel_name": "Gasoline",
                        "esto_flow": "07 Total exports",
                        "esto_product": "07.02 Aviation gasoline",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    exceptions = pd.DataFrame(
        [
            {
                "check_name": "raw_leap_fuel_name_to_esto_product",
                "source_value": "Gasoline",
                "target_value": "07.02 Aviation gasoline",
                "include": True,
                "exception_reason": "temporary test exception",
            }
        ]
    )
    with pd.ExcelWriter(workbook, mode="a", if_sheet_exists="replace", engine="openpyxl") as writer:
        leap_esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    qa = build_individual_mapping_consistency_qa(effective_tables, exceptions)
    row = qa[
        qa["check_name"].eq("raw_leap_fuel_name_to_esto_product")
        & qa["source_value"].eq("Gasoline")
        & qa["target_value"].eq("07.02 Aviation gasoline")
    ].iloc[0]

    assert row["exception_status"] == "recorded_exception"
    assert row["exception_reason"] == "temporary test exception"
    assert row["qa_severity"] == "info"


def test_original_label_presence_flags_missing_source_and_target_labels(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    qa = build_original_label_presence_qa(
        effective_tables,
        {
            "raw_leap_fuel_name": {"gasoline"},
            "ninth_fuel": {"07_01_motor_gasoline"},
            "esto_product": {"08.01 recycled products"},
        },
    )

    assert set(qa["label_name"]) == {"esto_product"}
    assert set(qa["label_value"]) == {"07.01 Motor gasoline"}
    assert set(qa["issue_type"]) == {"target_label_missing_from_original_dataset"}


def test_original_label_presence_marks_recorded_exception(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    exceptions = pd.DataFrame(
        [
            {
                "check_name": "raw_leap_fuel_name_to_esto_product_target_label_presence",
                "source_value": "",
                "target_value": "07.01 Motor gasoline",
                "include": True,
                "exception_reason": "known source label issue",
            }
        ]
    )
    qa = build_original_label_presence_qa(
        effective_tables,
        {
            "raw_leap_fuel_name": {"gasoline"},
            "ninth_fuel": {"07_01_motor_gasoline"},
            "esto_product": {"08.01 recycled products"},
        },
        exceptions,
    )
    row = qa[
        qa["presence_check_name"].eq("raw_leap_fuel_name_to_esto_product_target_label_presence")
        & qa["label_value"].eq("07.01 Motor gasoline")
    ].iloc[0]

    assert row["exception_status"] == "recorded_exception"
    assert row["exception_reason"] == "known source label issue"
    assert row["qa_severity"] == "info"


def test_subtotal_alignment_flags_subtotal_to_non_subtotal(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    qa = build_subtotal_alignment_qa(
        effective_tables,
        {
            "LEAP": {("transfers/imports", "gasoline"): True, ("transfers/exports", "gasoline"): False},
            "ESTO": {
                ("08.01 recycled products", "07.01 motor gasoline"): False,
                ("08.02 interproduct transfers", "07.01 motor gasoline"): False,
            },
            "NINTH": {("08_transfers", "07_01_motor_gasoline"): False},
        },
    )

    leap_to_esto = qa[qa["use_case"].eq("leap_to_esto_balance_conversion")]
    assert len(leap_to_esto) == 1
    assert leap_to_esto.iloc[0]["issue_type"] == "source_subtotal_to_target_non_subtotal"
    assert leap_to_esto.iloc[0]["exception_status"] == "unrecorded_exception"


def test_subtotal_alignment_marks_recorded_exception(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    exceptions = pd.DataFrame(
        [
            {
                "check_name": "leap_to_esto_balance_conversion_subtotal_alignment",
                "source_value": "Transfers/Imports || Gasoline",
                "target_value": "08.01 Recycled products || 07.01 Motor gasoline",
                "include": True,
                "exception_reason": "expected subtotal comparison",
            }
        ]
    )
    qa = build_subtotal_alignment_qa(
        effective_tables,
        {
            "LEAP": {("transfers/imports", "gasoline"): True, ("transfers/exports", "gasoline"): False},
            "ESTO": {
                ("08.01 recycled products", "07.01 motor gasoline"): False,
                ("08.02 interproduct transfers", "07.01 motor gasoline"): False,
            },
            "NINTH": {("08_transfers", "07_01_motor_gasoline"): False},
        },
        exceptions,
    )

    assert qa.loc[0, "exception_status"] == "recorded_exception"
    assert qa.loc[0, "exception_reason"] == "expected subtotal comparison"
    assert qa.loc[0, "qa_severity"] == "info"


def test_mapping_balance_coverage_flags_uncovered_esto_component(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)
    esto_data = pd.DataFrame(
        [
            {
                "economy": "00_APEC",
                "flows": "01 Production",
                "products": "01 Coal",
                "2022": 100.0,
            },
            {
                "economy": "00_APEC",
                "flows": "02 Imports",
                "products": "01 Coal",
                "2022": 20.0,
            },
            {
                "economy": "00_APEC",
                "flows": "07 Total primary energy supply",
                "products": "19 Total",
                "2022": 120.0,
            },
        ]
    )
    ninth_data = pd.DataFrame(
        [
            {
                "economy": "00_APEC",
                "scenarios": "reference",
                "sectors": "07_total_primary_energy_supply",
                "sub1sectors": "x",
                "fuels": "19_total",
                "subfuels": "x",
                "2022": 120.0,
            }
        ]
    )
    esto_path = tmp_path / "esto.csv"
    ninth_path = tmp_path / "ninth.csv"
    esto_data.to_csv(esto_path, index=False)
    ninth_data.to_csv(ninth_path, index=False)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    qa = build_mapping_balance_coverage_qa(
        effective_tables,
        esto_data_path=esto_path,
        ninth_data_path=ninth_path,
        tolerance_pj=1e-9,
    )
    row = qa[
        qa["dataset"].eq("ESTO")
        & qa["mapping_set"].eq("leap_combined_esto")
        & qa["check_name"].eq("total_primary_supply")
    ].iloc[0]

    assert row["status"] == "fail"
    assert row["failed_group_count"] == 1
    assert row["difference_percent"] == -100.0


def test_mapping_rows_using_rollup_created_categories_get_note(tmp_path: Path) -> None:
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    _write_minimal_workbook(workbook)
    ensure_rollup_sheets(workbook)

    leap_esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transformation/Gas processing plants",
                "raw_leap_fuel_name": "Natural gas",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                "Note": "",
            }
        ]
    )
    leap_rollups = pd.DataFrame(
        [
            {
                "rollup_context": "leap_to_esto",
                "input_leap_sector_name_full_path": "Transformation/Gas works plants",
                "input_raw_leap_fuel_name": "",
                "rolled_leap_sector_name_full_path": "Transformation/Gas processing plants",
                "rolled_raw_leap_fuel_name": "",
                "rollup_group_id": "rollup_09_06_gas_processing_plants",
                "rollup_reason": "combined_with_gas_processing_for_leap_scope",
                "include": True,
            }
        ]
    )
    with pd.ExcelWriter(workbook, mode="a", if_sheet_exists="replace", engine="openpyxl") as writer:
        leap_esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        leap_rollups.to_excel(writer, sheet_name="leap_rollup_rules", index=False)

    effective_tables, _rollup_qa = build_all_effective_mappings(workbook, include_reverse=False)
    note = effective_tables["leap_to_esto_balance_conversion"].loc[0, "Note"]

    assert (
        "Transformation/Gas processing plants from leap_sector_name_full_path "
        "is a rollup category from leap_rollup_rules for leap_to_esto."
    ) in note

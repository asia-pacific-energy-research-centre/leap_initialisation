"""Regression checks for transfer producers with legitimately empty source data."""

#%%

from pathlib import Path

import pandas as pd

from codebase.functions import supply_leap_io
from codebase.functions import transformation_record_builder as record_builder


def _minimal_transfer_catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "branch_path": (
                    "Transformation\\Transfers unallocated\\Processes\\Transfers unallocated"
                    "\\Feedstock Fuels\\Natural gas liquids"
                ),
                "fuel_group": "Feedstock Fuels",
            },
            {
                "branch_path": (
                    "Transformation\\Transfers unallocated\\Output Fuels\\Other products"
                ),
                "fuel_group": "Output Fuels",
            },
        ]
    )


def test_empty_process_records_write_catalog_zero_skeleton(tmp_path: Path) -> None:
    """The shared exporter must reach catalogue zero-fill without source records."""
    output_path = record_builder.save_transformation_export(
        process_records=[],
        region="New Zealand",
        base_year=2022,
        final_year=2023,
        code_to_name_mapping={},
        output_dir=str(tmp_path),
        output_filename="transfer_leap_imports_12_NZ_Reference.xlsx",
        model_name="Test model",
        scenarios=["Reference"],
        full_branch_catalog_df=_minimal_transfer_catalog(),
        in_scope_sector_titles={"Transfers unallocated"},
    )

    assert output_path is not None
    exported = pd.read_excel(output_path, sheet_name="LEAP", header=2)
    assert not exported.empty
    canonical_paths = {
        (
            "Transformation\\Transfers unallocated\\Processes\\Transfers unallocated"
            "\\Feedstock Fuels\\Natural gas liquids"
        ),
        "Transformation\\Transfers unallocated\\Output Fuels\\Other products",
        "Transformation\\Transfers unallocated\\Processes\\Transfers unallocated",
    }
    exported_paths = set(exported["Branch Path"])
    assert exported_paths <= canonical_paths
    assert (
        "Transformation\\Transfers unallocated\\Processes\\Transfers unallocated"
        in exported_paths
    )
    assert any("\\Feedstock Fuels\\" in path for path in exported_paths)
    assert set(exported["Scenario"]) == {"Reference"}


def test_transfer_override_writer_keeps_no_data_economy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """No-data economies still receive one producer workbook per scenario."""
    calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        supply_leap_io.transfers_workflow,
        "build_transfer_rows",
        lambda economy, use_output_targets: [],
    )

    def _fake_save(
        process_records,
        region,
        base_year,
        final_year,
        code_to_name_mapping,
        output_dir,
        output_filename,
        model_name,
        scenarios,
        full_branch_catalog_df=None,
        in_scope_sector_titles=None,
    ):
        calls.append((output_filename, scenarios[0], len(process_records)))
        path = Path(output_dir) / output_filename
        path.touch()
        return str(path)

    monkeypatch.setattr(
        supply_leap_io.transformation_workflow.core,
        "save_transformation_export",
        _fake_save,
    )
    monkeypatch.setattr(
        supply_leap_io,
        "_find_legacy_transfer_branch_paths",
        lambda export_path: [],
    )

    paths = supply_leap_io.save_transfer_exports_with_supply_overrides(
        reconciliation_table=pd.DataFrame(),
        economies=["05_PRC"],
        scenarios=["Target", "Reference", "Current Accounts"],
        output_dir=tmp_path,
        full_branch_catalog_df=_minimal_transfer_catalog(),
    )

    assert len(paths) == 3
    assert [scenario for _, scenario, _ in calls] == [
        "Target",
        "Reference",
        "Current Accounts",
    ]
    assert all(record_count == 0 for _, _, record_count in calls)
    assert all("05_PRC" in path.name for path in paths)


#%%

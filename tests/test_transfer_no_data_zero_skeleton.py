"""Regression checks for transfer producers with legitimately empty source data."""

#%%

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions import supply_leap_io
from codebase.functions import transformation_record_builder as record_builder
from codebase import transfers_workflow


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
    preflight_calls: list[dict[str, object]] = []
    projection_scenarios: list[str | None] = []

    def _fake_build_transfer_rows(economy, use_output_targets, scenario=None):
        projection_scenarios.append(scenario)
        return []

    monkeypatch.setattr(
        supply_leap_io.transfers_workflow,
        "build_transfer_rows",
        _fake_build_transfer_rows,
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
    monkeypatch.setattr(
        supply_leap_io.fuel_catalog_preflight,
        "run_fuel_catalog_preflight",
        lambda **kwargs: preflight_calls.append(kwargs) or {"skipped": False},
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
    assert projection_scenarios == ["target", "reference", "reference"]
    assert [call["scenario"] for call in preflight_calls] == [
        "Target",
        "Reference",
        "Current Accounts",
    ]
    assert all(call["context"] == "transfers_workflow.export_generation" for call in preflight_calls)


def test_transfer_override_writer_rejects_legacy_generic_transfer_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Legacy generic Transfers branches must stop before catalog preflight/import."""
    def _fake_build_transfer_rows(economy, use_output_targets, scenario=None):
        return []

    def _fake_save(*args, **kwargs):
        path = Path(args[5]) / args[6]
        path.touch()
        return str(path)

    monkeypatch.setattr(
        supply_leap_io.transfers_workflow,
        "build_transfer_rows",
        _fake_build_transfer_rows,
    )
    monkeypatch.setattr(
        supply_leap_io.transformation_workflow.core,
        "save_transformation_export",
        _fake_save,
    )
    monkeypatch.setattr(
        supply_leap_io,
        "_find_legacy_transfer_branch_paths",
        lambda export_path: ["Transformation\\Transfers\\Legacy process"],
    )
    preflight_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        supply_leap_io.fuel_catalog_preflight,
        "run_fuel_catalog_preflight",
        lambda **kwargs: preflight_calls.append(kwargs) or {"skipped": False},
    )

    with pytest.raises(ValueError, match="legacy generic transfer branches"):
        supply_leap_io.save_transfer_exports_with_supply_overrides(
            reconciliation_table=pd.DataFrame(),
            economies=["05_PRC"],
            scenarios=["Reference"],
            output_dir=tmp_path,
            full_branch_catalog_df=_minimal_transfer_catalog(),
        )

    assert preflight_calls == []


def test_transfer_projection_routes_generic_crosswalk_flow_to_active_subflow() -> None:
    """Canonical 08 Transfers projections must feed the historical transfer flow."""
    projection = pd.DataFrame(
        {
            "economy_key": ["20USA"],
            "esto_flow": ["08 Transfers"],
            "esto_product": ["07.11 Ethane"],
            2023: [25.0],
        }
    )
    history = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA"],
            "flows": ["08.01 Recycled products", "08.99 Transfers nonspecified"],
            "products": ["07.11 Ethane", "07.11 Ethane"],
            2022: [0.0, 10.0],
        }
    )

    routed = transfers_workflow._route_transfer_projection_to_historical_flow(
        projection,
        history,
        base_year=2022,
    )

    assert routed.loc[0, "esto_flow"] == "08.99 Transfers nonspecified"
    assert routed.loc[0, 2023] == 25.0


#%%

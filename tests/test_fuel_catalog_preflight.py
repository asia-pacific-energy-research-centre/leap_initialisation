import os
from pathlib import Path

import pandas as pd

from codebase.utilities import fuel_catalog_preflight as preflight


def _rows_for_source(source_path: Path):
    fuel_name = "Natural gas" if source_path.stem.endswith(" nz") else "Natural Gas"
    return [
        {
            "catalog_type": "transformation",
            "source_workbook": source_path.name,
            "scenario": "Reference",
            "module_or_root": "Electricity Generation",
            "fuel_group": "Feedstock Fuels",
            "fuel_name": fuel_name,
            "branch_path": f"Transformation\\Electricity Generation\\Feedstock Fuels\\{fuel_name}",
            "variable": "Feedstock Fuel Share",
            "catalog_source": "template",
            "probe_status": "",
        }
    ]


def test_incremental_catalog_reuses_unchanged_sources_and_preserves_exact_labels(
    tmp_path, monkeypatch
):
    source_directory = tmp_path / "templates"
    source_directory.mkdir()
    usa = source_directory / "leap_export_template usa.xlsx"
    nz = source_directory / "leap_export_template nz.xlsx"
    usa.write_bytes(b"usa")
    nz.write_bytes(b"nz")
    calls = []

    def fake_rows(*, source_path, sheet_name):
        calls.append(source_path.name)
        return _rows_for_source(source_path)

    monkeypatch.setattr(preflight, "_catalog_rows_from_full_model_export", fake_rows)
    kwargs = {
        "template_directory": source_directory,
        "full_model_export_path": tmp_path / "does-not-exist.xlsx",
        "cache_directory": tmp_path / "cache",
        "manifest_path": tmp_path / "manifest.json",
        "catalog_path": tmp_path / "catalog.csv",
        "registry_path": tmp_path / "fuel_registry.csv",
    }

    first, registry = preflight.build_incremental_template_catalog(**kwargs)
    second, _ = preflight.build_incremental_template_catalog(**kwargs)

    assert calls == sorted([usa.name, nz.name])
    assert set(first["fuel_name"]) == {"Natural gas", "Natural Gas"}
    assert set(second["fuel_name"]) == {"Natural gas", "Natural Gas"}
    assert set(registry["fuel_name"]) == {"Natural gas", "Natural Gas"}
    assert registry["label_variant_count"].eq(2).all()

    os.utime(nz, ns=(nz.stat().st_atime_ns, nz.stat().st_mtime_ns + 1_000_000))
    preflight.build_incremental_template_catalog(**kwargs)
    assert calls == sorted([usa.name, nz.name]) + [nz.name]


def test_catalog_records_all_source_templates_for_deduplicated_rows(tmp_path, monkeypatch):
    source_directory = tmp_path / "templates"
    source_directory.mkdir()
    usa = source_directory / "leap_export_template usa.xlsx"
    nz = source_directory / "leap_export_template nz.xlsx"
    usa.write_bytes(b"usa")
    nz.write_bytes(b"nz")

    def fake_rows(*, source_path, sheet_name):
        return [
            {
                "catalog_type": "transformation",
                "source_workbook": source_path.name,
                "scenario": "Reference",
                "module_or_root": "Electricity Generation",
                "fuel_group": "Feedstock Fuels",
                "fuel_name": "Natural gas",
                "branch_path": "Transformation\\Electricity Generation\\Feedstock Fuels\\Natural gas",
                "variable": "Feedstock Fuel Share",
                "catalog_source": "template",
                "probe_status": "",
            }
        ]

    monkeypatch.setattr(preflight, "_catalog_rows_from_full_model_export", fake_rows)
    catalog, _ = preflight.build_incremental_template_catalog(
        template_directory=source_directory,
        full_model_export_path=tmp_path / "does-not-exist.xlsx",
        cache_directory=tmp_path / "cache",
        manifest_path=tmp_path / "manifest.json",
        catalog_path=tmp_path / "catalog.csv",
        registry_path=tmp_path / "fuel_registry.csv",
    )

    assert len(catalog) == 1
    assert catalog.iloc[0]["source_templates"] == "; ".join(sorted([usa.name, nz.name]))


def test_preflight_expected_identity_is_branch_path_and_variable():
    catalog = pd.DataFrame(
        [
            {
                "catalog_type": "transformation",
                "scenario": "Reference",
                "module_or_root": "Electricity Generation",
                "fuel_group": "Feedstock Fuels",
                "fuel_name": "Natural gas",
                "branch_path": "Transformation\\Electricity Generation\\Feedstock Fuels\\Natural gas",
                "variable": "Feedstock Fuel Share",
            }
        ]
    )
    for column in ("catalog_type", "scenario", "module_or_root", "fuel_group", "fuel_name"):
        catalog[f"{column}_norm"] = catalog[column].str.lower()

    result = preflight._expected_branch_rows_for_scope(
        catalog,
        catalog_type="transformation",
        module_or_root="electricity generation",
        scenario="Reference",
    )

    assert result == {
        (
            "Transformation\\Electricity Generation\\Feedstock Fuels\\Natural gas",
            "Feedstock Fuel Share",
        )
    }


def _write_export_fixture(path: Path, rows: list[dict[str, str]]) -> None:
    header = pd.DataFrame([{"Branch Path": "Area:"}, {}])
    data = pd.DataFrame(rows)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        header.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        data.to_excel(writer, sheet_name="LEAP", index=False, startrow=2)


def _catalog_row(branch_path: str, fuel_name: str) -> dict[str, str]:
    return {
        "catalog_type": "demand",
        "scenario": "Target",
        "module_or_root": "All demand aggregated",
        "fuel_group": "",
        "fuel_name": fuel_name,
        "branch_path": branch_path,
        "variable": "Activity Level",
    }


def test_shared_union_does_not_require_every_economy_branch(tmp_path):
    export_path = tmp_path / "nz.xlsx"
    expected_path = "Demand\\All demand aggregated\\Natural gas"
    union_only_path = "Demand\\All demand aggregated\\Coal"
    _write_export_fixture(
        export_path,
        [
            {
                "Branch Path": expected_path,
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "New Zealand",
            }
        ],
    )
    catalog_path = tmp_path / "catalog.csv"
    pd.DataFrame(
        [_catalog_row(expected_path, "Natural gas"), _catalog_row(union_only_path, "Coal")]
    ).to_csv(catalog_path, index=False)

    result = preflight.run_fuel_catalog_preflight(
        export_path=export_path,
        sheet_name="LEAP",
        scenario="Target",
        catalog_path=catalog_path,
        auto_refresh_stale_catalog=False,
    )

    assert result["missing_total"] == 0
    assert result["extra_total"] == 1
    assert result["report"].iloc[0]["status"] == "ok"


def test_preflight_reports_generated_rows_absent_from_shared_union(tmp_path):
    export_path = tmp_path / "nz.xlsx"
    generated_path = "Demand\\All demand aggregated\\Uncatalogued fuel"
    _write_export_fixture(
        export_path,
        [
            {
                "Branch Path": generated_path,
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "New Zealand",
            }
        ],
    )
    catalog_path = tmp_path / "catalog.csv"
    pd.DataFrame([_catalog_row("Demand\\All demand aggregated\\Natural gas", "Natural gas")]).to_csv(
        catalog_path, index=False
    )

    result = preflight.run_fuel_catalog_preflight(
        export_path=export_path,
        sheet_name="LEAP",
        scenario="Target",
        catalog_path=catalog_path,
        auto_refresh_stale_catalog=False,
    )

    assert result["missing_total"] == 1
    assert result["report"].iloc[0]["status"] == "missing_from_catalog"

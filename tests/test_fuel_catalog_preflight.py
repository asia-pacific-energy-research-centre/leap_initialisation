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

from __future__ import annotations

import pandas as pd

from codebase.functions import supply_assets
from codebase.functions import supply_data_pipeline


def test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup(monkeypatch) -> None:
    esto_raw = pd.DataFrame(
        {
            "economy": ["20_USA"],
            "flows": ["02 Imports"],
            "products": ["01 Coal"],
            2022: [1.0],
        }
    )
    ninth_raw = pd.DataFrame(
        {
            "scenarios": ["reference"],
            "economy": ["20_USA"],
            "fuels": ["01_coal"],
            "subfuels": ["x"],
            "subtotal_results": [False],
            2022: [2.0],
        }
    )
    calls = {"aggregate_labels": [], "mapped": False}

    monkeypatch.setattr(
        supply_assets,
        "build_supply_sector_config",
        lambda code_paths, exclude_prefixes: {
            "01 Coal": {"fuel_label_esto": "01 Coal", "fuel_name": "01 Coal"}
        },
    )
    monkeypatch.setattr(
        supply_assets,
        "load_code_to_name_mapping",
        lambda code_paths: {"01 Coal": "Coal"},
    )

    def fake_apply_code_to_name_mapping(sector_config, code_to_name_mapping):
        calls["mapped"] = True
        updated = {key: value.copy() for key, value in sector_config.items()}
        updated["01 Coal"]["fuel_name"] = code_to_name_mapping["01 Coal"]
        return updated

    monkeypatch.setattr(
        supply_assets,
        "apply_code_to_name_mapping",
        fake_apply_code_to_name_mapping,
    )
    monkeypatch.setattr(
        supply_assets.workflow_common,
        "archive_config_dir_once_per_day",
        lambda: None,
    )
    monkeypatch.setattr(
        supply_assets,
        "load_augmented_reference_tables",
        lambda **kwargs: (esto_raw.copy(), ninth_raw.copy()),
    )
    monkeypatch.setattr(
        supply_assets,
        "normalize_year_columns",
        lambda df: (df.copy(), [2022]),
    )
    monkeypatch.setattr(
        supply_assets,
        "filter_reference_scenario",
        lambda df, label: df.copy(),
    )
    monkeypatch.setattr(
        supply_assets,
        "apply_matt_subtotal_mapping",
        lambda df, path: df.copy(),
    )
    monkeypatch.setattr(
        supply_assets,
        "filter_matt_subtotals",
        lambda df: df.copy(),
    )
    monkeypatch.setattr(
        supply_assets.workflow_common,
        "normalize_economies",
        lambda economies: list(economies),
    )
    monkeypatch.setattr(
        supply_assets.workflow_common,
        "resolve_aggregate_economy",
        lambda economy_list, aggregate_label: (True, aggregate_label, economy_list),
    )

    def fake_add_all_economy_total(df, year_cols, aggregate_label):
        calls["aggregate_labels"].append(aggregate_label)
        total = df.iloc[[0]].copy()
        total["economy"] = aggregate_label
        return pd.concat([df, total], ignore_index=True)

    monkeypatch.setattr(supply_assets, "add_all_economy_total", fake_add_all_economy_total)

    def fake_build_esto_projection_table(
        ninth_data,
        esto_data,
        mapping_path,
        base_year,
        projection_years,
        sign_stable_flows,
        strict_conservation,
    ):
        assert "00_APEC" in set(ninth_data["economy"])
        assert "00_APEC" in set(esto_data["economy"])
        assert sign_stable_flows == "all"
        assert strict_conservation is True
        return pd.DataFrame({"value": [1.0]}), pd.DataFrame()

    monkeypatch.setattr(
        supply_assets,
        "build_esto_projection_table",
        fake_build_esto_projection_table,
    )
    monkeypatch.setattr(
        supply_assets,
        "build_projection_lookup",
        lambda projection_df: {"rows": len(projection_df)},
    )
    monkeypatch.setattr(
        supply_assets,
        "build_dataset_map",
        lambda esto_data, esto_year_cols, ninth_data, ninth_year_cols, raw_data, raw_year_cols: {
            "esto_rows": len(esto_data),
            "ninth_rows": len(ninth_data),
        },
    )

    assets, projection_lookup = supply_assets.prepare_supply_assets(
        economies=["20_USA", "00_APEC"],
        aggregate_economy_label="00_APEC",
        return_projection_lookup=True,
    )

    dataset_map, sector_config, code_to_name_mapping, ninth_data, esto_data = assets

    assert len(assets) == 5
    assert calls["mapped"] is True
    assert calls["aggregate_labels"] == ["00_APEC", "00_APEC"]
    assert sector_config["01 Coal"]["fuel_name"] == "Coal"
    assert code_to_name_mapping == {"01 Coal": "Coal"}
    assert dataset_map == {"esto_rows": 2, "ninth_rows": 2}
    assert projection_lookup == {"rows": 1}
    assert supply_assets.SUPPLY_PROJECTION_LOOKUP == projection_lookup
    assert set(ninth_data["economy"]) == {"20_USA", "00_APEC"}
    assert set(esto_data["economy"]) == {"20_USA", "00_APEC"}


def test_supply_data_pipeline_wrapper_preserves_five_tuple_and_updates_lookup(
    monkeypatch,
) -> None:
    expected_assets = ("dataset_map", "sector_config", "code_map", "ninth", "esto")
    expected_lookup = {"lookup": "value"}

    def fake_prepare_supply_assets(
        economies,
        aggregate_economy_label,
        save_subtotal_labeled,
        subtotal_output_path,
        return_projection_lookup,
    ):
        assert economies == ["20_USA"]
        assert return_projection_lookup is True
        return expected_assets, expected_lookup

    monkeypatch.setattr(
        supply_data_pipeline.supply_assets_module,
        "prepare_supply_assets",
        fake_prepare_supply_assets,
    )

    assets = supply_data_pipeline.prepare_supply_assets(economies=["20_USA"])

    assert assets == expected_assets
    assert supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP == expected_lookup

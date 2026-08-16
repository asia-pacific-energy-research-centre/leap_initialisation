"""Regression tests for typed augmented-reference table caches."""

from __future__ import annotations

import json

import pandas as pd
from pandas.testing import assert_frame_equal

from codebase.utilities.esto_reference_loader import load_augmented_reference_tables


def _write_sources(tmp_path):
    esto_path = tmp_path / "esto.csv"
    ninth_path = tmp_path / "ninth.csv"
    pd.DataFrame(
        [
            {"economy": "01AUS", "flows": "01 Production", "products": "01 Coal", "is_subtotal": False, "2022": 1.5},
            {"economy": "02BD", "flows": "01 Production", "products": "01 Coal", "is_subtotal": True, "2022": 2.5},
        ]
    ).to_csv(esto_path, index=False)
    pd.DataFrame(
        [
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "01_production", "fuels": "01_coal", "subtotal_results": False, "2022": 1.5, "2023": 1.6},
            {"economy": "02_BD", "scenarios": "reference", "sectors": "01_production", "fuels": "01_coal", "subtotal_results": True, "2022": 2.5, "2023": 2.6},
        ]
    ).to_csv(ninth_path, index=False)
    return esto_path, ninth_path


def test_augmented_reference_cache_uses_versioned_parquet_and_roundtrips_exactly(tmp_path):
    esto_path, ninth_path = _write_sources(tmp_path)
    cache_dir = tmp_path / "cache"

    first_esto, first_ninth = load_augmented_reference_tables(
        esto_path=esto_path,
        ninth_path=ninth_path,
        synthetic_rules_path=None,
        cache_dir=cache_dir,
    )
    second_esto, second_ninth = load_augmented_reference_tables(
        esto_path=esto_path,
        ninth_path=ninth_path,
        synthetic_rules_path=None,
        cache_dir=cache_dir,
    )

    parquet_paths = sorted(cache_dir.glob("*.parquet"))
    metadata_paths = sorted(cache_dir.glob("*_meta.json"))
    assert len(parquet_paths) == 2
    assert len(metadata_paths) == 1
    assert not list(cache_dir.glob("*.csv"))
    metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    assert metadata["cache_storage"] == {
        "format": "parquet",
        "compression": "zstd",
        "schema_version": 1,
    }
    assert_frame_equal(first_esto, second_esto, check_dtype=True, check_exact=True)
    assert_frame_equal(first_ninth, second_ninth, check_dtype=True, check_exact=True)


def test_augmented_reference_cache_key_changes_when_source_changes(tmp_path):
    esto_path, ninth_path = _write_sources(tmp_path)
    cache_dir = tmp_path / "cache"
    load_augmented_reference_tables(
        esto_path=esto_path,
        ninth_path=ninth_path,
        synthetic_rules_path=None,
        cache_dir=cache_dir,
    )

    ninth = pd.read_csv(ninth_path)
    ninth.loc[0, "2023"] = 99.0
    ninth.to_csv(ninth_path, index=False)
    reloaded_esto, reloaded_ninth = load_augmented_reference_tables(
        esto_path=esto_path,
        ninth_path=ninth_path,
        synthetic_rules_path=None,
        cache_dir=cache_dir,
    )

    assert reloaded_ninth.loc[0, "2023"] == 99.0
    assert len(list(cache_dir.glob("*.parquet"))) == 4
    assert len(list(cache_dir.glob("*_meta.json"))) == 2

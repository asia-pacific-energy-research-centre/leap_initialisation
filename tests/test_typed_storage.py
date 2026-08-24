"""Exact round-trip and corruption tests for typed Parquet cache bundles."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from codebase.utilities.typed_storage import (
    ensure_output_parent,
    read_manifested_parquet_file,
    read_typed_cache_bundle,
    write_json_atomic,
    write_manifested_parquet,
    write_typed_cache_bundle_atomic,
)


def test_ensure_output_parent_creates_a_missing_nested_directory(tmp_path):
    output_path = tmp_path / "workbooks" / "supporting_files" / "baseline_seed_validation" / "result.csv"

    assert ensure_output_parent(output_path) == output_path
    assert output_path.parent.is_dir()


def test_typed_cache_bundle_preserves_nested_values_columns_and_dtypes(tmp_path):
    source = {
        "table": pd.DataFrame(
            {
                "label": pd.Series(["a", None], dtype="object"),
                2022: pd.Series([1.5, np.nan], dtype="float64"),
                "is_subtotal": pd.Series([True, False], dtype="object"),
            }
        ),
        "records": [{"value": np.float64(2.5), "years": {2022: 1.0, 2023: np.nan}}],
        "assets": (pd.DataFrame(columns=pd.RangeIndex(0)), {"fuel": "Coal"}),
        "missing": pd.NA,
    }
    bundle_path = tmp_path / "cache.parquet_cache"

    write_typed_cache_bundle_atomic(source, bundle_path)
    restored = read_typed_cache_bundle(bundle_path)

    assert_frame_equal(source["table"], restored["table"], check_dtype=True, check_exact=True)
    assert_frame_equal(source["assets"][0], restored["assets"][0], check_dtype=True, check_exact=True)
    assert type(restored["records"][0]["value"]) is np.float64
    assert np.isnan(restored["records"][0]["years"][2023])
    assert restored["assets"][1] == source["assets"][1]
    assert restored["missing"] is pd.NA
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["storage_format"] == "leap_typed_cache_bundle"
    assert manifest["compression"] == "zstd"


def test_typed_cache_bundle_rejects_corrupted_parquet(tmp_path):
    bundle_path = tmp_path / "cache.parquet_cache"
    write_typed_cache_bundle_atomic({"table": pd.DataFrame({"value": [1, 2]})}, bundle_path)
    table_path = next(bundle_path.glob("*.parquet"))
    table_path.write_bytes(table_path.read_bytes() + b"corruption")

    with pytest.raises(ValueError, match="hash mismatch"):
        read_typed_cache_bundle(bundle_path)


def test_manifested_parquet_round_trip_preserves_table_contract(tmp_path):
    frame = pd.DataFrame(
        {
            "label": pd.Series(["a", pd.NA], dtype="string"),
            "year": pd.Series([2022, 2023], dtype="int64"),
            "value": pd.Series([1.25, float("nan")], dtype="float64"),
        }
    )
    path = tmp_path / "detail.parquet"

    manifest = write_manifested_parquet(frame, path, artifact_type="test_detail")
    restored = read_manifested_parquet_file(path)

    assert manifest["artifact_type"] == "test_detail"
    pd.testing.assert_frame_equal(restored, frame)


def test_atomic_storage_uses_short_temporary_paths_for_deep_artifacts(tmp_path):
    deep_path = tmp_path.joinpath(*(["nested_directory"] * 12))
    parquet_path = deep_path / "supply_reconciliation_balance_demand_conservation.parquet"
    frame = pd.DataFrame({"value": [1.0, 2.0]})

    write_manifested_parquet(frame, parquet_path, artifact_type="deep_path_test")
    write_json_atomic({"status": "ok"}, deep_path / "long_diagnostic_manifest.json")

    pd.testing.assert_frame_equal(read_manifested_parquet_file(parquet_path), frame)
    assert json.loads((deep_path / "long_diagnostic_manifest.json").read_text()) == {"status": "ok"}
    assert not list(deep_path.glob("*.tmp"))


def test_atomic_parquet_failure_cleans_up_its_temporary_file(tmp_path, monkeypatch):
    output_path = tmp_path / "nested" / "detail.parquet"
    frame = pd.DataFrame({"value": [1.0]})

    def fail_to_parquet(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_to_parquet)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        write_manifested_parquet(frame, output_path, artifact_type="test_failure")

    assert output_path.parent.is_dir()
    assert not list(output_path.parent.glob("*.tmp"))

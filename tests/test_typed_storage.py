"""Exact round-trip and corruption tests for typed Parquet cache bundles."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from codebase.utilities.typed_storage import (
    read_typed_cache_bundle,
    write_typed_cache_bundle_atomic,
)


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

#%%
"""Benchmark real cache families against Parquet/Zstandard prototypes."""

from __future__ import annotations

import gc
import json
import pickle
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from pandas.testing import assert_frame_equal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.utilities.typed_storage import (
    read_typed_cache_bundle,
    write_typed_cache_bundle_atomic,
)


# --- Measurement helpers ---

def measure_operation(function, *function_args, **function_kwargs):
    """Return result, elapsed seconds, and sampled peak RSS increase bytes."""
    process = psutil.Process()
    baseline_rss = process.memory_info().rss
    peak_rss = baseline_rss
    stop_event = threading.Event()

    def sample_memory() -> None:
        nonlocal peak_rss
        while not stop_event.wait(0.01):
            peak_rss = max(peak_rss, process.memory_info().rss)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        result = function(*function_args, **function_kwargs)
    finally:
        elapsed_seconds = time.perf_counter() - started
        stop_event.set()
        sampler.join(timeout=1.0)
        peak_rss = max(peak_rss, process.memory_info().rss)
    return result, elapsed_seconds, max(0, peak_rss - baseline_rss)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


# --- Typed bundle prototype ---

def encode_dataframe_columns(columns, bundle_dir: Path, table_counter: list[int]) -> dict:
    if isinstance(columns, pd.RangeIndex):
        return {
            "kind": "range_index",
            "start": columns.start,
            "stop": columns.stop,
            "step": columns.step,
            "name": encode_bundle_value(columns.name, bundle_dir, table_counter),
        }
    if isinstance(columns, pd.MultiIndex):
        return {
            "kind": "multi_index",
            "values": encode_bundle_value(list(columns), bundle_dir, table_counter),
            "names": encode_bundle_value(list(columns.names), bundle_dir, table_counter),
        }
    return {
        "kind": "index",
        "values": encode_bundle_value(list(columns), bundle_dir, table_counter),
        "name": encode_bundle_value(columns.name, bundle_dir, table_counter),
    }


def decode_dataframe_columns(node: dict, bundle_dir: Path):
    if node["kind"] == "range_index":
        return pd.RangeIndex(
            start=node["start"],
            stop=node["stop"],
            step=node["step"],
            name=decode_bundle_value(node["name"], bundle_dir),
        )
    if node["kind"] == "multi_index":
        values = decode_bundle_value(node["values"], bundle_dir)
        names = decode_bundle_value(node["names"], bundle_dir)
        return pd.MultiIndex.from_tuples(values, names=names)
    return pd.Index(
        decode_bundle_value(node["values"], bundle_dir),
        name=decode_bundle_value(node["name"], bundle_dir),
    )


def encode_bundle_value(value, bundle_dir: Path, table_counter: list[int]):
    """Encode nested cache values; DataFrames become Parquet and structure becomes JSON."""
    if isinstance(value, pd.DataFrame):
        table_number = table_counter[0]
        table_counter[0] += 1
        table_name = f"table_{table_number:04d}.parquet"
        value.to_parquet(bundle_dir / table_name, index=True, compression="zstd")
        return {
            "type": "dataframe",
            "path": table_name,
            "columns": encode_dataframe_columns(value.columns, bundle_dir, table_counter),
            "dtypes": [str(dtype) for dtype in value.dtypes],
        }
    if isinstance(value, dict):
        return {
            "type": "dict",
            "items": [
                [encode_bundle_value(key, bundle_dir, table_counter), encode_bundle_value(item, bundle_dir, table_counter)]
                for key, item in value.items()
            ],
        }
    if isinstance(value, list):
        return {"type": "list", "items": [encode_bundle_value(item, bundle_dir, table_counter) for item in value]}
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [encode_bundle_value(item, bundle_dir, table_counter) for item in value]}
    if isinstance(value, set):
        return {"type": "set", "items": [encode_bundle_value(item, bundle_dir, table_counter) for item in value]}
    if value is pd.NA:
        return {"type": "pd_na"}
    if isinstance(value, pd.Timestamp):
        return {"type": "timestamp", "value": value.isoformat()}
    if isinstance(value, np.generic):
        return {"type": "numpy_scalar", "dtype": str(value.dtype), "value": value.item()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return {"type": "scalar", "value": value}
    raise TypeError(f"Unsupported cache value: {type(value).__name__}")


def decode_bundle_value(node: dict, bundle_dir: Path):
    value_type = node["type"]
    if value_type == "dataframe":
        frame = pd.read_parquet(bundle_dir / node["path"])
        frame.columns = decode_dataframe_columns(node["columns"], bundle_dir)
        for column_position, dtype_name in enumerate(node["dtypes"]):
            if str(frame.dtypes.iloc[column_position]) != dtype_name:
                frame.isetitem(column_position, frame.iloc[:, column_position].astype(dtype_name))
        return frame
    if value_type == "dict":
        return {decode_bundle_value(key, bundle_dir): decode_bundle_value(value, bundle_dir) for key, value in node["items"]}
    if value_type == "list":
        return [decode_bundle_value(item, bundle_dir) for item in node["items"]]
    if value_type == "tuple":
        return tuple(decode_bundle_value(item, bundle_dir) for item in node["items"])
    if value_type == "set":
        return {decode_bundle_value(item, bundle_dir) for item in node["items"]}
    if value_type == "pd_na":
        return pd.NA
    if value_type == "timestamp":
        return pd.Timestamp(node["value"])
    if value_type == "numpy_scalar":
        return np.dtype(node["dtype"]).type(node["value"])
    if value_type == "scalar":
        return node["value"]
    raise ValueError(f"Unknown cache node type: {value_type}")


def write_typed_bundle(value, bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=False)
    structure = encode_bundle_value(value, bundle_dir=bundle_dir, table_counter=[0])
    manifest = {
        "storage_format": "leap_typed_cache_bundle",
        "format_version": 1,
        "table_format": "parquet",
        "compression": "zstd",
        "structure": structure,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def read_typed_bundle(bundle_dir: Path):
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("storage_format") != "leap_typed_cache_bundle" or manifest.get("format_version") != 1:
        raise ValueError(f"Unsupported typed bundle manifest: {bundle_dir}")
    return decode_bundle_value(manifest["structure"], bundle_dir=bundle_dir)


def assert_nested_equivalent(left, right, path: str = "root") -> None:
    if isinstance(left, pd.DataFrame):
        assert isinstance(right, pd.DataFrame), path
        assert_frame_equal(left, right, check_dtype=True, check_like=False, check_exact=True)
        return
    assert type(left) is type(right), f"{path}: {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        assert list(left.keys()) == list(right.keys()), f"{path}: dict keys/order differ"
        for key in left:
            assert_nested_equivalent(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, (list, tuple)):
        assert len(left) == len(right), f"{path}: sequence lengths differ"
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            assert_nested_equivalent(left_item, right_item, f"{path}[{index}]")
    elif isinstance(left, set):
        assert left == right, path
    elif left is pd.NA:
        assert right is pd.NA, path
    elif isinstance(left, float) and np.isnan(left):
        assert isinstance(right, float) and np.isnan(right), path
    else:
        assert left == right, path


def benchmark_pickle_bundle(pickle_path: Path, scratch_root: Path) -> dict:
    """Compare an existing pickle bundle with the typed Parquet/JSON prototype."""
    with pickle_path.open("rb") as handle:
        value, pickle_read_seconds, pickle_read_peak_rss = measure_operation(pickle.load, handle)

    bundle_dir = scratch_root / f"{pickle_path.stem}.typed_cache"
    _, parquet_write_seconds, parquet_write_peak_rss = measure_operation(write_typed_cache_bundle_atomic, value, bundle_dir)
    del value
    gc.collect()
    restored, parquet_read_seconds, parquet_read_peak_rss = measure_operation(read_typed_cache_bundle, bundle_dir)
    with pickle_path.open("rb") as handle:
        value = pickle.load(handle)
    assert_nested_equivalent(value, restored)

    result = {
        "candidate": str(pickle_path),
        "family": pickle_path.parent.name,
        "current_format": "pickle",
        "candidate_format": "parquet_zstd_plus_json_manifest",
        "current_bytes": pickle_path.stat().st_size,
        "candidate_bytes": directory_size(bundle_dir),
        "current_read_seconds": pickle_read_seconds,
        "candidate_write_seconds": parquet_write_seconds,
        "candidate_read_seconds": parquet_read_seconds,
        "current_read_peak_rss_increase_bytes": pickle_read_peak_rss,
        "candidate_write_peak_rss_increase_bytes": parquet_write_peak_rss,
        "candidate_read_peak_rss_increase_bytes": parquet_read_peak_rss,
        "equivalence": "pass_exact_nested_and_dataframe",
    }
    del restored
    del value
    shutil.rmtree(bundle_dir)
    return result


# --- CSV/Parquet benchmark ---

def read_csv_selected(path: Path, selected_columns: list[str]) -> pd.DataFrame:
    return pd.read_csv(path, usecols=selected_columns, low_memory=False)


def read_csv_filtered(path: Path, economy: str) -> pd.DataFrame:
    parts = []
    for chunk in pd.read_csv(path, chunksize=100_000, low_memory=False):
        selected = chunk[chunk["economy"].astype(str).eq(economy)]
        if not selected.empty:
            parts.append(selected)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def benchmark_csv_table(csv_path: Path, scratch_root: Path) -> dict:
    full_csv, csv_read_seconds, csv_read_peak_rss = measure_operation(pd.read_csv, csv_path, low_memory=False)
    selected_columns = list(full_csv.columns[: min(12, len(full_csv.columns))])
    if "economy" in full_csv.columns and "economy" not in selected_columns:
        selected_columns = ["economy", *selected_columns[:-1]]
    selected_csv, csv_selected_seconds, csv_selected_peak_rss = measure_operation(read_csv_selected, csv_path, selected_columns)
    economy_value = str(full_csv["economy"].dropna().iloc[0]) if "economy" in full_csv.columns and full_csv["economy"].notna().any() else None
    if economy_value is not None:
        filtered_csv, csv_filtered_seconds, csv_filtered_peak_rss = measure_operation(read_csv_filtered, csv_path, economy_value)
    else:
        filtered_csv, csv_filtered_seconds, csv_filtered_peak_rss = pd.DataFrame(), None, None

    parquet_path = scratch_root / f"{csv_path.stem}.parquet"
    _, parquet_write_seconds, parquet_write_peak_rss = measure_operation(full_csv.to_parquet, parquet_path, index=False, compression="zstd")
    full_parquet, parquet_read_seconds, parquet_read_peak_rss = measure_operation(pd.read_parquet, parquet_path)
    selected_parquet, parquet_selected_seconds, parquet_selected_peak_rss = measure_operation(pd.read_parquet, parquet_path, columns=selected_columns)
    if economy_value is not None:
        filtered_parquet, parquet_filtered_seconds, parquet_filtered_peak_rss = measure_operation(pd.read_parquet, parquet_path, filters=[("economy", "==", economy_value)])
    else:
        filtered_parquet, parquet_filtered_seconds, parquet_filtered_peak_rss = pd.DataFrame(), None, None

    assert_frame_equal(full_csv, full_parquet, check_dtype=True, check_exact=True)
    assert_frame_equal(selected_csv, selected_parquet, check_dtype=True, check_exact=True)
    if economy_value is not None:
        assert_frame_equal(filtered_csv.reset_index(drop=True), filtered_parquet.reset_index(drop=True), check_dtype=True, check_exact=True)

    result = {
        "candidate": str(csv_path),
        "family": csv_path.parent.name,
        "current_format": "csv",
        "candidate_format": "parquet_zstd",
        "current_bytes": csv_path.stat().st_size,
        "candidate_bytes": parquet_path.stat().st_size,
        "current_read_seconds": csv_read_seconds,
        "candidate_write_seconds": parquet_write_seconds,
        "candidate_read_seconds": parquet_read_seconds,
        "current_selected_read_seconds": csv_selected_seconds,
        "candidate_selected_read_seconds": parquet_selected_seconds,
        "current_filtered_read_seconds": csv_filtered_seconds,
        "candidate_filtered_read_seconds": parquet_filtered_seconds,
        "current_read_peak_rss_increase_bytes": csv_read_peak_rss,
        "candidate_write_peak_rss_increase_bytes": parquet_write_peak_rss,
        "candidate_read_peak_rss_increase_bytes": parquet_read_peak_rss,
        "current_selected_peak_rss_increase_bytes": csv_selected_peak_rss,
        "candidate_selected_peak_rss_increase_bytes": parquet_selected_peak_rss,
        "current_filtered_peak_rss_increase_bytes": csv_filtered_peak_rss,
        "candidate_filtered_peak_rss_increase_bytes": parquet_filtered_peak_rss,
        "equivalence": "pass_exact_dataframe",
    }
    parquet_path.unlink()
    return result


def run_benchmarks(pickle_paths: list[Path], csv_paths: list[Path], output_path: Path, scratch_parent: Path) -> pd.DataFrame:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_parent.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="parquet_migration_", dir=scratch_parent) as temporary_directory:
        scratch_root = Path(temporary_directory)
        for pickle_path in pickle_paths:
            print(f"Benchmarking pickle bundle: {pickle_path}")
            results.append(benchmark_pickle_bundle(pickle_path=pickle_path, scratch_root=scratch_root))
        for csv_path in csv_paths:
            print(f"Benchmarking CSV table: {csv_path}")
            results.append(benchmark_csv_table(csv_path=csv_path, scratch_root=scratch_root))
    result_df = pd.DataFrame(results)
    result_df.to_csv(output_path, index=False)
    print(f"Wrote {len(result_df)} benchmark result(s) to {output_path}")
    return result_df


# --- Notebook run toggles ---

RUN_BENCHMARKS = True
PICKLE_PATHS = [
    REPO_ROOT / "outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_20_USA_CHP_CHECK_20260805_RERUN/supporting_files/runtime/balance_demand_cache/5a725cff79776665.pkl",
    REPO_ROOT / "outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_REAL_BATCH1_AUS_USA_PRC_20260812_000002/supporting_files/runtime/balance_demand_cache/16f29c9d9edcc54d.pkl",
    REPO_ROOT / "outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_20_USA_FULL_NOPREFLIGHT_20260805/supporting_files/runtime/transform_supply_cache/bc79eb2cfb24d001.pkl",
]
CSV_PATHS = [
    REPO_ROOT / "data/.cache/industry_reference_tables/775fdef9a85fa3c8_ninth.csv",
]
BENCHMARK_OUTPUT_PATH = REPO_ROOT / "docs/diagnostics/parquet_migration/benchmark_results.csv"
SCRATCH_PARENT = Path(r"C:\Users\Work\Documents\Codex\2026-08-16\leap-initialisation-docs-prompts-parquet-migration\work")


#%%
if RUN_BENCHMARKS:
    try:
        benchmark_results = run_benchmarks(
            pickle_paths=PICKLE_PATHS,
            csv_paths=CSV_PATHS,
            output_path=BENCHMARK_OUTPUT_PATH,
            scratch_parent=SCRATCH_PARENT,
        )
        print(benchmark_results.to_string(index=False))
    except Exception as exc:
        print(f"[ERROR] Parquet migration benchmark failed: {type(exc).__name__}: {exc}")
        raise

#%%

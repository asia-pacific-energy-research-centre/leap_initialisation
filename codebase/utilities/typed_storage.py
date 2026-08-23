"""Small, explicit helpers for versioned Parquet/Zstandard artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet


PARQUET_SCHEMA_VERSION = 1
PARQUET_COMPRESSION = "zstd"
TYPED_BUNDLE_FORMAT = "leap_typed_cache_bundle"
TYPED_BUNDLE_VERSION = 1
TABULAR_ARTIFACT_FORMAT = "leap_manifested_tabular_artifact"
TABULAR_ARTIFACT_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet_atomic(
    frame: pd.DataFrame,
    output_path: Path,
    *,
    index: bool = False,
) -> dict:
    """Write one authoritative Parquet file atomically and return manifest fields."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary name deliberately short.  Repeating a long artifact
    # name here can make an otherwise valid final path exceed Windows MAX_PATH.
    temporary_path = output_path.parent / f".{uuid.uuid4().hex}.tmp"
    try:
        with temporary_path.open("wb") as handle:
            frame.to_parquet(
                handle,
                index=index,
                compression=PARQUET_COMPRESSION,
            )
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "path": output_path.name,
        "format": "parquet",
        "compression": PARQUET_COMPRESSION,
        "schema_version": PARQUET_SCHEMA_VERSION,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": [str(column) for column in frame.columns],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "byte_size": int(output_path.stat().st_size),
        "sha256": sha256_file(output_path),
    }


def write_json_atomic(payload: dict, output_path: Path) -> None:
    """Write JSON atomically in the same directory as its final path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.parent / f".{uuid.uuid4().hex}.tmp"
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def parquet_manifest_path(path: Path) -> Path:
    """Return the sidecar manifest path for one authoritative Parquet table."""
    path = Path(path)
    return path.with_name(f"{path.name}.manifest.json")


def write_manifested_parquet(
    frame: pd.DataFrame,
    output_path: Path,
    *,
    artifact_type: str,
    source_provenance: dict | None = None,
) -> dict:
    """Atomically write a Parquet table and its versioned integrity manifest."""
    artifact = write_parquet_atomic(frame, Path(output_path), index=False)
    manifest = {
        "storage_format": TABULAR_ARTIFACT_FORMAT,
        "format_version": TABULAR_ARTIFACT_VERSION,
        "artifact_type": str(artifact_type),
        "artifact": artifact,
    }
    if source_provenance is not None:
        manifest["source_provenance"] = source_provenance
    write_json_atomic(manifest, parquet_manifest_path(Path(output_path)))
    return manifest


def read_manifested_parquet_file(path: Path) -> pd.DataFrame:
    """Read a Parquet table after validating its versioned sidecar manifest."""
    path = Path(path)
    manifest_path = parquet_manifest_path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unreadable Parquet artifact manifest: {manifest_path}") from exc
    expected_header = {
        "storage_format": TABULAR_ARTIFACT_FORMAT,
        "format_version": TABULAR_ARTIFACT_VERSION,
    }
    actual_header = {key: manifest.get(key) for key in expected_header}
    if actual_header != expected_header:
        raise ValueError(f"Unsupported Parquet artifact manifest: {manifest_path}")
    return read_manifested_parquet(path, manifest.get("artifact", {}))


def read_manifested_parquet(path: Path, artifact_manifest: dict) -> pd.DataFrame:
    """Read a known Parquet authority after validating its version and hash."""
    path = Path(path)
    if artifact_manifest.get("format") != "parquet":
        raise ValueError(f"Unsupported cache format for {path}: {artifact_manifest.get('format')!r}")
    if artifact_manifest.get("compression") != PARQUET_COMPRESSION:
        raise ValueError(f"Unsupported cache compression for {path}: {artifact_manifest.get('compression')!r}")
    if artifact_manifest.get("schema_version") != PARQUET_SCHEMA_VERSION:
        raise ValueError(f"Unsupported cache schema version for {path}: {artifact_manifest.get('schema_version')!r}")
    expected_hash = artifact_manifest.get("sha256")
    if not path.exists() or not expected_hash or sha256_file(path) != expected_hash:
        raise ValueError(f"Parquet cache hash mismatch: {path}")
    # ``self_destruct`` releases Arrow buffers as pandas columns are created.
    # This matters for the wide object-heavy supply cache, whose temporary
    # Arrow table would otherwise more than double peak memory.
    arrow_table = parquet.read_table(path)
    frame = arrow_table.to_pandas(
        split_blocks=True,
        self_destruct=True,
        strings_to_categorical=True,
    )
    del arrow_table
    expected_dtypes = artifact_manifest.get("dtypes", [])
    for column_position, dtype_name in enumerate(expected_dtypes):
        if column_position < len(frame.columns) and str(frame.dtypes.iloc[column_position]) != dtype_name:
            frame.isetitem(column_position, frame.iloc[:, column_position].astype(dtype_name))
    expected_rows = artifact_manifest.get("row_count")
    if expected_rows is not None and len(frame) != int(expected_rows):
        raise ValueError(f"Parquet cache row-count mismatch: {path}")
    return frame


def _encode_columns(columns, bundle_dir: Path, table_counter: list[int]) -> dict:
    if isinstance(columns, pd.RangeIndex):
        return {
            "kind": "range_index",
            "start": columns.start,
            "stop": columns.stop,
            "step": columns.step,
            "name": _encode_value(columns.name, bundle_dir, table_counter),
        }
    if isinstance(columns, pd.MultiIndex):
        return {
            "kind": "multi_index",
            "values": _encode_value(list(columns), bundle_dir, table_counter),
            "names": _encode_value(list(columns.names), bundle_dir, table_counter),
        }
    return {
        "kind": "index",
        "values": _encode_value(list(columns), bundle_dir, table_counter),
        "name": _encode_value(columns.name, bundle_dir, table_counter),
    }


def _decode_columns(node: dict, bundle_dir: Path):
    if node["kind"] == "range_index":
        return pd.RangeIndex(
            start=node["start"],
            stop=node["stop"],
            step=node["step"],
            name=_decode_value(node["name"], bundle_dir),
        )
    if node["kind"] == "multi_index":
        return pd.MultiIndex.from_tuples(
            _decode_value(node["values"], bundle_dir),
            names=_decode_value(node["names"], bundle_dir),
        )
    return pd.Index(
        _decode_value(node["values"], bundle_dir),
        name=_decode_value(node["name"], bundle_dir),
    )


def _encode_value(value, bundle_dir: Path, table_counter: list[int]) -> dict:
    if isinstance(value, pd.DataFrame):
        table_number = table_counter[0]
        table_counter[0] += 1
        table_name = f"table_{table_number:04d}.parquet"
        physical_frame = value.copy(deep=False)
        physical_frame.columns = [f"column_{index:04d}" for index in range(len(value.columns))]
        artifact_manifest = write_parquet_atomic(
            physical_frame,
            bundle_dir / table_name,
            index=True,
        )
        return {
            "type": "dataframe",
            "artifact": artifact_manifest,
            "columns": _encode_columns(value.columns, bundle_dir, table_counter),
            "dtypes": [str(dtype) for dtype in value.dtypes],
        }
    if isinstance(value, dict):
        return {
            "type": "dict",
            "items": [
                [_encode_value(key, bundle_dir, table_counter), _encode_value(item, bundle_dir, table_counter)]
                for key, item in value.items()
            ],
        }
    if isinstance(value, list):
        return {"type": "list", "items": [_encode_value(item, bundle_dir, table_counter) for item in value]}
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [_encode_value(item, bundle_dir, table_counter) for item in value]}
    if isinstance(value, set):
        return {"type": "set", "items": [_encode_value(item, bundle_dir, table_counter) for item in value]}
    if value is pd.NA:
        return {"type": "pd_na"}
    if isinstance(value, pd.Timestamp):
        return {"type": "timestamp", "value": value.isoformat()}
    if isinstance(value, np.generic):
        return {"type": "numpy_scalar", "dtype": str(value.dtype), "value": value.item()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"type": "nonfinite_float", "value": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return {"type": "scalar", "value": value}
    raise TypeError(f"Unsupported typed-cache value: {type(value).__name__}")


def _decode_value(node: dict, bundle_dir: Path):
    value_type = node["type"]
    if value_type == "dataframe":
        artifact_manifest = node["artifact"]
        frame = read_manifested_parquet(bundle_dir / artifact_manifest["path"], artifact_manifest)
        frame.columns = _decode_columns(node["columns"], bundle_dir)
        for column_position, dtype_name in enumerate(node["dtypes"]):
            if str(frame.dtypes.iloc[column_position]) != dtype_name:
                frame.isetitem(column_position, frame.iloc[:, column_position].astype(dtype_name))
        return frame
    if value_type == "dict":
        return {_decode_value(key, bundle_dir): _decode_value(value, bundle_dir) for key, value in node["items"]}
    if value_type == "list":
        return [_decode_value(item, bundle_dir) for item in node["items"]]
    if value_type == "tuple":
        return tuple(_decode_value(item, bundle_dir) for item in node["items"])
    if value_type == "set":
        return {_decode_value(item, bundle_dir) for item in node["items"]}
    if value_type == "pd_na":
        return pd.NA
    if value_type == "timestamp":
        return pd.Timestamp(node["value"])
    if value_type == "numpy_scalar":
        return np.dtype(node["dtype"]).type(node["value"])
    if value_type == "nonfinite_float":
        return {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}[node["value"]]
    if value_type == "scalar":
        return node["value"]
    raise ValueError(f"Unknown typed-cache node type: {value_type}")


def write_typed_cache_bundle_atomic(value, bundle_path: Path) -> None:
    """Atomically write nested cache state using Parquet tables and JSON structure."""
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = bundle_path.parent / f".{uuid.uuid4().hex}.tmp"
    try:
        temporary_path.mkdir()
        structure = _encode_value(value, bundle_dir=temporary_path, table_counter=[0])
        write_json_atomic(
            {
                "storage_format": TYPED_BUNDLE_FORMAT,
                "format_version": TYPED_BUNDLE_VERSION,
                "table_format": "parquet",
                "compression": PARQUET_COMPRESSION,
                "schema_version": PARQUET_SCHEMA_VERSION,
                "structure": structure,
            },
            temporary_path / "manifest.json",
        )
        os.replace(temporary_path, bundle_path)
    except Exception:
        if temporary_path.exists():
            shutil.rmtree(temporary_path)
        raise


def read_typed_cache_bundle(bundle_path: Path):
    """Read and verify a versioned typed cache bundle."""
    bundle_path = Path(bundle_path)
    manifest_path = bundle_path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unreadable typed cache manifest: {manifest_path}") from exc
    expected_header = {
        "storage_format": TYPED_BUNDLE_FORMAT,
        "format_version": TYPED_BUNDLE_VERSION,
        "table_format": "parquet",
        "compression": PARQUET_COMPRESSION,
        "schema_version": PARQUET_SCHEMA_VERSION,
    }
    actual_header = {key: manifest.get(key) for key in expected_header}
    if actual_header != expected_header:
        raise ValueError(f"Unsupported typed cache bundle: {bundle_path}")
    return _decode_value(manifest["structure"], bundle_dir=bundle_path)

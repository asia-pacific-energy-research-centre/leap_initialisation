#%%
"""Strict initialisation consumer for mappings-owned structural truth."""

#%%
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


CONTRACT_NAME = "aperc_hierarchy_subtotal_contract"
SCHEMA_VERSION = "hierarchy_subtotal_contract_v1"


def load_hierarchy_subtotal_contract(
    contract_dir: Path,
    expected_build_id: str | None = None,
    expected_input_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, object], dict[str, pd.DataFrame]]:
    """Load one explicitly managed artifact; never import a mappings checkout."""
    contract_dir = Path(contract_dir)
    manifest_path = contract_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Selected hierarchy contract is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_name") != CONTRACT_NAME:
        raise ValueError("Selected hierarchy contract has the wrong contract name")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Selected hierarchy contract schema is incompatible")
    if manifest.get("validation_result") != "passed":
        raise ValueError("Selected hierarchy contract is invalid")
    if expected_build_id and manifest.get("build_id") != expected_build_id:
        raise ValueError("Selected hierarchy contract build_id does not match")
    actual_inputs = {
        Path(item["path"]).name: item["sha256"]
        for item in manifest.get("inputs", [])
    }
    for name, expected_hash in (expected_input_hashes or {}).items():
        if actual_inputs.get(name) != expected_hash:
            raise ValueError(f"Selected hierarchy contract input mismatch for {name}")

    frames: dict[str, pd.DataFrame] = {}
    for name, declaration in manifest.get("members", {}).items():
        path = contract_dir / declaration["path"]
        if not path.exists():
            raise FileNotFoundError(f"Hierarchy contract member is missing: {path}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != declaration["sha256"]:
            raise ValueError(f"Hierarchy contract member hash mismatch: {name}")
        frame = pd.read_csv(path, dtype=object)
        if len(frame) != int(declaration["row_count"]):
            raise ValueError(f"Hierarchy contract member row count mismatch: {name}")
        frames[name] = frame
    return manifest, frames


def attach_structural_pair_status(
    data: pd.DataFrame,
    canonical_pairs: pd.DataFrame,
    dataset_id: str,
    axis_1_column: str,
    axis_2_column: str,
) -> pd.DataFrame:
    """Attach structural truth and separate declared output treatment."""
    pair_columns = [
        "dataset_id",
        "axis_1_node_id",
        "axis_2_node_id",
        "pair_is_subtotal",
        "every_node_resolved",
    ]
    optional_columns = [
        column
        for column in ["declared_output_subtotal", "synthetic_status"]
        if column in canonical_pairs.columns
    ]
    pair_columns.extend(optional_columns)
    lookup = canonical_pairs[pair_columns].copy()
    lookup = lookup[lookup["dataset_id"].astype(str).eq(dataset_id)].rename(columns={
        "axis_1_node_id": axis_1_column,
        "axis_2_node_id": axis_2_column,
        "pair_is_subtotal": "structural_pair_is_subtotal",
        "every_node_resolved": "structural_pair_resolved",
        "declared_output_subtotal": "declared_output_is_subtotal",
        "synthetic_status": "structural_pair_synthetic_status",
    })
    result = data.merge(
        lookup.drop(columns="dataset_id"),
        on=[axis_1_column, axis_2_column],
        how="left",
        validate="many_to_one",
    )
    result["structural_contract_dataset_id"] = dataset_id
    return result


#%%

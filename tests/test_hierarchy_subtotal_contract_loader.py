"""Initialisation structural-contract migration tests."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from codebase.mappings.hierarchy_subtotal_contract_loader import (
    attach_structural_pair_status,
    load_hierarchy_subtotal_contract,
)


def _contract(root: Path) -> Path:
    payload = (
        b"dataset_id,axis_1_node_id,axis_2_node_id,pair_is_subtotal,every_node_resolved\n"
        b"ninth,parent,leaf,True,True\n"
    )
    (root / "canonical_source_pairs.csv").write_bytes(payload)
    manifest = {
        "contract_name": "aperc_hierarchy_subtotal_contract",
        "schema_version": "hierarchy_subtotal_contract_v1",
        "build_id": "build-1",
        "validation_result": "passed",
        "inputs": [{"path": "mapping.xlsx", "sha256": "abc"}],
        "members": {
            "canonical_source_pairs": {
                "path": "canonical_source_pairs.csv",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "row_count": 1,
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_loader_fails_closed_for_stale_or_mismatched_contract(tmp_path: Path) -> None:
    root = _contract(tmp_path)
    load_hierarchy_subtotal_contract(
        root,
        expected_build_id="build-1",
        expected_input_hashes={"mapping.xlsx": "abc"},
    )
    with pytest.raises(ValueError, match="build_id"):
        load_hierarchy_subtotal_contract(root, expected_build_id="stale")
    with pytest.raises(ValueError, match="input mismatch"):
        load_hierarchy_subtotal_contract(
            root,
            expected_input_hashes={"mapping.xlsx": "different"},
        )


def test_structural_status_is_attached_without_overwriting_period_flags() -> None:
    data = pd.DataFrame([{
        "sectors": "parent",
        "fuels": "leaf",
        "subtotal_results": False,
    }])
    pairs = pd.DataFrame([{
        "dataset_id": "ninth",
        "axis_1_node_id": "parent",
        "axis_2_node_id": "leaf",
        "pair_is_subtotal": True,
        "every_node_resolved": True,
    }])
    result = attach_structural_pair_status(
        data,
        pairs,
        dataset_id="ninth",
        axis_1_column="sectors",
        axis_2_column="fuels",
    )
    assert bool(result.iloc[0]["structural_pair_is_subtotal"])
    assert not bool(result.iloc[0]["subtotal_results"])

"""Tests for the canonical-mapping migration fixes (other loss/own use, refining)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


# --- C3: other loss/own use fuel mapping from canonical -----------------------
def test_other_loss_fuel_lookup_is_populated_and_unambiguous():
    from codebase.other_loss_own_use_proxy_workflow import (
        load_fuel_mapping_lookup,
        LAST_FUEL_MAPPING_AMBIGUITY,
    )

    lookup = load_fuel_mapping_lookup()
    # Previously silently empty (requested legacy sheets absent from canonical).
    assert lookup["esto"], "esto fuel lookup should be populated from canonical"
    assert lookup["ninth"], "ninth fuel lookup should be populated from canonical"
    # A known ESTO product resolves to its LEAP fuel name.
    assert lookup["esto"].get("01.01 coking coal") == "Coking coal"
    # Ambiguous source codes are recorded, never silently included in the lookup.
    ambiguous_ninth = set(LAST_FUEL_MAPPING_AMBIGUITY["ninth"])
    assert ambiguous_ninth.isdisjoint(lookup["ninth"].keys())


# --- C4: refining remap derives mapping from canonical, no missing csv --------
def test_refining_mapping_derived_from_canonical_without_csv():
    from codebase.functions.transformation_fuel_remap import _load_mapping

    mapping = _load_mapping(None, branch_root="Transformation\\Oil Refining")
    assert mapping, "refining mapping should be derived from canonical leap_combined_ninth"
    crude = mapping.get("Crude oil")
    assert crude is not None and crude.ninth_fuel == "06_01_crude_oil"
    # Derived rows are labelled for provenance.
    assert crude.notes == "derived_from_canonical_leap_combined_ninth"


def test_refining_mapping_missing_csv_is_not_an_error(tmp_path: Path):
    from codebase.functions.transformation_fuel_remap import _load_mapping

    missing = tmp_path / "does_not_exist.csv"
    mapping = _load_mapping(missing, branch_root="Transformation\\Oil Refining")
    assert mapping  # falls back to canonical derivation, no exception


def test_refining_csv_override_wins_when_present(tmp_path: Path):
    from codebase.functions.transformation_fuel_remap import _load_mapping

    csv = tmp_path / "override.csv"
    pd.DataFrame(
        [{"source_fuel": "Crude oil", "ninth_fuel": "99_override", "esto_product_override": "", "notes": "manual"}]
    ).to_csv(csv, index=False)
    mapping = _load_mapping(csv, branch_root="Transformation\\Oil Refining")
    assert mapping["Crude oil"].ninth_fuel == "99_override"


def test_refining_pairs_accepts_canonical_sheet_ref():
    from codebase.functions.transformation_fuel_remap import _load_pairs, _resolve_esto_product
    from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH

    pairs = _load_pairs((OUTLOOK_MAPPINGS_MASTER_PATH, "ninth_pairs_to_esto_pairs"))
    assert {"9th_fuel", "esto_product"}.issubset(pairs.columns)
    product, candidates = _resolve_esto_product(pairs, "06_01_crude_oil", "")
    assert product == "06.01 Crude oil"


# --- C2: balance pairs pointer now canonical ----------------------------------
def test_balance_mapping_pairs_path_is_canonical():
    from codebase.utilities.leap_results_dashboard_balance import DEFAULT_MAPPING_PAIRS_PATH

    path, sheet = DEFAULT_MAPPING_PAIRS_PATH
    assert Path(path).name == "outlook_mappings_master.xlsx"
    assert sheet == "ninth_pairs_to_esto_pairs"

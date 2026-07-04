#%%
"""Shared loaders for the canonical Outlook mapping workbook.

This module is the single entry point for reading the canonical mapping
workbook ``leap_mappings/config/outlook_mappings_master.xlsx`` from
supply-reconciliation workflows.  It centralises:

- resolving the canonical workbook path (from REPO_ROOT, notebook-safe);
- validating that a required sheet and its required columns are present;
- applying identical active-row filtering for ``remove_row`` and
  ``duplicate_to_remove`` *where those columns exist*;
- loading the four canonical semantic roles used across the workflows;
- detecting conflicting duplicate mappings (one source pair implying more than
  one target pair).

Semantic roles (do not collapse pair/context mappings into a global fuel-only
dictionary):

- ``leap_combined_esto``:  (LEAP sector path, raw LEAP fuel) -> (ESTO flow, ESTO product)
- ``leap_combined_ninth``: (LEAP sector path, raw LEAP fuel) -> (9th sector, 9th fuel)
- ``ninth_pairs_to_esto_pairs``: (9th sector, 9th fuel) -> (ESTO flow, ESTO product)
- ``leap_display_names``: code -> LEAP display name only

Loaders raise :class:`CanonicalMappingError` naming the workbook, sheet, and
missing columns rather than silently falling back to legacy workbooks.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH

# Canonical workbook and sheet names -----------------------------------------
CANONICAL_WORKBOOK_PATH: Path = OUTLOOK_MAPPINGS_MASTER_PATH

SHEET_LEAP_COMBINED_ESTO = "leap_combined_esto"
SHEET_LEAP_COMBINED_NINTH = "leap_combined_ninth"
SHEET_NINTH_PAIRS_TO_ESTO_PAIRS = "ninth_pairs_to_esto_pairs"
SHEET_LEAP_DISPLAY_NAMES = "leap_display_names"

# Required columns per canonical role -----------------------------------------
LEAP_COMBINED_ESTO_KEYS = ("leap_sector_name_full_path", "raw_leap_fuel_name")
LEAP_COMBINED_ESTO_TARGETS = ("esto_flow", "esto_product")
LEAP_COMBINED_NINTH_TARGETS = ("ninth_sector", "ninth_fuel")
NINTH_PAIRS_SOURCE = ("9th_sector", "9th_fuel")
NINTH_PAIRS_TARGET = ("esto_flow", "esto_product")
LEAP_DISPLAY_NAMES_REQUIRED = ("code", "leap_display_name")

# Column marking rows excluded from LEAP entirely. Explicit False excludes the
# row; blank/NaN or True keep it (blank is the common case and means "not
# reviewed / not flagged for exclusion", not "excluded").
USED_IN_LEAP_INITIALISATION_COLUMN = "USED_IN_LEAP_INITIALISATION"

# Optional active-row filter flags, applied only where present.
ACTIVE_ROW_FLAG_COLUMNS = ("remove_row", "duplicate_to_remove")

_TRUTHY = {"1", "true", "t", "yes", "y", "on"}


class CanonicalMappingError(RuntimeError):
    """Raised when the canonical workbook, a sheet, or required columns are missing."""


def _truthy_flag(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _clean(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() == "nan" else text


def _resolve_workbook(workbook: str | Path | None) -> Path:
    path = Path(workbook) if workbook is not None else CANONICAL_WORKBOOK_PATH
    if not path.exists():
        raise CanonicalMappingError(
            f"Canonical mapping workbook not found: {path}. "
            "Expected leap_mappings/config/outlook_mappings_master.xlsx."
        )
    return path


def _sheet_names(path: Path) -> list[str]:
    try:
        return list(pd.ExcelFile(path).sheet_names)
    except Exception as exc:  # pragma: no cover - unreadable workbook
        raise CanonicalMappingError(f"Could not open canonical workbook {path}: {exc}") from exc


def apply_active_row_filter(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop rows flagged by ``remove_row`` / ``duplicate_to_remove`` where present.

    Sheets that do not carry these columns are returned unchanged.  Boolean
    filtering matches the shared truthy convention used across the workflows.
    """
    if frame.empty:
        return frame
    mask = pd.Series(True, index=frame.index)
    for col in ACTIVE_ROW_FLAG_COLUMNS:
        if col in frame.columns:
            mask &= ~frame[col].map(_truthy_flag)
    return frame.loc[mask].copy()


def filter_used_in_leap_initialisation(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop rows explicitly excluded from LEAP via ``USED_IN_LEAP_INITIALISATION``.

    Only an explicit ``False`` (or falsy string equivalent) excludes a row;
    blank/NaN and ``True`` both keep it, since blank is the common "not
    flagged either way" case rather than "excluded". Frames without the
    column are returned unchanged.
    """
    if frame.empty or USED_IN_LEAP_INITIALISATION_COLUMN not in frame.columns:
        return frame
    col = frame[USED_IN_LEAP_INITIALISATION_COLUMN]

    def _excluded(value: object) -> bool:
        if pd.isna(value):
            return False
        text = str(value).strip().lower()
        return text in {"false", "0", "0.0", "f", "no", "n"}

    mask = ~col.map(_excluded)
    return frame.loc[mask].copy()


def load_canonical_sheet(
    sheet_name: str,
    required_columns: Sequence[str],
    *,
    workbook: str | Path | None = None,
    apply_active_filter: bool = True,
    apply_usage_filter: bool = True,
    dtype: object | None = None,
) -> pd.DataFrame:
    """Load one canonical sheet, validating presence and required columns.

    Raises :class:`CanonicalMappingError` naming the workbook, sheet, and any
    missing required columns. Drops rows explicitly excluded via
    ``USED_IN_LEAP_INITIALISATION`` unless ``apply_usage_filter`` is False, and
    applies ``remove_row`` / ``duplicate_to_remove`` filtering when those
    columns exist unless ``apply_active_filter`` is False.
    """
    path = _resolve_workbook(workbook)
    if sheet_name not in _sheet_names(path):
        raise CanonicalMappingError(
            f"Canonical workbook {path} is missing required sheet '{sheet_name}'."
        )
    read_kwargs: dict[str, object] = {"sheet_name": sheet_name}
    if dtype is not None:
        read_kwargs["dtype"] = dtype
    frame = pd.read_excel(path, **read_kwargs)
    frame.columns = [str(c).strip() for c in frame.columns]
    missing = [c for c in required_columns if c not in frame.columns]
    if missing:
        raise CanonicalMappingError(
            f"Canonical sheet '{sheet_name}' in {path} is missing required "
            f"columns {missing}. Present columns: {list(frame.columns)}."
        )
    if apply_usage_filter:
        frame = filter_used_in_leap_initialisation(frame)
    if apply_active_filter:
        frame = apply_active_row_filter(frame)
    return frame.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Semantic-role loaders
# ---------------------------------------------------------------------------
def load_leap_combined_esto(*, workbook: str | Path | None = None) -> pd.DataFrame:
    """(LEAP sector path, raw LEAP fuel) -> (ESTO flow, ESTO product)."""
    required = list(LEAP_COMBINED_ESTO_KEYS) + list(LEAP_COMBINED_ESTO_TARGETS)
    return load_canonical_sheet(SHEET_LEAP_COMBINED_ESTO, required, workbook=workbook)


def load_leap_combined_ninth(*, workbook: str | Path | None = None) -> pd.DataFrame:
    """(LEAP sector path, raw LEAP fuel) -> (9th sector, 9th fuel)."""
    required = list(LEAP_COMBINED_ESTO_KEYS) + list(LEAP_COMBINED_NINTH_TARGETS)
    return load_canonical_sheet(SHEET_LEAP_COMBINED_NINTH, required, workbook=workbook)


def load_ninth_pairs_to_esto_pairs(
    *, workbook: str | Path | None = None, detect_conflicts: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(9th sector, 9th fuel) -> (ESTO flow, ESTO product).

    Returns ``(clean_pairs, conflicts)`` where ``conflicts`` lists 9th
    sector/fuel keys that imply more than one ESTO target pair.
    """
    required = list(NINTH_PAIRS_SOURCE) + list(NINTH_PAIRS_TARGET)
    frame = load_canonical_sheet(SHEET_NINTH_PAIRS_TO_ESTO_PAIRS, required, workbook=workbook)
    conflicts = (
        detect_conflicting_pair_mappings(frame, NINTH_PAIRS_SOURCE, NINTH_PAIRS_TARGET)
        if detect_conflicts
        else _empty_conflicts(NINTH_PAIRS_SOURCE)
    )
    return frame, conflicts


def load_leap_display_names(
    *, workbook: str | Path | None = None, include_excluded: bool = False
) -> pd.DataFrame:
    """Raw ``leap_display_names`` sheet (code -> display name only).

    Read as strings so purely-numeric codes (e.g. ``"17"``) and codes with
    leading zeros (e.g. ``"06.01"``) are not coerced to floats.
    """
    return load_canonical_sheet(
        SHEET_LEAP_DISPLAY_NAMES,
        LEAP_DISPLAY_NAMES_REQUIRED,
        workbook=workbook,
        apply_active_filter=False,
        apply_usage_filter=not include_excluded,
        dtype=str,
    )


def build_code_to_display_name(
    *,
    workbook: str | Path | None = None,
    detect_conflicts: bool = True,
    include_excluded: bool = False,
) -> tuple[dict[str, str], pd.DataFrame]:
    """Build a ``code -> LEAP display name`` dict from ``leap_display_names``.

    Prefers ``leap_display_name``; falls back to ``auto_name`` when the display
    name is blank.  Returns ``(mapping, conflicts)`` where ``conflicts`` lists
    codes appearing more than once with differing resolved names.  The first
    occurrence wins in ``mapping`` (stable, sheet order).
    """
    frame = load_leap_display_names(
        workbook=workbook,
        include_excluded=include_excluded,
    )
    has_auto = "auto_name" in frame.columns
    mapping: dict[str, str] = {}
    per_code_names: dict[str, set[str]] = {}
    for _, row in frame.iterrows():
        code = _clean(row.get("code"))
        if not code:
            continue
        name = _clean(row.get("leap_display_name"))
        if not name and has_auto:
            name = _clean(row.get("auto_name"))
        if not name:
            continue
        per_code_names.setdefault(code, set()).add(name)
        if code not in mapping:
            mapping[code] = name

    conflicts = _empty_conflicts(("code",))
    if detect_conflicts:
        rows = [
            {"code": code, "issue": "duplicate_code_conflicting_name", "details": "; ".join(sorted(names))}
            for code, names in per_code_names.items()
            if len(names) > 1
        ]
        if rows:
            conflicts = pd.DataFrame(rows).sort_values("code").reset_index(drop=True)
    return mapping, conflicts


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------
def _empty_conflicts(source_cols: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=[*source_cols, "issue", "details"])


def detect_conflicting_pair_mappings(
    frame: pd.DataFrame,
    source_columns: Sequence[str],
    target_columns: Sequence[str],
) -> pd.DataFrame:
    """Return source keys that map to more than one distinct target pair.

    A conflict means the base mapping crosses a comparison boundary and cannot
    be applied unambiguously.  Callers should surface these rather than picking
    an arbitrary first row.
    """
    source_columns = list(source_columns)
    target_columns = list(target_columns)
    cols = source_columns + target_columns
    df = frame[[c for c in cols if c in frame.columns]].copy()
    if any(c not in df.columns for c in cols) or df.empty:
        return _empty_conflicts(source_columns)
    for c in cols:
        df[c] = df[c].map(_clean)
    df = df[(df[source_columns] != "").all(axis=1)]
    df = df[(df[target_columns] != "").all(axis=1)]
    if df.empty:
        return _empty_conflicts(source_columns)

    grouped = df.drop_duplicates(cols).groupby(source_columns, dropna=False)
    rows: list[dict[str, str]] = []
    for key, group in grouped:
        targets = group[target_columns].drop_duplicates()
        if len(targets) > 1:
            key_tuple = key if isinstance(key, tuple) else (key,)
            details = "; ".join(
                " | ".join(str(v) for v in t)
                for t in targets.itertuples(index=False)
            )
            row = dict(zip(source_columns, key_tuple))
            row["issue"] = "duplicate_source_conflicting_target"
            row["details"] = details
            rows.append(row)
    if not rows:
        return _empty_conflicts(source_columns)
    return pd.DataFrame(rows).sort_values(source_columns).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Context-aware fuel resolution (avoid global fuel-only collapse)
# ---------------------------------------------------------------------------
def resolve_leap_fuel_to_esto(
    leap_sector_path: str,
    raw_leap_fuel: str,
    esto_frame: pd.DataFrame,
) -> tuple[str, str, str]:
    """Resolve a LEAP (path, fuel) to an ESTO (flow, product) with context.

    Returns ``(esto_flow, esto_product, status)`` where status is one of
    ``"exact"``, ``"fuel_only_unambiguous"``, ``"ambiguous"``, ``"missing"``.
    Falls back to a fuel-only lookup only when no path/fuel row exists and the
    fuel maps to exactly one ESTO product across the sheet; ambiguity is
    reported rather than resolved by arbitrary first-row selection.
    """
    path_key = _clean(leap_sector_path)
    fuel_key = _clean(raw_leap_fuel)
    df = esto_frame
    exact = df[
        (df["leap_sector_name_full_path"].map(_clean) == path_key)
        & (df["raw_leap_fuel_name"].map(_clean) == fuel_key)
    ]
    exact_pairs = exact[["esto_flow", "esto_product"]].drop_duplicates()
    if len(exact_pairs) == 1:
        r = exact_pairs.iloc[0]
        return _clean(r["esto_flow"]), _clean(r["esto_product"]), "exact"
    if len(exact_pairs) > 1:
        return "", "", "ambiguous"

    fuel_rows = df[df["raw_leap_fuel_name"].map(_clean) == fuel_key]
    fuel_products = fuel_rows[["esto_flow", "esto_product"]].drop_duplicates()
    if len(fuel_products) == 1:
        r = fuel_products.iloc[0]
        return _clean(r["esto_flow"]), _clean(r["esto_product"]), "fuel_only_unambiguous"
    if len(fuel_products) > 1:
        return "", "", "ambiguous"
    return "", "", "missing"


__all__ = [
    "CANONICAL_WORKBOOK_PATH",
    "CanonicalMappingError",
    "SHEET_LEAP_COMBINED_ESTO",
    "SHEET_LEAP_COMBINED_NINTH",
    "SHEET_NINTH_PAIRS_TO_ESTO_PAIRS",
    "SHEET_LEAP_DISPLAY_NAMES",
    "apply_active_row_filter",
    "filter_used_in_leap_initialisation",
    "load_canonical_sheet",
    "load_leap_combined_esto",
    "load_leap_combined_ninth",
    "load_ninth_pairs_to_esto_pairs",
    "load_leap_display_names",
    "build_code_to_display_name",
    "detect_conflicting_pair_mappings",
    "resolve_leap_fuel_to_esto",
]

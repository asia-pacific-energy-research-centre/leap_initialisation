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
SHEET_NINTH_FUEL_TO_ESTO_PRODUCT = "ninth fuel to esto product"
SHEET_LEAP_ROLLUP_RULES = "leap_rollup_rules"
SHEET_ESTO_ROLLUP_RULES = "esto_rollup_rules"
SHEET_NINTH_ROLLUP_RULES = "ninth_rollup_rules"

# Required columns per canonical role -----------------------------------------
LEAP_COMBINED_ESTO_KEYS = ("leap_sector_name_full_path", "raw_leap_fuel_name")
LEAP_COMBINED_ESTO_TARGETS = ("esto_flow", "esto_product")
LEAP_COMBINED_NINTH_TARGETS = ("ninth_sector", "ninth_fuel")
NINTH_PAIRS_SOURCE = ("ninth_sector", "ninth_fuel")
NINTH_PAIRS_TARGET = ("esto_flow", "esto_product")
LEAP_DISPLAY_NAMES_REQUIRED = ("code", "leap_display_name")

# The complete canonical-workbook schema surface consumed by this repository.
# This is a subset contract: mapping authors may add columns, but a rename of a
# consumed column must fail at the workbook boundary rather than later in a
# workflow.
CANONICAL_SHEET_CONTRACT: dict[str, tuple[str, ...]] = {
    SHEET_LEAP_COMBINED_ESTO: (*LEAP_COMBINED_ESTO_KEYS, *LEAP_COMBINED_ESTO_TARGETS),
    SHEET_LEAP_COMBINED_NINTH: (*LEAP_COMBINED_ESTO_KEYS, *LEAP_COMBINED_NINTH_TARGETS),
    SHEET_NINTH_PAIRS_TO_ESTO_PAIRS: (*NINTH_PAIRS_SOURCE, *NINTH_PAIRS_TARGET),
    SHEET_LEAP_DISPLAY_NAMES: LEAP_DISPLAY_NAMES_REQUIRED,
    SHEET_NINTH_FUEL_TO_ESTO_PRODUCT: ("ninth_fuel", "esto_product"),
    SHEET_LEAP_ROLLUP_RULES: (
        "rollup_context", "input_leap_sector_name_full_path", "input_raw_leap_fuel_name",
        "rolled_leap_sector_name_full_path", "rolled_raw_leap_fuel_name",
        "rollup_group_id", "rollup_reason", "priority", "include", "Note",
    ),
    SHEET_ESTO_ROLLUP_RULES: (
        "rollup_context", "input_esto_flow", "input_esto_product", "rolled_esto_flow",
        "rolled_esto_product", "rollup_group_id", "rollup_reason", "priority", "include", "Note",
    ),
    SHEET_NINTH_ROLLUP_RULES: (
        "rollup_context", "input_ninth_sector", "input_ninth_fuel", "rolled_ninth_sector",
        "rolled_ninth_fuel", "rollup_group_id", "rollup_reason", "priority", "include", "Note",
    ),
}

# Column marking rows excluded from LEAP entirely. Explicit False excludes the
# row; blank/NaN or True keep it (blank is the common case and means "not
# reviewed / not flagged for exclusion", not "excluded").
USED_IN_LEAP_INITIALISATION_COLUMN = "USED_IN_LEAP_INITIALISATION"

# Column marking a leap_display_names row whose display name is a rollup
# (comparison-side aggregate), not a real LEAP branch name. No rollup ever
# appears in LEAP - only its components do, recursively where a component is
# itself a rollup (see resolve_rollup_components). Only an explicit truthy
# value excludes a row; blank/NaN/False all keep it.
IS_LEAP_ROLLUP_NAME_COLUMN = "IS_LEAP_ROLLUP_NAME"

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


def filter_leap_rollup_names(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop rows flagged ``IS_LEAP_ROLLUP_NAME`` (D3.2: rollups never appear in LEAP).

    Applied alongside ``filter_used_in_leap_initialisation`` under the same
    ``apply_usage_filter``/``include_excluded`` toggle, so a caller that
    already opts out of usage filtering (e.g. to see intentionally-suppressed
    labels for its own downstream guard) keeps seeing rollup labels too,
    rather than having them silently vanish from a QA/suppression path that
    depends on resolving them by name. Frames without the column are
    returned unchanged.
    """
    if frame.empty or IS_LEAP_ROLLUP_NAME_COLUMN not in frame.columns:
        return frame
    mask = ~frame[IS_LEAP_ROLLUP_NAME_COLUMN].map(_truthy_flag)
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
    ``USED_IN_LEAP_INITIALISATION`` and rows flagged ``IS_LEAP_ROLLUP_NAME``
    unless ``apply_usage_filter`` is False, and applies ``remove_row`` /
    ``duplicate_to_remove`` filtering when those columns exist unless
    ``apply_active_filter`` is False.
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
        frame = filter_leap_rollup_names(frame)
    if apply_active_filter:
        frame = apply_active_row_filter(frame)
    return frame.reset_index(drop=True)


def load_canonical_contract_sheet(
    sheet_name: str,
    *,
    workbook: str | Path | None = None,
    dtype: object | None = None,
) -> pd.DataFrame:
    """Load a declared canonical sheet using its repository-owned contract."""
    try:
        required_columns = CANONICAL_SHEET_CONTRACT[sheet_name]
    except KeyError as exc:
        raise CanonicalMappingError(
            f"Canonical sheet '{sheet_name}' has no declared initialisation contract."
        ) from exc
    return load_canonical_sheet(
        sheet_name,
        required_columns,
        workbook=workbook,
        apply_active_filter=False,
        apply_usage_filter=False,
        dtype=dtype,
    )


# ---------------------------------------------------------------------------
# Semantic-role loaders
# ---------------------------------------------------------------------------
def load_leap_combined_esto(*, workbook: str | Path | None = None) -> pd.DataFrame:
    """(LEAP sector path, raw LEAP fuel) -> (ESTO flow, ESTO product)."""
    required = CANONICAL_SHEET_CONTRACT[SHEET_LEAP_COMBINED_ESTO]
    return load_canonical_sheet(SHEET_LEAP_COMBINED_ESTO, required, workbook=workbook)


def load_leap_combined_ninth(*, workbook: str | Path | None = None) -> pd.DataFrame:
    """(LEAP sector path, raw LEAP fuel) -> (9th sector, 9th fuel)."""
    required = CANONICAL_SHEET_CONTRACT[SHEET_LEAP_COMBINED_NINTH]
    return load_canonical_sheet(SHEET_LEAP_COMBINED_NINTH, required, workbook=workbook)


def load_ninth_pairs_to_esto_pairs(
    *, workbook: str | Path | None = None, detect_conflicts: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(9th sector, 9th fuel) -> (ESTO flow, ESTO product).

    Returns ``(clean_pairs, conflicts)`` where ``conflicts`` lists 9th
    sector/fuel keys that imply more than one ESTO target pair.
    """
    required = CANONICAL_SHEET_CONTRACT[SHEET_NINTH_PAIRS_TO_ESTO_PAIRS]
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
        CANONICAL_SHEET_CONTRACT[SHEET_LEAP_DISPLAY_NAMES],
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
# Rollup-label handling (D3.2): no rollup ever appears in LEAP - only its
# components do, recursively where a component is itself a rollup. Sourced
# from leap_rollup_rules, authored in leap_mappings - do not build a second,
# initialisation-local notion of what a rollup expands to.
# ---------------------------------------------------------------------------

_ROLLUP_SECTOR_COLUMN = "rolled_leap_sector_name_full_path"
_ROLLUP_FUEL_COLUMN = "rolled_raw_leap_fuel_name"
_ROLLUP_INPUT_SECTOR_COLUMN = "input_leap_sector_name_full_path"
_ROLLUP_INPUT_FUEL_COLUMN = "input_raw_leap_fuel_name"


def _load_leap_rollup_rules(workbook: str | Path | None) -> pd.DataFrame:
    return load_canonical_contract_sheet(SHEET_LEAP_ROLLUP_RULES, workbook=workbook)


def is_rollup_label(name: str, rules: pd.DataFrame) -> bool:
    """Return whether ``name`` is a rollup per the rollup-rule sheet itself.

    This is the *stronger* cross-check T10 recommended over trusting
    ``IS_LEAP_ROLLUP_NAME`` alone: it asks whether ``name`` actually has a
    matching ``rolled_*`` row in ``leap_rollup_rules``, so an unflagged
    rollup label (the flag column missing a row) is still caught rather than
    silently passed through.
    """
    text = _clean(name)
    if not text or rules.empty:
        return False
    if _ROLLUP_SECTOR_COLUMN in rules.columns:
        if rules[_ROLLUP_SECTOR_COLUMN].astype(str).str.strip().eq(text).any():
            return True
    if _ROLLUP_FUEL_COLUMN in rules.columns:
        if rules[_ROLLUP_FUEL_COLUMN].astype(str).str.strip().eq(text).any():
            return True
    return False


def _rollup_components(name: str, rules: pd.DataFrame) -> list[str]:
    """One level of rollup expansion: ``name`` -> its immediate components."""
    text = _clean(name)
    sector_rows = (
        rules[rules[_ROLLUP_SECTOR_COLUMN].astype(str).str.strip().eq(text)]
        if _ROLLUP_SECTOR_COLUMN in rules.columns
        else rules.iloc[0:0]
    )
    if not sector_rows.empty:
        matched, component_col = sector_rows, _ROLLUP_INPUT_SECTOR_COLUMN
    else:
        fuel_rows = (
            rules[rules[_ROLLUP_FUEL_COLUMN].astype(str).str.strip().eq(text)]
            if _ROLLUP_FUEL_COLUMN in rules.columns
            else rules.iloc[0:0]
        )
        if fuel_rows.empty:
            raise CanonicalMappingError(
                f"{name!r} is a rollup label but has no matching row in "
                f"leap_rollup_rules ('{_ROLLUP_SECTOR_COLUMN}'/'{_ROLLUP_FUEL_COLUMN}')."
            )
        matched, component_col = fuel_rows, _ROLLUP_INPUT_FUEL_COLUMN
    if component_col not in matched.columns:
        raise CanonicalMappingError(
            f"leap_rollup_rules is missing '{component_col}', needed to expand {name!r}."
        )
    components = sorted(
        {_clean(v) for v in matched[component_col].tolist() if _clean(v)}
    )
    if not components:
        raise CanonicalMappingError(
            f"{name!r} matched a leap_rollup_rules row but it names no components "
            f"in '{component_col}'."
        )
    return components


def resolve_rollup_components(
    name: str,
    *,
    workbook: str | Path | None = None,
    _rules: pd.DataFrame | None = None,
    _chain: tuple[str, ...] = (),
) -> list[str]:
    """Recursively expand a rollup display name into its real (non-rollup) components.

    Matches ``name`` against ``leap_rollup_rules``'s
    ``rolled_leap_sector_name_full_path`` (sector-level rollup) or
    ``rolled_raw_leap_fuel_name`` (fuel-level rollup), takes the matching
    row(s)' ``input_*`` column as the immediate components, and recurses into
    any component that is itself a rollup - down to labels that are real LEAP
    branch names. Raises :class:`CanonicalMappingError` if ``name`` is not
    actually a rollup (no matching row), if a matched row names no
    components, or if expansion cycles back to a name already being expanded.
    Order is deterministic (sorted); duplicates across recursive branches are
    removed while preserving first-seen order.
    """
    rules = _rules if _rules is not None else _load_leap_rollup_rules(workbook)
    if name in _chain:
        raise CanonicalMappingError(
            f"Rollup cycle detected expanding {name!r}: {' -> '.join((*_chain, name))}"
        )
    chain = (*_chain, name)
    expanded: list[str] = []
    for component in _rollup_components(name, rules):
        if is_rollup_label(component, rules):
            expanded.extend(
                resolve_rollup_components(component, _rules=rules, _chain=chain)
            )
        else:
            expanded.append(component)
    seen: set[str] = set()
    result: list[str] = []
    for component in expanded:
        if component not in seen:
            seen.add(component)
            result.append(component)
    return result


def assert_not_rollup_label(
    name: str,
    *,
    code: str | None = None,
    call_site: str = "",
    workbook: str | Path | None = None,
    _rules: pd.DataFrame | None = None,
) -> None:
    """Raise :class:`CanonicalMappingError` if ``name`` is a rollup display name.

    Call this immediately before a resolved display name is written as (or
    used to build) a LEAP branch path. A rollup label reaching a LEAP branch
    write is a defect, not a fallback case - do not silently substitute a
    derived name, since that would hide exactly the failure D3.2 exists to
    prevent. Uses the cross-check (``is_rollup_label``), not just the
    ``IS_LEAP_ROLLUP_NAME`` flag, so an unflagged rollup is still caught.
    """
    rules = _rules if _rules is not None else _load_leap_rollup_rules(workbook)
    if is_rollup_label(name, rules):
        location = f" ({call_site})" if call_site else ""
        code_part = f" for code {code!r}" if code else ""
        raise CanonicalMappingError(
            f"Rollup label {name!r}{code_part} reached a LEAP branch write{location}. "
            "Rollups never appear in LEAP - resolve its real components via "
            "resolve_rollup_components() instead of writing this label directly."
        )


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
    "SHEET_NINTH_FUEL_TO_ESTO_PRODUCT",
    "SHEET_LEAP_ROLLUP_RULES",
    "SHEET_ESTO_ROLLUP_RULES",
    "SHEET_NINTH_ROLLUP_RULES",
    "CANONICAL_SHEET_CONTRACT",
    "apply_active_row_filter",
    "filter_used_in_leap_initialisation",
    "filter_leap_rollup_names",
    "load_canonical_sheet",
    "load_canonical_contract_sheet",
    "load_leap_combined_esto",
    "load_leap_combined_ninth",
    "load_ninth_pairs_to_esto_pairs",
    "load_leap_display_names",
    "build_code_to_display_name",
    "resolve_rollup_components",
    "is_rollup_label",
    "assert_not_rollup_label",
    "detect_conflicting_pair_mappings",
    "resolve_leap_fuel_to_esto",
]

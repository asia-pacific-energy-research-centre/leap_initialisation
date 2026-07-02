"""
Pure-computation helpers extracted from outlook_mapping_maintenance_workflow.py.

These functions have no file I/O, no module-level global references, and no
LEAP API calls. They operate solely on their arguments and return new values.
"""

from __future__ import annotations

import re
from typing import Sequence

import pandas as pd


# ---------------------------------------------------------------------------
# String / value normalisation helpers
# ---------------------------------------------------------------------------

def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def _norm_text(value: object) -> str:
    return " ".join(_clean(value).lower().split())


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _path_key(path: object) -> str:
    parts = [part.strip() for part in str(path or "").split("/") if part.strip()]
    return "/".join(_norm_text(part) for part in parts)


# ---------------------------------------------------------------------------
# Cardinality / alignment helpers
# ---------------------------------------------------------------------------

def _mapping_cardinality(source_target_count: int, target_source_count: int) -> str:
    if source_target_count <= 0 or target_source_count <= 0:
        return ""
    if source_target_count == 1 and target_source_count == 1:
        return "one_to_one"
    if source_target_count > 1 and target_source_count == 1:
        return "one_to_many"
    if source_target_count == 1 and target_source_count > 1:
        return "many_to_one"
    return "many_to_many"


def _subtotal_alignment(leap_is_subtotal: bool, target_is_subtotal: bool) -> str:
    if leap_is_subtotal and target_is_subtotal:
        return "aligned_subtotal"
    if (not leap_is_subtotal) and (not target_is_subtotal):
        return "aligned_non_subtotal"
    return "mismatch"


# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------

def _active_mask(frame: pd.DataFrame) -> pd.Series:
    remove_mask = frame.get("remove_row", False)
    duplicate_mask = frame.get("duplicate_to_remove", False)
    remove_mask = pd.Series(remove_mask, index=frame.index).map(_truthy)
    duplicate_mask = pd.Series(duplicate_mask, index=frame.index).map(_truthy)
    return ~(remove_mask | duplicate_mask)


def _drop_unnamed_columns(frame: pd.DataFrame) -> pd.DataFrame:
    keep_cols = [col for col in frame.columns if not str(col).startswith("Unnamed:")]
    return frame.loc[:, keep_cols].copy()


def _drop_columns_if_present(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    drop_cols = [col for col in columns if col in frame.columns]
    if not drop_cols:
        return frame.copy()
    return frame.drop(columns=drop_cols).copy()


def _reorder_columns(frame: pd.DataFrame, preferred_columns: Sequence[str]) -> pd.DataFrame:
    ordered = [col for col in preferred_columns if col in frame.columns]
    trailing = [col for col in frame.columns if col not in ordered]
    return frame.loc[:, ordered + trailing].copy()


# ---------------------------------------------------------------------------
# Subtotal / cardinality computation
# ---------------------------------------------------------------------------

def _compute_leap_subtotals(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in ["leap_sector_name_full_path", "raw_leap_fuel_name"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()

    active = _active_mask(out)
    active_paths = {
        _clean(value)
        for value in out.loc[active, "leap_sector_name_full_path"].tolist()
        if _clean(value)
    }

    def leap_sector_is_subtotal(path: object) -> bool:
        text = _clean(path)
        key = _path_key(text)
        if not key:
            return False
        if key.startswith("total "):
            return True
        prefix = f"{text}/"
        return any(other != text and other.startswith(prefix) for other in active_paths)

    def leap_fuel_is_subtotal(fuel: object) -> bool:
        key = _norm_text(fuel)
        return key == "total" or key.startswith("total ")

    leap_sector_is_subtotal = out["leap_sector_name_full_path"].map(leap_sector_is_subtotal)
    leap_fuel_is_subtotal = out["raw_leap_fuel_name"].map(leap_fuel_is_subtotal)
    out["leap_is_subtotal"] = leap_sector_is_subtotal.fillna(False).astype(bool) | leap_fuel_is_subtotal.fillna(False).astype(bool)
    return out


def _compute_pair_cardinality(frame: pd.DataFrame, target_sector_col: str, target_fuel_col: str) -> pd.DataFrame:
    """Compute cardinality of (leap_sector, leap_fuel) <-> (target_sector, target_fuel) pairs."""
    out = frame.copy()
    source_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    target_cols = [target_sector_col, target_fuel_col]
    all_cols = source_cols + [c for c in target_cols if c not in source_cols]
    for col in all_cols:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()
    active = _active_mask(out)
    valid = (
        active
        & out["leap_sector_name_full_path"].ne("")
        & out["raw_leap_fuel_name"].ne("")
        & out[target_sector_col].ne("")
        & out[target_fuel_col].ne("")
    )
    pair_frame = out.loc[valid, source_cols + [target_sector_col, target_fuel_col]].copy()
    pair_frame["_source_key"] = pair_frame["leap_sector_name_full_path"] + "|||" + pair_frame["raw_leap_fuel_name"]
    pair_frame["_target_key"] = pair_frame[target_sector_col] + "|||" + pair_frame[target_fuel_col]
    pairs = pair_frame[["_source_key", "_target_key"]].drop_duplicates()
    source_count = pairs.groupby("_source_key")["_target_key"].nunique()
    target_count = pairs.groupby("_target_key")["_source_key"].nunique()
    out["_source_key"] = out["leap_sector_name_full_path"].fillna("").astype(str).str.strip() + "|||" + out["raw_leap_fuel_name"].fillna("").astype(str).str.strip()
    out["_target_key"] = out[target_sector_col].fillna("").astype(str).str.strip() + "|||" + out[target_fuel_col].fillna("").astype(str).str.strip()
    out["pair_mapping_cardinality"] = ""
    valid_rows = out["leap_sector_name_full_path"].ne("") & out["raw_leap_fuel_name"].ne("") & out[target_sector_col].ne("") & out[target_fuel_col].ne("")
    out.loc[valid_rows, "pair_mapping_cardinality"] = out.loc[valid_rows].apply(
        lambda row: _mapping_cardinality(
            int(source_count.get(row["_source_key"], 0)),
            int(target_count.get(row["_target_key"], 0)),
        ),
        axis=1,
    )
    out = out.drop(columns=["_source_key", "_target_key"])
    return out


def _apply_auto_remove_rules(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Mark obvious rows as remove_row=True and annotate the reason."""
    out = frame.copy()
    for col in [
        "leap_sector_name_full_path",
        "raw_leap_fuel_name",
        "remove_row",
        "remove_row_reason",
    ]:
        if col not in out.columns:
            out[col] = ""
    out["leap_sector_name_full_path"] = out["leap_sector_name_full_path"].fillna("").astype(str).str.strip()
    out["raw_leap_fuel_name"] = out["raw_leap_fuel_name"].fillna("").astype(str).str.strip()
    out["remove_row_reason"] = out["remove_row_reason"].fillna("").astype(str).str.strip()

    fuel_total_mask = out["raw_leap_fuel_name"].map(_norm_text).eq("total")
    def _sector_ends_with_fuel(path_value: object, fuel_value: object) -> bool:
        path_text = _clean(path_value)
        fuel_text = _clean(fuel_value)
        if not path_text or not fuel_text:
            return False
        parts = [part.strip() for part in path_text.split("/") if part.strip()]
        return len(parts) > 1 and parts[-1] == fuel_text

    suffix_mask = out.apply(
        lambda row: _sector_ends_with_fuel(row["leap_sector_name_full_path"], row["raw_leap_fuel_name"])
        and _norm_text(row["raw_leap_fuel_name"]) != "total"
        and not _clean(row["leap_sector_name_full_path"]).startswith("Electricity Generation/"),
        axis=1,
    )

    existing_remove_mask = out["remove_row"].map(_truthy)
    auto_mask = fuel_total_mask | suffix_mask
    newly_removed_mask = auto_mask & ~existing_remove_mask

    out["remove_row"] = existing_remove_mask | auto_mask

    def _append_reason(existing: str, reason: str) -> str:
        if not reason:
            return existing
        if not existing:
            return reason
        if reason in existing.split(" | "):
            return existing
        return f"{existing} | {reason}"

    def _strip_auto_reasons(existing: str) -> str:
        reasons = [part.strip() for part in existing.split(" | ") if part.strip()]
        reasons = [reason for reason in reasons if reason not in {"auto_remove_total_fuel", "auto_remove_sector_fuel_suffix"}]
        return " | ".join(reasons)

    out["remove_row_reason"] = out["remove_row_reason"].map(_strip_auto_reasons)
    out.loc[fuel_total_mask, "remove_row_reason"] = out.loc[fuel_total_mask, "remove_row_reason"].map(
        lambda reason: _append_reason(reason, "auto_remove_total_fuel")
    )
    out.loc[suffix_mask, "remove_row_reason"] = out.loc[suffix_mask, "remove_row_reason"].map(
        lambda reason: _append_reason(reason, "auto_remove_sector_fuel_suffix")
    )

    diagnostics = {
        "auto_remove_total_fuel_rows": int(fuel_total_mask.sum()),
        "auto_remove_sector_fuel_suffix_rows": int(suffix_mask.sum()),
        "auto_removed_new_rows": int(newly_removed_mask.sum()),
    }
    return out, diagnostics


# ---------------------------------------------------------------------------
# Sheet refresh helpers
# ---------------------------------------------------------------------------

def _refresh_esto_sheet(frame: pd.DataFrame, esto_lookup: pd.DataFrame) -> pd.DataFrame:
    out = _drop_unnamed_columns(frame)
    out = _drop_columns_if_present(
        out,
        [
            "many_to_many_is_ok",
            "esto_pair_is_subtotal",
            "esto_pair_is_subtotal_x",
            "esto_pair_is_subtotal_y",
            "esto_pair_abs_sum",
            "esto_pair_abs_sum_x",
            "esto_pair_abs_sum_y",
            "leap_sector_is_subtotal_computed",
            "leap_fuel_is_subtotal_computed",
        ],
    )
    out = _compute_leap_subtotals(out)
    out = _compute_pair_cardinality(out, "esto_flow", "esto_product")
    lookup = esto_lookup.copy()
    for col in ["esto_flow", "esto_product"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()
    out = out.merge(
        lookup[["esto_flow", "esto_product", "esto_pair_is_subtotal", "esto_pair_abs_sum"]],
        on=["esto_flow", "esto_product"],
        how="left",
    )
    if "esto_pair_is_subtotal" not in out.columns:
        out["esto_pair_is_subtotal"] = False
    out["esto_pair_is_subtotal"] = out["esto_pair_is_subtotal"].fillna(False).astype(bool)
    if "esto_pair_abs_sum" not in out.columns:
        out["esto_pair_abs_sum"] = 0.0
    out["esto_pair_abs_sum"] = pd.to_numeric(out["esto_pair_abs_sum"], errors="coerce").fillna(0.0)
    total_mask = out["esto_product"].fillna("").astype(str).str.strip().str.lower().eq("19 total")
    out.loc[total_mask, "esto_pair_is_subtotal"] = True
    out["subtotal_alignment"] = out.apply(
        lambda row: _subtotal_alignment(bool(row.get("leap_is_subtotal", False)), bool(row.get("esto_pair_is_subtotal", False))),
        axis=1,
    )
    return _reorder_columns(
        out,
        [
            "leap_sector_name_original",
            "leap_sector_name_full_path",
            "raw_leap_fuel_name",
            "value",
            "esto_flow",
            "esto_product",
            "pair_mapping_cardinality",
            "leap_is_subtotal",
            "esto_pair_is_subtotal",
            "subtotal_mismatch_is_ok",
            "subtotal_alignment",
            "esto_pair_abs_sum",
            "remove_row",
            "remove_row_reason",
        ],
    )


def _refresh_ninth_sheet(frame: pd.DataFrame, ninth_lookup: pd.DataFrame) -> pd.DataFrame:
    out = _drop_unnamed_columns(frame)
    out = _drop_columns_if_present(
        out,
        [
            "many_to_many_is_ok",
            "ninth_pair_is_subtotal",
            "ninth_pair_is_subtotal_x",
            "ninth_pair_is_subtotal_y",
            "ninth_pair_abs_sum",
            "ninth_pair_abs_sum_x",
            "ninth_pair_abs_sum_y",
            "leap_sector_is_subtotal_computed",
            "leap_fuel_is_subtotal_computed",
        ],
    )
    out = _compute_leap_subtotals(out)
    out = _compute_pair_cardinality(out, "ninth_sector", "ninth_fuel")
    lookup = ninth_lookup.copy()
    for col in ["ninth_sector", "ninth_fuel"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()
    out = out.merge(
        lookup[["ninth_sector", "ninth_fuel", "ninth_pair_is_subtotal", "ninth_pair_abs_sum"]],
        on=["ninth_sector", "ninth_fuel"],
        how="left",
    )
    if "ninth_pair_is_subtotal" not in out.columns:
        out["ninth_pair_is_subtotal"] = False
    out["ninth_pair_is_subtotal"] = out["ninth_pair_is_subtotal"].fillna(False).astype(bool)
    if "ninth_pair_abs_sum" not in out.columns:
        out["ninth_pair_abs_sum"] = 0.0
    out["ninth_pair_abs_sum"] = pd.to_numeric(out["ninth_pair_abs_sum"], errors="coerce").fillna(0.0)
    total_mask = out["ninth_fuel"].fillna("").astype(str).str.strip().str.lower().eq("19_total")
    out.loc[total_mask, "ninth_pair_is_subtotal"] = True
    out["subtotal_alignment"] = out.apply(
        lambda row: _subtotal_alignment(bool(row.get("leap_is_subtotal", False)), bool(row.get("ninth_pair_is_subtotal", False))),
        axis=1,
    )
    return _reorder_columns(
        out,
        [
            "leap_sector_name_original",
            "leap_sector_name_full_path",
            "raw_leap_fuel_name",
            "value",
            "ninth_sector",
            "ninth_fuel",
            "pair_mapping_cardinality",
            "leap_is_subtotal",
            "ninth_pair_is_subtotal",
            "subtotal_mismatch_is_ok",
            "subtotal_alignment",
            "ninth_pair_abs_sum",
            "remove_row",
            "remove_row_reason",
        ],
    )


# ---------------------------------------------------------------------------
# Active pair / presence helpers
# ---------------------------------------------------------------------------

def _active_pairs(frame: pd.DataFrame, col_a: str, col_b: str) -> set[tuple[str, str]]:
    """Return the set of (col_a, col_b) pairs in active (non-removed) rows."""
    active = frame[_active_mask(frame)].copy()
    a = active[col_a].fillna("").astype(str).str.strip() if col_a in active.columns else pd.Series("", index=active.index)
    b = active[col_b].fillna("").astype(str).str.strip() if col_b in active.columns else pd.Series("", index=active.index)
    return {(av, bv) for av, bv in zip(a, b) if av and bv}


def _active_leap_source_pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
    """Return active LEAP sector/fuel source pairs from a mapping sheet."""
    active = frame[_active_mask(frame)].copy()
    for col in ["leap_sector_name_full_path", "raw_leap_fuel_name"]:
        if col not in active.columns:
            active[col] = ""
        active[col] = active[col].fillna("").astype(str).str.strip()
    return {
        (_path_key(sector), _norm_text(fuel))
        for sector, fuel in zip(active["leap_sector_name_full_path"], active["raw_leap_fuel_name"])
        if _path_key(sector) and _norm_text(fuel)
    }


def _leap_source_pair_presence_lookup(frame: pd.DataFrame) -> dict[tuple[str, str], dict[str, object]]:
    """Return active/removed presence counts for LEAP source pairs in a mapping sheet."""
    work = frame.copy()
    for col in ["leap_sector_name_full_path", "raw_leap_fuel_name", "remove_row", "duplicate_to_remove"]:
        if col not in work.columns:
            work[col] = ""
    work["leap_sector_name_full_path"] = work["leap_sector_name_full_path"].fillna("").astype(str).str.strip()
    work["raw_leap_fuel_name"] = work["raw_leap_fuel_name"].fillna("").astype(str).str.strip()
    work["_source_key"] = list(zip(
        work["leap_sector_name_full_path"].map(_path_key),
        work["raw_leap_fuel_name"].map(_norm_text),
    ))
    work = work[work["_source_key"].map(lambda key: bool(key[0] and key[1]))].copy()
    if work.empty:
        return {}

    work["_is_removed"] = work["remove_row"].map(_truthy)
    work["_is_duplicate_removed"] = work["duplicate_to_remove"].map(_truthy)
    work["_is_active"] = ~(work["_is_removed"] | work["_is_duplicate_removed"])

    lookup: dict[tuple[str, str], dict[str, object]] = {}
    for source_key, group in work.groupby("_source_key", dropna=False):
        active_count = int(group["_is_active"].sum())
        removed_count = int(group["_is_removed"].sum())
        duplicate_removed_count = int(group["_is_duplicate_removed"].sum())
        total_count = int(len(group))
        if active_count:
            state = "active"
        elif removed_count and duplicate_removed_count:
            state = "removed_or_duplicate_removed_only"
        elif removed_count:
            state = "removed_only"
        elif duplicate_removed_count:
            state = "duplicate_removed_only"
        else:
            state = "present_but_inactive"
        lookup[source_key] = {
            "state": state,
            "detail": (
                f"active={active_count}; removed={removed_count}; "
                f"duplicate_removed={duplicate_removed_count}; total={total_count}"
            ),
        }
    return lookup


# ---------------------------------------------------------------------------
# Conflict / duplicate builders
# ---------------------------------------------------------------------------

def _build_duplicate_mappings(frame: pd.DataFrame, *, sheet_name: str, target_a: str, target_b: str) -> pd.DataFrame:
    """Return exact active duplicate source/target rows for one mapping sheet."""
    work = frame.copy().fillna("")
    source_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    target_cols = [target_a, target_b]
    required_cols = [*source_cols, *target_cols, "remove_row", "duplicate_to_remove"]
    for col in required_cols:
        if col not in work.columns:
            work[col] = ""
        work[col] = work[col].fillna("").astype(str).str.strip()

    active = work[_active_mask(work)].copy()
    valid = active[source_cols + target_cols].apply(lambda col: col.map(_clean).ne("")).all(axis=1)
    active = active.loc[valid].copy()
    if active.empty:
        return pd.DataFrame(
            columns=[
                "sheet_name",
                "mapping_row_number",
                "duplicate_group_size",
                *source_cols,
                *target_cols,
            ]
        )

    duplicate_mask = active.duplicated(subset=[*source_cols, *target_cols], keep=False)
    duplicates = active.loc[duplicate_mask].copy()
    if duplicates.empty:
        return pd.DataFrame(
            columns=[
                "sheet_name",
                "mapping_row_number",
                "duplicate_group_size",
                *source_cols,
                *target_cols,
            ]
        )

    duplicates.insert(0, "mapping_row_number", duplicates.index + 2)
    duplicates.insert(0, "sheet_name", sheet_name)
    duplicates["duplicate_group_size"] = duplicates.groupby([*source_cols, *target_cols])[source_cols[0]].transform("size")
    return duplicates[[
        "sheet_name",
        "mapping_row_number",
        "duplicate_group_size",
        *source_cols,
        *target_cols,
    ]].reset_index(drop=True)


def _build_trio_presence_check(esto_sheet: pd.DataFrame, ninth_sheet: pd.DataFrame) -> pd.DataFrame:
    """Return row-level presence diagnostics for the two mapping sheets."""
    source_cols = ["leap_sector_name_original", "leap_sector_name_full_path", "raw_leap_fuel_name"]

    def _sheet_row_status(frame: pd.DataFrame, sheet_name: str, target_cols: list[str]) -> pd.DataFrame:
        work = frame.copy().fillna("")
        for col in source_cols + target_cols + ["remove_row", "duplicate_to_remove"]:
            if col not in work.columns:
                work[col] = ""
            work[col] = work[col].fillna("").astype(str).str.strip()
        valid = work[source_cols + target_cols].apply(lambda col: col.map(_clean).ne("")).all(axis=1)
        work = work.loc[valid].copy()
        if work.empty:
            return pd.DataFrame(
                columns=[
                    "sheet_name",
                    "mapping_row_number",
                    *source_cols,
                    *target_cols,
                    "this_row_status",
                    "this_row_is_removed",
                    "this_row_is_duplicate_removed",
                ]
            )
        work["sheet_name"] = sheet_name
        work["mapping_row_number"] = work.index + 2
        work["this_row_is_removed"] = work["remove_row"].map(_truthy)
        work["this_row_is_duplicate_removed"] = work["duplicate_to_remove"].map(_truthy)
        work["this_row_status"] = work.apply(
            lambda row: "removed_row_true"
            if row["this_row_is_removed"]
            else "duplicate_removed_row_true"
            if row["this_row_is_duplicate_removed"]
            else "active",
            axis=1,
        )
        return work[
            [
                "sheet_name",
                "mapping_row_number",
                *source_cols,
                *target_cols,
                "this_row_status",
                "this_row_is_removed",
                "this_row_is_duplicate_removed",
            ]
        ].reset_index(drop=True)

    def _first_non_empty(series: pd.Series) -> str:
        values = [str(value).strip() for value in series.tolist() if _clean(value)]
        unique_values = list(dict.fromkeys(values))
        return " | ".join(unique_values)

    def _sheet_source_summary(frame: pd.DataFrame, sheet_name: str, target_cols: list[str]) -> pd.DataFrame:
        work = frame.copy().fillna("")
        for col in source_cols + target_cols + ["remove_row", "duplicate_to_remove"]:
            if col not in work.columns:
                work[col] = ""
            work[col] = work[col].fillna("").astype(str).str.strip()
        valid = work[source_cols + target_cols].apply(lambda col: col.map(_clean).ne("")).all(axis=1)
        work = work.loc[valid].copy()
        if work.empty:
            return pd.DataFrame(
                columns=[
                    *source_cols,
                    *target_cols,
                    f"{sheet_name}_active_row_count",
                    f"{sheet_name}_removed_row_count",
                    f"{sheet_name}_duplicate_removed_row_count",
                    f"{sheet_name}_presence_state",
                ]
            )
        work[f"{sheet_name}_is_active"] = ~work["remove_row"].map(_truthy) & ~work["duplicate_to_remove"].map(_truthy)
        work[f"{sheet_name}_is_removed"] = work["remove_row"].map(_truthy)
        work[f"{sheet_name}_is_duplicate_removed"] = work["duplicate_to_remove"].map(_truthy)
        grouped = (
            work.groupby(source_cols, as_index=False)
            .agg(
                **{
                    f"{sheet_name}_active_row_count": (f"{sheet_name}_is_active", "sum"),
                    f"{sheet_name}_removed_row_count": (f"{sheet_name}_is_removed", "sum"),
                    f"{sheet_name}_duplicate_removed_row_count": (f"{sheet_name}_is_duplicate_removed", "sum"),
                    **{col: (col, _first_non_empty) for col in target_cols},
                }
            )
            .reset_index(drop=True)
        )
        for col in [
            f"{sheet_name}_active_row_count",
            f"{sheet_name}_removed_row_count",
            f"{sheet_name}_duplicate_removed_row_count",
        ]:
            grouped[col] = pd.to_numeric(grouped[col], errors="coerce").fillna(0).astype(int)
        grouped[f"{sheet_name}_presence_state"] = grouped.apply(
            lambda row: "active"
            if row[f"{sheet_name}_active_row_count"] > 0
            else "removed_only"
            if row[f"{sheet_name}_removed_row_count"] > 0
            else "duplicate_removed_only"
            if row[f"{sheet_name}_duplicate_removed_row_count"] > 0
            else "missing",
            axis=1,
        )
        return grouped

    def _comparison_status(sheet_name: str, this_row_status: str, counterpart_presence_state: str) -> str:
        if this_row_status == "active" and counterpart_presence_state == "active":
            return "both_active"
        if sheet_name == "esto":
            if this_row_status == "active" and counterpart_presence_state in {"removed_only", "duplicate_removed_only"}:
                return "esto_active_ninth_removed"
            if this_row_status in {"removed_row_true", "duplicate_removed_row_true"} and counterpart_presence_state == "active":
                return "esto_removed_ninth_active"
            if this_row_status == "active" and counterpart_presence_state == "missing":
                return "esto_active_ninth_missing"
            if this_row_status in {"removed_row_true", "duplicate_removed_row_true"} and counterpart_presence_state == "missing":
                return "esto_removed_ninth_missing"
        if sheet_name == "ninth":
            if this_row_status == "active" and counterpart_presence_state in {"removed_only", "duplicate_removed_only"}:
                return "ninth_active_esto_removed"
            if this_row_status in {"removed_row_true", "duplicate_removed_row_true"} and counterpart_presence_state == "active":
                return "ninth_removed_esto_active"
            if this_row_status == "active" and counterpart_presence_state == "missing":
                return "ninth_active_esto_missing"
            if this_row_status in {"removed_row_true", "duplicate_removed_row_true"} and counterpart_presence_state == "missing":
                return "ninth_removed_esto_missing"
        if this_row_status in {"removed_row_true", "duplicate_removed_row_true"} and counterpart_presence_state in {"removed_only", "duplicate_removed_only"}:
            return "both_removed"
        if counterpart_presence_state == "missing":
            return "actually_missing"
        return "mixed"

    def _issue_side(comparison_status: str) -> str:
        if comparison_status == "both_active":
            return "both_active"
        if comparison_status == "both_removed":
            return "both_removed"
        if comparison_status in {"esto_removed_ninth_active", "esto_removed_ninth_missing"}:
            return "esto_removed"
        if comparison_status in {"ninth_removed_esto_active", "ninth_removed_esto_missing"}:
            return "ninth_removed"
        if comparison_status in {"esto_active_ninth_removed"}:
            return "ninth_removed"
        if comparison_status in {"ninth_active_esto_removed"}:
            return "esto_removed"
        if comparison_status in {"esto_active_ninth_missing"}:
            return "ninth_missing"
        if comparison_status in {"ninth_active_esto_missing"}:
            return "esto_missing"
        if comparison_status == "actually_missing":
            return "missing"
        return comparison_status

    esto_rows = _sheet_row_status(esto_sheet, "esto", ["esto_flow", "esto_product"])
    ninth_rows = _sheet_row_status(ninth_sheet, "ninth", ["ninth_sector", "ninth_fuel"])
    esto_summary = _sheet_source_summary(esto_sheet, "esto", ["esto_flow", "esto_product"])
    ninth_summary = _sheet_source_summary(ninth_sheet, "ninth", ["ninth_sector", "ninth_fuel"])

    esto_rows = esto_rows.merge(
        ninth_summary[source_cols + ["ninth_sector", "ninth_fuel", "ninth_presence_state"]],
        on=source_cols,
        how="left",
    )
    ninth_rows = ninth_rows.merge(
        esto_summary[source_cols + ["esto_flow", "esto_product", "esto_presence_state"]],
        on=source_cols,
        how="left",
    )

    esto_rows["counterpart_presence_state"] = esto_rows["ninth_presence_state"].fillna("missing")
    ninth_rows["counterpart_presence_state"] = ninth_rows["esto_presence_state"].fillna("missing")

    esto_rows["presence_status"] = esto_rows.apply(
        lambda row: _comparison_status("esto", row["this_row_status"], row["counterpart_presence_state"]),
        axis=1,
    )
    ninth_rows["presence_status"] = ninth_rows.apply(
        lambda row: _comparison_status("ninth", row["this_row_status"], row["counterpart_presence_state"]),
        axis=1,
    )

    for work in [esto_rows, ninth_rows]:
        work["comparison_status"] = work["presence_status"]
        work["row_status"] = work["this_row_status"]
        work["issue_side"] = work["comparison_status"].map(_issue_side)
        work["missing_reason"] = work["comparison_status"].map(lambda value: "" if value == "both_active" else value)
        work["has_removed_row"] = work["this_row_is_removed"]
        work["has_duplicate_removed_row"] = work["this_row_is_duplicate_removed"]

    combined = pd.concat([esto_rows, ninth_rows], ignore_index=True)
    combined["issue_side"] = combined.apply(
        lambda row: _issue_side(str(row.get("comparison_status", ""))),
        axis=1,
    )
    combined["is_issue_row"] = combined["comparison_status"].ne("both_active")

    return combined.sort_values(
        ["is_issue_row", "sheet_name", *source_cols, "mapping_row_number"],
        ascending=[False, True, True, True, True, True],
    ).reset_index(drop=True)


def _active_mapping_rows(frame: pd.DataFrame, target_cols: Sequence[str]) -> pd.DataFrame:
    """Return active rows with nonblank LEAP source and target columns."""
    source_cols = ["leap_sector_name_original", "leap_sector_name_full_path", "raw_leap_fuel_name"]
    work = frame.copy().fillna("")
    for col in [*source_cols, *target_cols, "remove_row", "duplicate_to_remove", "pair_mapping_cardinality"]:
        if col not in work.columns:
            work[col] = ""
        work[col] = work[col].fillna("").astype(str).str.strip()
    work["mapping_row_number"] = work.index + 2
    active = work[_active_mask(work)].copy()
    valid = active[["leap_sector_name_full_path", "raw_leap_fuel_name", *target_cols]].apply(
        lambda col: col.map(_clean).ne("")
    ).all(axis=1)
    return active.loc[valid].copy()


def _build_missing_between_sheet_conflicts(trio_presence: pd.DataFrame) -> pd.DataFrame:
    """Return active rows that are missing or removed in the counterpart sheet."""
    if trio_presence.empty:
        return pd.DataFrame()
    conflict_statuses = {
        "esto_active_ninth_missing",
        "ninth_active_esto_missing",
    }
    out = trio_presence[trio_presence["presence_status"].isin(conflict_statuses)].copy()
    if out.empty:
        return pd.DataFrame(
            columns=[
                "conflict_type",
                "sheet_name",
                "mapping_row_number",
                "presence_status",
                "leap_sector_name_full_path",
                "raw_leap_fuel_name",
                "esto_flow",
                "esto_product",
                "ninth_sector",
                "ninth_fuel",
                "counterpart_presence_state",
            ]
        )
    out.insert(0, "conflict_type", "active_mapping_missing_from_counterpart")
    keep_cols = [
        "conflict_type",
        "sheet_name",
        "mapping_row_number",
        "presence_status",
        "leap_sector_name_full_path",
        "raw_leap_fuel_name",
        "esto_flow",
        "esto_product",
        "ninth_sector",
        "ninth_fuel",
        "counterpart_presence_state",
    ]
    return out.loc[:, keep_cols].fillna("").reset_index(drop=True)


def _filter_researcher_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep rows that are not marked as removed, duplicate-removed, or faulty."""
    out = frame.copy()
    active = pd.Series(True, index=out.index)
    for col in ["remove_row", "duplicate_to_remove", "removed", "is_removed", "faulty mapping", "faulty_mapping"]:
        if col in out.columns:
            active &= ~out[col].map(_truthy)
    return out.loc[active].copy()


_ROLLUP_FLOW_RE = re.compile(
    r"^(\d{2}(?:\.\d{2})*(?:,\d{2}(?:\.\d{2})*)+)\s+(.+)$"
)


def _parse_esto_target_pairs(target_str: str) -> set[tuple[str, str]]:
    """Parse 'flow1 || product1 | flow2 || product2' into a set of (flow, product) tuples."""
    pairs: set[tuple[str, str]] = set()
    for entry in str(target_str or "").split(" | "):
        entry = entry.strip()
        if " || " in entry:
            flow, product = entry.split(" || ", 1)
            flow, product = flow.strip(), product.strip()
            if flow and product:
                pairs.add((flow, product))
    return pairs


def _expand_rollup_flow(flow: str) -> list[str] | None:
    """If flow is a rollup like '09.01.02,09.02.02 CHP plants', return the component flows.

    Returns None when the flow is not a multi-code rollup.
    """
    m = _ROLLUP_FLOW_RE.match(flow.strip())
    if not m:
        return None
    codes = m.group(1).split(",")
    suffix = m.group(2)
    return [f"{code} {suffix}" for code in codes] if len(codes) > 1 else None


def _rollup_covers_implied(active_targets_str: str, implied_targets_str: str) -> bool:
    """Return True when an active combined ESTO target covers all implied component targets.

    This detects the pattern where leap_combined_esto maps to a rollup
    (e.g. '09.01.02,09.02.02 CHP plants') while ninthpairs_to_esto maps to the
    individual components — both representations are equivalent, but the user
    should standardise on one.
    """
    implied = _parse_esto_target_pairs(implied_targets_str)
    if not implied:
        return False
    for flow, product in _parse_esto_target_pairs(active_targets_str):
        component_flows = _expand_rollup_flow(flow)
        if component_flows is None:
            continue
        if implied.issubset({(cf, product) for cf in component_flows}):
            return True
    return False


def _build_crosswalk_target_conflicts(
    esto_sheet: pd.DataFrame,
    ninth_sheet: pd.DataFrame,
    ninth_to_esto_pairs: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compare active LEAP mapping targets against master 9th -> ESTO pair mappings.

    A row is reported when an active 9th mapping for a LEAP source has no matching
    active ESTO target implied by ninth_pairs_to_esto_pairs. The conflict type is
    split by cardinality so strict one-to-one mismatches are separated from
    one-to-many / many-to-one rows that need review.
    """
    source_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    esto_sheet = _compute_pair_cardinality(esto_sheet, "esto_flow", "esto_product")
    ninth_sheet = _compute_pair_cardinality(ninth_sheet, "ninth_sector", "ninth_fuel")
    esto_active = _active_mapping_rows(esto_sheet, ["esto_flow", "esto_product"])
    ninth_active = _active_mapping_rows(ninth_sheet, ["ninth_sector", "ninth_fuel"])

    if esto_active.empty or ninth_active.empty:
        return pd.DataFrame(
            columns=[
                "conflict_type",
                "leap_sector_name_full_path",
                "raw_leap_fuel_name",
                "ninth_sector",
                "ninth_fuel",
                "implied_esto_targets",
                "active_esto_targets",
                "esto_cardinalities",
                "ninth_cardinality",
                "ninth_mapping_row_number",
            ]
        )

    pairs = _filter_researcher_rows(ninth_to_esto_pairs).copy().fillna("")
    for col in ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]:
        if col not in pairs.columns:
            pairs[col] = ""
        pairs[col] = pairs[col].fillna("").astype(str).str.strip()
    pairs = pairs[pairs[["9th_sector", "9th_fuel", "esto_flow", "esto_product"]].apply(lambda col: col.map(_clean).ne("")).all(axis=1)].copy()
    pairs = pairs.drop_duplicates(subset=["9th_sector", "9th_fuel", "esto_flow", "esto_product"])

    esto_targets = (
        esto_active.groupby(source_cols, as_index=False)
        .agg(
            active_esto_targets=(
                "esto_flow",
                lambda series: " | ".join(
                    sorted(
                        {
                            f"{flow} || {product}"
                            for flow, product in zip(
                                series.astype(str),
                                esto_active.loc[series.index, "esto_product"].astype(str),
                            )
                            if _clean(flow) and _clean(product)
                        }
                    )
                ),
            ),
            esto_cardinalities=(
                "pair_mapping_cardinality",
                lambda series: " | ".join(
                    sorted({str(value).strip() for value in series.tolist() if _clean(value)})
                ),
            ),
        )
    )
    active_esto_pairs = set(
        zip(
            esto_active["leap_sector_name_full_path"].astype(str),
            esto_active["raw_leap_fuel_name"].astype(str),
            esto_active["esto_flow"].astype(str),
            esto_active["esto_product"].astype(str),
        )
    )

    merged = ninth_active.merge(
        pairs,
        left_on=["ninth_sector", "ninth_fuel"],
        right_on=["9th_sector", "9th_fuel"],
        how="left",
    )
    merged["_ninth_row_key"] = merged["mapping_row_number"].astype(str)
    merged["has_master_pair"] = (
        merged["esto_flow"].fillna("").astype(str).str.strip().ne("")
        & merged["esto_product"].fillna("").astype(str).str.strip().ne("")
    )
    merged["has_matching_esto_target"] = merged.apply(
        lambda row: (
            row["leap_sector_name_full_path"],
            row["raw_leap_fuel_name"],
            row["esto_flow"],
            row["esto_product"],
        )
        in active_esto_pairs,
        axis=1,
    )

    def _joined_targets(group: pd.DataFrame) -> str:
        values = sorted(
            {
                f"{flow} || {product}"
                for flow, product in zip(group["esto_flow"].astype(str), group["esto_product"].astype(str))
                if _clean(flow) and _clean(product)
            }
        )
        return " | ".join(values)

    grouped = (
        merged.groupby("_ninth_row_key", as_index=False)
        .agg(
            leap_sector_name_full_path=("leap_sector_name_full_path", "first"),
            raw_leap_fuel_name=("raw_leap_fuel_name", "first"),
            ninth_sector=("ninth_sector", "first"),
            ninth_fuel=("ninth_fuel", "first"),
            ninth_cardinality=("pair_mapping_cardinality", "first"),
            ninth_mapping_row_number=("mapping_row_number", "first"),
            implied_esto_targets=("esto_flow", lambda series: _joined_targets(merged.loc[series.index])),
            has_master_pair=("has_master_pair", "max"),
            has_matching_esto_target=("has_matching_esto_target", "max"),
        )
        .reset_index(drop=True)
    )
    grouped = grouped.merge(esto_targets, on=source_cols, how="left")
    has_active_esto_target = grouped["active_esto_targets"].fillna("").astype(str).str.strip().ne("")
    conflicts = grouped[
        has_active_esto_target
        & (~grouped["has_master_pair"] | ~grouped["has_matching_esto_target"])
    ].copy()
    if conflicts.empty:
        return pd.DataFrame(
            columns=[
                "conflict_type",
                "leap_sector_name_full_path",
                "raw_leap_fuel_name",
                "ninth_sector",
                "ninth_fuel",
                "implied_esto_targets",
                "active_esto_targets",
                "esto_cardinalities",
                "ninth_cardinality",
                "ninth_mapping_row_number",
            ]
        )

    def _split_cardinalities(value: object) -> set[str]:
        return {part.strip() for part in str(value or "").split("|") if part.strip()}

    def _target_conflict_type(row: pd.Series) -> str:
        if not bool(row["has_master_pair"]):
            return "ninth_pair_missing_from_master_crosswalk"
        if _rollup_covers_implied(
            row.get("active_esto_targets", ""),
            row.get("implied_esto_targets", ""),
        ):
            return "rollup_covers_implied_components"
        esto_cardinalities = _split_cardinalities(row.get("esto_cardinalities", ""))
        ninth_cardinality = _clean(row.get("ninth_cardinality", ""))
        if esto_cardinalities == {"one_to_one"} and ninth_cardinality == "one_to_one":
            return "strict_one_to_one_target_mismatch"
        if "many_to_many" in esto_cardinalities or ninth_cardinality == "many_to_many":
            return "many_to_many_target_review"
        return "non_strict_cardinality_target_review"

    conflicts["conflict_type"] = conflicts.apply(
        _target_conflict_type,
        axis=1,
    )
    keep_cols = [
        "conflict_type",
        "leap_sector_name_full_path",
        "raw_leap_fuel_name",
        "ninth_sector",
        "ninth_fuel",
        "implied_esto_targets",
        "active_esto_targets",
        "esto_cardinalities",
        "ninth_cardinality",
        "ninth_mapping_row_number",
    ]
    return conflicts.loc[:, keep_cols].fillna("").drop_duplicates().reset_index(drop=True)


def _active_ninth_to_esto_pairs(ninth_to_esto_pairs: pd.DataFrame) -> pd.DataFrame:
    """Return active/non-faulty rows from master 9th -> ESTO pair mapping."""
    pairs = _filter_researcher_rows(ninth_to_esto_pairs).copy().fillna("")
    for col in ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]:
        if col not in pairs.columns:
            pairs[col] = ""
        pairs[col] = pairs[col].fillna("").astype(str).str.strip()
    pairs = pairs[
        pairs[["9th_sector", "9th_fuel", "esto_flow", "esto_product"]]
        .apply(lambda col: col.map(_clean).ne(""))
        .all(axis=1)
    ].copy()
    return pairs.drop_duplicates(subset=["9th_sector", "9th_fuel", "esto_flow", "esto_product"])


def _build_implied_missing_crosswalk_pairs(
    esto_sheet: pd.DataFrame,
    ninth_sheet: pd.DataFrame,
    ninth_to_esto_pairs: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build candidate ninth_pairs_to_esto_pairs rows implied by active LEAP mappings.

    The candidates are inferred by joining active leap_combined_ninth and
    leap_combined_esto rows on the same LEAP sector/fuel source pair, then
    removing exact pairs already present in ninth_pairs_to_esto_pairs.
    """
    columns = [
        "candidate_status",
        "would_create_many_to_many",
        "candidate_crosswalk_cardinality",
        "9th_sector",
        "9th_fuel",
        "esto_flow",
        "esto_product",
        "leap_sector_name_full_path",
        "raw_leap_fuel_name",
        "ninth_cardinality",
        "esto_cardinality",
        "ninth_mapping_row_number",
        "esto_mapping_row_number",
    ]
    source_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    esto_sheet = _compute_pair_cardinality(esto_sheet, "esto_flow", "esto_product")
    ninth_sheet = _compute_pair_cardinality(ninth_sheet, "ninth_sector", "ninth_fuel")
    esto_active = _active_mapping_rows(esto_sheet, ["esto_flow", "esto_product"])
    ninth_active = _active_mapping_rows(ninth_sheet, ["ninth_sector", "ninth_fuel"])
    if esto_active.empty or ninth_active.empty:
        return pd.DataFrame(columns=columns)

    esto_keep = [
        *source_cols,
        "esto_flow",
        "esto_product",
        "pair_mapping_cardinality",
        "mapping_row_number",
    ]
    ninth_keep = [
        *source_cols,
        "ninth_sector",
        "ninth_fuel",
        "pair_mapping_cardinality",
        "mapping_row_number",
    ]
    implied = ninth_active[ninth_keep].merge(
        esto_active[esto_keep],
        on=source_cols,
        how="inner",
        suffixes=("_ninth", "_esto"),
    )
    if implied.empty:
        return pd.DataFrame(columns=columns)

    implied = implied.rename(
        columns={
            "pair_mapping_cardinality_ninth": "ninth_cardinality",
            "pair_mapping_cardinality_esto": "esto_cardinality",
            "mapping_row_number_ninth": "ninth_mapping_row_number",
            "mapping_row_number_esto": "esto_mapping_row_number",
        }
    )
    master_pairs = _active_ninth_to_esto_pairs(ninth_to_esto_pairs)
    existing_keys = set(
        zip(
            master_pairs["9th_sector"].astype(str),
            master_pairs["9th_fuel"].astype(str),
            master_pairs["esto_flow"].astype(str),
            master_pairs["esto_product"].astype(str),
        )
    )
    implied["_pair_key"] = list(
        zip(
            implied["ninth_sector"].astype(str),
            implied["ninth_fuel"].astype(str),
            implied["esto_flow"].astype(str),
            implied["esto_product"].astype(str),
        )
    )
    implied = implied[~implied["_pair_key"].isin(existing_keys)].copy()
    if implied.empty:
        return pd.DataFrame(columns=columns)

    combined_pairs = pd.concat(
        [
            master_pairs.rename(columns={"9th_sector": "ninth_sector", "9th_fuel": "ninth_fuel"})[
                ["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]
            ],
            implied[["ninth_sector", "ninth_fuel", "esto_flow", "esto_product"]],
        ],
        ignore_index=True,
    ).drop_duplicates()
    combined_pairs["_source_key"] = combined_pairs["ninth_sector"].astype(str) + "|||" + combined_pairs["ninth_fuel"].astype(str)
    combined_pairs["_target_key"] = combined_pairs["esto_flow"].astype(str) + "|||" + combined_pairs["esto_product"].astype(str)
    source_count = combined_pairs.groupby("_source_key")["_target_key"].nunique()
    target_count = combined_pairs.groupby("_target_key")["_source_key"].nunique()

    implied["_source_key"] = implied["ninth_sector"].astype(str) + "|||" + implied["ninth_fuel"].astype(str)
    implied["_target_key"] = implied["esto_flow"].astype(str) + "|||" + implied["esto_product"].astype(str)
    implied["candidate_crosswalk_cardinality"] = implied.apply(
        lambda row: _mapping_cardinality(
            int(source_count.get(row["_source_key"], 0)),
            int(target_count.get(row["_target_key"], 0)),
        ),
        axis=1,
    )
    implied["would_create_many_to_many"] = implied["candidate_crosswalk_cardinality"].eq("many_to_many")
    implied["candidate_status"] = implied["would_create_many_to_many"].map(
        lambda value: "review_many_to_many_before_adding" if bool(value) else "candidate_to_add"
    )
    implied = implied.rename(columns={"ninth_sector": "9th_sector", "ninth_fuel": "9th_fuel"})
    return (
        implied.loc[:, columns]
        .fillna("")
        .drop_duplicates()
        .sort_values(["would_create_many_to_many", "9th_sector", "9th_fuel", "esto_flow", "esto_product"], ascending=[False, True, True, True, True])
        .reset_index(drop=True)
    )


def _build_many_to_many_conflicts(esto_sheet: pd.DataFrame, ninth_sheet: pd.DataFrame) -> pd.DataFrame:
    """Return active rows whose pair cardinality is many_to_many."""
    records: list[pd.DataFrame] = []
    sheet_specs = [
        ("leap_combined_esto", esto_sheet, ["esto_flow", "esto_product"]),
        ("leap_combined_ninth", ninth_sheet, ["ninth_sector", "ninth_fuel"]),
    ]
    source_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    for sheet_name, frame, target_cols in sheet_specs:
        work = _active_mapping_rows(frame, target_cols)
        if "pair_mapping_cardinality" not in work.columns:
            work = _compute_pair_cardinality(work, target_cols[0], target_cols[1])
        work = work[work["pair_mapping_cardinality"].fillna("").astype(str).str.strip().eq("many_to_many")].copy()
        if work.empty:
            continue
        work.insert(0, "conflict_type", "many_to_many_mapping")
        work.insert(1, "sheet_name", sheet_name)
        keep_cols = [
            "conflict_type",
            "sheet_name",
            "mapping_row_number",
            *source_cols,
            *target_cols,
            "pair_mapping_cardinality",
        ]
        records.append(work.loc[:, keep_cols])
    if not records:
        return pd.DataFrame(
            columns=[
                "conflict_type",
                "sheet_name",
                "mapping_row_number",
                "leap_sector_name_full_path",
                "raw_leap_fuel_name",
                "esto_flow",
                "esto_product",
                "ninth_sector",
                "ninth_fuel",
                "pair_mapping_cardinality",
            ]
        )
    return pd.concat(records, ignore_index=True).fillna("")


def build_mapping_conflict_report(
    esto_sheet: pd.DataFrame,
    ninth_sheet: pd.DataFrame,
    ninth_to_esto_pairs: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build conflict-check sheets for mapping maintenance."""
    trio_presence = _build_trio_presence_check(esto_sheet, ninth_sheet)
    many_to_many = _build_many_to_many_conflicts(esto_sheet, ninth_sheet)
    missing_between_sheets = _build_missing_between_sheet_conflicts(trio_presence)
    crosswalk_target_conflicts = _build_crosswalk_target_conflicts(
        esto_sheet,
        ninth_sheet,
        ninth_to_esto_pairs,
    )
    implied_missing_crosswalk = _build_implied_missing_crosswalk_pairs(
        esto_sheet,
        ninth_sheet,
        ninth_to_esto_pairs,
    )
    summary_records = [
        {"check_name": "many_to_many", "row_count": int(len(many_to_many))},
        {"check_name": "missing_between_sheets", "row_count": int(len(missing_between_sheets))},
        {"check_name": "crosswalk_target_conflicts", "row_count": int(len(crosswalk_target_conflicts))},
        {"check_name": "implied_missing_crosswalk", "row_count": int(len(implied_missing_crosswalk))},
    ]
    return {
        "summary": pd.DataFrame(summary_records),
        "many_to_many": many_to_many,
        "missing_between_sheets": missing_between_sheets,
        "crosswalk_target_conflicts": crosswalk_target_conflicts,
        "implied_missing_crosswalk": implied_missing_crosswalk,
    }


def _pair_cardinality_for_columns(
    frame: pd.DataFrame,
    *,
    source_cols: Sequence[str],
    target_cols: Sequence[str],
    cardinality_col: str = "cardinality",
) -> pd.DataFrame:
    """Add cardinality between source column pairs and target column pairs."""
    out = frame.copy()
    for col in [*source_cols, *target_cols]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()

    valid = pd.Series(True, index=out.index)
    for col in [*source_cols, *target_cols]:
        valid &= out[col].ne("")

    pairs = out.loc[valid, [*source_cols, *target_cols]].drop_duplicates().copy()
    if pairs.empty:
        out[cardinality_col] = ""
        return out

    pairs["_source_key"] = pairs[list(source_cols)].agg("|||".join, axis=1)
    pairs["_target_key"] = pairs[list(target_cols)].agg("|||".join, axis=1)
    source_count = pairs.groupby("_source_key")["_target_key"].nunique()
    target_count = pairs.groupby("_target_key")["_source_key"].nunique()

    out["_source_key"] = out[list(source_cols)].agg("|||".join, axis=1)
    out["_target_key"] = out[list(target_cols)].agg("|||".join, axis=1)
    out[cardinality_col] = ""
    out.loc[valid, cardinality_col] = out.loc[valid].apply(
        lambda row: _mapping_cardinality(
            int(source_count.get(row["_source_key"], 0)),
            int(target_count.get(row["_target_key"], 0)),
        ),
        axis=1,
    )
    return out.drop(columns=["_source_key", "_target_key"])


def _researcher_export_frame(
    frame: pd.DataFrame,
    *,
    column_rename: dict[str, str],
    include_name: bool = False,
) -> pd.DataFrame:
    """Return the narrow researcher-facing mapping columns."""
    out = _filter_researcher_rows(_drop_unnamed_columns(frame))
    out = out.rename(columns={old: new for old, new in column_rename.items() if old in out.columns})
    if "pair_mapping_cardinality" in out.columns and "cardinality" not in out.columns:
        out = out.rename(columns={"pair_mapping_cardinality": "cardinality"})
    if "sector_mapping_cardinality" in out.columns and "cardinality" not in out.columns:
        out = out.rename(columns={"sector_mapping_cardinality": "cardinality"})
    if "cardinality" not in out.columns:
        out["cardinality"] = ""

    requested_cols = ["9th_sector", "9th_fuel", "esto_flow", "esto_product", "leap_flow", "leap_product"]
    for col in requested_cols:
        if col not in out.columns:
            out[col] = ""

    final_cols = [*requested_cols, "cardinality"]
    if include_name and "name" in out.columns:
        final_cols.insert(-1, "name")
    out = out.loc[:, final_cols].copy()
    for col in out.columns:
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out.drop_duplicates().reset_index(drop=True)

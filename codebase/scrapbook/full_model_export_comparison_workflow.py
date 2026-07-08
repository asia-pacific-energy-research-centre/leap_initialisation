#%%
"""Compare two LEAP full model export workbooks and separate the useful diffs.

The comparison ignores row order, yearly value columns, Expression, Scenario,
Region, Method, and the lower-priority Units / Scale / Per... metadata columns.
It writes one main issues file for core branches, one separate file for
non-core branches, and a separate metadata report for Units / Scale / Per...
changes.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

import pandas as pd


#%%
# --- Stable configuration ---

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_EXPORT_PATH = REPO_ROOT / "data" / "full model export.xlsx"
DEFAULT_NEW_EXPORT_PATH = REPO_ROOT / "data" / "full model export new.xlsx"
DEFAULT_SHEET_NAME = "Export"
OUTPUT_DIR = REPO_ROOT / "outputs" / "full_model_export_comparison"

CORE_BRANCH_ROOTS = ("Demand", "Transformation", "Resources")
LOW_PRIORITY_METADATA_COLUMNS = ("Units", "Scale", "Per...")
IGNORED_VALUE_COLUMNS = ("Expression", "Scenario", "Region", "Method")
IGNORED_ID_COLUMNS = ("ScenarioID", "RegionID")
IGNORED_PREFIXES = ("Unnamed:",)


#%%
# --- Helpers ---

def _resolve(path: str | Path) -> Path:
    """Resolve a notebook-friendly path against the repository root."""
    candidate = Path(str(path).replace("\\", "/"))
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def _is_year_column(column_name: str) -> bool:
    text = str(column_name).strip()
    return len(text) == 4 and text.isdigit()


def _normalize_value(value: object) -> str:
    """Normalize a cell value so workbook comparisons are stable."""
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.12g}"
    return str(value).strip()


def _normalize_column_name(column_name: object) -> str:
    if isinstance(column_name, float) and column_name.is_integer():
        return str(int(column_name))
    return str(column_name).strip()


def _clean_branch_path(branch_path: object) -> str:
    return _normalize_value(branch_path).replace("/", "\\")


def _branch_root(branch_path: object) -> str:
    text = _clean_branch_path(branch_path)
    if not text:
        return ""
    return text.split("\\", 1)[0].strip()


def _branch_importance(branch_path: object) -> str:
    return "core" if _branch_root(branch_path) in CORE_BRANCH_ROOTS else "other"


def _join_unique(values: Iterable[object]) -> str:
    cleaned = sorted({_normalize_value(value) for value in values if _normalize_value(value)})
    return "|".join(cleaned)


def _read_export_workbook(path: str | Path, *, sheet_name: str = DEFAULT_SHEET_NAME) -> pd.DataFrame:
    workbook_path = _resolve(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Export workbook not found: {workbook_path}")

    data = pd.read_excel(
        workbook_path,
        sheet_name=sheet_name,
        header=2,
        dtype=object,
        engine="openpyxl",
    )
    data = data.copy()
    data.columns = [_normalize_column_name(column) for column in data.columns]
    data = data.drop(columns=[column for column in data.columns if column.startswith(IGNORED_PREFIXES)], errors="ignore")
    data = data.dropna(how="all").reset_index(drop=True)
    data["__source_row"] = data.index + 4
    return data


def _comparison_columns(data: pd.DataFrame) -> list[str]:
    """Return the columns used to compare two export rows."""
    excluded = set(IGNORED_VALUE_COLUMNS)
    excluded.update(LOW_PRIORITY_METADATA_COLUMNS)
    excluded.update(IGNORED_ID_COLUMNS)
    excluded.update(column for column in data.columns if _is_year_column(column))
    excluded.update(column for column in data.columns if column.startswith(IGNORED_PREFIXES))
    excluded.add("__source_row")
    return [column for column in data.columns if column not in excluded]


def _build_signature_frame(data: pd.DataFrame, comparison_columns: list[str]) -> pd.DataFrame:
    working = data.copy()
    working["__signature"] = working[comparison_columns].apply(
        lambda row: tuple(_normalize_value(value) for value in row),
        axis=1,
    )
    return working


def _representative_row(group: pd.DataFrame) -> pd.Series:
    """Pick the first row in a signature group for reporting."""
    return group.iloc[0]


def _format_signature_issue_row(
    *,
    representative_row: pd.Series,
    issue_type: str,
    old_count: int,
    new_count: int,
) -> dict[str, object]:
    row = {
        "issue_type": issue_type,
        "branch_importance": _branch_importance(representative_row.get("Branch Path", "")),
        "branch_root": _branch_root(representative_row.get("Branch Path", "")),
        "old_count": old_count,
        "new_count": new_count,
        "row_delta": new_count - old_count,
        "Branch Path": representative_row.get("Branch Path", ""),
        "Variable": representative_row.get("Variable", ""),
        "BranchID": representative_row.get("BranchID", ""),
        "VariableID": representative_row.get("VariableID", ""),
    }
    level_columns = [column for column in representative_row.index if str(column).startswith("Level ")]
    for column in sorted(level_columns, key=lambda value: (len(str(value)), str(value))):
        row[column] = representative_row.get(column, "")
    return row


def _compare_signature_counts(
    old_data: pd.DataFrame,
    new_data: pd.DataFrame,
    *,
    comparison_columns: list[str],
) -> pd.DataFrame:
    old_signature_frame = _build_signature_frame(old_data, comparison_columns)
    new_signature_frame = _build_signature_frame(new_data, comparison_columns)

    old_counts = Counter(old_signature_frame["__signature"])
    new_counts = Counter(new_signature_frame["__signature"])

    old_groups = {
        signature: group
        for signature, group in old_signature_frame.groupby("__signature", sort=False)
    }
    new_groups = {
        signature: group
        for signature, group in new_signature_frame.groupby("__signature", sort=False)
    }

    rows: list[dict[str, object]] = []
    all_signatures = set(old_counts) | set(new_counts)
    for signature in all_signatures:
        old_count = int(old_counts.get(signature, 0))
        new_count = int(new_counts.get(signature, 0))
        if old_count == new_count:
            continue
        issue_type = "row_added" if new_count > old_count else "row_removed"
        representative_group = new_groups.get(signature) if issue_type == "row_added" else old_groups.get(signature)
        if representative_group is None:
            representative_group = new_groups.get(signature) or old_groups.get(signature)
        representative_row = _representative_row(representative_group)
        rows.append(
            _format_signature_issue_row(
                representative_row=representative_row,
                issue_type=issue_type,
                old_count=old_count,
                new_count=new_count,
            )
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            by=["branch_importance", "branch_root", "Branch Path", "Variable", "issue_type"],
            kind="stable",
            ignore_index=True,
        )
    return result


def _compare_metadata(
    old_data: pd.DataFrame,
    new_data: pd.DataFrame,
) -> pd.DataFrame:
    """Compare Units / Scale / Per... for matching logical export rows."""
    key_columns = [
        column
        for column in ["Branch Path", "Variable", "Scenario", "Region"]
        if column in old_data.columns and column in new_data.columns
    ]
    metadata_columns = [column for column in LOW_PRIORITY_METADATA_COLUMNS if column in old_data.columns and column in new_data.columns]
    if not key_columns or not metadata_columns:
        return pd.DataFrame()

    old_keys = old_data[key_columns].copy()
    new_keys = new_data[key_columns].copy()
    old_keys["__join_key"] = old_keys[key_columns].apply(
        lambda row: tuple(_normalize_value(value) for value in row),
        axis=1,
    )
    new_keys["__join_key"] = new_keys[key_columns].apply(
        lambda row: tuple(_normalize_value(value) for value in row),
        axis=1,
    )

    old_groups = old_data.copy()
    new_groups = new_data.copy()
    old_groups["__join_key"] = old_keys["__join_key"]
    new_groups["__join_key"] = new_keys["__join_key"]

    old_group_map = {join_key: group for join_key, group in old_groups.groupby("__join_key", sort=False)}
    new_group_map = {join_key: group for join_key, group in new_groups.groupby("__join_key", sort=False)}
    common_keys = sorted(set(old_group_map) & set(new_group_map))

    rows: list[dict[str, object]] = []
    for join_key in common_keys:
        old_group = old_group_map[join_key]
        new_group = new_group_map[join_key]
        old_row = _representative_row(old_group)
        new_row = _representative_row(new_group)

        changed_columns = []
        for column in metadata_columns:
            old_values = _join_unique(old_group[column].tolist())
            new_values = _join_unique(new_group[column].tolist())
            if old_values != new_values:
                changed_columns.append(column)

        if not changed_columns:
            continue

        row = {
            "branch_importance": _branch_importance(old_row.get("Branch Path", "")),
            "branch_root": _branch_root(old_row.get("Branch Path", "")),
            "Branch Path": old_row.get("Branch Path", ""),
            "Variable": old_row.get("Variable", ""),
            "Scenario": old_row.get("Scenario", ""),
            "Region": old_row.get("Region", ""),
            "old_units_values": _join_unique(old_group["Units"].tolist()) if "Units" in old_group.columns else "",
            "new_units_values": _join_unique(new_group["Units"].tolist()) if "Units" in new_group.columns else "",
            "old_scale_values": _join_unique(old_group["Scale"].tolist()) if "Scale" in old_group.columns else "",
            "new_scale_values": _join_unique(new_group["Scale"].tolist()) if "Scale" in new_group.columns else "",
            "old_per_values": _join_unique(old_group["Per..."].tolist()) if "Per..." in old_group.columns else "",
            "new_per_values": _join_unique(new_group["Per..."].tolist()) if "Per..." in new_group.columns else "",
            "changed_columns": "|".join(changed_columns),
        }
        rows.append(row)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            by=["branch_importance", "branch_root", "Branch Path", "Variable"],
            kind="stable",
            ignore_index=True,
        )
    return result


def _duplicate_logical_keys(data: pd.DataFrame) -> pd.DataFrame:
    """Return duplicate Branch Path / Variable / Scenario / Region keys, if any."""
    key_columns = [column for column in ["Branch Path", "Variable", "Scenario", "Region"] if column in data.columns]
    if len(key_columns) != 4:
        return pd.DataFrame()
    duplicated = data[data.duplicated(subset=key_columns, keep=False)].copy()
    if duplicated.empty:
        return duplicated
    duplicated["branch_importance"] = duplicated["Branch Path"].map(_branch_importance)
    duplicated["branch_root"] = duplicated["Branch Path"].map(_branch_root)
    duplicated = duplicated.sort_values(
        by=["branch_importance", "branch_root", "Branch Path", "Variable", "Scenario", "Region"],
        kind="stable",
        ignore_index=True,
    )
    return duplicated


def _build_summary(
    *,
    old_data: pd.DataFrame,
    new_data: pd.DataFrame,
    old_signature_count: int,
    new_signature_count: int,
    signature_issues_all: pd.DataFrame,
    metadata_issues_all: pd.DataFrame,
    main_issues: pd.DataFrame,
    other_branch_issues: pd.DataFrame,
    metadata_issues: pd.DataFrame,
    other_branch_metadata_issues: pd.DataFrame,
    duplicate_keys_old: pd.DataFrame,
    duplicate_keys_new: pd.DataFrame,
) -> pd.DataFrame:
    summary_rows = [
        {"metric": "old_rows", "value": len(old_data)},
        {"metric": "new_rows", "value": len(new_data)},
        {"metric": "old_comparable_signatures", "value": old_signature_count},
        {"metric": "new_comparable_signatures", "value": new_signature_count},
        {"metric": "signature_issue_rows_all", "value": len(signature_issues_all)},
        {"metric": "main_issue_rows", "value": len(main_issues)},
        {"metric": "other_branch_issue_rows", "value": len(other_branch_issues)},
        {"metric": "metadata_issue_rows_all", "value": len(metadata_issues_all)},
        {"metric": "metadata_issue_rows", "value": len(metadata_issues)},
        {"metric": "other_branch_metadata_issue_rows_file", "value": len(other_branch_metadata_issues)},
        {"metric": "duplicate_logical_keys_old", "value": len(duplicate_keys_old)},
        {"metric": "duplicate_logical_keys_new", "value": len(duplicate_keys_new)},
        {"metric": "core_main_issue_rows", "value": int((signature_issues_all["branch_importance"] == "core").sum()) if not signature_issues_all.empty else 0},
        {"metric": "other_branch_main_issue_rows", "value": int((signature_issues_all["branch_importance"] == "other").sum()) if not signature_issues_all.empty else 0},
        {"metric": "core_metadata_issue_rows", "value": int((metadata_issues_all["branch_importance"] == "core").sum()) if not metadata_issues_all.empty else 0},
        {"metric": "other_branch_metadata_issue_rows", "value": int((metadata_issues_all["branch_importance"] == "other").sum()) if not metadata_issues_all.empty else 0},
    ]
    return pd.DataFrame(summary_rows)


def compare_full_model_exports(
    base_export_path: str | Path = DEFAULT_BASE_EXPORT_PATH,
    new_export_path: str | Path = DEFAULT_NEW_EXPORT_PATH,
    *,
    sheet_name: str = DEFAULT_SHEET_NAME,
    output_dir: str | Path = OUTPUT_DIR,
) -> dict[str, object]:
    """Compare two LEAP export workbooks and write the key report files."""
    base_path = _resolve(base_export_path)
    candidate_path = _resolve(new_export_path)
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    old_data = _read_export_workbook(base_path, sheet_name=sheet_name)
    new_data = _read_export_workbook(candidate_path, sheet_name=sheet_name)

    comparison_columns = _comparison_columns(old_data)
    old_signature_count = len(_build_signature_frame(old_data, comparison_columns).drop_duplicates("__signature"))
    new_signature_count = len(_build_signature_frame(new_data, comparison_columns).drop_duplicates("__signature"))

    signature_issues_all = _compare_signature_counts(old_data, new_data, comparison_columns=comparison_columns)
    metadata_issues_all = _compare_metadata(old_data, new_data)
    duplicate_keys_old = _duplicate_logical_keys(old_data)
    duplicate_keys_new = _duplicate_logical_keys(new_data)

    main_issues = signature_issues_all[signature_issues_all["branch_importance"] == "core"].copy() if not signature_issues_all.empty else signature_issues_all.copy()
    other_branch_issues = signature_issues_all[signature_issues_all["branch_importance"] == "other"].copy() if not signature_issues_all.empty else signature_issues_all.copy()

    metadata_issues = metadata_issues_all[metadata_issues_all["branch_importance"] == "core"].copy() if not metadata_issues_all.empty else metadata_issues_all.copy()
    other_branch_metadata_issues = metadata_issues_all[metadata_issues_all["branch_importance"] == "other"].copy() if not metadata_issues_all.empty else metadata_issues_all.copy()

    if not main_issues.empty:
        main_issues = main_issues.sort_values(
            by=["branch_root", "Branch Path", "Variable", "issue_type"],
            kind="stable",
            ignore_index=True,
        )

    if not other_branch_issues.empty:
        other_branch_issues = other_branch_issues.sort_values(
            by=["branch_root", "Branch Path", "Variable", "issue_type"],
            kind="stable",
            ignore_index=True,
        )

    if not metadata_issues.empty:
        metadata_issues = metadata_issues.sort_values(
            by=["branch_root", "Branch Path", "Variable"],
            kind="stable",
            ignore_index=True,
        )

    if not other_branch_metadata_issues.empty:
        other_branch_metadata_issues = other_branch_metadata_issues.sort_values(
            by=["branch_root", "Branch Path", "Variable"],
            kind="stable",
            ignore_index=True,
        )

    summary = _build_summary(
        old_data=old_data,
        new_data=new_data,
        old_signature_count=old_signature_count,
        new_signature_count=new_signature_count,
        signature_issues_all=signature_issues_all,
        metadata_issues_all=metadata_issues_all,
        main_issues=main_issues,
        other_branch_issues=other_branch_issues,
        metadata_issues=metadata_issues,
        other_branch_metadata_issues=other_branch_metadata_issues,
        duplicate_keys_old=duplicate_keys_old,
        duplicate_keys_new=duplicate_keys_new,
    )

    summary_path = output_path / "summary.csv"
    main_issues_path = output_path / "main_issues.csv"
    metadata_issues_path = output_path / "metadata_issues.csv"
    other_branch_issues_path = output_path / "other_branch_issues.csv"
    other_branch_metadata_issues_path = output_path / "other_branch_metadata_issues.csv"
    duplicate_old_path = output_path / "duplicate_logical_keys_old.csv"
    duplicate_new_path = output_path / "duplicate_logical_keys_new.csv"

    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    main_issues.to_csv(main_issues_path, index=False, encoding="utf-8-sig")
    metadata_issues.to_csv(metadata_issues_path, index=False, encoding="utf-8-sig")
    other_branch_issues.to_csv(other_branch_issues_path, index=False, encoding="utf-8-sig")
    other_branch_metadata_issues.to_csv(other_branch_metadata_issues_path, index=False, encoding="utf-8-sig")
    duplicate_keys_old.to_csv(duplicate_old_path, index=False, encoding="utf-8-sig")
    duplicate_keys_new.to_csv(duplicate_new_path, index=False, encoding="utf-8-sig")

    return {
        "base_path": base_path,
        "candidate_path": candidate_path,
        "output_dir": output_path,
        "summary": summary,
        "main_issues": main_issues,
        "metadata_issues": metadata_issues,
        "other_branch_issues": other_branch_issues,
        "other_branch_metadata_issues": other_branch_metadata_issues,
        "duplicate_keys_old": duplicate_keys_old,
        "duplicate_keys_new": duplicate_keys_new,
        "paths": {
            "summary": summary_path,
            "main_issues": main_issues_path,
            "metadata_issues": metadata_issues_path,
            "other_branch_issues": other_branch_issues_path,
            "other_branch_metadata_issues": other_branch_metadata_issues_path,
            "duplicate_keys_old": duplicate_old_path,
            "duplicate_keys_new": duplicate_new_path,
        },
    }


def print_comparison_summary(result: dict[str, object]) -> None:
    """Print a short console summary for notebook runs."""
    summary = result["summary"]
    assert isinstance(summary, pd.DataFrame)
    print("\n=== Full model export comparison summary ===")
    print(f"Base export: {result['base_path']}")
    print(f"New export:  {result['candidate_path']}")
    print(f"Output dir:  {result['output_dir']}")
    print(summary.to_string(index=False))
    print("\nFiles written:")
    for name, path in result["paths"].items():
        print(f"  {name}: {path}")


#%%
# --- Run configuration ---

RUN_COMPARISON = True
BASE_EXPORT_PATH = DEFAULT_BASE_EXPORT_PATH
NEW_EXPORT_PATH = DEFAULT_NEW_EXPORT_PATH
SHEET_NAME = DEFAULT_SHEET_NAME
OUTPUT_DIRECTORY = OUTPUT_DIR


#%%
# --- Run ---

if RUN_COMPARISON:
    comparison_result = compare_full_model_exports(
        BASE_EXPORT_PATH,
        NEW_EXPORT_PATH,
        sheet_name=SHEET_NAME,
        output_dir=OUTPUT_DIRECTORY,
    )
    print_comparison_summary(comparison_result)

#%%

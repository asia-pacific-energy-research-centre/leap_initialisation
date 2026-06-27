#%%
"""Compare generated LEAP baseline seeds with a reviewed backup set.

The comparison keeps structural, metadata, expression, duplicate-key, and
share-total findings separate so a difference is visible without being
automatically classified as a modelling error.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from codebase.functions.leap_expressions import parse_expression


# --- Stable configuration ---

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGICAL_KEY_COLUMNS = ["Branch Path", "Variable", "Scenario", "Region"]
ID_COLUMNS = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
IGNORED_COLUMNS = {"Unnamed: 12"}
SHARE_VARIABLES = {
    "Output Share",
    "Process Share",
    "Feedstock Fuel Share",
}
SEED_FILE_PATTERN = "leap_import_baseline_seed_*.xlsx"
ECONOMY_PATTERN = re.compile(r"leap_import_baseline_seed_(\d{2}_[A-Za-z]+)_")


@dataclass(frozen=True)
class ComparisonOutputs:
    output_dir: Path
    file_inventory_csv: Path
    summary_csv: Path
    row_differences_csv: Path
    expression_differences_csv: Path
    duplicate_keys_csv: Path
    share_sum_checks_csv: Path


def _resolve(path: str | Path) -> Path:
    """Resolve notebook-provided paths against the repository root."""
    normalized = Path(str(path).replace("\\", "/"))
    if normalized.is_absolute():
        return normalized
    return REPO_ROOT / normalized


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _economy_from_filename(path: Path) -> str:
    match = ECONOMY_PATTERN.search(path.name)
    if not match:
        raise ValueError(f"Could not identify economy from seed filename: {path.name}")
    return match.group(1).upper()


def discover_seed_files(directory: str | Path) -> dict[str, Path]:
    """Return one baseline-seed workbook per economy.

    Multiple files for one economy are rejected instead of silently selecting a
    dated version. The workflow normally archives old seeds before writing a new
    one, so multiple active files indicate an ambiguous comparison input.
    """
    directory_path = _resolve(directory)
    if not directory_path.exists():
        raise FileNotFoundError(f"Seed directory does not exist: {directory_path}")

    grouped: dict[str, list[Path]] = {}
    for path in sorted(directory_path.glob(SEED_FILE_PATTERN)):
        grouped.setdefault(_economy_from_filename(path), []).append(path)

    duplicates = {economy: paths for economy, paths in grouped.items() if len(paths) > 1}
    if duplicates:
        details = "; ".join(
            f"{economy}: {[path.name for path in paths]}"
            for economy, paths in sorted(duplicates.items())
        )
        raise ValueError(f"Multiple active seed files found for an economy. {details}")
    return {economy: paths[0] for economy, paths in grouped.items()}


def read_seed_workbook(path: str | Path, sheet_name: str = "LEAP") -> pd.DataFrame:
    """Read the LEAP data rows while retaining their original Excel row number."""
    workbook_path = _resolve(path)
    data = pd.read_excel(
        workbook_path,
        sheet_name=sheet_name,
        header=2,
        dtype=object,
        engine="openpyxl",
        engine_kwargs={"read_only": True, "data_only": False},
    )
    data.columns = [str(column).strip() for column in data.columns]
    data = data.drop(columns=[column for column in data.columns if column in IGNORED_COLUMNS], errors="ignore")
    missing = [column for column in LOGICAL_KEY_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"{workbook_path.name} is missing LEAP key columns: {missing}")

    data = data.dropna(how="all").copy()
    data["source_excel_row"] = data.index + 4
    return data.reset_index(drop=True)


def _expression_signature(value: object) -> tuple[str, str]:
    raw = _text(value)
    mode, payload = parse_expression(value)
    kind = mode
    if mode == "series":
        stripped = raw.lstrip().lower()
        kind = "interp" if stripped.startswith("interp(") else "data"
        series = payload if isinstance(payload, dict) else {}
        canonical = "|".join(f"{int(year)}={float(number):.12g}" for year, number in sorted(series.items()))
        return kind, canonical
    if mode == "const" and payload is not None:
        return kind, f"{float(payload):.12g}"
    return kind, raw


def _normalized_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.12g}"
    return str(value).strip()


def _prepare_rows(data: pd.DataFrame) -> pd.DataFrame:
    prepared = data.copy()
    for column in LOGICAL_KEY_COLUMNS:
        prepared[f"__key_{column}"] = prepared[column].map(_normalized_cell)

    available_id_columns = [column for column in ID_COLUMNS if column in prepared.columns]
    if available_id_columns:
        prepared["__invalid_id_count"] = prepared[available_id_columns].apply(
            lambda row: sum(
                pd.to_numeric(value, errors="coerce") < 0
                for value in row
                if not pd.isna(value)
            ),
            axis=1,
        )
    else:
        prepared["__invalid_id_count"] = 0
    sort_columns = ["__invalid_id_count"] + available_id_columns
    sort_columns += [
        column
        for column in prepared.columns
        if column not in {"Expression", "source_excel_row"}
        and not column.startswith("__key_")
        and column not in LOGICAL_KEY_COLUMNS
        and column not in sort_columns
    ]
    prepared["__expression_sort"] = prepared.get("Expression", pd.Series("", index=prepared.index)).map(
        lambda value: _expression_signature(value)[1]
    )
    sort_columns += ["__expression_sort", "source_excel_row"]
    key_helpers = [f"__key_{column}" for column in LOGICAL_KEY_COLUMNS]
    prepared = prepared.sort_values(key_helpers + sort_columns, kind="stable", na_position="first")
    prepared["duplicate_ordinal"] = prepared.groupby(key_helpers, dropna=False).cumcount() + 1
    prepared["duplicate_count"] = prepared.groupby(key_helpers, dropna=False)[key_helpers[0]].transform("size")
    return prepared.reset_index(drop=True)


def _compare_expression_values(
    reference_value: object,
    candidate_value: object,
    *,
    tolerance: float,
) -> tuple[bool, list[dict[str, object]], str, str]:
    reference_kind, reference_signature = _expression_signature(reference_value)
    candidate_kind, candidate_signature = _expression_signature(candidate_value)
    reference_mode, reference_payload = parse_expression(reference_value)
    candidate_mode, candidate_payload = parse_expression(candidate_value)

    details: list[dict[str, object]] = []
    if reference_mode == "series" and candidate_mode == "series":
        reference_series = reference_payload if isinstance(reference_payload, dict) else {}
        candidate_series = candidate_payload if isinstance(candidate_payload, dict) else {}
        for year in sorted(set(reference_series) | set(candidate_series)):
            reference_number = reference_series.get(year)
            candidate_number = candidate_series.get(year)
            if reference_number is None:
                status = "candidate_year_only"
                difference = pd.NA
            elif candidate_number is None:
                status = "reference_year_only"
                difference = pd.NA
            else:
                difference = float(candidate_number) - float(reference_number)
                status = "same" if abs(difference) <= tolerance else "changed"
            if status != "same":
                details.append(
                    {
                        "year": int(year),
                        "reference_value": reference_number,
                        "candidate_value": candidate_number,
                        "difference": difference,
                        "status": status,
                    }
                )
        if not details and reference_kind != candidate_kind:
            details.append(
                {
                    "year": pd.NA,
                    "reference_value": _text(reference_value),
                    "candidate_value": _text(candidate_value),
                    "difference": pd.NA,
                    "status": "expression_kind_changed",
                }
            )
        same = not details
        return same, details, reference_kind, candidate_kind

    if reference_mode == "const" and candidate_mode == "const":
        difference = float(candidate_payload) - float(reference_payload)
        same = abs(difference) <= tolerance
        if not same:
            details.append(
                {
                    "year": pd.NA,
                    "reference_value": float(reference_payload),
                    "candidate_value": float(candidate_payload),
                    "difference": difference,
                    "status": "changed",
                }
            )
        return same, details, reference_kind, candidate_kind

    same = reference_kind == candidate_kind and reference_signature == candidate_signature
    if not same:
        details.append(
            {
                "year": pd.NA,
                "reference_value": _text(reference_value),
                "candidate_value": _text(candidate_value),
                "difference": pd.NA,
                "status": "expression_form_changed",
            }
        )
    return same, details, reference_kind, candidate_kind


def _duplicate_key_rows(data: pd.DataFrame, economy: str, source: str, file_path: Path) -> list[dict[str, object]]:
    prepared = _prepare_rows(data)
    duplicates = prepared[prepared["duplicate_count"] > 1]
    rows: list[dict[str, object]] = []
    helper_columns = [f"__key_{column}" for column in LOGICAL_KEY_COLUMNS]
    for key, group in duplicates.groupby(helper_columns, dropna=False, sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        expression_counts = Counter(_expression_signature(value) for value in group.get("Expression", pd.Series(dtype=object)))
        duplicate_details = []
        for _, duplicate_row in group.sort_values("source_excel_row").iterrows():
            duplicate_details.append(
                {
                    "source_excel_row": int(duplicate_row["source_excel_row"]),
                    **{
                        column: _normalized_cell(duplicate_row.get(column, pd.NA))
                        for column in ID_COLUMNS
                        if column in duplicate_row.index
                    },
                    "expression": _text(duplicate_row.get("Expression", pd.NA)),
                }
            )
        row = {
            "economy": economy,
            "source": source,
            "file": str(file_path),
            "duplicate_count": len(group),
            "distinct_expression_count": len(expression_counts),
            "source_excel_rows": ",".join(str(int(value)) for value in group["source_excel_row"]),
            "duplicate_rows": json.dumps(duplicate_details, ensure_ascii=False),
        }
        row.update(dict(zip(LOGICAL_KEY_COLUMNS, key_values)))
        rows.append(row)
    return rows


def compare_seed_tables(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    economy: str,
    reference_file: Path,
    candidate_file: Path,
    numeric_tolerance: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Compare two workbooks after deterministic pairing of duplicate logical keys."""
    reference_prepared = _prepare_rows(reference).add_prefix("reference__")
    candidate_prepared = _prepare_rows(candidate).add_prefix("candidate__")
    join_columns = [f"__key_{column}" for column in LOGICAL_KEY_COLUMNS] + ["duplicate_ordinal"]
    left_on = [f"reference__{column}" for column in join_columns]
    right_on = [f"candidate__{column}" for column in join_columns]
    merged = reference_prepared.merge(
        candidate_prepared,
        how="outer",
        left_on=left_on,
        right_on=right_on,
        indicator=True,
        sort=True,
    )

    comparable_columns = sorted(
        (
            set(reference.columns)
            | set(candidate.columns)
        )
        - {"Expression", "source_excel_row"}
    )
    row_differences: list[dict[str, object]] = []
    expression_differences: list[dict[str, object]] = []
    counts = Counter()

    def _row_snapshot(row: pd.Series, prefix: str, present: bool) -> str:
        if not present:
            return ""
        snapshot = {
            column: _normalized_cell(row.get(f"{prefix}{column}", pd.NA))
            for column in sorted((set(reference.columns) | set(candidate.columns)) - {"source_excel_row"})
        }
        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    for _, row in merged.iterrows():
        merge_state = row["_merge"]
        reference_present = merge_state in {"both", "left_only"}
        candidate_present = merge_state in {"both", "right_only"}
        key_data = {
            column: row.get(f"reference____key_{column}") if reference_present else row.get(f"candidate____key_{column}")
            for column in LOGICAL_KEY_COLUMNS
        }
        ordinal = row.get("reference__duplicate_ordinal") if reference_present else row.get("candidate__duplicate_ordinal")
        common = {
            "economy": economy,
            **key_data,
            "duplicate_ordinal": int(ordinal),
            "reference_excel_row": row.get("reference__source_excel_row", pd.NA),
            "candidate_excel_row": row.get("candidate__source_excel_row", pd.NA),
        }

        if merge_state != "both":
            status = "reference_only" if merge_state == "left_only" else "candidate_only"
            counts[status] += 1
            row_differences.append(
                {
                    **common,
                    "status": status,
                    "changed_columns": "",
                    "expression_changed": pd.NA,
                    "reference_row": _row_snapshot(row, "reference__", reference_present),
                    "candidate_row": _row_snapshot(row, "candidate__", candidate_present),
                }
            )
            continue

        changed_columns = []
        metadata_changes: dict[str, dict[str, str]] = {}
        for column in comparable_columns:
            reference_cell = row.get(f"reference__{column}", pd.NA)
            candidate_cell = row.get(f"candidate__{column}", pd.NA)
            if _normalized_cell(reference_cell) != _normalized_cell(candidate_cell):
                changed_columns.append(column)
                metadata_changes[column] = {
                    "reference": _normalized_cell(reference_cell),
                    "candidate": _normalized_cell(candidate_cell),
                }

        expression_same, expression_details, reference_kind, candidate_kind = _compare_expression_values(
            row.get("reference__Expression", pd.NA),
            row.get("candidate__Expression", pd.NA),
            tolerance=numeric_tolerance,
        )
        for detail in expression_details:
            expression_differences.append(
                {
                    **common,
                    "reference_expression_kind": reference_kind,
                    "candidate_expression_kind": candidate_kind,
                    **detail,
                }
            )

        if changed_columns or not expression_same:
            if changed_columns and not expression_same:
                status = "metadata_and_expression_changed"
            elif changed_columns:
                status = "metadata_changed"
            else:
                status = "expression_changed"
            counts[status] += 1
            row_differences.append(
                {
                    **common,
                    "status": status,
                    "changed_columns": "|".join(changed_columns),
                    "metadata_changes": json.dumps(metadata_changes, ensure_ascii=False, sort_keys=True),
                    "expression_changed": not expression_same,
                    "reference_expression": _text(row.get("reference__Expression", pd.NA)),
                    "candidate_expression": _text(row.get("candidate__Expression", pd.NA)),
                    "reference_row": _row_snapshot(row, "reference__", True),
                    "candidate_row": _row_snapshot(row, "candidate__", True),
                }
            )
        else:
            counts["same"] += 1

    summary = {
        "economy": economy,
        "reference_file": str(reference_file),
        "candidate_file": str(candidate_file),
        "reference_rows": len(reference),
        "candidate_rows": len(candidate),
        "same_rows": counts["same"],
        "reference_only_rows": counts["reference_only"],
        "candidate_only_rows": counts["candidate_only"],
        "metadata_changed_rows": counts["metadata_changed"],
        "expression_changed_rows": counts["expression_changed"],
        "metadata_and_expression_changed_rows": counts["metadata_and_expression_changed"],
        "expression_difference_details": len(expression_differences),
    }
    return pd.DataFrame(row_differences), pd.DataFrame(expression_differences), summary


def _share_group_path(branch_path: object, variable: str) -> str:
    parts = [part.strip() for part in _text(branch_path).split("\\") if part.strip()]
    if len(parts) < 2:
        return _text(branch_path)
    if variable in SHARE_VARIABLES:
        return "\\".join(parts[:-1])
    return _text(branch_path)


def build_share_sum_checks(
    data: pd.DataFrame,
    *,
    economy: str,
    source: str,
    file_path: Path,
    tolerance: float,
) -> pd.DataFrame:
    """Audit sibling Output, Process, and Feedstock Fuel shares against 100."""
    share_rows = data[data["Variable"].map(_text).isin(SHARE_VARIABLES)].copy()
    if share_rows.empty:
        return pd.DataFrame()

    share_rows["share_group_path"] = share_rows.apply(
        lambda row: _share_group_path(row["Branch Path"], _text(row["Variable"])), axis=1
    )
    group_columns = ["share_group_path", "Variable", "Scenario", "Region"]
    results: list[dict[str, object]] = []

    for group_key, group in share_rows.groupby(group_columns, dropna=False, sort=True):
        path, variable, scenario, region = group_key
        logical_groups = list(group.groupby(LOGICAL_KEY_COLUMNS, dropna=False, sort=True))
        all_years: set[int] = set()
        parsed_rows: list[tuple[str, object, int]] = []
        ambiguous_keys = 0
        empty_keys = 0
        unknown_keys = 0

        for _, logical_group in logical_groups:
            signatures = {_expression_signature(value) for value in logical_group["Expression"]}
            if len(signatures) > 1:
                ambiguous_keys += 1
            chosen = logical_group.sort_values("source_excel_row").iloc[-1]
            mode, payload = parse_expression(chosen["Expression"])
            if mode == "series" and isinstance(payload, dict):
                all_years.update(int(year) for year in payload)
            elif mode == "empty":
                empty_keys += 1
            elif mode == "unknown":
                unknown_keys += 1
            parsed_rows.append((mode, payload, int(chosen["source_excel_row"])))

        years: list[int | None] = sorted(all_years) if all_years else [None]
        for year in years:
            values: list[float] = []
            missing_value_count = 0
            for mode, payload, _ in parsed_rows:
                if mode == "const" and payload is not None:
                    values.append(float(payload))
                elif mode == "series" and isinstance(payload, dict) and year is not None and year in payload:
                    values.append(float(payload[year]))
                else:
                    missing_value_count += 1

            share_sum = sum(values) if values else pd.NA
            delta = float(share_sum) - 100.0 if values else pd.NA
            if ambiguous_keys or unknown_keys:
                status = "review_ambiguous_expression"
            elif missing_value_count:
                status = "review_missing_share_value"
            elif abs(float(delta)) <= tolerance:
                status = "pass"
            else:
                status = "fail_not_100"
            results.append(
                {
                    "economy": economy,
                    "source": source,
                    "file": str(file_path),
                    "share_group_path": path,
                    "variable": variable,
                    "scenario": scenario,
                    "region": region,
                    "year": year,
                    "share_sum": share_sum,
                    "difference_from_100": delta,
                    "share_leaf_count": len(logical_groups),
                    "evaluated_leaf_count": len(values),
                    "duplicate_logical_key_count": sum(len(item) > 1 for _, item in logical_groups),
                    "ambiguous_logical_key_count": ambiguous_keys,
                    "empty_expression_count": empty_keys,
                    "unknown_expression_count": unknown_keys,
                    "status": status,
                }
            )
    return pd.DataFrame(results)


def run_baseline_seed_comparison(
    reference_dir: str | Path,
    candidate_dir: str | Path,
    output_dir: str | Path,
    *,
    economies: Iterable[str] | None = None,
    numeric_tolerance: float = 1e-9,
    share_tolerance: float = 1e-6,
) -> ComparisonOutputs:
    """Compare every economy available in either directory and write CSV diagnostics."""
    reference_files = discover_seed_files(reference_dir)
    candidate_files = discover_seed_files(candidate_dir)
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    inventory_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    row_difference_frames: list[pd.DataFrame] = []
    expression_difference_frames: list[pd.DataFrame] = []
    duplicate_rows: list[dict[str, object]] = []
    share_frames: list[pd.DataFrame] = []

    requested_economies = {str(economy).strip().upper() for economy in economies or []}
    available_economies = set(reference_files) | set(candidate_files)
    if requested_economies:
        unknown = requested_economies - available_economies
        if unknown:
            raise ValueError(f"Requested economies have no seed file in either directory: {sorted(unknown)}")
        comparison_economies = requested_economies
    else:
        comparison_economies = available_economies

    for economy in sorted(comparison_economies):
        reference_file = reference_files.get(economy)
        candidate_file = candidate_files.get(economy)
        inventory_status = "paired"
        if reference_file is None:
            inventory_status = "candidate_only"
        elif candidate_file is None:
            inventory_status = "reference_only"
        inventory_rows.append(
            {
                "economy": economy,
                "status": inventory_status,
                "reference_file": str(reference_file or ""),
                "candidate_file": str(candidate_file or ""),
            }
        )
        if reference_file is None or candidate_file is None:
            continue

        reference_data = read_seed_workbook(reference_file)
        if reference_file.resolve() == candidate_file.resolve():
            candidate_data = reference_data.copy()
        else:
            candidate_data = read_seed_workbook(candidate_file)
        row_diff, expression_diff, summary = compare_seed_tables(
            reference_data,
            candidate_data,
            economy=economy,
            reference_file=reference_file,
            candidate_file=candidate_file,
            numeric_tolerance=numeric_tolerance,
        )
        summary_rows.append(summary)
        if not row_diff.empty:
            row_difference_frames.append(row_diff)
        if not expression_diff.empty:
            expression_difference_frames.append(expression_diff)

        duplicate_rows.extend(_duplicate_key_rows(reference_data, economy, "reference", reference_file))
        duplicate_rows.extend(_duplicate_key_rows(candidate_data, economy, "candidate", candidate_file))
        share_frames.append(
            build_share_sum_checks(
                reference_data,
                economy=economy,
                source="reference",
                file_path=reference_file,
                tolerance=share_tolerance,
            )
        )
        share_frames.append(
            build_share_sum_checks(
                candidate_data,
                economy=economy,
                source="candidate",
                file_path=candidate_file,
                tolerance=share_tolerance,
            )
        )

    paths = ComparisonOutputs(
        output_dir=output_path,
        file_inventory_csv=output_path / "file_inventory.csv",
        summary_csv=output_path / "comparison_summary.csv",
        row_differences_csv=output_path / "row_differences.csv",
        expression_differences_csv=output_path / "expression_differences.csv",
        duplicate_keys_csv=output_path / "duplicate_keys.csv",
        share_sum_checks_csv=output_path / "share_sum_checks.csv",
    )
    pd.DataFrame(inventory_rows).to_csv(paths.file_inventory_csv, index=False)
    pd.DataFrame(summary_rows).to_csv(paths.summary_csv, index=False)
    pd.concat(row_difference_frames, ignore_index=True).to_csv(paths.row_differences_csv, index=False) if row_difference_frames else pd.DataFrame().to_csv(paths.row_differences_csv, index=False)
    pd.concat(expression_difference_frames, ignore_index=True).to_csv(paths.expression_differences_csv, index=False) if expression_difference_frames else pd.DataFrame().to_csv(paths.expression_differences_csv, index=False)
    pd.DataFrame(duplicate_rows).to_csv(paths.duplicate_keys_csv, index=False)
    nonempty_share_frames = [frame for frame in share_frames if not frame.empty]
    pd.concat(nonempty_share_frames, ignore_index=True).to_csv(paths.share_sum_checks_csv, index=False) if nonempty_share_frames else pd.DataFrame().to_csv(paths.share_sum_checks_csv, index=False)
    return paths


# --- Frequently changed notebook settings ---

REFERENCE_SEED_DIR = REPO_ROOT / "data" / "backup_tgt_ref_ca_20260625"
CANDIDATE_SEED_DIR = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"
COMPARISON_OUTPUT_DIR = CANDIDATE_SEED_DIR / "supporting_files" / "baseline_seed_comparison"
RUN_COMPARISON = False
ECONOMIES_TO_COMPARE: list[str] | None = None  # Example: ["20_USA"]


#%%
if RUN_COMPARISON:
    COMPARISON_OUTPUTS = run_baseline_seed_comparison(
        reference_dir=REFERENCE_SEED_DIR,
        candidate_dir=CANDIDATE_SEED_DIR,
        output_dir=COMPARISON_OUTPUT_DIR,
        economies=ECONOMIES_TO_COMPARE,
    )
    print(f"[OK] Baseline seed comparison written to {COMPARISON_OUTPUTS.output_dir}")

#%%

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

import re

from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.utilities.workflow_utils import _resolve
from codebase.utilities import workflow_common
from codebase.supply_reconciliation_utils import _normalize_label_for_lookup
from codebase.supply_reconciliation_history import (
    _build_results_signature,
    _results_signature_state_key,
    _state_token,
)

def _parse_year_column_token(value: object) -> int | None:
    """Parse an integer year from sheet column headers like 2030 or 2030.0."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        return None
    year = int(text)
    if year < BASE_YEAR or year > FINAL_YEAR:
        return None
    return year


def _find_supply_results_header_row(raw: pd.DataFrame) -> int:
    """Return the header row index for LEAP results-table sheets."""
    for idx in range(len(raw.index)):
        row_values = [str(item or "").strip().lower() for item in raw.iloc[idx].tolist()]
        if "fuel" in row_values:
            return int(idx)
    raise ValueError("Could not locate 'Fuel' header row in supply results table.")


def _read_supply_results_trade_sheet(
    workbook_path: Path,
    sheet_name: str,
    economy: str,
    scenario: str,
    label_to_product: dict[str, str],
    value_field: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Read one supply results trade sheet into economy/scenario/product/year rows."""
    raw = pd.read_excel(workbook_path, sheet_name=sheet_name, header=None)
    header_row = _find_supply_results_header_row(raw)
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = raw.iloc[header_row].tolist()
    if "Fuel" not in data.columns:
        raise ValueError(
            f"Workbook '{workbook_path.name}' sheet '{sheet_name}' missing 'Fuel' column."
        )

    year_columns: list[tuple[object, int]] = []
    for column in data.columns:
        year = _parse_year_column_token(column)
        if year is not None:
            year_columns.append((column, year))
    if not year_columns:
        raise ValueError(
            f"Workbook '{workbook_path.name}' sheet '{sheet_name}' has no {BASE_YEAR}-{FINAL_YEAR} year columns."
        )

    rows: list[dict[str, object]] = []
    unmapped_fuels: set[str] = set()
    for _, row in data.iterrows():
        fuel_label = str(row.get("Fuel") or "").strip()
        if not fuel_label:
            continue
        fuel_lookup = (
            label_to_product.get(fuel_label)
            or label_to_product.get(fuel_label.lower())
            or label_to_product.get(_normalize_label_for_lookup(fuel_label))
        )
        if not fuel_lookup:
            unmapped_fuels.add(fuel_label)
            continue
        for col, year in year_columns:
            numeric = pd.to_numeric(row.get(col), errors="coerce")
            if pd.isna(numeric):
                continue
            rows.append(
                {
                    "economy": str(economy),
                    "scenario": str(scenario),
                    "esto_product": str(fuel_lookup),
                    "year": int(year),
                    value_field: max(float(numeric), 0.0),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["economy", "scenario", "esto_product", "year", value_field]
        ), sorted(unmapped_fuels)
    out = (
        pd.DataFrame(rows)
        .groupby(
            ["economy", "scenario", "esto_product", "year"],
            as_index=False,
            dropna=False,
        )[value_field]
        .sum(min_count=1)
    )
    return out, sorted(unmapped_fuels)


def _read_supply_results_import_sheet(
    workbook_path: Path,
    sheet_name: str,
    economy: str,
    scenario: str,
    label_to_product: dict[str, str],
) -> tuple[pd.DataFrame, list[str]]:
    """Read one supply results imports sheet into economy/scenario/product/year rows."""
    return _read_supply_results_trade_sheet(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        economy=economy,
        scenario=scenario,
        label_to_product=label_to_product,
        value_field="observed_imports",
    )


def _read_supply_results_export_sheet(
    workbook_path: Path,
    sheet_name: str,
    economy: str,
    scenario: str,
    label_to_product: dict[str, str],
) -> tuple[pd.DataFrame, list[str]]:
    """Read one supply results exports sheet into economy/scenario/product/year rows."""
    return _read_supply_results_trade_sheet(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        economy=economy,
        scenario=scenario,
        label_to_product=label_to_product,
        value_field="observed_exports",
    )


def _balance_table_csv_candidates(results_source: Path | str | Iterable[Path | str]) -> list[Path]:
    """Return explicit balance-table CSV candidates from a directory or path list."""
    if isinstance(results_source, (str, Path)):
        root = _resolve(results_source)
        if root.is_dir():
            return sorted(root.glob("balance_table_*.csv"))
        return [root] if root.suffix.lower() == ".csv" else []
    candidates: list[Path] = []
    for value in results_source:
        path = _resolve(value)
        if path.suffix.lower() == ".csv":
            candidates.append(path)
    return sorted(candidates)


def _collect_observed_trade_from_balance_tables(
    *,
    scenario_pairs: list[tuple[str, str]],
    results_dir: Path | str | Iterable[Path | str],
    include_exports: bool,
) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    """Collect observed imports/exports from yearly balance-table CSVs."""
    candidates = _balance_table_csv_candidates(results_dir)
    if not candidates:
        raise FileNotFoundError(
            f"No yearly balance-table CSV files were found in '{results_dir}'."
        )

    required_columns = {
        "economy",
        "scenario",
        "year",
        "esto_product",
        "balance_component",
        "value",
    }
    frames: list[pd.DataFrame] = []
    for path in candidates:
        table = pd.read_csv(path)
        missing = [column for column in required_columns if column not in table.columns]
        if missing:
            raise ValueError(
                f"Balance table '{path}' is missing required columns: {missing}"
            )
        frame = table[
            [
                "economy",
                "scenario",
                "year",
                "esto_product",
                "balance_component",
                "value",
            ]
        ].copy()
        frame["economy"] = frame["economy"].astype(str).str.strip()
        frame["scenario"] = frame["scenario"].astype(str).str.strip()
        frame["economy_key"] = frame["economy"].map(_state_token)
        frame["scenario_key"] = frame["scenario"].map(_state_token)
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
        frame["balance_component"] = frame["balance_component"].astype(str).str.strip()
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined[
        combined["balance_component"].isin({"adjusted_imports", "adjusted_exports"})
    ].copy()
    if combined.empty:
        raise FileNotFoundError(
            f"Balance tables in '{results_dir}' did not contain adjusted import/export rows."
        )

    observed_rows: list[pd.DataFrame] = []
    missing_pairs: list[tuple[str, str]] = []
    for economy, scenario_key in scenario_pairs:
        economy_key = _state_token(economy)
        scenario_key = _state_token(scenario_key)
        subset = combined[
            (combined["economy_key"] == economy_key)
            & (combined["scenario_key"] == scenario_key)
        ].copy()
        if subset.empty:
            missing_pairs.append((str(economy), str(scenario_key)))
            continue

        import_rows = subset[subset["balance_component"] == "adjusted_imports"][
            ["economy", "scenario", "esto_product", "year", "value"]
        ].copy()
        import_rows["scenario"] = scenario_key
        import_rows["value"] = pd.to_numeric(import_rows["value"], errors="coerce").abs()
        import_rows = import_rows.rename(columns={"value": "observed_imports"})
        observed_rows.append(import_rows)

        if include_exports:
            export_rows = subset[subset["balance_component"] == "adjusted_exports"][
                ["economy", "scenario", "esto_product", "year", "value"]
            ].copy()
            export_rows["scenario"] = scenario_key
            export_rows["value"] = pd.to_numeric(export_rows["value"], errors="coerce").abs()
            export_rows = export_rows.rename(columns={"value": "observed_exports"})
            observed_rows.append(export_rows)

    if missing_pairs:
        preview = ", ".join(f"{economy}/{scenario}" for economy, scenario in missing_pairs[:6])
        raise FileNotFoundError(
            "Could not locate balance-table rows for economy/scenario: "
            f"{preview}. source='{results_dir}'."
        )

    import_rows = (
        pd.concat(
            [frame for frame in observed_rows if "observed_imports" in frame.columns],
            ignore_index=True,
            sort=False,
        )
        if observed_rows
        else pd.DataFrame(
            columns=["economy", "scenario", "esto_product", "year", "observed_imports"]
        )
    )
    if not import_rows.empty:
        import_rows = (
            import_rows.groupby(
                ["economy", "scenario", "esto_product", "year"],
                as_index=False,
                dropna=False,
            )["observed_imports"]
            .sum(min_count=1)
        )

    if include_exports:
        export_rows = (
            pd.concat(
                [frame for frame in observed_rows if "observed_exports" in frame.columns],
                ignore_index=True,
                sort=False,
            )
            if observed_rows
            else pd.DataFrame(
                columns=["economy", "scenario", "esto_product", "year", "observed_exports"]
            )
        )
        if not export_rows.empty:
            export_rows = (
                export_rows.groupby(
                    ["economy", "scenario", "esto_product", "year"],
                    as_index=False,
                    dropna=False,
                )["observed_exports"]
                .sum(min_count=1)
            )
    else:
        export_rows = pd.DataFrame(
            columns=["economy", "scenario", "esto_product", "year", "observed_exports"]
        )

    observed = import_rows
    if include_exports:
        observed = observed.merge(
            export_rows,
            on=["economy", "scenario", "esto_product", "year"],
            how="outer",
        )

    signature_map: dict[str, object] = {}
    signature_payload = {
        "source": "balance_tables",
        "files": [_build_results_signature(path) for path in candidates],
    }
    for economy, scenario_key in scenario_pairs:
        signature_map[_results_signature_state_key(economy, scenario_key)] = signature_payload

    return observed, signature_map, []


def _select_supply_results_workbook(
    *,
    economy: str,
    scenario: str,
    results_dir: Path | str = CAPACITY_UNMET_RESULTS_DIR,
) -> Path:
    """Select the best matching supply results workbook for economy/scenario."""
    root = _resolve(results_dir)
    candidates = sorted(root.glob("supply_results_*.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"No supply results workbooks found in '{root}'.")

    economy_tokens = {
        _state_token(economy),
        _state_token(str(economy).replace("_", "")),
    }
    scenario_tokens = {
        _state_token(scenario),
        _state_token(str(scenario).replace(" ", "")),
        _state_token(str(scenario).replace("_", "")),
    }
    scenario_tokens.update(_state_token(item) for item in _scenario_filename_candidates(scenario))
    economy_tokens = {token for token in economy_tokens if token}
    scenario_tokens = {token for token in scenario_tokens if token}

    scored: list[tuple[int, float, Path]] = []
    for path in candidates:
        name_token = _state_token(path.stem.replace("_", ""))
        econ_score = max((1 if token and token in name_token else 0) for token in economy_tokens) if economy_tokens else 0
        scen_score = max((1 if token and token in name_token else 0) for token in scenario_tokens) if scenario_tokens else 0
        if econ_score == 0 or scen_score == 0:
            continue
        try:
            stat = path.stat()
            mtime = float(stat.st_mtime)
        except Exception:
            mtime = 0.0
        scored.append((econ_score + scen_score, mtime, path))
    if not scored:
        raise FileNotFoundError(
            "Could not locate supply results workbook for economy/scenario: "
            f"economy='{economy}', scenario='{scenario}', dir='{root}'."
        )
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[-1][2]


def _scenario_filename_candidates(scenario: str) -> list[str]:
    """Return scenario tokens to try in refinery-results filenames."""
    raw = str(scenario or "").strip()
    if not raw:
        return []
    compact = raw.replace(" ", "")
    title = raw.title()
    return list(dict.fromkeys([raw, compact, title]))


def _abbreviate_scenario(scenario: object) -> str:
    """Return a compact file-safe scenario token for summary workbook names."""
    raw = str(scenario or "").strip()
    if not raw:
        return ""
    aliases = {
        "current accounts": "ca",
        "current account": "ca",
        "reference": "ref",
        "target": "tgt",
    }
    normalized = re.sub(r"\s+", " ", raw).lower()
    return aliases.get(normalized, workflow_common.format_filename_segment(raw))


def _resolve_refinery_results_workbook(economy: str, scenario: str) -> Path | None:
    """Resolve scenario-specific transformation+supply workbook for refinery fallback."""
    for token in _scenario_filename_candidates(scenario):
        filename = REFINERY_RESULTS_FILENAME_TEMPLATE.format(economy=economy, scenario=token)
        candidate = LEAP_RESULTS_TABLES_DIR / filename
        if candidate.exists():
            return candidate
    return None


def _resolve_transformation_results_workbook(economy: str, scenario: str) -> Path | None:
    """Resolve scenario-specific transformation results template workbook."""
    for token in _scenario_filename_candidates(scenario):
        filename = TRANSFORMATION_RESULTS_FILENAME_TEMPLATE.format(economy=economy, scenario=token)
        candidate = LEAP_RESULTS_TABLES_DIR / filename
        if candidate.exists():
            return candidate
    return None



from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BALANCE_EXPORTS_ROOT = REPO_ROOT / "data" / "leap balances exports"

BALANCE_EXPORT_FILENAME_PATTERN = re.compile(
    r"^full model output all years (?P<date_id>\d{5,8}) (?P<scenario>[A-Za-z]+)(?:\s[^.]*)?\.xlsx$",
    re.IGNORECASE,
)


SCENARIO_CODE_ALIASES = {
    "ref": "REF",
    "reference": "REF",
    "tgt": "TGT",
    "target": "TGT",
}


@dataclass(frozen=True)
class BalanceExportWorkbook:
    path: Path
    economy: str
    scenario_code: str
    date_id: str
    parsed_date: date | None


def normalize_balance_scenario_code(scenario: str) -> str:
    """Return the balance-export filename scenario token."""
    text = str(scenario).strip()
    if not text:
        raise ValueError("Balance-export scenario cannot be blank.")
    return SCENARIO_CODE_ALIASES.get(text.lower(), text.upper())


def normalize_balance_label(value: object) -> str:
    """Return a compact lowercase key for LEAP balance row/fuel matching."""
    return " ".join(str(value or "").strip().lower().split())


# LEAP's own-use/loss balance rows are exported as positive quantities, but they
# represent energy consumed out of the demand side of the balance (not supply),
# so ESTO/NINTH and the balance tables represent the same category as negative.
#
# This module's own-use/loss handling is intentionally narrow:
#   - `load_leap_balance_activity_table` below negates these rows via
#     `is_leap_balance_own_use_or_loss_row` because its only consumer (the
#     own-use/loss proxy workflow's activity-driver path) needs a value that's
#     directly comparable to ESTO/NINTH's signed convention.
#   - LEAP-native arithmetic elsewhere in this repo (`supply_conservation.py`,
#     `supply_reconciliation_tables.py`) intentionally treats own-use/loss
#     `demand_value` as a *positive* consumption quantity, and must keep doing
#     so — those modules sum it unconditionally (no `abs()`), so sign-flipping
#     it at the parse source would throw off `closure_residual`/
#     `adjusted_balance` and produce false conservation-violation errors. Do
#     not extend the negation below to that path.
#   - The dashboard's ESTO/NINTH-comparable pipeline is a fully separate
#     codebase (`leap_mappings`) that reads the same raw balance export files
#     independently; its own sign handling lives in
#     `leap_mappings/codebase/mapping_tools/convert_leap_results_to_esto.py`
#     and has no dependency on this module.
LEAP_BALANCE_LOSS_AND_OWN_USE_ROWS = (
    "Other loss and own use",
    "Coal mines",
    "Electricity CHP and heat plants",
    "Liquefaction and regasification plants",
    "Oil and gas extraction",
    "Oil refineries",
    "Pump storage plants",
    "Transmission and distribution loss",
)
LEAP_BALANCE_LOSS_AND_OWN_USE_ROW_KEYS = frozenset(
    normalize_balance_label(row) for row in LEAP_BALANCE_LOSS_AND_OWN_USE_ROWS
)


def is_leap_balance_own_use_or_loss_row(row_label: object) -> bool:
    """Return True when a LEAP balance row is one of the own-use/loss rows above."""
    return normalize_balance_label(row_label) in LEAP_BALANCE_LOSS_AND_OWN_USE_ROW_KEYS


def _resolve_path(path: Path | str) -> Path:
    """Resolve repo-relative paths while leaving absolute paths unchanged."""
    raw = str(path).replace("\\", "/")
    drive_match = re.match(r"^([a-zA-Z]):/(.*)$", raw)
    if drive_match:
        drive = drive_match.group(1).lower()
        rest = drive_match.group(2)
        if os.name == "nt":
            return Path(f"{drive.upper()}:/{rest}")
        return Path(f"/mnt/{drive}/{rest}")
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def _parse_balance_export_date_id(date_id: str) -> date | None:
    """Parse compact workbook date ids such as 492026 or 4212026."""
    token = str(date_id).strip()
    if not token.isdigit():
        return None

    if len(token) == 8:
        for year, month, day in (
            (token[:4], token[4:6], token[6:8]),
            (token[4:8], token[:2], token[2:4]),
        ):
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                continue

    if len(token) in {6, 7}:
        year_text = token[-4:]
        month_day = token[:-4]
        month_day_splits: list[tuple[str, str]] = []
        if len(month_day) >= 3 and month_day[:2] in {"10", "11", "12"}:
            month_day_splits.append((month_day[:2], month_day[2:]))
        month_day_splits.append((month_day[:1], month_day[1:]))
        if len(month_day) == 4:
            month_day_splits.append((month_day[:2], month_day[2:]))
        for month_text, day_text in month_day_splits:
            try:
                return date(int(year_text), int(month_text), int(day_text))
            except ValueError:
                continue

    return None


def _iter_balance_export_workbooks(
    export_dir: Path,
    *,
    economy: str,
    scenario_code: str,
) -> Iterable[BalanceExportWorkbook]:
    if not export_dir.exists():
        return
    for path in export_dir.glob("*.xlsx"):
        if path.name.startswith("~$"):
            continue
        match = BALANCE_EXPORT_FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        if normalize_balance_scenario_code(match.group("scenario")) != scenario_code:
            continue
        date_id = match.group("date_id")
        yield BalanceExportWorkbook(
            path=path,
            economy=economy,
            scenario_code=scenario_code,
            date_id=date_id,
            parsed_date=_parse_balance_export_date_id(date_id),
        )


def resolve_balance_export_workbook(
    *,
    economy: str,
    scenario: str,
    date_id: str | None = None,
    exports_root: Path | str = DEFAULT_BALANCE_EXPORTS_ROOT,
) -> Path:
    """Resolve a LEAP balance-export workbook by economy, scenario, and optional date id."""
    economy_text = str(economy).strip()
    if not economy_text:
        raise ValueError("Balance-export economy cannot be blank.")
    scenario_code = normalize_balance_scenario_code(scenario)
    export_dir = _resolve_path(exports_root) / economy_text
    candidates = list(
        _iter_balance_export_workbooks(
            export_dir,
            economy=economy_text,
            scenario_code=scenario_code,
        )
    )

    if date_id is not None:
        date_text = str(date_id).strip()
        candidates = [candidate for candidate in candidates if candidate.date_id == date_text]
        if not candidates:
            raise FileNotFoundError(
                "No LEAP balance-export workbook matched "
                f"economy={economy_text!r}, scenario={scenario_code!r}, date_id={date_text!r} "
                f"under {export_dir}."
            )
        if len(candidates) > 1:
            paths = "\n".join(
                f"- {candidate.path}"
                for candidate in sorted(candidates, key=lambda item: item.path.name)
            )
            raise ValueError(
                "Multiple LEAP balance-export workbooks matched "
                f"economy={economy_text!r}, scenario={scenario_code!r}, date_id={date_text!r}:\n{paths}"
            )
        return candidates[0].path

    if not candidates:
        raise FileNotFoundError(
            "No LEAP balance-export workbook matched "
            f"economy={economy_text!r}, scenario={scenario_code!r} under {export_dir}."
        )

    sortable = [
        candidate
        for candidate in candidates
        if candidate.parsed_date is not None
    ]
    if sortable:
        latest_date = max(candidate.parsed_date for candidate in sortable)
        latest = [candidate for candidate in sortable if candidate.parsed_date == latest_date]
    else:
        latest = candidates

    if len(latest) > 1:
        paths = "\n".join(
            f"- {candidate.path}"
            for candidate in sorted(latest, key=lambda item: item.path.name)
        )
        raise ValueError(
            "Multiple LEAP balance-export workbooks matched the latest date for "
            f"economy={economy_text!r}, scenario={scenario_code!r}. Set date_id explicitly.\n{paths}"
        )

    return latest[0].path


def _leap_balance_sheet_unit_to_pj_multiplier(raw: pd.DataFrame) -> float:
    """Return the multiplier needed to convert a LEAP balance sheet to PJ."""
    unit_text = ""
    for row_idx in range(min(4, len(raw))):
        for value in raw.iloc[row_idx].tolist():
            text = str(value or "").strip()
            match = re.search(r"units:\s*(.+)$", text, flags=re.IGNORECASE)
            if match:
                unit_text = match.group(1).strip().lower()
                break
        if unit_text:
            break
    if not unit_text:
        return 1.0

    unit_text = unit_text.rstrip(".")
    if unit_text.startswith("thousand petajoule"):
        return 1000.0
    if unit_text.startswith("petajoule"):
        return 1.0
    if unit_text.startswith("terajoule"):
        return 0.001
    if unit_text.startswith("gigajoule"):
        return 0.000001
    if unit_text.startswith("million gigajoule"):
        return 1.0
    return 1.0


SCENARIO_LABEL_ALIASES = {
    "reference": "REF",
    "ref": "REF",
    "target": "TGT",
    "tgt": "TGT",
}


def _leap_balance_sheet_scenario_label(raw: pd.DataFrame) -> str:
    """Return the normalized REF/TGT scenario code from a sheet's "Scenario:" subtitle, or "" if absent/unrecognized."""
    for row_idx in range(min(4, len(raw))):
        for value in raw.iloc[row_idx].tolist():
            text = str(value or "").strip()
            match = re.search(r"scenario:\s*([^,]+)", text, flags=re.IGNORECASE)
            if match:
                label = match.group(1).strip().lower()
                return SCENARIO_LABEL_ALIASES.get(label, "")
    return ""


def _scenario_code_from_balance_export_filename(workbook: Path) -> str:
    """Return the REF/TGT scenario code implied by a balance-export filename, or "" if unrecognized."""
    match = BALANCE_EXPORT_FILENAME_PATTERN.match(workbook.name)
    if not match:
        return ""
    try:
        return normalize_balance_scenario_code(match.group("scenario"))
    except ValueError:
        return ""


def load_leap_balance_activity_table(
    workbook_path: Path | str,
    *,
    balance_rows: Sequence[str],
    fuels: Sequence[str],
) -> pd.DataFrame:
    """Return long LEAP balance values for selected row labels and fuel columns.

    Values are normalized to petajoules when the LEAP sheet subtitle declares a
    recognized energy unit.
    """
    workbook = _resolve_path(workbook_path)
    if not workbook.exists():
        raise FileNotFoundError(f"Missing LEAP balance workbook: {workbook}")

    wanted_rows = {normalize_balance_label(row) for row in balance_rows}
    wanted_fuels = {normalize_balance_label(fuel) for fuel in fuels}
    rows: list[dict[str, object]] = []
    xls = pd.ExcelFile(workbook)
    for sheet_name in xls.sheet_names:
        name = str(sheet_name).strip()
        if name.lower().startswith("ebal|"):
            year_text = name.split("|", 1)[1]
        elif name.isdigit():
            # Raw "full model output" exports from LEAP use bare-year sheet
            # names (e.g. "2022") rather than the "EBal|2022" convention used
            # by this pipeline's own generated balance workbooks.
            year_text = name
        else:
            continue
        try:
            year = int(year_text)
        except Exception:
            continue
        raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
        if raw.shape[0] < 3 or raw.shape[1] < 2:
            continue
        unit_multiplier = _leap_balance_sheet_unit_to_pj_multiplier(raw)
        header_row_idx = None
        best_match_count = 0
        for candidate_idx in range(min(8, len(raw))):
            candidate_labels = raw.iloc[candidate_idx].fillna("").astype(str).tolist()
            match_count = sum(
                1
                for label in candidate_labels[1:]
                if normalize_balance_label(label) in wanted_fuels
            )
            if match_count > best_match_count:
                best_match_count = match_count
                header_row_idx = candidate_idx
        if header_row_idx is None or best_match_count == 0:
            continue
        fuel_labels = raw.iloc[header_row_idx].fillna("").astype(str).tolist()
        fuel_columns = {
            col_idx: label
            for col_idx, label in enumerate(fuel_labels)
            if col_idx > 0 and normalize_balance_label(label) in wanted_fuels
        }
        if not fuel_columns:
            continue
        for row_idx in range(header_row_idx + 1, len(raw)):
            row_label = str(raw.iat[row_idx, 0] or "").strip()
            if normalize_balance_label(row_label) not in wanted_rows:
                continue
            for col_idx, fuel_label in fuel_columns.items():
                value = pd.to_numeric(raw.iat[row_idx, col_idx], errors="coerce")
                if pd.isna(value):
                    value = 0.0
                value = float(value) * unit_multiplier
                if is_leap_balance_own_use_or_loss_row(row_label):
                    value = -value
                rows.append(
                    {
                        "source_dataset": "leap_balance",
                        "year": int(year),
                        "balance_row": row_label,
                        "fuel_label": str(fuel_label).strip(),
                        "value": value,
                    }
                )
    columns = ["source_dataset", "year", "balance_row", "fuel_label", "value"]
    return pd.DataFrame(rows, columns=columns)


def build_leap_balance_activity_series(
    leap_balance_activity: pd.DataFrame,
    *,
    balance_rows: Sequence[str],
    fuels: Sequence[str],
    value_mode: str = "signed_sum",
    base_year: int,
    final_year: int,
) -> dict[int, float]:
    """Sum selected LEAP balance rows/fuels into one yearly activity series."""
    wanted_fuels = {normalize_balance_label(fuel) for fuel in fuels}
    wanted_rows = {normalize_balance_label(row) for row in balance_rows}
    year_range = range(int(base_year), int(final_year) + 1)
    if leap_balance_activity.empty or not wanted_fuels or not wanted_rows:
        return {year: 0.0 for year in year_range}

    subset = leap_balance_activity[
        leap_balance_activity["fuel_label"].map(normalize_balance_label).isin(wanted_fuels)
        & leap_balance_activity["balance_row"].map(normalize_balance_label).isin(wanted_rows)
    ].copy()
    if subset.empty:
        return {year: 0.0 for year in year_range}

    mode = str(value_mode or "signed_sum").strip().lower()
    values = pd.to_numeric(subset["value"], errors="coerce").fillna(0.0)
    if mode in {"signed", "signed_sum", ""}:
        subset["activity_value"] = values
    elif mode in {"positive", "positive_only", "outputs"}:
        subset["activity_value"] = values.where(values > 0.0, 0.0)
    elif mode in {"negative_abs", "input_abs", "inputs_abs"}:
        subset["activity_value"] = values.where(values < 0.0, 0.0).abs()
    elif mode in {"absolute", "abs"}:
        subset["activity_value"] = values.abs()
    else:
        raise ValueError(f"Invalid LEAP balance value_mode={mode!r}.")

    grouped = subset.groupby("year", dropna=False)["activity_value"].sum()
    return {
        year: float(grouped.get(year, 0.0))
        for year in year_range
    }

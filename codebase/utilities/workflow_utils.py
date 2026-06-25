"""
Shared utilities for LEAP initialisation workflow scripts.

Provides:
- REPO_ROOT — canonical repo root path
- _resolve(path) — resolve a relative path against REPO_ROOT
- _normalize_economy(value) — normalise economy code strings (e.g. "01AUS" → "01_AUS")
- _normalize_year_columns(df) — rename string year columns to int
- load_ninth_outlook_csv(path) — cached loader for the 9th Outlook CSV (~275 MB)
- load_esto_csv(path) — cached loader for the ESTO base CSV

All CSV loaders are cached by path in a module-level dict so each file is only
read once per process, regardless of how many workflow scripts import this module.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default data file paths (used when callers pass no explicit path).
_DEFAULT_NINTH_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
_DEFAULT_ESTO_PATH = REPO_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv"

# Module-level cache: absolute Path → loaded DataFrame.
_csv_cache: dict[Path, pd.DataFrame] = {}


def _resolve(path: Path | str) -> Path:
    """Resolve a possibly relative path against REPO_ROOT.

    Normalises backslashes before constructing the Path object so that
    Windows-style separators work in both Windows and WSL contexts.
    Absolute paths are returned as-is.
    """
    raw = str(path).replace("\\", "/")
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def _normalize_economy(value: object) -> str:
    """Normalise economy code strings to the canonical underscore form.

    Examples
    --------
    "01AUS"  → "01_AUS"
    "20usa"  → "20_USA"
    "01_AUS" → "01_AUS"  (already canonical)
    """
    text = str(value or "").strip().upper()
    if len(text) >= 5 and text[:2].isdigit() and text[2] != "_":
        return f"{text[:2]}_{text[2:]}"
    return text


def _normalize_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename all string year columns (e.g. "2022") to int (e.g. 2022).

    Non-year columns are left unchanged.
    """
    return df.rename(columns={col: int(col) for col in df.columns if str(col).isdigit()})


def load_ninth_outlook_csv(path: Path | str | None = None) -> pd.DataFrame:
    """Load the 9th Outlook merged energy CSV, caching by path.

    Parameters
    ----------
    path:
        Explicit path to the CSV file. Defaults to
        ``data/merged_file_energy_ALL_20251106.csv`` under REPO_ROOT.

    Returns
    -------
    DataFrame with all columns from the file. The caller is responsible for
    any column filtering or economy subsetting.
    """
    key = Path(path).resolve() if path else _DEFAULT_NINTH_PATH
    if key not in _csv_cache:
        _csv_cache[key] = pd.read_csv(key, low_memory=False)
    return _csv_cache[key]


def load_esto_csv(path: Path | str | None = None) -> pd.DataFrame:
    """Load the ESTO base-table CSV, caching by path.

    Parameters
    ----------
    path:
        Explicit path to the CSV file. Defaults to
        ``data/00APEC_2025_low_with_subtotals.csv`` under REPO_ROOT.

    Returns
    -------
    DataFrame with all columns from the file.
    """
    key = Path(path).resolve() if path else _DEFAULT_ESTO_PATH
    if key not in _csv_cache:
        _csv_cache[key] = pd.read_csv(key, low_memory=False)
    return _csv_cache[key]

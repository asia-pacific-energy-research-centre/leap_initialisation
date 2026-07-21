"""
Shared utilities for LEAP initialisation workflow scripts.

Provides:
- REPO_ROOT — canonical repo root path
- _resolve(path) — resolve a relative path against REPO_ROOT
- _normalize_economy(value) — normalise economy code strings (e.g. "01AUS" → "01_AUS")
- _normalize_year_columns(df) — rename string year columns to int
- load_ninth_outlook_csv(path) — cached loader for the 9th Outlook CSV (~275 MB)
- load_esto_csv(path) — cached loader for the ESTO base CSV

All CSV loaders are cached by resolved path and source-file signature in a
module-level dict. They reload automatically when the source file changes.

The returned DataFrame is the cached object. Callers that add, remove, or
modify columns must call ``.copy()`` first so their local transformations do
not affect later callers in the same Python process.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default data file paths (used when callers pass no explicit path).
_DEFAULT_NINTH_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
_DEFAULT_ESTO_PATH = workflow_cfg.get_energy_source_config().esto_base_table_path

@dataclass(frozen=True)
class _CachedCsv:
    """One in-memory CSV value and the source signature it was read from."""

    signature: tuple[int, int]
    dataframe: pd.DataFrame


# Module-level cache: resolved source path → loaded value and source signature.
_csv_cache: dict[Path, _CachedCsv] = {}


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


def _csv_source_signature(path: Path) -> tuple[int, int]:
    """Return the inexpensive file-state signature used for cache invalidation."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _load_cached_csv(path: Path) -> pd.DataFrame:
    """Read ``path`` when absent or changed; otherwise return its cached frame."""
    signature = _csv_source_signature(path)
    cached = _csv_cache.get(path)
    if cached is None or cached.signature != signature:
        _csv_cache[path] = _CachedCsv(
            signature=signature,
            dataframe=pd.read_csv(path, low_memory=False),
        )
    return _csv_cache[path].dataframe


def clear_csv_cache(path: Path | str | None = None) -> None:
    """Clear one cached source, or all cached CSV sources when ``path`` is omitted.

    This is mainly useful in long-lived notebook sessions after a user replaces
    source data. Normal file changes are detected automatically, so callers do
    not need to clear the cache for ordinary rewrites.
    """
    if path is None:
        _csv_cache.clear()
        return
    _csv_cache.pop(_resolve(path).resolve(), None)


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
    key = _resolve(path).resolve() if path else _DEFAULT_NINTH_PATH.resolve()
    return _load_cached_csv(key)


def load_esto_csv(path: Path | str | None = None) -> pd.DataFrame:
    """Load the ESTO base-table CSV, caching by path.

    Parameters
    ----------
    path:
        Explicit path to the CSV file. Defaults to the configured
        ``esto_base_table_path`` (see ``workflow_config.get_energy_source_config``).

    Returns
    -------
    DataFrame with all columns from the file.
    """
    key = _resolve(path).resolve() if path else _DEFAULT_ESTO_PATH.resolve()
    return _load_cached_csv(key)

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

Both loaders accept an optional ``economies`` filter. When a caller knows
this process only needs one economy (or a small subset) - the common case
for the per-economy parallel worker processes in
``parallel_economy_runner.py``, and for any single-economy run in general -
passing ``economies=`` reads the source in chunks and keeps only matching
rows, so the full multi-economy table (287 MB on disk for the 9th Outlook
CSV, several times that once parsed into pandas) is never held in memory at
all. This is a real, measured saving: with 21 economies in the source file,
a one-economy caller previously held roughly 20x more rows than it needed.
Omitting ``economies`` preserves the original full-table caching, which is
still the right choice for a single process that legitimately handles many
economies in one loop (the full table is loaded once and reused, cheaper
than re-reading per economy).
"""
from __future__ import annotations

from collections.abc import Sequence
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


@dataclass(frozen=True)
class _CsvCacheKey:
    """A source plus the selected columns used to read it."""

    path: Path
    usecols: tuple[str, ...] | None


@dataclass(frozen=True)
class _CsvCacheKeyByEconomy:
    """A source plus columns plus the economy scope it was filtered to."""

    path: Path
    usecols: tuple[str, ...] | None
    economies: tuple[str, ...]


# Module-level cache: source and selected columns → loaded value and signature.
_csv_cache: dict[_CsvCacheKey, _CachedCsv] = {}
# Separate cache for economy-scoped reads - never holds the full table, only
# whatever chunked rows matched the requested economies.
_csv_cache_by_economy: dict[_CsvCacheKeyByEconomy, _CachedCsv] = {}

# Row-chunk size for economy-scoped reads. Bounds peak memory during the read
# itself to roughly one chunk's worth of the full table, regardless of how
# large the source file is; the accumulated filtered result is the only part
# that persists afterwards.
_ECONOMY_FILTER_CHUNKSIZE = 250_000


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


def _normalize_usecols(usecols: Sequence[str] | None) -> tuple[str, ...] | None:
    """Create a stable cache-key representation for a selected column set."""
    if usecols is None:
        return None
    return tuple(sorted({str(column) for column in usecols}))


def _normalize_economies_filter(economies: Sequence[str] | None) -> tuple[str, ...] | None:
    """Create a stable, deduplicated, canonical-form cache-key for an economy scope.

    Normalizes through ``_normalize_economy`` because the two source files do
    not agree on economy-code form: the 9th Outlook CSV already uses the
    canonical underscore form ("01_AUS"), but the ESTO base-table CSV uses
    the compact form ("01AUS"). Comparing both sides in canonical form (see
    ``_load_cached_csv_filtered_by_economy``) is what makes one filter
    implementation correct for both sources.
    """
    if economies is None:
        return None
    normalized = tuple(
        sorted({_normalize_economy(economy) for economy in economies if str(economy).strip()})
    )
    return normalized or None


def _load_cached_csv(
    path: Path,
    *,
    usecols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read ``path`` when absent or changed; otherwise return its cached frame."""
    key = _CsvCacheKey(path=path, usecols=_normalize_usecols(usecols))
    signature = _csv_source_signature(path)
    cached = _csv_cache.get(key)
    if cached is None or cached.signature != signature:
        _csv_cache[key] = _CachedCsv(
            signature=signature,
            dataframe=pd.read_csv(path, usecols=key.usecols, low_memory=False),
        )
    return _csv_cache[key].dataframe


def _load_cached_csv_filtered_by_economy(
    path: Path,
    *,
    usecols: Sequence[str] | None,
    economies: tuple[str, ...],
    chunksize: int,
) -> pd.DataFrame:
    """Read ``path`` in chunks, keeping only rows for ``economies``.

    Never materializes the full table: each chunk is filtered and discarded
    immediately, so peak memory during the read is bounded by one chunk plus
    the accumulated (small, economy-scoped) result - not the whole source
    file. Cached separately from the full-table cache, keyed on the exact
    economy scope requested, so a different worker/economy combination in the
    same process gets its own correctly-scoped entry rather than reusing
    another economy's rows.
    """
    read_cols = list(usecols) if usecols is not None else None
    if read_cols is not None and "economy" not in read_cols:
        read_cols = [*read_cols, "economy"]
    key = _CsvCacheKeyByEconomy(
        path=path, usecols=_normalize_usecols(read_cols), economies=economies
    )
    signature = _csv_source_signature(path)
    cached = _csv_cache_by_economy.get(key)
    if cached is not None and cached.signature == signature:
        return cached.dataframe

    matched_chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, usecols=read_cols, chunksize=chunksize, low_memory=False):
        # Compare in canonical form - the source's own raw economy-code form
        # (compact vs underscored) must not matter here (see
        # _normalize_economies_filter).
        chunk_economy = chunk["economy"].map(_normalize_economy)
        matched = chunk.loc[chunk_economy.isin(economies)]
        if not matched.empty:
            matched_chunks.append(matched)
    filtered = (
        pd.concat(matched_chunks, ignore_index=True)
        if matched_chunks
        else pd.read_csv(path, usecols=read_cols, nrows=0)
    )
    _csv_cache_by_economy[key] = _CachedCsv(signature=signature, dataframe=filtered)
    return filtered


def clear_csv_cache(path: Path | str | None = None) -> None:
    """Clear one cached source, or all cached CSV sources when ``path`` is omitted.

    This is mainly useful in long-lived notebook sessions after a user replaces
    source data. Normal file changes are detected automatically, so callers do
    not need to clear the cache for ordinary rewrites. Clears both the
    full-table cache and any economy-scoped cache entries for the source.
    """
    if path is None:
        _csv_cache.clear()
        _csv_cache_by_economy.clear()
        return
    source_path = _resolve(path).resolve()
    for key in [key for key in _csv_cache if key.path == source_path]:
        _csv_cache.pop(key, None)
    for key in [key for key in _csv_cache_by_economy if key.path == source_path]:
        _csv_cache_by_economy.pop(key, None)


def load_ninth_outlook_csv(
    path: Path | str | None = None,
    *,
    usecols: Sequence[str] | None = None,
    economies: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load the 9th Outlook merged energy CSV, caching by path and columns.

    Parameters
    ----------
    path:
        Explicit path to the CSV file. Defaults to
        ``data/merged_file_energy_ALL_20251106.csv`` under REPO_ROOT.
    usecols:
        Optional source columns to load. A selected-column frame has its own
        cache entry, so it never forces a full-table read.
    economies:
        Optional economy codes to filter to. When given, the source is read
        in chunks and only matching rows are kept - the full multi-economy
        table is never held in memory. Omit this for a process that
        legitimately needs many/all economies in one run (the full table,
        loaded once, is cheaper to reuse than re-reading per economy).

    Returns
    -------
    DataFrame with all requested columns from the file (plus ``economy`` when
    ``economies`` is given, even if not in ``usecols``, since it is needed to
    filter). The caller is responsible for any further column filtering.
    """
    key = _resolve(path).resolve() if path else _DEFAULT_NINTH_PATH.resolve()
    economies_key = _normalize_economies_filter(economies)
    if economies_key is None:
        return _load_cached_csv(key, usecols=usecols)
    return _load_cached_csv_filtered_by_economy(
        key, usecols=usecols, economies=economies_key, chunksize=_ECONOMY_FILTER_CHUNKSIZE
    )


def load_esto_csv(
    path: Path | str | None = None,
    *,
    usecols: Sequence[str] | None = None,
    economies: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load the ESTO base-table CSV, caching by path and columns.

    Parameters
    ----------
    path:
        Explicit path to the CSV file. Defaults to the configured
        ``esto_base_table_path`` (see ``workflow_config.get_energy_source_config``).
    usecols:
        Optional source columns to load. A selected-column frame has its own
        cache entry, so it never forces a full-table read.
    economies:
        Optional economy codes to filter to. When given, the source is read
        in chunks and only matching rows are kept - the full multi-economy
        table is never held in memory. Omit this for a process that
        legitimately needs many/all economies in one run.

    Returns
    -------
    DataFrame with all requested columns from the file (plus ``economy`` when
    ``economies`` is given, even if not in ``usecols``).
    """
    key = _resolve(path).resolve() if path else _DEFAULT_ESTO_PATH.resolve()
    economies_key = _normalize_economies_filter(economies)
    if economies_key is None:
        return _load_cached_csv(key, usecols=usecols)
    return _load_cached_csv_filtered_by_economy(
        key, usecols=usecols, economies=economies_key, chunksize=_ECONOMY_FILTER_CHUNKSIZE
    )

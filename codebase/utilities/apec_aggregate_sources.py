"""Create and resolve aggregate ESTO/9th source files for APEC preflights."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
APEC_AGGREGATES_DIR = REPO_ROOT / "data" / "APEC_aggregates"
APEC_ECONOMY_LABEL = "00_APEC"


def _year_from_source_name(source_path: Path) -> int:
    """Return the four-digit source vintage embedded in a source filename."""
    for token in source_path.stem.split("_"):
        if token.isdigit() and len(token) == 4:
            return int(token)
    raise ValueError(f"Could not identify a four-digit source vintage in {source_path.name!r}.")


def build_apec_esto_aggregate(
    source_path: Path | str,
    output_path: Path | str,
    *,
    economy_label: str = APEC_ECONOMY_LABEL,
) -> Path:
    """Sum one ESTO vintage over all source economies by flow/product identity.

    The source files are one-economy-at-a-time ESTO tables. The aggregate keeps
    the source schema, replaces ``economy`` with ``00_APEC``, and sums all year
    columns by ``flows``, ``products``, and ``is_subtotal``. Each vintage is
    aggregated independently so year values are not double-counted across the
    2024 and 2025 snapshots.
    """
    source = Path(source_path)
    output = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"ESTO source file does not exist: {source}")

    header = pd.read_csv(source, nrows=0)
    required = {"economy", "flows", "products"}
    missing = sorted(required - set(header.columns))
    if missing:
        raise ValueError(f"ESTO source {source.name} is missing required columns: {missing}")

    year_columns = [column for column in header.columns if str(column).isdigit()]
    group_columns = [column for column in ["flows", "products", "is_subtotal"] if column in header.columns]
    use_columns = ["economy", *group_columns, *year_columns]
    frame = pd.read_csv(source, usecols=use_columns, low_memory=False)

    if "is_subtotal" in frame.columns:
        frame["is_subtotal"] = (
            frame["is_subtotal"]
            .fillna(False)
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"true", "1", "yes"})
        )
    for column in year_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)

    aggregate = frame.groupby(group_columns, dropna=False, as_index=False)[year_columns].sum()
    aggregate.insert(0, "economy", economy_label)
    aggregate = aggregate[[column for column in header.columns if column in aggregate.columns]]

    output.parent.mkdir(parents=True, exist_ok=True)
    aggregate.to_csv(output, index=False)
    print(
        f"[INFO] Created APEC ESTO aggregate {output} from {source.name}: "
        f"{len(aggregate):,} grouped rows."
    )
    return output


def ensure_apec_esto_aggregate(
    source_path: Path | str,
    *,
    output_dir: Path | str = APEC_AGGREGATES_DIR,
) -> Path:
    """Return the aggregate ESTO file, creating it only when absent."""
    source = Path(source_path)
    output = Path(output_dir) / f"APEC_aggregate_{_year_from_source_name(source)}_low_with_subtotals.csv"
    if not output.exists():
        build_apec_esto_aggregate(source, output)
    return output


def resolve_apec_ninth_aggregate(source_path: Path | str) -> Path:
    """Resolve the existing aggregate 9th file matching the configured vintage."""
    source = Path(source_path)
    candidates = [
        APEC_AGGREGATES_DIR / source.name,
        APEC_AGGREGATES_DIR / "merged_file_energy_00_APEC_20251106.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "No aggregate APEC 9th source exists. Checked: "
        + ", ".join(str(candidate) for candidate in candidates)
    )

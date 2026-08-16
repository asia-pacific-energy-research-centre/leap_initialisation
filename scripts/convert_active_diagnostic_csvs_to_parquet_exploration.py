#%%
"""Convert only current approved diagnostic CSVs to manifested Parquet.

The conversion is deliberately non-destructive: legacy CSV/CSV.gz files stay
in place, existing Parquet authorities are never overwritten, and published
Common ESTO mapping contracts are hard-excluded.
"""

from __future__ import annotations

import importlib.util
import gc
import json
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pandas as pd


# --- Stable paths and conversion scope ------------------------------------

INITIALISATION_ROOT = Path(__file__).resolve().parents[1]
MAPPINGS_ROOT = INITIALISATION_ROOT.parent / "leap_mappings"
SUPPLY_OUTPUT_ROOT = (
    INITIALISATION_ROOT
    / "outputs/leap_exports/supply_reconciliation"
)
MAPPING_TREE_ROOT = MAPPINGS_ROOT / "results/tree_structure"
MAPPING_BROAD_ROOT = MAPPINGS_ROOT / "results/common_esto/diagnostics"
MAPPING_COMMON_ROOT = MAPPINGS_ROOT / "results/common_esto"
REPORT_PATH = (
    INITIALISATION_ROOT
    / "docs/diagnostics/parquet_migration/active_legacy_csv_conversion_report.json"
)

INITIALISATION_BASENAME_MAP = {
    "supply_reconciliation_balance_demand_conservation.csv": (
        "supply_reconciliation_balance_demand_conservation.parquet"
    ),
    "supply_reconciliation_balance_demand_conservation_breakdown.csv": (
        "supply_reconciliation_balance_demand_conservation_breakdown.parquet"
    ),
    "supply_reconciliation_balance_demand_conservation_lineage.csv": (
        "supply_reconciliation_balance_demand_conservation_lineage.parquet"
    ),
    "supply_reconciliation_transformation_output_conservation.csv": (
        "supply_reconciliation_transformation_output_conservation.parquet"
    ),
    "supply_reconciliation_transformation_output_conservation_breakdown.csv": (
        "supply_reconciliation_transformation_output_conservation_breakdown.parquet"
    ),
    "supply_reconciliation_transformation_output_conservation_lineage.csv": (
        "supply_reconciliation_transformation_output_conservation_lineage.parquet"
    ),
    "baseline_seed_artifact_findings.csv": "baseline_seed_artifact_findings.parquet",
    "baseline_seed_artifact_findings_review.csv": (
        "baseline_seed_artifact_findings_review.parquet"
    ),
    "baseline_seed_artifact_summary.csv": "baseline_seed_artifact_summary.parquet",
    "leap_export_readiness_findings.csv": "leap_export_readiness_findings.parquet",
}

MAPPING_SOURCE_MAP = {
    "source_parent_anchor_validation.csv": "source_parent_anchor_validation.parquet",
    "source_parent_anchor_validation_full.csv.gz": (
        "source_parent_anchor_validation_full.parquet"
    ),
    "source_parent_anchor_validation_summary.csv": (
        "source_parent_anchor_validation_summary.parquet"
    ),
    "source_parent_anchor_child_values.csv": (
        "source_parent_anchor_child_values.parquet"
    ),
    "source_parent_anchor_child_context_values.csv": (
        "source_parent_anchor_child_context_values.parquet"
    ),
    "source_parent_anchor_mapped_component_context_values.csv": (
        "source_parent_anchor_mapped_component_context_values.parquet"
    ),
    "source_parent_anchor_economy_examples.csv": (
        "source_parent_anchor_economy_examples.parquet"
    ),
    "source_parent_anchor_economy_child_context_values.csv": (
        "source_parent_anchor_economy_child_context_values.parquet"
    ),
    "source_parent_anchor_economy_mapped_component_context_values.csv": (
        "source_parent_anchor_economy_mapped_component_context_values.parquet"
    ),
    "source_parent_anchor_leaf_reconciliation_candidates.csv": (
        "source_parent_anchor_leaf_reconciliation_candidates.parquet"
    ),
    "broad_common_row_summary.csv": "broad_common_row_summary.parquet",
    "broad_common_row_components.csv": "broad_common_row_components.parquet",
    "broad_common_row_affected_output.csv": (
        "broad_common_row_affected_output.parquet"
    ),
}

# These published mapping authorities must never be selected by this utility.
PROTECTED_COMMON_MAPPING_CSVS = {
    "common_esto_rows.csv",
    "common_esto_row_components.csv",
    "common_esto_row_metadata.csv",
    "esto_to_common_esto_map.csv",
    "source_to_common_esto_map.csv",
    "common_row_to_source_pairs.csv",
    "source_pair_to_esto_component.csv",
    "esto_component_to_common_row.csv",
}


# --- Helpers ---------------------------------------------------------------

def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_provenance(source_path: Path, repository_root: Path, sha256_file) -> dict:
    return {
        "conversion_type": "legacy_csv_to_parquet",
        "conversion_format_version": 1,
        "converted_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path.relative_to(repository_root).as_posix(),
        "source_format": "csv.gz" if source_path.name.endswith(".csv.gz") else "csv",
        "source_byte_size": int(source_path.stat().st_size),
        "source_mtime_ns": int(source_path.stat().st_mtime_ns),
        "source_sha256": sha256_file(source_path),
        "source_retained": True,
    }


def _convert_one(
    *,
    source_path: Path,
    destination_path: Path,
    repository_root: Path,
    storage_module: ModuleType,
    artifact_type: str,
) -> dict[str, object]:
    if source_path.name in PROTECTED_COMMON_MAPPING_CSVS:
        raise ValueError(f"Protected Common ESTO mapping CSV selected: {source_path}")
    if destination_path.exists():
        storage_module.read_active_parquet(destination_path)
        return {
            "source": str(source_path),
            "destination": str(destination_path),
            "status": "skipped_existing_parquet",
        }

    source_frame = pd.read_csv(source_path, low_memory=False)
    provenance = _source_provenance(
        source_path,
        repository_root,
        storage_module.sha256_file,
    )
    storage_module.write_manifested_parquet(
        source_frame,
        destination_path,
        artifact_type=artifact_type,
        source_provenance=provenance,
    )
    restored = storage_module.read_active_parquet(destination_path)
    pd.testing.assert_frame_equal(source_frame, restored, check_exact=True)
    record = {
        "source": str(source_path),
        "destination": str(destination_path),
        "status": "converted_and_verified",
        "rows": int(len(source_frame)),
        "source_bytes": int(source_path.stat().st_size),
        "parquet_bytes": int(destination_path.stat().st_size),
        "source_sha256": provenance["source_sha256"],
        "source_retained": True,
    }
    del source_frame, restored
    gc.collect()
    return record


def _active_initialisation_sources() -> list[tuple[Path, Path]]:
    selected: list[tuple[Path, Path]] = []
    for source_path in SUPPLY_OUTPUT_ROOT.rglob("*.csv"):
        relative_parts = {part.casefold() for part in source_path.relative_to(SUPPLY_OUTPUT_ROOT).parts}
        if "runs" in relative_parts:
            continue
        destination_name = INITIALISATION_BASENAME_MAP.get(source_path.name)
        if destination_name:
            selected.append((source_path, source_path.with_name(destination_name)))
    return sorted(selected)


def _active_mapping_sources() -> list[tuple[Path, Path]]:
    selected: list[tuple[Path, Path]] = []
    for source_name, destination_name in MAPPING_SOURCE_MAP.items():
        root = MAPPING_BROAD_ROOT if source_name.startswith("broad_common_row_") else MAPPING_TREE_ROOT
        source_path = root / source_name
        if source_path.exists():
            selected.append((source_path, root / destination_name))
    common_replacements = {
        MAPPING_COMMON_ROOT / "common_esto_comparison_data.csv": (
            MAPPING_COMMON_ROOT / "common_esto_comparison_data.parquet"
        ),
        MAPPING_COMMON_ROOT / "structural_artifacts/source_pair_to_common_row.csv": (
            MAPPING_COMMON_ROOT / "structural_artifacts/source_pair_to_common_row.parquet"
        ),
        MAPPING_COMMON_ROOT / "source_to_common_esto_map_coverage.csv": (
            MAPPING_COMMON_ROOT / "source_to_common_esto_map_coverage.parquet"
        ),
    }
    selected.extend(
        (source_path, destination_path)
        for source_path, destination_path in common_replacements.items()
        if source_path.exists()
    )
    return selected


def convert_active_diagnostic_csvs() -> list[dict[str, object]]:
    """Convert the bounded active set and write a JSON audit report."""
    initialisation_storage = _load_module(
        "initialisation_typed_storage",
        INITIALISATION_ROOT / "codebase/utilities/typed_storage.py",
    )
    mappings_storage = _load_module(
        "mappings_typed_output",
        MAPPINGS_ROOT / "codebase/mapping_tools/typed_output.py",
    )
    # Give both repository helpers one adapter name without replacing either
    # module's internal read function.
    initialisation_storage.read_active_parquet = (
        initialisation_storage.read_manifested_parquet_file
    )
    mappings_storage.read_active_parquet = mappings_storage.read_manifested_parquet

    records: list[dict[str, object]] = []
    for source_path, destination_path in _active_initialisation_sources():
        records.append(
            _convert_one(
                source_path=source_path,
                destination_path=destination_path,
                repository_root=INITIALISATION_ROOT,
                storage_module=initialisation_storage,
                artifact_type=destination_path.stem,
            )
        )
    for source_path, destination_path in _active_mapping_sources():
        records.append(
            _convert_one(
                source_path=source_path,
                destination_path=destination_path,
                repository_root=MAPPINGS_ROOT,
                storage_module=mappings_storage,
                artifact_type=destination_path.stem,
            )
        )

    # Current broad-row output did not historically have a sample file.
    broad_detail_path = MAPPING_BROAD_ROOT / "broad_common_row_affected_output.parquet"
    broad_sample_path = MAPPING_BROAD_ROOT / "broad_common_row_affected_output_sample.parquet"
    if broad_detail_path.exists() and not broad_sample_path.exists():
        affected = mappings_storage.read_manifested_parquet(broad_detail_path)
        group_columns = [
            column
            for column in ("common_row_id", "source_system")
            if column in affected.columns
        ]
        sample = (
            affected.groupby(group_columns, dropna=False, sort=True).head(5).reset_index(drop=True)
            if group_columns and not affected.empty
            else affected.head(100).reset_index(drop=True)
        )
        mappings_storage.write_manifested_parquet(
            sample,
            broad_sample_path,
            artifact_type="broad_common_row_affected_output_sample",
            source_provenance={
                "conversion_type": "derived_from_converted_active_parquet",
                "source_path": broad_detail_path.relative_to(MAPPINGS_ROOT).as_posix(),
                "source_retained": True,
            },
        )
        mappings_storage.read_manifested_parquet(broad_sample_path)
        records.append(
            {
                "source": str(broad_detail_path),
                "destination": str(broad_sample_path),
                "status": "derived_and_verified",
                "rows": int(len(sample)),
            }
        )

    # Preserve details from earlier successful conversions when a resumed run
    # merely revalidates and skips the already-present destination.
    previous_records: list[dict[str, object]] = []
    if REPORT_PATH.exists():
        previous_records = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    merged = {
        (str(record.get("source", "")), str(record.get("destination", ""))): record
        for record in previous_records
    }
    for record in records:
        key = (str(record.get("source", "")), str(record.get("destination", "")))
        if record.get("status") != "skipped_existing_parquet" or key not in merged:
            merged[key] = record

    final_records = list(merged.values())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(final_records, indent=2) + "\n", encoding="utf-8")
    return final_records


#%%
RUN_ACTIVE_DIAGNOSTIC_CONVERSION = False

if RUN_ACTIVE_DIAGNOSTIC_CONVERSION:
    conversion_records = convert_active_diagnostic_csvs()
    print(pd.DataFrame(conversion_records).to_string(index=False))

#%%

#%%
"""Build an exact, read-only archive proposal for superseded migration caches."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import zlib
from datetime import datetime, timezone
from pathlib import Path


# --- Stable paths and archive rules ---

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_LABEL = "parquet_migration_20260816"
DIAGNOSTICS_ROOT = REPO_ROOT / "docs" / "diagnostics" / "parquet_migration"
MANIFEST_PATH = DIAGNOSTICS_ROOT / "archive_proposal_manifest.csv"
SUMMARY_PATH = DIAGNOSTICS_ROOT / "archive_proposal_summary.json"

SHARED_PICKLE_ROOTS = (
    REPO_ROOT
    / "outputs"
    / "leap_exports"
    / "supply_reconciliation"
    / "supporting_files"
    / "runtime",
    REPO_ROOT
    / "outputs"
    / "leap_exports"
    / "supply_reconciliation"
    / "baseline_seed"
    / "supporting_files"
    / "runtime",
)
REFERENCE_CACHE_ROOT = REPO_ROOT / "data" / ".cache"

MANIFEST_COLUMNS = (
    "batch_id",
    "repository",
    "relative_path",
    "byte_size",
    "modified_time_utc",
    "sha256",
    "reason_superseded",
    "replacement_logical_artifact",
    "planned_zip_filename",
    "planned_member_path",
    "selection_evidence",
)

ZIP_ESTIMATE_SAMPLE_BYTES = 4 * 1024 * 1024


# --- Safety and hashing helpers ---

def _is_reparse_point(path: Path) -> bool:
    """Return True for symlinks and Windows reparse points."""
    if path.is_symlink():
        return True
    stat_result = path.stat(follow_symlinks=False)
    file_attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_attribute = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(file_attributes & reparse_attribute)


def _assert_safe_candidate(path: Path) -> Path:
    """Resolve one file inside the repository without traversing a link."""
    candidate = path.resolve(strict=True)
    candidate.relative_to(REPO_ROOT.resolve(strict=True))
    current = path
    while True:
        if _is_reparse_point(current):
            raise ValueError(f"Archive proposal refuses reparse point: {current}")
        if current == REPO_ROOT:
            break
        current = current.parent
    if not candidate.is_file():
        raise ValueError(f"Archive candidate is not a regular file: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sampled_deflate_ratio(path: Path) -> tuple[float, int]:
    """Estimate ZIP deflate ratio from the start, middle and end of one file."""
    size = path.stat().st_size
    if size == 0:
        return 1.0, 0
    block_size = min(ZIP_ESTIMATE_SAMPLE_BYTES, size)
    offsets = sorted({0, max(0, (size - block_size) // 2), size - block_size})
    sampled_bytes = 0
    compressed_bytes = 0
    with path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            payload = handle.read(block_size)
            sampled_bytes += len(payload)
            compressed_bytes += len(zlib.compress(payload, level=6))
    ratio = compressed_bytes / sampled_bytes if sampled_bytes else 1.0
    return min(1.0, max(0.0, ratio)), sampled_bytes


def _estimate_batch_zip_size(rows: list[dict[str, object]]) -> tuple[int, int]:
    """Return a sampled ZIP-size estimate and the number of bytes sampled."""
    predicted_bytes = 0
    sampled_bytes = 0
    for row in rows:
        path = REPO_ROOT / str(row["relative_path"])
        ratio, file_sampled_bytes = _sampled_deflate_ratio(path)
        # Allow a small amount for local and central ZIP member headers.
        member_overhead = 160 + (2 * len(str(row["planned_member_path"])))
        predicted_bytes += round(int(row["byte_size"]) * ratio) + member_overhead
        sampled_bytes += file_sampled_bytes
    return predicted_bytes, sampled_bytes


def _manifest_row(
    *,
    path: Path,
    batch_id: str,
    reason_superseded: str,
    replacement_logical_artifact: str,
    planned_zip_filename: str,
    selection_evidence: str,
) -> dict[str, object]:
    candidate = _assert_safe_candidate(path)
    relative_path = candidate.relative_to(REPO_ROOT.resolve()).as_posix()
    stat_result = candidate.stat()
    return {
        "batch_id": batch_id,
        "repository": "leap_initialisation",
        "relative_path": relative_path,
        "byte_size": int(stat_result.st_size),
        "modified_time_utc": datetime.fromtimestamp(
            stat_result.st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "sha256": _sha256(candidate),
        "reason_superseded": reason_superseded,
        "replacement_logical_artifact": replacement_logical_artifact,
        "planned_zip_filename": planned_zip_filename,
        "planned_member_path": relative_path,
        "selection_evidence": selection_evidence,
    }


# --- Candidate selection ---

def collect_shared_pickle_candidates() -> list[dict[str, object]]:
    """Collect only shared caches; historical labelled-run caches stay live."""
    rows: list[dict[str, object]] = []
    for root in SHARED_PICKLE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.pkl")):
            replacement_family = path.parent.relative_to(REPO_ROOT).as_posix()
            rows.append(
                _manifest_row(
                    path=path,
                    batch_id="INIT-CACHE-PKL-001",
                    reason_superseded=(
                        "The production cache producer and consumer now use a "
                        "versioned checksummed Parquet/Zstandard bundle and no "
                        "code path reads pickle."
                    ),
                    replacement_logical_artifact=(
                        f"{replacement_family}/*.parquet_cache "
                        "(runtime-keyed and regenerated on demand)"
                    ),
                    planned_zip_filename="runtime_pickle_caches_001.zip",
                    selection_evidence=(
                        "Explicit shared runtime cache root; .pkl suffix; historical "
                        "runs/** paths excluded by construction; the live producer and "
                        "consumer use typed Parquet bundles and no live code reads pickle. "
                        "The current cache key is recalculated from runtime inputs, so an "
                        "obsolete pickle key is not represented as a same-key replacement."
                    ),
                )
            )
    return rows


def _replacement_family_for_old_reference_csv(path: Path) -> tuple[Path, Path, Path] | None:
    """Return the complete Parquet pair/meta only when all replacements exist."""
    name = path.name
    suffix = "_esto.csv" if name.endswith("_esto.csv") else "_ninth.csv"
    if not name.endswith(("_esto.csv", "_ninth.csv")):
        return None
    cache_key = name[: -len(suffix)]
    esto_parquet = path.parent / f"{cache_key}_esto.parquet"
    ninth_parquet = path.parent / f"{cache_key}_ninth.parquet"
    meta_path = path.parent / f"{cache_key}_meta.json"
    if not (esto_parquet.is_file() and ninth_parquet.is_file() and meta_path.is_file()):
        return None
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata.get("cache_storage") != {
        "format": "parquet",
        "compression": "zstd",
        "schema_version": "parquet-zstd-v1",
    }:
        return None
    return esto_parquet, ninth_parquet, meta_path


def collect_reference_csv_candidates() -> list[dict[str, object]]:
    """Collect old cache CSVs only when their exact-key Parquet pair is complete."""
    rows: list[dict[str, object]] = []
    if not REFERENCE_CACHE_ROOT.exists():
        return rows
    for path in sorted(REFERENCE_CACHE_ROOT.rglob("*.csv")):
        replacement_family = _replacement_family_for_old_reference_csv(path)
        if replacement_family is None:
            continue
        esto_parquet, ninth_parquet, meta_path = replacement_family
        replacement = esto_parquet if path.name.endswith("_esto.csv") else ninth_parquet
        rows.append(
            _manifest_row(
                path=path,
                batch_id="INIT-CACHE-CSV-001",
                reason_superseded=(
                    "The same cache key has a complete Parquet/Zstandard pair and "
                    "versioned metadata written last; the current loader ignores CSV caches."
                ),
                replacement_logical_artifact=(
                    replacement.relative_to(REPO_ROOT).as_posix()
                ),
                planned_zip_filename="augmented_reference_csv_caches_001.zip",
                selection_evidence=(
                    f"Exact-key replacements verified: {esto_parquet.name}, "
                    f"{ninth_parquet.name}, {meta_path.name}."
                ),
            )
        )
    return rows


# --- Proposal output ---

def write_archive_proposal() -> tuple[Path, Path]:
    """Hash candidates and write a proposal; never create archives or move files."""
    rows = collect_shared_pickle_candidates() + collect_reference_csv_candidates()
    rows.sort(key=lambda row: (str(row["batch_id"]), str(row["relative_path"])))
    DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    batches: dict[str, dict[str, object]] = {}
    for row in rows:
        batch = batches.setdefault(
            str(row["batch_id"]),
            {
                "file_count": 0,
                "original_bytes": 0,
                "planned_zip_filename": row["planned_zip_filename"],
            },
        )
        batch["file_count"] = int(batch["file_count"]) + 1
        batch["original_bytes"] = int(batch["original_bytes"]) + int(row["byte_size"])

    for batch_id, batch in batches.items():
        batch_rows = [row for row in rows if row["batch_id"] == batch_id]
        predicted_zip_bytes, sampled_bytes = _estimate_batch_zip_size(batch_rows)
        batch["predicted_zip_bytes"] = predicted_zip_bytes
        batch["zip_estimate_sampled_bytes"] = sampled_bytes
        batch["zip_estimate_method"] = (
            "Deflate level 6 sampled from up to 4 MiB at the start, middle and end "
            "of every proposed member; estimate includes approximate ZIP headers."
        )

    disk_usage = shutil.disk_usage(REPO_ROOT)

    summary = {
        "proposal_created_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "leap_initialisation",
        "archive_label": ARCHIVE_LABEL,
        "proposal_only": True,
        "originals_moved_or_deleted": False,
        "available_disk_bytes_at_proposal": disk_usage.free,
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "batches": batches,
        "explicit_exclusions": [
            "all outputs/**/runs/** historical and current run trees",
            "human-facing CSV/XLSX reports and workbooks",
            "published mapping/dashboard/review contracts",
            "source/configuration inputs",
            "Git metadata, worktrees, symlinks, junctions and other reparse points",
            "old reference CSV caches without a complete exact-key Parquet pair and metadata",
        ],
        "restoration_procedure": (
            "After an approved ZIP is created and verified, extract members at the "
            "leap_initialisation repository root so each stored repository-relative "
            "path is restored exactly; verify SHA-256 against the manifest before use."
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} proposed members to {MANIFEST_PATH}")
    print(f"Wrote proposal summary to {SUMMARY_PATH}")
    return MANIFEST_PATH, SUMMARY_PATH


# --- Run toggle ---

WRITE_ARCHIVE_PROPOSAL = False

if WRITE_ARCHIVE_PROPOSAL:
    ARCHIVE_PROPOSAL_OUTPUTS = write_archive_proposal()

#%%

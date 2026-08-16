#%%
"""Inventory tabular artifacts and read/write sites for the Parquet migration."""

from __future__ import annotations

import gzip
import os
import re
import stat
from collections import defaultdict
from pathlib import Path

import pandas as pd


# --- Stable configuration ---

REPOSITORIES = {
    "leap_initialisation": Path(r"C:\Users\Work\github\leap_initialisation"),
    "leap_mappings": Path(r"C:\Users\Work\github\leap_mappings"),
    "leap_dashboard": Path(r"C:\Users\Work\github\leap_dashboard"),
    "leap_review_tools": Path(r"C:\Users\Work\github\leap_review_tools"),
    "leap_review_web_app": Path(r"C:\Users\Work\github\leap_review_web_app"),
}

TABULAR_SUFFIXES = (
    ".csv",
    ".csv.gz",
    ".xlsx",
    ".xls",
    ".pkl",
    ".pickle",
    ".feather",
    ".arrow",
    ".parquet",
)
CODE_SUFFIXES = {".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".toml", ".yaml", ".yml"}
SKIP_DIRECTORY_NAMES = {
    ".git",
    ".claude",  # Separate worktrees are inventoried only through their owning roots.
    ".venv",
    "node_modules",
    "site-packages",
    "_internal",  # Frozen third-party libraries, not repository-owned artifacts.
    "__pycache__",
    ".pytest_cache",
}

READ_WRITE_PATTERNS = {
    "read_csv": re.compile(r"\b(?:pd\.)?read_csv\s*\("),
    "write_csv": re.compile(r"\.to_csv\s*\("),
    "read_excel": re.compile(r"\b(?:pd\.)?read_excel\s*\("),
    "write_excel": re.compile(r"\.to_excel\s*\(|ExcelWriter\s*\("),
    "read_pickle": re.compile(r"\bread_pickle\s*\(|pickle\.load\s*\(|_pickle\.load\s*\("),
    "write_pickle": re.compile(r"\.to_pickle\s*\(|pickle\.dump\s*\(|_pickle\.dump\s*\("),
    "read_parquet": re.compile(r"\bread_parquet\s*\("),
    "write_parquet": re.compile(r"\.to_parquet\s*\("),
    "read_feather_or_arrow": re.compile(r"\bread_feather\s*\(|pyarrow\.|\bipc\.open"),
    "write_feather_or_arrow": re.compile(r"\.to_feather\s*\(|\bipc\.new"),
}


# --- Filesystem and classification helpers ---

def _is_reparse_point(path: Path) -> bool:
    """Return True for Windows junctions/symlinks without following them."""
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (FileNotFoundError, OSError):
        return True


def iter_files(repo_root: Path):
    """Yield repository files while pruning Git metadata and all reparse points."""
    for current_root, directory_names, file_names in os.walk(repo_root, followlinks=False):
        current = Path(current_root)
        kept_directories = []
        for directory_name in directory_names:
            child = current / directory_name
            if directory_name in SKIP_DIRECTORY_NAMES or _is_reparse_point(child):
                continue
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories
        for file_name in file_names:
            path = current / file_name
            if not _is_reparse_point(path):
                yield path


def detect_format(path: Path) -> str | None:
    name = path.name.lower()
    for suffix in TABULAR_SUFFIXES:
        if name.endswith(suffix):
            return suffix.removeprefix(".")
    return None


def normalize_family_path(relative_path: str) -> str:
    """Collapse generated run IDs, cache hashes, and dated copies into families."""
    value = relative_path.replace("\\", "/")
    value = re.sub(r"(/runs/)[^/]+", r"\1{run_label}", value, flags=re.IGNORECASE)
    value = re.sub(r"(?i)(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])", "{cache_key}", value)
    value = re.sub(r"(?<!\d)20\d{6}(?:[_T-]?\d{4,6})?(?!\d)", "{timestamp}", value)
    value = re.sub(r"(?<!\d)20\d{2}[-_]\d{2}[-_]\d{2}(?!\d)", "{date}", value)
    return value


def classify_artifact(relative_path: str, file_format: str) -> tuple[str, str, str]:
    """Apply conservative policy classifications; uncertain human files stay retained."""
    lower = relative_path.lower().replace("\\", "/")
    is_output = lower.startswith(("outputs/", "results/", "release_build/"))
    is_runtime = "/runtime/" in lower or lower.startswith("runtime/")
    is_cache = "/.cache/" in lower or "/cache/" in lower or "_cache/" in lower
    is_browser = any(token in lower for token in ("chart_bundle", "browser", "static/"))
    is_human = any(
        token in lower
        for token in (
            "review",
            "audit",
            "diagnostic",
            "checks/",
            "findings",
            "summary",
            "manifest",
            "readiness",
            "leap_export",
            "baseline_seed",
        )
    )

    if file_format in {"pkl", "pickle"}:
        return "migrate", "high", "Python-only cache/intermediate; pickle is not an approved authority."
    if file_format in {"parquet", "feather", "arrow"}:
        return "migrate", "high", "Existing code-only typed columnar artifact."
    if is_browser:
        return "retain_browser", "high", "Browser-facing artifact family must remain web-readable."
    if file_format in {"xlsx", "xls"}:
        if is_output or lower.startswith("config/"):
            return "retain_human", "high", "Workbook semantics or direct human/LEAP use require reviewable format."
        return "retain_external", "medium", "Workbook is treated conservatively as an input until ownership is proven."
    if lower.startswith("data/") and not is_cache:
        return "retain_external", "high", "Source data is externally owned or intentionally interoperable."
    if is_runtime and not is_cache:
        return "retain_contract_temporarily", "high", "Packaged runtime contract must migrate with all consumers."
    if "/common_esto/" in lower or "mapping_chain" in lower or file_format == "csv.gz":
        return "retain_contract_temporarily", "high", "Published cross-repository contract requires atomic migration."
    if is_cache:
        return "migrate", "high", "Regenerable code-only cache."
    if is_human:
        return "retain_human", "medium", "Detailed output appears review-oriented; retain pending the decision register."
    if is_output:
        return "retain_human", "low", "Generated CSV use is ambiguous; retain pending human-format review."
    return "retain_external", "low", "Ownership/use is unclear; preserve until traced."


def read_csv_header(path: Path) -> str:
    """Read only the header line, including gzip-compressed CSVs."""
    try:
        opener = gzip.open if path.name.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8-sig", errors="replace", newline="") as handle:
            return handle.readline().strip()[:4000]
    except (OSError, UnicodeError) as exc:
        return f"<header unavailable: {type(exc).__name__}>"


def scan_code_sites(repository: str, repo_root: Path, repository_files: list[Path]) -> list[dict]:
    rows = []
    for path in repository_files:
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative_path = path.relative_to(repo_root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for operation, pattern in READ_WRITE_PATTERNS.items():
                if pattern.search(line):
                    rows.append(
                        {
                            "repository": repository,
                            "code_path": relative_path,
                            "line_number": line_number,
                            "operation": operation,
                            "direction": "write" if operation.startswith("write") else "read",
                            "evidence": line.strip()[:1000],
                        }
                    )
    return rows


def build_inventory() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    artifact_rows = []
    code_rows = []
    repo_commits = {}

    for repository, repo_root in REPOSITORIES.items():
        if not repo_root.exists():
            print(f"[WARN] Missing repository: {repo_root}")
            continue
        repository_files = list(iter_files(repo_root))
        code_rows.extend(scan_code_sites(repository, repo_root, repository_files))
        for path in repository_files:
            file_format = detect_format(path)
            if file_format is None:
                continue
            relative_path = path.relative_to(repo_root).as_posix()
            classification, confidence, reason = classify_artifact(relative_path, file_format)
            file_stat = path.stat()
            artifact_rows.append(
                {
                    "repository": repository,
                    "relative_path": relative_path,
                    "family_path_pattern": normalize_family_path(relative_path),
                    "format": file_format,
                    "compression": "gzip" if file_format == "csv.gz" else ("zstd/unknown" if file_format == "parquet" else "none_or_internal"),
                    "bytes": int(file_stat.st_size),
                    "modified_time": pd.Timestamp(file_stat.st_mtime, unit="s", tz="UTC").isoformat(),
                    "source_or_generated": "generated" if relative_path.lower().startswith(("outputs/", "results/", "release_build/")) or "/.cache/" in relative_path.lower() else "source_or_config",
                    "classification": classification,
                    "classification_confidence": confidence,
                    "classification_reason": reason,
                    "schema_or_header_preview": read_csv_header(path) if file_format in {"csv", "csv.gz"} else "",
                    "logical_primary_key": "unknown_pending_family_trace",
                    "ordering_significant": "unknown_pending_family_trace",
                    "regeneration_cost": "unknown_pending_family_trace",
                    "provenance": "repository path and mtime recorded; producer commit pending code trace",
                }
            )

    artifact_df = pd.DataFrame(artifact_rows)
    code_df = pd.DataFrame(code_rows)
    family_df = (
        artifact_df.groupby(
            [
                "repository",
                "family_path_pattern",
                "format",
                "compression",
                "source_or_generated",
                "classification",
                "classification_confidence",
                "classification_reason",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            file_count=("relative_path", "size"),
            total_bytes=("bytes", "sum"),
            typical_file_bytes=("bytes", "median"),
            largest_file_bytes=("bytes", "max"),
            representative_path=("relative_path", "first"),
            schema_or_header_preview=("schema_or_header_preview", "first"),
        )
        .sort_values(["total_bytes", "repository"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return artifact_df, family_df, code_df


def write_inventory_outputs(
    artifact_df: pd.DataFrame,
    family_df: pd.DataFrame,
    code_df: pd.DataFrame,
    diagnostics_dir: Path,
    trace_dir: Path,
) -> None:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)
    artifact_df.to_csv(trace_dir / "artifact_file_inventory.csv", index=False)
    family_df.to_csv(diagnostics_dir / "format_family_inventory.csv", index=False)
    code_df.to_csv(diagnostics_dir / "tabular_read_write_sites.csv", index=False)

    summary = (
        family_df.groupby(["repository", "format", "classification"], as_index=False)
        .agg(family_count=("family_path_pattern", "size"), file_count=("file_count", "sum"), total_bytes=("total_bytes", "sum"))
        .sort_values(["repository", "total_bytes"], ascending=[True, False])
    )
    summary.to_csv(diagnostics_dir / "inventory_summary.csv", index=False)

    print(f"Wrote {len(artifact_df):,} artifact rows, {len(family_df):,} families, and {len(code_df):,} code sites to {diagnostics_dir}")


# --- Notebook run toggles ---

GENERATE_INVENTORY = True
DIAGNOSTICS_DIR = Path("docs/diagnostics/parquet_migration")
TRACE_DIR = Path("outputs/parquet_migration/diagnostics")


#%%
if GENERATE_INVENTORY:
    try:
        artifact_inventory, family_inventory, code_site_inventory = build_inventory()
        write_inventory_outputs(
            artifact_df=artifact_inventory,
            family_df=family_inventory,
            code_df=code_site_inventory,
            diagnostics_dir=DIAGNOSTICS_DIR,
            trace_dir=TRACE_DIR,
        )
    except Exception as exc:
        print(f"[ERROR] Parquet migration inventory failed: {type(exc).__name__}: {exc}")
        raise

#%%

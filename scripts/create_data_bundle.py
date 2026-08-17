#%%
"""Create the portable source-data ZIP used to set up leap_initialisation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


# --- Stable bundle contract ---

REPO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_NAME = "leap_initialisation"
MANIFEST_NAME = "bundle_manifest.json"
SCHEMA_VERSION = 1

SOURCE_TABLE_PATHS = (
    Path("data/00APEC_2024_low_with_subtotals.csv"),
    Path("data/00APEC_2025_low_with_subtotals.csv"),
    Path("data/merged_file_energy_ALL_20251106.csv"),
    Path("data/9th merged_file_energy_00_APEC_20251106.csv"),
)
TEMPLATE_DIRECTORY = Path("data/leap_export_templates")
BALANCE_EXPORT_DIRECTORY = Path("data/leap balances exports")
ACTIVE_EXPORT_SUFFIXES = {".csv", ".xlsm", ".xlsx"}


def _git_commit(repo_root: Path) -> str:
    """Return the commit recorded in the manifest without requiring Git to exist."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"


def _is_active_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    lower_parts = {part.lower() for part in relative.parts}
    return (
        path.is_file()
        and "archive" not in lower_parts
        and ".archive" not in lower_parts
        and not path.name.startswith("~$")
        and not path.name.endswith(".inspect.ndjson")
        and path.name.lower() != "readme.md"
    )


def collect_bundle_files(repo_root: Path = REPO_ROOT) -> list[dict[str, object]]:
    """Collect current inputs only; generated outputs and archive folders are excluded."""
    selected: list[tuple[Path, str]] = [
        (repo_root / relative_path, "source_table")
        for relative_path in SOURCE_TABLE_PATHS
    ]

    template_root = repo_root / TEMPLATE_DIRECTORY
    selected.extend(
        (path, "leap_export_template")
        for path in template_root.glob("*.xlsx")
        if _is_active_file(path, template_root)
    )

    export_root = repo_root / BALANCE_EXPORT_DIRECTORY
    selected.extend(
        (path, "leap_balance_export")
        for path in export_root.rglob("*")
        if _is_active_file(path, export_root)
        and path.suffix.lower() in ACTIVE_EXPORT_SUFFIXES
    )

    missing = [path for path, _role in selected if not path.is_file()]
    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"Required bundle inputs are missing:\n{missing_text}")

    if not any(role == "leap_export_template" for _path, role in selected):
        raise FileNotFoundError(f"No active .xlsx templates found in {template_root}")
    if not any(role == "leap_balance_export" for _path, role in selected):
        raise FileNotFoundError(f"No active balance exports found in {export_root}")

    records = [
        {
            "path": path.relative_to(repo_root).as_posix(),
            "role": role,
            "size_bytes": path.stat().st_size,
        }
        for path, role in selected
    ]
    records.sort(key=lambda record: str(record["path"]).casefold())

    paths = [str(record["path"]) for record in records]
    if len(paths) != len(set(paths)):
        raise ValueError("The bundle file selection contains duplicate paths")
    return records


def default_bundle_path(repo_root: Path = REPO_ROOT) -> Path:
    commit = _git_commit(repo_root)
    short_commit = commit[:8] if commit != "unknown" else "uncommitted"
    date_text = datetime.now(timezone.utc).date().isoformat()
    return repo_root / "data_bundles" / f"{REPOSITORY_NAME}_data_{date_text}_{short_commit}.zip"


def create_data_bundle(
    repo_root: Path = REPO_ROOT,
    bundle_path: Path | None = None,
    replace_existing: bool = False,
) -> Path:
    """Write the ZIP atomically and return its resolved path."""
    repo_root = Path(repo_root).resolve()
    bundle_path = Path(bundle_path or default_bundle_path(repo_root)).resolve()
    if bundle_path.exists() and not replace_existing:
        raise FileExistsError(f"Bundle already exists: {bundle_path}")

    records = collect_bundle_files(repo_root=repo_root)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository_name": REPOSITORY_NAME,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_git_commit": _git_commit(repo_root),
        "file_count": len(records),
        "total_uncompressed_bytes": sum(int(record["size_bytes"]) for record in records),
        "files": records,
    }

    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{bundle_path.stem}_",
            suffix=".tmp",
            dir=bundle_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
            for record in records:
                relative_path = Path(str(record["path"]))
                archive.write(repo_root / relative_path, arcname=relative_path.as_posix())

        os.replace(temporary_path, bundle_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    print(f"Created {bundle_path}")
    print(f"Files: {manifest['file_count']:,}")
    print(f"Uncompressed data: {manifest['total_uncompressed_bytes'] / 1_000_000:.1f} MB")
    print(f"ZIP size: {bundle_path.stat().st_size / 1_000_000:.1f} MB")
    return bundle_path


#%%
# --- Frequently changed run settings ---

CREATE_BUNDLE = True
BUNDLE_PATH: Path | None = None
REPLACE_EXISTING_BUNDLE = False

if __name__ == "__main__" and CREATE_BUNDLE:
    create_data_bundle(
        repo_root=REPO_ROOT,
        bundle_path=BUNDLE_PATH,
        replace_existing=REPLACE_EXISTING_BUNDLE,
    )

#%%

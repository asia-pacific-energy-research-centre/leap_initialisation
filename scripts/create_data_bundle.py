#%%
"""Create the portable source-data ZIP used to set up leap_initialisation."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# --- Stable bundle contract ---

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.utilities.leap_export_template_resolver import is_excluded_template_file


REPOSITORY_NAME = "leap_initialisation"
SIBLING_REPOSITORY_NAME = "leap_mappings"
MANIFEST_NAME = "bundle_manifest.json"
SCHEMA_VERSION = 1

SOURCE_TABLE_PATHS = (
    Path("data/00APEC_2024_low_with_subtotals.csv"),
    Path("data/00APEC_2025_low_with_subtotals.csv"),
    Path("data/00APEC_2026_low_with_subtotals_PRELIMINARY.csv"),
    Path("data/merged_file_energy_ALL_20251106.csv"),
    Path("data/9th merged_file_energy_00_APEC_20251106.csv"),
)
TEMPLATE_DIRECTORY = Path("data/leap_export_templates")
BALANCE_EXPORT_DIRECTORY = Path("data/leap balances exports")
VALIDATION_EXCEPTION_PATH = Path("config/baseline_seed_validation_exception_sets.xlsx")
ACTIVE_EXPORT_SUFFIXES = {".csv", ".xlsm", ".xlsx"}


def _require_sibling_repository(repo_root: Path) -> Path:
    """Return the sibling mappings checkout required for paired bundle refreshes."""
    sibling_root = Path(repo_root).resolve().parent / SIBLING_REPOSITORY_NAME
    if not (sibling_root / ".git").exists():
        raise FileNotFoundError(
            "Coordinated data-bundle refresh requires the sibling "
            f"{SIBLING_REPOSITORY_NAME!r} repository at {sibling_root}. "
            "Clone it beside leap_initialisation before creating bundles."
        )
    return sibling_root


def _load_sibling_bundle_module(sibling_root: Path):
    module_path = sibling_root / "scripts" / "create_data_bundle.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"Sibling bundle creator not found: {module_path}")
    if str(sibling_root) not in sys.path:
        sys.path.insert(0, str(sibling_root))
    spec = importlib.util.spec_from_file_location("leap_mappings_create_data_bundle", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load sibling bundle creator: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    # This workbook carries the approved baseline-seed exceptions and is a
    # required process input, not a disposable local diagnostic.
    selected.append((repo_root / VALIDATION_EXCEPTION_PATH, "baseline_seed_validation_exceptions"))

    template_root = repo_root / TEMPLATE_DIRECTORY
    selected.extend(
        (path, "leap_export_template")
        for path in template_root.glob("*.xlsx")
        if _is_active_file(path, template_root)
        and not is_excluded_template_file(path)
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
    bundle_pair_id: str | None = None,
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
    if bundle_pair_id is not None:
        manifest["bundle_pair_id"] = bundle_pair_id

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


def create_coordinated_data_bundles(
    repo_root: Path = REPO_ROOT,
    *,
    bundle_path: Path | None = None,
    sibling_bundle_path: Path | None = None,
    replace_existing: bool = False,
) -> dict[str, Path]:
    """Create both sibling repositories' bundles as one visible refresh operation."""
    repo_root = Path(repo_root).resolve()
    sibling_root = _require_sibling_repository(repo_root)
    print(
        "[INFO] Coordinated bundle refresh: creating leap_initialisation and "
        "leap_mappings bundles together."
    )
    sibling_module = _load_sibling_bundle_module(sibling_root)
    # Check both source inventories before publishing either bundle.
    collect_bundle_files(repo_root)
    sibling_module.collect_bundle_files(sibling_root)
    bundle_pair_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid.uuid4().hex[:8]}"
    print(f"[INFO] Bundle pair ID: {bundle_pair_id}")
    paths = {
        REPOSITORY_NAME: create_data_bundle(
            repo_root=repo_root,
            bundle_path=bundle_path,
            replace_existing=replace_existing,
            bundle_pair_id=bundle_pair_id,
        ),
        SIBLING_REPOSITORY_NAME: sibling_module.create_data_bundle(
            repo_root=sibling_root,
            bundle_path=sibling_bundle_path,
            replace_existing=replace_existing,
            bundle_pair_id=bundle_pair_id,
        ),
    }
    print(f"[INFO] Coordinated bundle refresh complete: {paths}")
    return paths


#%%
# --- Frequently changed run settings ---

CREATE_BUNDLE = True
BUNDLE_PATH: Path | None = None
REPLACE_EXISTING_BUNDLE = False

if __name__ == "__main__" and CREATE_BUNDLE:
    create_coordinated_data_bundles(
        repo_root=REPO_ROOT,
        bundle_path=BUNDLE_PATH,
        replace_existing=REPLACE_EXISTING_BUNDLE,
    )

#%%

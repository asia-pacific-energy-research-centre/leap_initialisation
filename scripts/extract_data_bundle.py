#%%
"""Safely install a leap_initialisation data bundle into a repository clone."""

from __future__ import annotations

import filecmp
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath


# --- Stable bundle contract ---

REPO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_NAME = "leap_initialisation"
SIBLING_REPOSITORY_NAME = "leap_mappings"
MANIFEST_NAME = "bundle_manifest.json"
SCHEMA_VERSION = 1
REQUIRED_SOURCE_PATHS = {
    "data/00APEC_2024_low_with_subtotals.csv",
    "data/00APEC_2025_low_with_subtotals.csv",
    "data/merged_file_energy_ALL_20251106.csv",
    "data/9th merged_file_energy_00_APEC_20251106.csv",
}


def _require_sibling_repository(repo_root: Path) -> Path:
    """Return the sibling mappings checkout required for paired installs."""
    sibling_root = Path(repo_root).resolve().parent / SIBLING_REPOSITORY_NAME
    if not (sibling_root / ".git").exists():
        raise FileNotFoundError(
            "Coordinated data-bundle install requires the sibling "
            f"{SIBLING_REPOSITORY_NAME!r} repository at {sibling_root}. "
            "Clone it beside leap_initialisation and put its data bundle in "
            "leap_mappings/data_bundles before installing."
        )
    return sibling_root


def _load_sibling_bundle_module(sibling_root: Path):
    module_path = sibling_root / "scripts" / "extract_data_bundle.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"Sibling bundle extractor not found: {module_path}")
    if str(sibling_root) not in sys.path:
        sys.path.insert(0, str(sibling_root))
    spec = importlib.util.spec_from_file_location("leap_mappings_extract_data_bundle", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load sibling bundle extractor: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_latest_bundle(repo_root: Path = REPO_ROOT) -> Path:
    bundle_directory = Path(repo_root) / "data_bundles"
    candidates = sorted(
        bundle_directory.glob(f"{REPOSITORY_NAME}_data_*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No {REPOSITORY_NAME} data bundle found in {bundle_directory}")
    return candidates[0]


def _validate_member_name(name: str) -> None:
    if "\\" in name or ":" in name:
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    if name != MANIFEST_NAME and path.parts[0] != "data":
        raise ValueError(f"Unexpected path outside data/: {name!r}")


def _load_and_validate_manifest(archive: zipfile.ZipFile) -> tuple[dict[str, object], list[str]]:
    infos = archive.infolist()
    names = [info.filename for info in infos if not info.is_dir()]
    for name in names:
        _validate_member_name(name)
    if len(names) != len(set(names)):
        raise ValueError("The ZIP contains duplicate file paths")
    if MANIFEST_NAME not in names:
        raise ValueError(f"The ZIP does not contain {MANIFEST_NAME}")

    manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported bundle schema: {manifest.get('schema_version')!r}")
    if manifest.get("repository_name") != REPOSITORY_NAME:
        raise ValueError(f"Bundle is for {manifest.get('repository_name')!r}, not {REPOSITORY_NAME!r}")

    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("Manifest files must be a non-empty list")
    manifest_paths = [str(record.get("path", "")) for record in records]
    for path in manifest_paths:
        _validate_member_name(path)
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ValueError("Manifest contains duplicate file paths")
    if set(names) != {MANIFEST_NAME, *manifest_paths}:
        raise ValueError("ZIP contents do not exactly match the manifest")
    if not REQUIRED_SOURCE_PATHS.issubset(manifest_paths):
        missing = sorted(REQUIRED_SOURCE_PATHS.difference(manifest_paths))
        raise ValueError(f"Manifest is missing required source files: {missing}")
    if int(manifest.get("file_count", -1)) != len(records):
        raise ValueError("Manifest file_count does not match its file list")

    info_by_name = {info.filename: info for info in infos}
    expected_total = 0
    for record in records:
        path = str(record["path"])
        expected_size = int(record["size_bytes"])
        expected_total += expected_size
        if info_by_name[path].file_size != expected_size:
            raise ValueError(f"Stored size does not match the manifest for {path}")
    if int(manifest.get("total_uncompressed_bytes", -1)) != expected_total:
        raise ValueError("Manifest total_uncompressed_bytes is incorrect")
    return manifest, manifest_paths


def _open_data_bundle(bundle_path: Path) -> zipfile.ZipFile:
    """Open a data bundle, unwrapping the single ZIP Google Drive may create."""
    archive = zipfile.ZipFile(bundle_path, mode="r")
    if MANIFEST_NAME in archive.namelist():
        return archive

    file_members = [info for info in archive.infolist() if not info.is_dir()]
    nested_zips = [info for info in file_members if info.filename.lower().endswith(".zip")]
    if len(file_members) != 1 or len(nested_zips) != 1:
        archive.close()
        raise ValueError(
            "ZIP is not a data bundle or a single-file wrapper around one. "
            f"Expected {MANIFEST_NAME} or one inner .zip file."
        )

    inner_info = nested_zips[0]
    extracted_inner = bundle_path.parent / f".{uuid.uuid4().hex}.bundle.zip"
    try:
        with archive.open(inner_info) as source, extracted_inner.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    except Exception:
        extracted_inner.unlink(missing_ok=True)
        archive.close()
        raise
    archive.close()
    try:
        inner_archive = zipfile.ZipFile(extracted_inner, mode="r")
    except Exception:
        extracted_inner.unlink(missing_ok=True)
        raise
    # The caller closes this handle; attach the disposable wrapper path so it
    # can be removed after validation and staging.
    inner_archive._leap_wrapper_path = extracted_inner  # type: ignore[attr-defined]
    return inner_archive


def extract_data_bundle(
    bundle_path: Path,
    repo_root: Path = REPO_ROOT,
    allow_overwrite: bool = False,
) -> list[Path]:
    """Validate, stage, and atomically install bundle files into repo_root/data."""
    bundle_path = Path(bundle_path).resolve()
    repo_root = Path(repo_root).resolve()
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    if not (repo_root / ".git").exists():
        raise FileNotFoundError(f"Target is not a Git repository clone: {repo_root}")

    archive = _open_data_bundle(bundle_path)
    wrapper_path = getattr(archive, "_leap_wrapper_path", None)
    try:
        manifest, manifest_paths = _load_and_validate_manifest(archive)
        with tempfile.TemporaryDirectory(prefix=f"{REPOSITORY_NAME}_bundle_") as staging_text:
            staging_root = Path(staging_text)
            for relative_text in manifest_paths:
                staged_path = staging_root / Path(relative_text)
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(relative_text, mode="r") as source, staged_path.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

            records = {str(record["path"]): record for record in manifest["files"]}
            for relative_text in manifest_paths:
                staged_path = staging_root / Path(relative_text)
                if staged_path.stat().st_size != int(records[relative_text]["size_bytes"]):
                    raise ValueError(f"Extracted size does not match the manifest for {relative_text}")

            conflicts = []
            for relative_text in manifest_paths:
                target_path = repo_root / Path(relative_text)
                staged_path = staging_root / Path(relative_text)
                if target_path.exists() and not filecmp.cmp(target_path, staged_path, shallow=False):
                    conflicts.append(relative_text)
            if conflicts and not allow_overwrite:
                conflict_text = "\n".join(conflicts)
                raise FileExistsError(
                    "Refusing to replace different existing files. Set ALLOW_OVERWRITE=True "
                    f"only after reviewing them:\n{conflict_text}"
                )

            installed: list[Path] = []
            for relative_text in manifest_paths:
                target_path = repo_root / Path(relative_text)
                staged_path = staging_root / Path(relative_text)
                if target_path.exists() and filecmp.cmp(target_path, staged_path, shallow=False):
                    installed.append(target_path)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    prefix=f".{target_path.name}_",
                    suffix=".tmp",
                    dir=target_path.parent,
                    delete=False,
                ) as temporary_file:
                    temporary_target = Path(temporary_file.name)
                try:
                    shutil.copy2(staged_path, temporary_target)
                    os.replace(temporary_target, target_path)
                except Exception:
                    temporary_target.unlink(missing_ok=True)
                    raise
                installed.append(target_path)

    finally:
        archive.close()
        if wrapper_path is not None:
            Path(wrapper_path).unlink(missing_ok=True)

    template_count = len(list((repo_root / "data/leap_export_templates").glob("*.xlsx")))
    export_count = sum(1 for path in (repo_root / "data/leap balances exports").rglob("*") if path.is_file())
    if template_count == 0 or export_count == 0:
        raise RuntimeError("Extraction finished but template/export readiness checks failed")

    print(f"Installed {len(installed):,} files from {bundle_path.name}")
    print(f"Templates available: {template_count:,}; balance exports available: {export_count:,}")
    return installed


def extract_coordinated_data_bundles(
    bundle_path: Path,
    repo_root: Path = REPO_ROOT,
    *,
    sibling_bundle_path: Path | None = None,
    allow_overwrite: bool = False,
) -> dict[str, list[Path]]:
    """Install both sibling bundles so code and mapping inputs stay aligned."""
    repo_root = Path(repo_root).resolve()
    sibling_root = _require_sibling_repository(repo_root)
    sibling_module = _load_sibling_bundle_module(sibling_root)
    selected_sibling_bundle = sibling_bundle_path or sibling_module.find_latest_bundle(sibling_root)
    print(
        "[INFO] Coordinated bundle install: installing leap_initialisation and "
        "leap_mappings bundles together."
    )
    installed = {
        REPOSITORY_NAME: extract_data_bundle(
            bundle_path=bundle_path,
            repo_root=repo_root,
            allow_overwrite=allow_overwrite,
        ),
        SIBLING_REPOSITORY_NAME: sibling_module.extract_data_bundle(
            bundle_path=selected_sibling_bundle,
            repo_root=sibling_root,
            allow_overwrite=allow_overwrite,
        ),
    }
    print("[INFO] Coordinated bundle install complete.")
    return installed


#%%
# --- Frequently changed run settings ---

EXTRACT_BUNDLE = True
BUNDLE_PATH: Path | None = None
ALLOW_OVERWRITE = False

if __name__ == "__main__" and EXTRACT_BUNDLE:
    selected_bundle = BUNDLE_PATH or find_latest_bundle(REPO_ROOT)
    extract_coordinated_data_bundles(
        bundle_path=selected_bundle,
        repo_root=REPO_ROOT,
        allow_overwrite=ALLOW_OVERWRITE,
    )

#%%

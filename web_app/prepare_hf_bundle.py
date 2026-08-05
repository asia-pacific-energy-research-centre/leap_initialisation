#%%
"""Prepare a small, self-contained Hugging Face runtime bundle locally.

The preparation function reads the existing portable-release manifest, copies
only its declared runtime code/configuration/data assets from the three sibling
repositories, adds the developer launcher needed by the Gradio app, and writes
source commit provenance. It is intended to be called from a notebook or an
interactive Python session before publishing ``leap_review_web_app``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PARENT = REPO_ROOT.parent
DEFAULT_OUTPUT_REPOSITORY = DEFAULT_SOURCE_PARENT / "leap_review_web_app"
MANIFEST_PATH = REPO_ROOT / "config" / "portable_release_manifest.toml"

REQUIRED_REPOSITORIES = (
    "leap_initialisation",
    "leap_mappings",
    "leap_dashboard",
)

# The web app uses developer_launcher even though the portable executable
# manifest deliberately excludes maintainer-only launcher modules.
EXTRA_RUNTIME_PATHS = {
    "leap_initialisation": (
        "codebase/portable_release/developer_launcher.py",
        "codebase/portable_release/settings.py",
        "config/portable_release_manifest.toml",
    )
}


def _normalise_path(path: object) -> Path:
    return Path(str(path).replace("\\", "/"))


def _git_metadata(repository_root: Path) -> dict[str, object]:
    """Return the source commit and dirty state for one repository."""
    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        check=True,
        text=True,
    )
    status_result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repository_root,
        capture_output=True,
        check=True,
        text=True,
    )
    return {
        "commit": commit_result.stdout.strip(),
        "dirty": bool(status_result.stdout.strip()),
    }


def _copy_file(
    *,
    source_root: Path,
    output_root: Path,
    relative_path: str,
    copied_files: list[str],
    dry_run: bool,
) -> None:
    relative = _normalise_path(relative_path)
    source = source_root / relative
    destination = output_root / relative
    if not source.is_file():
        raise FileNotFoundError(f"Required bundle source is missing: {source}")
    copied_files.append(relative.as_posix())
    if dry_run:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def prepare_hf_bundle(
    *,
    source_parent: Path | str = DEFAULT_SOURCE_PARENT,
    output_repository: Path | str = DEFAULT_OUTPUT_REPOSITORY,
    dry_run: bool = False,
    allow_dirty_sources: bool = False,
) -> dict[str, Any]:
    """Copy the declared runtime closure into a publishable HF repository.

    ``source_parent`` must contain the three sibling repositories. The output
    repository is created if needed, but existing ``hf_bundle`` contents are
    replaced only after all source repositories and manifest entries validate.
    """
    source_parent_path = _normalise_path(source_parent).resolve()
    output_repository_path = _normalise_path(output_repository).resolve()
    manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    repositories = manifest.get("repositories") or {}
    config_assets = manifest.get("config_assets") or []
    data_assets = manifest.get("data_assets") or []

    source_roots = {
        name: source_parent_path / name for name in REQUIRED_REPOSITORIES
    }
    missing_repositories = [
        name for name, path in source_roots.items() if not (path / ".git").exists()
    ]
    if missing_repositories:
        raise FileNotFoundError(
            "Missing sibling repositories: " + ", ".join(missing_repositories)
        )

    source_metadata = {
        name: _git_metadata(path) for name, path in source_roots.items()
    }
    dirty_sources = [
        name for name, metadata in source_metadata.items() if metadata["dirty"]
    ]
    if dirty_sources and not allow_dirty_sources:
        raise RuntimeError(
            "Source repositories have uncommitted changes: "
            + ", ".join(dirty_sources)
            + ". Commit them first or pass allow_dirty_sources=True."
        )

    copied_by_repository: dict[str, list[str]] = {
        name: [] for name in REQUIRED_REPOSITORIES
    }

    # Validate every source path before deleting/replacing a previous bundle.
    copy_plan: list[tuple[str, str]] = []
    for repository_name, specification in repositories.items():
        source_name = specification.get("source_key", repository_name)
        if source_name not in source_roots:
            continue
        for relative_path in specification.get("paths") or []:
            copy_plan.append((source_name, str(relative_path)))
    for asset in [*config_assets, *data_assets]:
        source_name = str(asset["repository"])
        copy_plan.append((source_name, str(asset["path"])))
    for source_name, paths in EXTRA_RUNTIME_PATHS.items():
        copy_plan.extend((source_name, path) for path in paths)

    deduplicated_plan = list(dict.fromkeys(copy_plan))
    for source_name, relative_path in deduplicated_plan:
        source = source_roots[source_name] / _normalise_path(relative_path)
        if not source.is_file():
            raise FileNotFoundError(f"Required bundle source is missing: {source}")

    bundle_root = output_repository_path / "hf_bundle"
    if not dry_run:
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        bundle_root.mkdir(parents=True, exist_ok=True)

    for source_name, relative_path in deduplicated_plan:
        _copy_file(
            source_root=source_roots[source_name],
            output_root=bundle_root / source_name,
            relative_path=relative_path,
            copied_files=copied_by_repository[source_name],
            dry_run=dry_run,
        )

    manifest_output = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "source_repositories": source_metadata,
        "file_counts": {
            name: len(paths) for name, paths in copied_by_repository.items()
        },
        "dry_run": dry_run,
    }
    if not dry_run:
        (bundle_root / "source_manifest.json").write_text(
            json.dumps(manifest_output, indent=2), encoding="utf-8"
        )
    return {
        "bundle_root": bundle_root,
        "manifest": manifest_output,
        "copied_files": copied_by_repository,
    }


#%%
# Notebook controls. Set this to True for the first validation pass; set it to
# False only after reviewing the dry-run file counts and source commits.
PREPARE_BUNDLE = False

if PREPARE_BUNDLE:
    BUNDLE_RESULT = prepare_hf_bundle()
    print(json.dumps(BUNDLE_RESULT["manifest"], indent=2))

#%%

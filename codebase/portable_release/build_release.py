#%%
"""Build a portable Windows release from the commits a manifest declares.

The builder never packages "whatever happens to be in a working tree". Every
source file is read out of Git at the exact commit the manifest pins, using
``git cat-file``, so a release is reproducible from the manifest alone and a
maintainer's uncommitted work-in-progress can never leak into a colleague's
copy. The maintainer's checkouts are only ever read: no ``checkout``, no
``reset``, no ``stash``, no temporary branch.

Configuration assets are handled separately and deliberately: they are copied to
an external ``config/`` directory in the package, not embedded in the
executable, so an approved mapping or template can be replaced without a
rebuild. Their SHA-256 values are recorded in the release report and re-hashed
into every run manifest.

Notebook use::

    from codebase.portable_release import build_release
    build_release.validate_only()          # check the manifest, build nothing
    build_release.build(freeze=True)       # stage + PyInstaller --onedir
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.portable_release.commands import IMPLEMENTED_COMMANDS  # noqa: E402
from codebase.portable_release.manifest import (  # noqa: E402
    ManifestValidationReport,
    ReleaseManifest,
    ReleaseManifestError,
    load_release_manifest,
    validate_release_manifest,
)
from codebase.portable_release import workspace  # noqa: E402
from codebase.portable_release.provenance import sha256_file  # noqa: E402
from codebase.portable_release.settings import (  # noqa: E402
    DeveloperSettingsError,
    detect_repository_roots,
    load_developer_settings,
)


DEFAULT_MANIFEST_PATH = REPO_ROOT / "config" / "portable_release_manifest.toml"
#: Generated staging/build/package trees. Ignored by Git and safe to delete by
#: hand: the builder never creates a symlink or junction inside it.
DEFAULT_BUILD_ROOT = REPO_ROOT / "release_build"

PACKAGE_DIRECTORIES = ("code", "config", "data", "input", "output", "logs", "licenses")

#: Name of the isolated mapping-chain worker executable. Must match what
#: codebase/portable_release/mapping_chain_client.py looks for at
#: ``package_root / "mapping-chain" / f"{WORKER_EXECUTABLE_NAME}.exe"``.
WORKER_EXECUTABLE_NAME = "leap-mapping-chain"


class ReleaseBuildError(RuntimeError):
    """Raised when a release cannot be built."""


@dataclass
class BuildReport:
    """What a build produced."""

    manifest_name: str
    manifest_version: str
    built_utc: str
    staging_dir: Path
    package_dir: Path | None
    frozen: bool
    validation: ManifestValidationReport
    source_files: list[dict[str, Any]] = field(default_factory=list)
    config_files: list[dict[str, Any]] = field(default_factory=list)
    data_files: list[dict[str, Any]] = field(default_factory=list)
    package_files: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "release": {"name": self.manifest_name, "version": self.manifest_version},
            "built_utc": self.built_utc,
            "staging_dir": str(self.staging_dir),
            "package_dir": str(self.package_dir) if self.package_dir else None,
            "frozen": self.frozen,
            "validation": {
                "ok": self.validation.ok,
                "errors": self.validation.errors,
                "warnings": self.validation.warnings,
                "source_files_checked": self.validation.checked_source_files,
                "config_assets_checked": self.validation.checked_config_assets,
                "data_assets_checked": self.validation.checked_data_assets,
                "data_asset_bytes": self.validation.data_asset_bytes,
            },
            "source_files": self.source_files,
            "config_files": self.config_files,
            "data_files": self.data_files,
            "package_files": self.package_files,
            "notes": self.notes,
        }

    def as_text(self) -> str:
        lines = [
            f"Release build report: {self.manifest_name} {self.manifest_version}",
            "=" * 72,
            f"Built (UTC)  : {self.built_utc}",
            f"Staging      : {self.staging_dir}",
            f"Package      : {self.package_dir or '(staging only)'}",
            f"Frozen build : {'yes' if self.frozen else 'no'}",
            "",
            f"Source files staged from pinned commits: {len(self.source_files)}",
            "-" * 72,
        ]
        for item in self.source_files:
            lines.append(f"  {item['repository']:<20} {item['path']}")
            lines.append(f"    -> {item['staged_as']}  sha256={item['sha256']}")
        lines += ["", f"Configuration assets: {len(self.config_files)}", "-" * 72]
        for item in self.config_files:
            lines.append(f"  {item['role']:<34} {item['dest']}")
            lines.append(
                f"    from {item['repository']}:{item['path']}  "
                f"({item['source']})  sha256={item['sha256']}"
            )
        if self.data_files:
            total_data = sum(int(item["size_bytes"]) for item in self.data_files)
            lines += [
                "",
                f"Source data tables: {len(self.data_files)} ({total_data:,} bytes)",
                "-" * 72,
            ]
            for item in self.data_files:
                lines.append(
                    f"  {item['role']:<34} {item['dest']}  ({item['size_bytes']:,} bytes)"
                )
                lines.append(
                    f"    from {item['repository']}:{item['path']}  "
                    f"({item['source']})  sha256={item['sha256']}"
                )
        if self.package_files:
            total = sum(int(item["size_bytes"]) for item in self.package_files)
            lines += [
                "",
                f"Package contents: {len(self.package_files)} files, {total:,} bytes",
                "-" * 72,
            ]
        for note in self.notes:
            lines.append(f"[note] {note}")
        for warning in self.validation.warnings:
            lines.append(f"[warning] {warning}")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Repository resolution
# ---------------------------------------------------------------------------


def resolve_repository_roots(
    manifest: ReleaseManifest,
    overrides: Mapping[str, Path] | None = None,
) -> dict[str, Path]:
    """Resolve each declared repository to a local checkout.

    Order: explicit overrides, then the developer settings file, then sibling
    directories next to this repository. The builder only ever reads them.
    """
    roots: dict[str, Path] = {}
    detected = detect_repository_roots()
    try:
        settings_roots = dict(load_developer_settings().repositories)
    except DeveloperSettingsError:
        settings_roots = {}
    for key, spec in manifest.repositories.items():
        # A second repository entry may point at a checkout already named by
        # another entry (leap_mappings' single flat file for the main exe vs.
        # its full closure for the worker exe) — `source_key` says which
        # checkout to resolve, while `key` still identifies this entry.
        lookup_key = spec.source_key or key
        if overrides and key in overrides:
            roots[key] = Path(overrides[key])
        elif overrides and lookup_key in overrides:
            roots[key] = Path(overrides[lookup_key])
        elif lookup_key in settings_roots:
            roots[key] = Path(settings_roots[lookup_key])
        elif lookup_key in detected:
            roots[key] = detected[lookup_key]
        else:
            raise ReleaseBuildError(
                f"Could not locate a checkout of {lookup_key!r} (for repositories.{key}). "
                "Add it to your developer settings file, or pass repository_roots={...} "
                "to build()."
            )
    return roots


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseBuildError(
            f"git {' '.join(args)} failed in {root}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _stage_sources(
    manifest: ReleaseManifest,
    roots: Mapping[str, Path],
    code_root: Path,
) -> list[dict[str, Any]]:
    """Copy every allowlisted module out of Git at its pinned commit."""
    staged: list[dict[str, Any]] = []
    for key, spec in manifest.repositories.items():
        root = Path(roots[key])
        for path in spec.paths:
            payload = _git_bytes(root, "cat-file", "blob", f"{spec.commit}:{path}")
            relative = spec.staged_relative_path(path)
            target = code_root / relative
            _write_bytes(target, payload)
            staged.append(
                {
                    "repository": key,
                    "commit": spec.commit,
                    "path": path,
                    "staged_as": relative.as_posix(),
                    "size_bytes": len(payload),
                    "sha256": sha256_file(target),
                }
            )
        # Namespace-package directories (leap_mappings' mapping_tools has no
        # __init__.py) work as implicit namespace packages, so nothing else is
        # needed here beyond the files the manifest allowlists.
    return staged


def _stage_config_assets(
    manifest: ReleaseManifest,
    roots: Mapping[str, Path],
    config_root: Path,
) -> list[dict[str, Any]]:
    """Copy the reviewed configuration assets into the external config folder."""
    staged: list[dict[str, Any]] = []
    for asset in manifest.config_assets:
        spec = manifest.repositories[asset.repository]
        root = Path(roots[asset.repository])
        target = config_root / asset.dest
        try:
            payload = _git_bytes(root, "cat-file", "blob", f"{spec.commit}:{asset.path}")
            source = f"commit {spec.commit[:12]}"
        except ReleaseBuildError:
            working_copy = root / asset.path
            if not working_copy.is_file():
                raise ReleaseBuildError(
                    f"Configuration asset {asset.path!r} is neither tracked at "
                    f"{spec.commit[:12]} nor present in {root}."
                ) from None
            payload = working_copy.read_bytes()
            source = "working tree (not tracked at the pinned commit)"
        _write_bytes(target, payload)
        staged.append(
            {
                "role": asset.role,
                "repository": asset.repository,
                "path": asset.path,
                "dest": asset.dest,
                "source": source,
                "size_bytes": len(payload),
                "sha256": sha256_file(target),
            }
        )
    return staged


def _stage_data_assets(
    manifest: ReleaseManifest,
    roots: Mapping[str, Path],
    data_root: Path,
) -> list[dict[str, Any]]:
    """Copy the large read-only source tables into the package's data folder.

    These are streamed from the working tree when they are not tracked, which is
    the normal case: the ESTO and 9th-edition tables are restored from shared
    archives rather than committed. Either way the copy is hashed, so the exact
    table a release carries is always identifiable.
    """
    staged: list[dict[str, Any]] = []
    for asset in manifest.data_assets:
        spec = manifest.repositories[asset.repository]
        root = Path(roots[asset.repository])
        target = data_root / asset.dest
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = _git_bytes(root, "cat-file", "blob", f"{spec.commit}:{asset.path}")
            target.write_bytes(payload)
            source = f"commit {spec.commit[:12]}"
        except ReleaseBuildError:
            working_copy = root / asset.path
            if not working_copy.is_file():
                raise ReleaseBuildError(
                    f"Source data table {asset.path!r} is neither tracked at "
                    f"{spec.commit[:12]} nor present in {root}."
                ) from None
            # Copied rather than read into memory: these run to hundreds of MB.
            shutil.copyfile(working_copy, target)
            source = "working tree (not tracked at the pinned commit)"
        staged.append(
            {
                "role": asset.role,
                "repository": asset.repository,
                "path": asset.path,
                "dest": asset.dest,
                "source": source,
                "size_bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )
    return staged


#: The user-facing guide shipped at the package's top level, read from the
#: pinned leap_initialisation commit like everything else. A colleague who
#: receives only a ZIP should not also need an accompanying email.
USER_GUIDE_SOURCE_PATH = "docs/docx/leap_review_tools_user_guide.docx"
USER_GUIDE_PACKAGE_NAME = "LEAP Review Tools - user guide.docx"


def _stage_user_guide(
    package_root: Path,
    manifest: ReleaseManifest,
    roots: Mapping[str, Path],
) -> str | None:
    """Copy the user guide into the package, or explain why it is absent."""
    spec = manifest.repositories.get("leap_initialisation")
    if spec is None:
        return "No leap_initialisation entry; user guide not shipped."
    root = Path(roots["leap_initialisation"])
    try:
        payload = _git_bytes(
            root, "cat-file", "blob", f"{spec.commit}:{USER_GUIDE_SOURCE_PATH}"
        )
    except ReleaseBuildError:
        return (
            f"User guide not shipped: {USER_GUIDE_SOURCE_PATH} is not committed at "
            f"{spec.commit[:12]}. Regenerate it with "
            "`python scripts/convert_docs.py --docs-dir docs` and commit it."
        )
    (package_root / USER_GUIDE_PACKAGE_NAME).write_bytes(payload)
    return None


def _write_package_scaffold(
    package_root: Path,
    manifest: ReleaseManifest,
    *,
    config_files: Sequence[Mapping[str, Any]],
) -> None:
    """Create the package's folder layout and its README."""
    for name in PACKAGE_DIRECTORIES:
        (package_root / name).mkdir(parents=True, exist_ok=True)
    # Scaffold the folder the documentation actually tells users to fill, and
    # put the naming rules next to it. A bare "put files here" placeholder left
    # the package contradicting its own guide: the guide says
    # input\leap balances exports\<ECONOMY>\, and that folder did not exist.
    exports_root = package_root / "input" / workspace.BALANCE_EXPORTS_DIRNAME
    exports_root.mkdir(parents=True, exist_ok=True)
    (exports_root / "README.md").write_text(workspace.INPUT_README, encoding="utf-8")
    (package_root / "output" / "RESULTS_APPEAR_HERE.txt").write_text(
        "Results appear here, grouped by economy, so nothing is overwritten:\n"
        "  output/<ECONOMY>/balance_review/   workbooks for that economy\n"
        "  output/<ECONOMY>/dashboard/        that economy's dashboard\n"
        "Each run also leaves a record under run_records/ beside its results,\n"
        "holding the run manifest and the input validation report.\n",
        encoding="utf-8",
    )
    (package_root / "logs" / "LOGS_APPEAR_HERE.txt").write_text(
        "Run logs are written here. A support bundle collects these together "
        "with the run manifest, and never includes input data.\n",
        encoding="utf-8",
    )
    (package_root / "licenses" / "README.txt").write_text(
        "Third-party licence texts for the packaged runtime belong here.\n"
        "The freeze step does not collect them automatically; add them before "
        "distributing this release outside the team.\n",
        encoding="utf-8",
    )

    command_lines = []
    for spec in manifest.commands:
        command_lines.append(f"### {spec.name}")
        command_lines.append("")
        command_lines.append(spec.summary)
        command_lines.append("")
        command_lines.append(f"Input mode: `{spec.input_mode}`")
        command_lines.append("")
        command_lines.append("Inputs:")
        for item in spec.inputs:
            flag = "required" if item.required else "optional"
            command_lines.append(f"- `{item.key}` ({item.kind}, {flag}) — {item.description}")
        command_lines.append("")
        command_lines.append(f"Produces: {spec.outputs}")
        command_lines.append("")

    config_lines = [
        f"- `config/{item['dest']}` — {item['role']}" for item in config_files
    ]

    (package_root / "README.md").write_text(
        "\n".join(
            [
                f"# {manifest.name} {manifest.version}",
                "",
                manifest.description,
                "",
                "## Running it",
                "",
                "Double-click the executable in this folder for a guided flow, or "
                "run it from a terminal:",
                "",
                "```",
                f"{manifest.name}.exe info",
                f"{manifest.name}.exe balance-review --help",
                "```",
                "",
                "## Folders",
                "",
                "- `input/` — put your input files here",
                "- `output/` — one dated folder per run, with results and a run manifest",
                "- `logs/` — run logs",
                "- `config/` — approved mapping and template files (editable, see below)",
                "- `code/` — the packaged program modules",
                "- `licenses/` — third-party licence texts",
                "",
                "## Commands",
                "",
                *command_lines,
                "## Updating configuration without a new release",
                "",
                "The files under `config/` are read at start-up and their SHA-256 "
                "values are recorded in every run manifest. Replacing one with an "
                "approved newer version changes the next run's behaviour and is "
                "visible in that run's manifest — no rebuild is needed.",
                "",
                *config_lines,
                "",
                "A **code** change, by contrast, always needs a new tested release.",
                "",
                "## Getting help",
                "",
                "If a run fails, send the support bundle (`--support-bundle`). It "
                "contains the run manifest, the validation report, the effective "
                "settings, and the logs — and deliberately no input data.",
                "",
            ]
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Freezing
# ---------------------------------------------------------------------------


#: Hidden imports for the main review-tools executable. pandas reaches
#: zoneinfo through a Cython module, so the dependency is invisible to static
#: analysis and the pure-Python half of the stdlib package is otherwise left
#: behind next to _zoneinfo.pyd — both targets need this entry.
_ZONEINFO_HIDDEN_IMPORTS = ["'zoneinfo'", "'tzdata'"]

MAIN_HIDDEN_IMPORTS = [
    "'codebase.portable_release.commands'",
    "'codebase.portable_release.portable_main'",
    "'codebase.portable_release.runtime'",
    "'codebase.portable_release.validation'",
    "'codebase.portable_release.provenance'",
    "'codebase.portable_release.mapping_chain_client'",
    "'codebase.functions.balance_review_workbook_builder'",
    "'codebase.functions.balance_review_workbooks'",
    "'codebase.utilities.leap_balance_export_resolver'",
    "'codebase.utilities.output_paths'",
    "'codebase.configuration.workflow_config'",
    "'common_esto_dashboard_portable'",
    "'common_esto_dashboard_data'",
    "'common_esto_dashboard_renderer'",
    "'common_esto_dashboard_output_layout'",
    "'mapping_tools.source_branch_preflight'",
    *_ZONEINFO_HIDDEN_IMPORTS,
]

#: The worker's own imports are all static top-level `from codebase.x import y`
#: statements (no importlib/dynamic loading in its closure — checked by
#: grepping codebase/mapping_tools and codebase/utilities in leap_mappings), so
#: PyInstaller's Analysis discovers the whole closure by following
#: entry_point_worker.py -> codebase.portable_mapping_chain. Only the
#: Cython-hidden stdlib dependency needs to be listed explicitly.
WORKER_HIDDEN_IMPORTS = [
    "'codebase.portable_mapping_chain'",
    *_ZONEINFO_HIDDEN_IMPORTS,
]


#: Registry CSVs the worker's mapping_tools modules read via module-level
#: (import-time) defaults from `Path(__file__).resolve().parents[2]`, rather
#: than through an explicit job/config path. They must land inside the
#: worker's own PyInstaller bundle at the same relative location those
#: modules resolve when frozen (`sys._MEIPASS/config/datasets/`) - see the
#: matching `sys._MEIPASS` fallback added to each registry module in
#: leap_mappings (handover §3.3 build notes).
WORKER_DATASET_REGISTRY_DIR = "config/datasets"


def _worker_data_bundles(
    manifest: ReleaseManifest, roots: Mapping[str, Path]
) -> list[tuple[Path, str]]:
    """Return the (source, dest) data bundles the worker target needs.

    Only ``leap_mappings_worker`` needs this today; the loop is written to
    stay correct if a future worker-target repository needs its own bundled
    data too.
    """
    bundles: list[tuple[Path, str]] = []
    for key, spec in manifest.repositories_for_target("worker").items():
        registry_dir = Path(roots[key]) / WORKER_DATASET_REGISTRY_DIR
        if registry_dir.is_dir():
            bundles.append((registry_dir, WORKER_DATASET_REGISTRY_DIR))
    return bundles


def _pyinstaller_spec(
    *,
    name: str,
    entry_point: Path,
    stage_dirs: Sequence[Path],
    code_root: Path,
    hidden: Sequence[str],
    datas: Sequence[tuple[Path, str]] = (),
) -> str:
    """Return a PyInstaller spec for a one-folder Windows build.

    A one-folder build is used rather than ``--onefile`` so the package stays
    inspectable, starts without unpacking to a temporary directory, and keeps
    ``config/`` genuinely external and editable.

    Generic over which executable it builds: the caller supplies the entry
    point, the ``sys.path`` stage directories, and the hidden-import list, so
    the same function produces both the main review-tools executable and the
    isolated mapping-chain worker (handover §1/§3.3) — each Analysis only ever
    sees the stage dirs for its own target, which is what keeps the two
    ``codebase`` packages from colliding: isolation by construction, not by
    discipline.

    ``datas`` bundles non-Python files the target's own modules read at import
    time (or by a default argument) rather than via an explicit job/config
    path - the worker's registry CSVs under ``config/datasets/`` are the
    reason this exists (handover §3.3 build notes).
    """
    pathex = [f"r'{path.as_posix()}'" for path in stage_dirs] + [f"r'{code_root.as_posix()}'"]
    data_entries = [f"(r'{src.as_posix()}', r'{dest}')" for src, dest in datas]
    return f"""# Generated by codebase/portable_release/build_release.py - do not edit by hand.
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    [r'{entry_point.as_posix()}'],
    pathex=[{', '.join(pathex)}],
    binaries=[],
    datas=[{', '.join(data_entries)}],
    hiddenimports=[{', '.join(hidden)}],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'IPython', 'win32com', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='{name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='{name}',
)
"""


def _entry_point_source(stage_dirs: Sequence[str], *, import_line: str, call: str) -> str:
    """Return a generated entry point for a package with these stage dirs.

    The stage directory names are baked in rather than discovered by scanning,
    because when this script is the frozen application's entry point its
    directory is PyInstaller's ``_internal`` bundle — scanning that and putting
    every subdirectory on ``sys.path`` shadows standard-library modules with
    third-party package internals.

    When frozen, the program modules are inside the bundle and ``sys.path``
    needs no help at all. ``import_line``/``call`` let the same generator
    produce both the main executable's entry point and the mapping-chain
    worker's — each with only its own target's stage dirs on ``sys.path``.
    """
    listed = ", ".join(repr(name) for name in stage_dirs)
    return f'''"""Portable release entry point. Generated by the release builder."""

import sys
from pathlib import Path

STAGE_DIRS = [{listed}]

if not getattr(sys, "frozen", False):
    # Staged (unfrozen) package: the program modules live in sibling folders
    # next to this file. A frozen build has them inside its own bundle.
    _HERE = Path(__file__).resolve().parent
    for _name in reversed(STAGE_DIRS):
        _candidate = str(_HERE / _name)
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)

{import_line}

if __name__ == "__main__":
    raise SystemExit({call})
'''


def _main_entry_point_source(stage_dirs: Sequence[str]) -> str:
    return _entry_point_source(
        stage_dirs,
        import_line="from codebase.portable_release.portable_main import main",
        call="main()",
    )


def _worker_entry_point_source(stage_dirs: Sequence[str]) -> str:
    return _entry_point_source(
        stage_dirs,
        import_line="from codebase.portable_mapping_chain import main",
        call="main()",
    )


def _freeze_target(
    *,
    name: str,
    entry_point: Path,
    stage_dirs: Sequence[Path],
    code_root: Path,
    hidden: Sequence[str],
    build_root: Path,
    label: str,
    datas: Sequence[tuple[Path, str]] = (),
) -> tuple[Path, list[str]]:
    """Run PyInstaller for one executable target and return its built folder.

    PyInstaller resolves imports through the *build process's* own import
    environment as well as the spec's ``pathex``. Running it in-process from a
    checkout is therefore actively dangerous: the maintainer's live ``codebase``
    package sits on ``sys.path`` and gets baked into the executable in place of
    the staged one — which is exactly what a portable release must never do, and
    it fails at start-up on a machine with no LEAP COM API.

    So it runs as a subprocess, from a directory that contains none of the
    repositories, with ``PYTHONPATH``/``PYTHONHOME`` stripped. Each target
    (``label``) gets its own isolated cwd, spec, dist, and work directory so a
    concurrent or sequential second build cannot see the first target's
    intermediate state — this is also what stops the worker's Analysis from
    ever seeing the main target's stage dirs, and vice versa.
    """
    notes: list[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise ReleaseBuildError(
            "PyInstaller is not installed in this interpreter, so the executable "
            "cannot be built. Install it with:\n"
            f"    {sys.executable} -m pip install pyinstaller\n"
            "or call build(freeze=False) to produce the staged folder only."
        ) from exc

    target_root = build_root / label
    dist_dir = target_root / "dist"
    work_dir = target_root / "pyinstaller_work"
    isolation_dir = target_root / "pyinstaller_cwd"
    isolation_dir.mkdir(parents=True, exist_ok=True)
    spec_path = target_root / f"{name}.spec"
    spec_path.write_text(
        _pyinstaller_spec(
            name=name,
            entry_point=entry_point,
            stage_dirs=stage_dirs,
            code_root=code_root,
            hidden=hidden,
            datas=datas,
        ),
        encoding="utf-8",
    )

    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(spec_path),
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            "--noconfirm",
            "--clean",
        ],
        cwd=str(isolation_dir),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path = target_root / "pyinstaller.log"
    log_path.write_text(
        f"$ {' '.join([sys.executable, '-m', 'PyInstaller', str(spec_path)])}\n"
        f"cwd={isolation_dir}\nexit={result.returncode}\n\n"
        f"{result.stdout}\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise ReleaseBuildError(
            f"PyInstaller failed for {label!r} target (exit {result.returncode}). "
            f"Full log: {log_path}\n" + "\n".join(result.stderr.splitlines()[-20:])
        )
    built = dist_dir / name
    if not built.is_dir():
        raise ReleaseBuildError(f"PyInstaller did not produce {built}.")
    notes.append(f"PyInstaller spec ({label}): {spec_path}")
    notes.append(f"PyInstaller log ({label}): {log_path}")
    return built, notes


def verify_frozen_package(package_root: Path, executable_name: str) -> dict[str, Any]:
    """Run the built executable's ``info`` and ``selfcheck`` commands.

    This is the build's own proof that the package works: it runs from a
    directory unrelated to any repository, with ``PYTHONPATH`` stripped, so an
    import that reached back into a checkout shows up here rather than on a
    colleague's machine.

    ``info`` alone is not enough. A packaged program can start and print its own
    version while a missing hidden import or a shadowed standard-library module
    waits to break the first real run — which is exactly what happened once.
    ``selfcheck`` imports every module a command needs and checks that each
    standard-library module it relies on is the real one.
    """
    executable = package_root / f"{executable_name}.exe"
    if not executable.is_file():
        executable = package_root / executable_name
    if not executable.is_file():
        raise ReleaseBuildError(f"No executable found in {package_root}.")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    outputs: dict[str, str] = {}
    for command in ("info", "selfcheck"):
        result = subprocess.run(
            [str(executable), command],
            cwd=str(package_root.parent),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        outputs[command] = result.stdout
        if result.returncode != 0:
            raise ReleaseBuildError(
                f"The built executable failed `{command}`:\n"
                + (result.stdout + "\n" + result.stderr).strip()[-4000:]
            )
    return {
        "executable": str(executable),
        "selfcheck": outputs["selfcheck"].strip().splitlines()[-1].strip(),
    }


def verify_frozen_worker(worker_root: Path, executable_name: str) -> dict[str, Any]:
    """Run the built mapping-chain worker's ``--self-test`` and check its JSON.

    Mirrors :func:`verify_frozen_package`: run from a directory unrelated to any
    repository, with ``PYTHONPATH`` stripped, so a worker whose Analysis leaked
    into the main target's ``codebase`` package (or failed to bundle its own)
    fails here instead of on a colleague's machine.
    """
    executable = worker_root / f"{executable_name}.exe"
    if not executable.is_file():
        executable = worker_root / executable_name
    if not executable.is_file():
        raise ReleaseBuildError(f"No worker executable found in {worker_root}.")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    result = subprocess.run(
        [str(executable), "--self-test"],
        cwd=str(worker_root.parent),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseBuildError(
            f"The mapping-chain worker failed `--self-test`:\n"
            + (result.stdout + "\n" + result.stderr).strip()[-4000:]
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise ReleaseBuildError(
            f"The mapping-chain worker's --self-test output was not valid JSON: {exc}\n"
            f"Raw output: {result.stdout[:2000]}"
        ) from exc
    if not payload.get("ok"):
        raise ReleaseBuildError(f"The mapping-chain worker reported not ok: {payload}")
    return {"executable": str(executable), "self_test": payload}


# ---------------------------------------------------------------------------
# Package hygiene
# ---------------------------------------------------------------------------

FORBIDDEN_PACKAGE_SEGMENTS = frozenset(
    {".git", ".codex", ".claude", "node_modules", "__pycache__", ".pytest_cache", ".venv"}
)


def inspect_package(package_root: Path) -> dict[str, Any]:
    """Return the package's file list plus anything that must not be shipped."""
    files: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in sorted(package_root.rglob("*")):
        relative = path.relative_to(package_root).as_posix()
        if path.is_symlink() or (path.is_dir() and _is_reparse_point(path)):
            problems.append(f"{relative} is a symlink or junction and must not be shipped.")
            continue
        if any(part in FORBIDDEN_PACKAGE_SEGMENTS for part in path.parts):
            problems.append(f"{relative} is under a forbidden directory.")
            continue
        if path.is_file():
            files.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return {"files": files, "problems": problems}


def _is_reparse_point(path: Path) -> bool:
    """Detect a Windows junction, which ``Path.is_symlink`` does not report."""
    try:
        attributes = path.lstat().st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_only(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    repository_roots: Mapping[str, Path] | None = None,
) -> ManifestValidationReport:
    """Validate the manifest against real repositories without building anything."""
    manifest = load_release_manifest(manifest_path)
    roots = resolve_repository_roots(manifest, repository_roots)
    report = validate_release_manifest(
        manifest,
        roots,
        known_command_names=IMPLEMENTED_COMMANDS,
    )
    print(report.as_text())
    return report


def build(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    build_root: Path | str = DEFAULT_BUILD_ROOT,
    repository_roots: Mapping[str, Path] | None = None,
    freeze: bool = True,
    clean: bool = True,
) -> BuildReport:
    """Stage and (optionally) freeze a portable release.

    ``freeze=False`` produces the staged package only. That is a complete,
    runnable program for anyone who already has a suitable Python; the freeze
    step is what removes the Python prerequisite for a colleague.
    """
    manifest = load_release_manifest(manifest_path)
    roots = resolve_repository_roots(manifest, repository_roots)
    validation = validate_release_manifest(
        manifest,
        roots,
        known_command_names=IMPLEMENTED_COMMANDS,
    )
    if not validation.ok:
        raise ReleaseManifestError(validation.errors)

    build_dir = Path(str(build_root).replace("\\", "/"))
    staging_dir = build_dir / "staging" / manifest.package_stem
    if clean and staging_dir.exists():
        shutil.rmtree(staging_dir)
    code_root = staging_dir / "code"
    config_root = staging_dir / "config"
    for name in PACKAGE_DIRECTORIES:
        (staging_dir / name).mkdir(parents=True, exist_ok=True)

    source_files = _stage_sources(manifest, roots, code_root)
    config_files = _stage_config_assets(manifest, roots, config_root)
    data_files = _stage_data_assets(manifest, roots, staging_dir / "data")
    (code_root / "entry_point.py").write_text(
        _main_entry_point_source(manifest.sys_path_stage_dirs("main")),
        encoding="utf-8",
    )
    has_worker_target = bool(manifest.repositories_for_target("worker"))
    if has_worker_target:
        (code_root / "entry_point_worker.py").write_text(
            _worker_entry_point_source(manifest.sys_path_stage_dirs("worker")),
            encoding="utf-8",
        )

    frozen_manifest = manifest.to_frozen_dict()
    staged_data_by_role = {item["role"]: item for item in data_files}
    for asset in frozen_manifest["data_assets"]:
        staged = staged_data_by_role[asset["role"]]
        asset.update(
            {
                "source": staged["source"],
                "size_bytes": staged["size_bytes"],
                "sha256": staged["sha256"],
            }
        )
    frozen_manifest["built_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (staging_dir / "release_manifest.json").write_text(
        json.dumps(frozen_manifest, indent=2),
        encoding="utf-8",
    )
    _write_package_scaffold(staging_dir, manifest, config_files=config_files)
    guide_note = _stage_user_guide(staging_dir, manifest, roots)

    report = BuildReport(
        manifest_name=manifest.name,
        manifest_version=manifest.version,
        built_utc=frozen_manifest["built_utc"],
        staging_dir=staging_dir,
        package_dir=None,
        frozen=False,
        validation=validation,
        source_files=source_files,
        config_files=config_files,
        data_files=data_files,
        notes=[guide_note] if guide_note else [],
    )

    package_dir = staging_dir
    if freeze:
        main_stage_dirs = [code_root / d for d in manifest.sys_path_stage_dirs("main")]
        built, notes = _freeze_target(
            name=manifest.name,
            entry_point=code_root / "entry_point.py",
            stage_dirs=main_stage_dirs,
            code_root=code_root,
            hidden=MAIN_HIDDEN_IMPORTS,
            build_root=build_dir,
            label="main",
        )
        report.notes.extend(notes)
        package_dir = build_dir / "package" / manifest.package_stem
        if package_dir.exists():
            shutil.rmtree(package_dir)
        package_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built, package_dir)
        # The frozen executable carries the code; config, input, output, logs,
        # licenses, the README, and the release manifest stay external.
        for name in ("config", "data", "input", "output", "logs", "licenses"):
            shutil.copytree(staging_dir / name, package_dir / name, dirs_exist_ok=True)
        # Every top-level file staged, not a hardcoded list: the user guide was
        # written into staging and then silently left behind here, because this
        # loop named only the two files that existed when it was written.
        for staged_file in sorted(staging_dir.iterdir()):
            if staged_file.is_file():
                shutil.copy2(staged_file, package_dir / staged_file.name)
        report.frozen = True
        verification = verify_frozen_package(package_dir, manifest.name)
        report.notes.append(
            f"Executable info + selfcheck passed: {verification['executable']} "
            f"({verification['selfcheck']})"
        )

        if has_worker_target:
            worker_stage_dirs = [code_root / d for d in manifest.sys_path_stage_dirs("worker")]
            worker_datas = _worker_data_bundles(manifest, roots)
            worker_built, worker_notes = _freeze_target(
                name=WORKER_EXECUTABLE_NAME,
                entry_point=code_root / "entry_point_worker.py",
                stage_dirs=worker_stage_dirs,
                code_root=code_root,
                hidden=WORKER_HIDDEN_IMPORTS,
                build_root=build_dir,
                label="worker",
                datas=worker_datas,
            )
            report.notes.extend(worker_notes)
            worker_package_dir = package_dir / "mapping-chain"
            if worker_package_dir.exists():
                shutil.rmtree(worker_package_dir)
            shutil.copytree(worker_built, worker_package_dir)
            worker_verification = verify_frozen_worker(worker_package_dir, WORKER_EXECUTABLE_NAME)
            report.notes.append(
                f"Mapping-chain worker --self-test passed: "
                f"{worker_verification['executable']} ({worker_verification['self_test']})"
            )
        else:
            report.notes.append(
                "No repositories declared target = \"worker\" in the manifest; "
                "the mapping-chain worker executable was not built (handover §3.4)."
            )

    report.package_dir = package_dir
    inspection = inspect_package(package_dir)
    report.package_files = inspection["files"]
    if inspection["problems"]:
        raise ReleaseBuildError(
            "The built package contains content that must not be distributed:\n  - "
            + "\n  - ".join(inspection["problems"])
        )

    report_dir = build_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{manifest.package_stem}_{report.built_utc.replace(':', '').replace('-', '')}"
    (report_dir / f"{stem}.json").write_text(
        json.dumps(report.as_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    (report_dir / f"{stem}.txt").write_text(report.as_text(), encoding="utf-8")
    print(report.as_text())
    print(f"Release report: {report_dir / f'{stem}.txt'}")
    return report


#%%
# ---------------------------------------------------------------------------
# NOTEBOOK CONTROLS
# ---------------------------------------------------------------------------
RUN_RELEASE_BUILD = False

# "validate" checks the manifest and builds nothing.
# "stage" produces the staged package folder without PyInstaller.
# "build" produces the staged folder and the frozen one-folder package.
RELEASE_ACTION = "validate"
MANIFEST_PATH = DEFAULT_MANIFEST_PATH
BUILD_ROOT = DEFAULT_BUILD_ROOT

if RUN_RELEASE_BUILD:
    if RELEASE_ACTION == "validate":
        BUILD_RESULT = validate_only(MANIFEST_PATH)
    elif RELEASE_ACTION == "stage":
        BUILD_RESULT = build(MANIFEST_PATH, build_root=BUILD_ROOT, freeze=False)
    elif RELEASE_ACTION == "build":
        BUILD_RESULT = build(MANIFEST_PATH, build_root=BUILD_ROOT, freeze=True)
    else:
        raise ValueError(f"Unknown RELEASE_ACTION: {RELEASE_ACTION!r}")

#%%

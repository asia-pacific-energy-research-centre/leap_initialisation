"""Release manifest: the reviewed contract for what a portable release contains.

The manifest is the single declaration of a release. It names the exact commit
of every participating repository, every source file that may be copied, every
external configuration asset, the supported commands and their input/output
contract, and the runtime packages the package needs.

Nothing else decides what goes into a package. :func:`validate_release_manifest`
is deliberately strict: a manifest that references a missing commit or file, that
allowlists a path escaping a repository root, that allowlists a private,
generated, or non-module path, or that declares a command with no implementation
is rejected before any staging happens. A build fails loudly rather than
shipping a partial program.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1

SEMANTIC_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
STAGE_DIR_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")

#: Path segments that must never appear in an allowlisted path. These cover
#: version-control internals, agent/tooling private directories, dependency and
#: cache trees, and this workspace's generated / large-input output trees.
DENIED_PATH_SEGMENTS = frozenset(
    {
        ".git",
        ".codex",
        ".claude",
        ".vscode",
        ".idea",
        ".venv",
        "venv",
        "env_leap",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ipynb_checkpoints",
        "archive",
        ".archive",
        "exploration",
        "scrapbook",
        "outputs",
        "output",
        "results",
        "intermediate_data",
        "data",
        "tmp",
        "temp",
        "htmlcov",
        "build",
        "dist",
        "site-packages",
    }
)

#: Source allowlists carry whole Python modules only. Anything else belongs in
#: ``config_assets`` so it can be replaced without rebuilding the executable.
ALLOWED_SOURCE_SUFFIXES = frozenset({".py"})

#: Configuration/template assets are distributed under the package's external
#: ``config/`` directory and hashed into every run manifest.
ALLOWED_CONFIG_SUFFIXES = frozenset(
    {".json", ".csv", ".toml", ".yaml", ".yml", ".md", ".txt", ".xlsx"}
)

#: A configuration asset larger than this is almost certainly generated data
#: rather than reviewed configuration, so the manifest refuses it.
MAX_CONFIG_ASSET_BYTES = 8 * 1024 * 1024

VALID_INPUT_KINDS = frozenset({"file", "directory"})


class ReleaseManifestError(ValueError):
    """Raised when a release manifest is malformed or fails validation."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        joined = "\n  - ".join(self.problems)
        super().__init__(f"Release manifest is not valid:\n  - {joined}")


@dataclass(frozen=True)
class RepositorySpec:
    """One participating repository, pinned to an exact commit."""

    key: str
    commit: str
    stage_dir: str
    paths: tuple[str, ...]
    #: Prefix stripped from each path when staging, so a repository whose modules
    #: are imported flat (``import common_esto_dashboard_data``) stages flat.
    strip_prefix: str = ""
    #: Whether the staged directory is added to the packaged app's ``sys.path``.
    on_sys_path: bool = True

    def staged_relative_path(self, path: str) -> PurePosixPath:
        """Return the path of *path* inside the package, relative to the stage root."""
        pure = PurePosixPath(path)
        if self.strip_prefix:
            prefix = PurePosixPath(self.strip_prefix)
            pure = pure.relative_to(prefix)
        return PurePosixPath(self.stage_dir) / pure


@dataclass(frozen=True)
class ConfigAssetSpec:
    """One reviewed configuration/template file distributed outside the executable."""

    repository: str
    path: str
    dest: str
    role: str
    description: str = ""


@dataclass(frozen=True)
class CommandInputSpec:
    """One input a supported command requires from the user."""

    key: str
    kind: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class CommandSpec:
    """A supported command and its input/output contract."""

    name: str
    summary: str
    input_mode: str
    inputs: tuple[CommandInputSpec, ...]
    outputs: str


@dataclass(frozen=True)
class ReleaseManifest:
    """The parsed release contract."""

    schema_version: int
    name: str
    version: str
    description: str
    runtime_python: str
    runtime_packages: tuple[str, ...]
    repositories: Mapping[str, RepositorySpec]
    config_assets: tuple[ConfigAssetSpec, ...]
    commands: tuple[CommandSpec, ...]
    source_path: Path | None = None

    @property
    def package_stem(self) -> str:
        """Return the versioned package folder name, e.g. ``leap-review-tools-0.1.0``."""
        return f"{self.name}-{self.version}"

    def command(self, name: str) -> CommandSpec:
        for spec in self.commands:
            if spec.name == name:
                return spec
        available = ", ".join(sorted(spec.name for spec in self.commands))
        raise KeyError(f"Unknown command {name!r}. Available commands: {available}")

    def sys_path_stage_dirs(self) -> tuple[str, ...]:
        return tuple(
            spec.stage_dir for spec in self.repositories.values() if spec.on_sys_path
        )

    def to_frozen_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable form written into a built package."""
        return {
            "schema_version": self.schema_version,
            "release": {
                "name": self.name,
                "version": self.version,
                "description": self.description,
            },
            "runtime": {
                "python": self.runtime_python,
                "packages": list(self.runtime_packages),
            },
            "repositories": {
                key: {
                    "commit": spec.commit,
                    "stage_dir": spec.stage_dir,
                    "strip_prefix": spec.strip_prefix,
                    "on_sys_path": spec.on_sys_path,
                    "paths": list(spec.paths),
                }
                for key, spec in self.repositories.items()
            },
            "config_assets": [
                {
                    "repository": asset.repository,
                    "path": asset.path,
                    "dest": asset.dest,
                    "role": asset.role,
                    "description": asset.description,
                }
                for asset in self.config_assets
            ],
            "commands": [
                {
                    "name": spec.name,
                    "summary": spec.summary,
                    "input_mode": spec.input_mode,
                    "outputs": spec.outputs,
                    "inputs": [
                        {
                            "key": item.key,
                            "kind": item.kind,
                            "required": item.required,
                            "description": item.description,
                        }
                        for item in spec.inputs
                    ],
                }
                for spec in self.commands
            ],
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _require(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ReleaseManifestError([f"{context} is missing required key {key!r}."])
    return mapping[key]


def _as_str_tuple(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ReleaseManifestError([f"{context} must be a list of strings."])
    return tuple(value)


def parse_release_manifest(text: str, *, source_path: Path | None = None) -> ReleaseManifest:
    """Parse manifest TOML into a :class:`ReleaseManifest` without touching Git."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseManifestError([f"Manifest is not valid TOML: {exc}"]) from exc

    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ReleaseManifestError(
            [
                f"Unsupported schema_version {schema_version!r}; "
                f"this builder understands {SCHEMA_VERSION}."
            ]
        )

    release = _require(raw, "release", "manifest")
    runtime = raw.get("runtime", {})

    repositories: dict[str, RepositorySpec] = {}
    for key, block in (raw.get("repositories") or {}).items():
        context = f"repositories.{key}"
        repositories[key] = RepositorySpec(
            key=key,
            commit=str(_require(block, "commit", context)),
            stage_dir=str(_require(block, "stage_dir", context)),
            paths=_as_str_tuple(_require(block, "paths", context), f"{context}.paths"),
            strip_prefix=str(block.get("strip_prefix", "")),
            on_sys_path=bool(block.get("on_sys_path", True)),
        )

    config_assets: list[ConfigAssetSpec] = []
    for index, block in enumerate(raw.get("config_assets") or []):
        context = f"config_assets[{index}]"
        config_assets.append(
            ConfigAssetSpec(
                repository=str(_require(block, "repository", context)),
                path=str(_require(block, "path", context)),
                dest=str(_require(block, "dest", context)),
                role=str(_require(block, "role", context)),
                description=str(block.get("description", "")),
            )
        )

    commands: list[CommandSpec] = []
    for index, block in enumerate(raw.get("commands") or []):
        context = f"commands[{index}]"
        inputs: list[CommandInputSpec] = []
        for input_index, item in enumerate(block.get("inputs") or []):
            item_context = f"{context}.inputs[{input_index}]"
            inputs.append(
                CommandInputSpec(
                    key=str(_require(item, "key", item_context)),
                    kind=str(_require(item, "kind", item_context)),
                    description=str(_require(item, "description", item_context)),
                    required=bool(item.get("required", True)),
                )
            )
        commands.append(
            CommandSpec(
                name=str(_require(block, "name", context)),
                summary=str(_require(block, "summary", context)),
                input_mode=str(_require(block, "input_mode", context)),
                inputs=tuple(inputs),
                outputs=str(_require(block, "outputs", context)),
            )
        )

    return ReleaseManifest(
        schema_version=int(schema_version),
        name=str(_require(release, "name", "release")),
        version=str(_require(release, "version", "release")),
        description=str(release.get("description", "")),
        runtime_python=str(runtime.get("python", "")),
        runtime_packages=_as_str_tuple(runtime.get("packages", []), "runtime.packages"),
        repositories=repositories,
        config_assets=tuple(config_assets),
        commands=tuple(commands),
        source_path=source_path,
    )


def load_release_manifest(path: Path | str) -> ReleaseManifest:
    """Read and parse a manifest file."""
    manifest_path = Path(str(path).replace("\\", "/"))
    if not manifest_path.exists():
        raise ReleaseManifestError([f"Manifest file does not exist: {manifest_path}"])
    return parse_release_manifest(
        manifest_path.read_text(encoding="utf-8"),
        source_path=manifest_path,
    )


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def path_safety_problems(path: str, *, context: str) -> list[str]:
    """Return every reason *path* is unsafe to copy out of a repository."""
    problems: list[str] = []
    if not path or path != path.strip():
        problems.append(f"{context}: path {path!r} is blank or has surrounding whitespace.")
        return problems
    if "\\" in path:
        problems.append(
            f"{context}: path {path!r} must use forward slashes so it is platform-neutral."
        )
        return problems

    pure = PurePosixPath(path)
    if pure.is_absolute():
        problems.append(f"{context}: path {path!r} must be relative to the repository root.")
    if re.match(r"^[A-Za-z]:", path):
        problems.append(f"{context}: path {path!r} must not contain a drive letter.")
    if ".." in pure.parts:
        problems.append(f"{context}: path {path!r} escapes the repository root.")

    denied = sorted(DENIED_PATH_SEGMENTS.intersection(part.lower() for part in pure.parts))
    if denied:
        problems.append(
            f"{context}: path {path!r} is under a private, generated, or cache "
            f"directory ({', '.join(denied)}) and must not be packaged."
        )
    return problems


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_exists(root: Path, commit: str) -> bool:
    return _git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def _tree_entry(root: Path, commit: str, path: str) -> tuple[str, str] | None:
    """Return ``(mode, type)`` for *path* at *commit*, or ``None`` when absent."""
    result = _git(root, "ls-tree", "-z", commit, "--", path)
    if result.returncode != 0 or not result.stdout.strip("\0"):
        return None
    first = result.stdout.split("\0")[0]
    meta, _, _ = first.partition("\t")
    parts = meta.split(" ")
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class ManifestValidationReport:
    """Outcome of validating a manifest against real repositories."""

    manifest_name: str
    manifest_version: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_source_files: int = 0
    checked_config_assets: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_text(self) -> str:
        lines = [
            f"Release manifest validation: {self.manifest_name} {self.manifest_version}",
            f"  source files checked : {self.checked_source_files}",
            f"  config assets checked: {self.checked_config_assets}",
            f"  result               : {'OK' if self.ok else 'FAILED'}",
        ]
        for warning in self.warnings:
            lines.append(f"  [warning] {warning}")
        for error in self.errors:
            lines.append(f"  [error]   {error}")
        return "\n".join(lines)


def validate_release_manifest(
    manifest: ReleaseManifest,
    repository_roots: Mapping[str, Path],
    *,
    known_command_names: Iterable[str] = (),
    check_git: bool = True,
) -> ManifestValidationReport:
    """Validate a manifest against the real repositories it names.

    ``check_git=False`` skips commit/file existence checks and validates only the
    declarative contract, which is what unit tests and offline reviews need.
    """
    report = ManifestValidationReport(
        manifest_name=manifest.name,
        manifest_version=manifest.version,
    )
    errors = report.errors

    if not SEMANTIC_VERSION_PATTERN.match(manifest.version):
        errors.append(
            f"release.version {manifest.version!r} is not a semantic version (MAJOR.MINOR.PATCH)."
        )
    if not manifest.name:
        errors.append("release.name must not be blank.")
    if not manifest.repositories:
        errors.append("At least one repository must be declared.")
    if not manifest.commands:
        errors.append("At least one command must be declared.")
    if not manifest.runtime_packages:
        errors.append("runtime.packages must list the packages the release needs.")

    stage_dirs: dict[str, str] = {}
    for key, spec in manifest.repositories.items():
        context = f"repositories.{key}"
        if not COMMIT_PATTERN.match(spec.commit):
            errors.append(
                f"{context}.commit must be a full 40-character SHA, found {spec.commit!r}. "
                "Abbreviated SHAs are ambiguous over time."
            )
        if not STAGE_DIR_PATTERN.match(spec.stage_dir):
            errors.append(
                f"{context}.stage_dir {spec.stage_dir!r} must be a simple directory name."
            )
        elif spec.stage_dir in stage_dirs:
            errors.append(
                f"{context}.stage_dir {spec.stage_dir!r} is already used by "
                f"repositories.{stage_dirs[spec.stage_dir]}."
            )
        else:
            stage_dirs[spec.stage_dir] = key

        if not spec.paths:
            errors.append(f"{context}.paths must not be empty.")
        if len(set(spec.paths)) != len(spec.paths):
            duplicates = sorted({p for p in spec.paths if spec.paths.count(p) > 1})
            errors.append(f"{context}.paths lists duplicates: {', '.join(duplicates)}")

        if spec.strip_prefix:
            errors.extend(
                path_safety_problems(spec.strip_prefix, context=f"{context}.strip_prefix")
            )

        for path in spec.paths:
            path_context = f"{context}.paths"
            problems = path_safety_problems(path, context=path_context)
            errors.extend(problems)
            if problems:
                continue
            suffix = PurePosixPath(path).suffix.lower()
            if suffix not in ALLOWED_SOURCE_SUFFIXES:
                errors.append(
                    f"{path_context}: {path!r} is not a Python module. Source "
                    "allowlists carry whole modules only; put configuration, "
                    "templates, and other assets in config_assets."
                )
            if spec.strip_prefix and not PurePosixPath(path).is_relative_to(
                PurePosixPath(spec.strip_prefix)
            ):
                errors.append(
                    f"{path_context}: {path!r} is not under strip_prefix "
                    f"{spec.strip_prefix!r}, so it cannot be staged."
                )

        if key not in repository_roots:
            errors.append(f"{context}: no repository root was supplied for {key!r}.")

    seen_dests: dict[str, str] = {}
    for index, asset in enumerate(manifest.config_assets):
        context = f"config_assets[{index}]"
        if asset.repository not in manifest.repositories:
            errors.append(
                f"{context}.repository {asset.repository!r} is not a declared repository."
            )
        errors.extend(path_safety_problems(asset.path, context=f"{context}.path"))
        errors.extend(path_safety_problems(asset.dest, context=f"{context}.dest"))
        suffix = PurePosixPath(asset.path).suffix.lower()
        if suffix not in ALLOWED_CONFIG_SUFFIXES:
            errors.append(
                f"{context}.path: {asset.path!r} has unsupported type {suffix!r} for a "
                f"configuration asset."
            )
        if asset.dest in seen_dests:
            errors.append(
                f"{context}.dest {asset.dest!r} collides with {seen_dests[asset.dest]}."
            )
        else:
            seen_dests[asset.dest] = context

    known = set(known_command_names)
    seen_command_names: set[str] = set()
    for index, spec in enumerate(manifest.commands):
        context = f"commands[{index}]"
        if spec.name in seen_command_names:
            errors.append(f"{context}.name {spec.name!r} is declared more than once.")
        seen_command_names.add(spec.name)
        if known and spec.name not in known:
            errors.append(
                f"{context}.name {spec.name!r} has no implementation. "
                f"Implemented commands: {', '.join(sorted(known))}."
            )
        input_keys: set[str] = set()
        for item in spec.inputs:
            if item.kind not in VALID_INPUT_KINDS:
                errors.append(
                    f"{context}: input {item.key!r} has kind {item.kind!r}; "
                    f"expected one of {sorted(VALID_INPUT_KINDS)}."
                )
            if item.key in input_keys:
                errors.append(f"{context}: input key {item.key!r} is declared more than once.")
            input_keys.add(item.key)
    if known - seen_command_names:
        report.warnings.append(
            "Implemented but not declared in the manifest (unavailable in the "
            f"release): {', '.join(sorted(known - seen_command_names))}."
        )

    if not check_git or errors:
        return report

    for key, spec in manifest.repositories.items():
        root = Path(repository_roots[key])
        context = f"repositories.{key}"
        if not (root / ".git").exists():
            errors.append(f"{context}: {root} is not a Git repository.")
            continue
        if not _commit_exists(root, spec.commit):
            errors.append(f"{context}: commit {spec.commit} does not exist in {root}.")
            continue
        for path in spec.paths:
            entry = _tree_entry(root, spec.commit, path)
            if entry is None:
                errors.append(
                    f"{context}: {path!r} does not exist at commit {spec.commit[:12]}. "
                    "Commit the file before releasing it."
                )
                continue
            mode, object_type = entry
            if object_type != "blob":
                errors.append(
                    f"{context}: {path!r} is a {object_type} at commit "
                    f"{spec.commit[:12]}, not a regular file."
                )
            elif mode == "120000":
                errors.append(
                    f"{context}: {path!r} is a symlink/junction and must not be packaged."
                )
            else:
                report.checked_source_files += 1

    for index, asset in enumerate(manifest.config_assets):
        context = f"config_assets[{index}]"
        spec = manifest.repositories.get(asset.repository)
        if spec is None:
            continue
        root = Path(repository_roots[asset.repository])
        entry = _tree_entry(root, spec.commit, asset.path)
        if entry is None:
            # Configuration assets are frequently gitignored on purpose (the
            # canonical mapping workbooks are), so fall back to the working tree
            # and record that the asset is not commit-pinned.
            working_copy = root / asset.path
            if not working_copy.is_file():
                errors.append(
                    f"{context}: {asset.path!r} exists neither at commit "
                    f"{spec.commit[:12]} nor in the working tree of {root}."
                )
                continue
            report.warnings.append(
                f"{context}: {asset.path!r} is not tracked at commit "
                f"{spec.commit[:12]}; it will be taken from the working tree and "
                "pinned by SHA-256 in the release report."
            )
            size = working_copy.stat().st_size
        else:
            mode, object_type = entry
            if object_type != "blob" or mode == "120000":
                errors.append(
                    f"{context}: {asset.path!r} is not a regular tracked file."
                )
                continue
            size_result = _git(root, "cat-file", "-s", f"{spec.commit}:{asset.path}")
            size = int(size_result.stdout.strip() or 0)
        if size > MAX_CONFIG_ASSET_BYTES:
            errors.append(
                f"{context}: {asset.path!r} is {size:,} bytes, above the "
                f"{MAX_CONFIG_ASSET_BYTES:,}-byte configuration-asset limit. "
                "Large generated data belongs in the run input, not the package."
            )
        else:
            report.checked_config_assets += 1

    return report

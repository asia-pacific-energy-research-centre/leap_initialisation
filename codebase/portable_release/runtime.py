"""The runtime context that makes developer mode and portable mode interchangeable.

A :class:`RuntimeContext` answers four questions for a run:

* where does the *code* come from (which roots go on ``sys.path``);
* where does the *configuration* come from (the external ``config/`` directory,
  whose files are hashed into every run manifest);
* where do *outputs* and *logs* go;
* what provenance should the run manifest record.

Developer mode builds a context pointing at the maintainer's live checkouts and
records each repository's commit and dirty state. Portable mode builds a context
pointing inside the frozen package and records the commits the package was built
from. :mod:`codebase.portable_release.commands` sees only the context, so the two
modes run identical code.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from codebase.portable_release.provenance import RepositoryState, describe_repository_state


MODE_DEVELOPER = "developer"
MODE_PORTABLE = "portable"


@dataclass
class RuntimeContext:
    """Everything a command needs that differs between the two modes."""

    mode: str
    release_name: str
    release_version: str
    package_root: Path
    config_root: Path
    output_root: Path
    log_root: Path
    input_root: Path
    #: Roots prepended to ``sys.path`` so the packaged/live modules import.
    sys_path_roots: tuple[Path, ...] = ()
    #: Role -> resolved path for each external configuration asset.
    config_assets: Mapping[str, Path] = field(default_factory=dict)
    #: Role -> resolved path for each large read-only source data table.
    data_assets: Mapping[str, Path] = field(default_factory=dict)
    #: Live repository roots, developer mode only.
    repository_roots: Mapping[str, Path] = field(default_factory=dict)
    #: Commit each source repository was released from, portable mode only.
    release_commits: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for directory in (self.output_root, self.log_root):
            directory.mkdir(parents=True, exist_ok=True)

    def config_asset(self, role: str) -> Path | None:
        """Return the configuration asset registered under *role*, if present."""
        path = self.config_assets.get(role)
        return Path(path) if path is not None else None

    def data_asset(self, role: str) -> Path | None:
        """Return the source data table registered under *role*, if present."""
        path = self.data_assets.get(role)
        return Path(path) if path is not None else None

    def require_data_asset(self, role: str) -> Path:
        path = self.data_asset(role)
        if path is None or not path.is_file():
            available = ", ".join(sorted(self.data_assets)) or "none"
            raise FileNotFoundError(
                f"Required source data table {role!r} was not found. "
                f"Available tables: {available}."
            )
        return path

    def require_config_asset(self, role: str) -> Path:
        path = self.config_asset(role)
        if path is None or not path.is_file():
            available = ", ".join(sorted(self.config_assets)) or "none"
            raise FileNotFoundError(
                f"Required configuration asset {role!r} was not found under "
                f"{self.config_root}. Available roles: {available}."
            )
        return path

    def repository_states(self) -> list[RepositoryState]:
        """Return the live commit/dirty state of each repository (developer mode)."""
        return [
            describe_repository_state(key, root)
            for key, root in sorted(self.repository_roots.items())
        ]

    def activate_sys_path(self) -> list[str]:
        """Prepend this context's roots to ``sys.path`` and return what was added."""
        added: list[str] = []
        for root in reversed(self.sys_path_roots):
            text = str(root)
            if text not in sys.path:
                sys.path.insert(0, text)
                added.append(text)
        return added

    def preflight(self) -> list[str]:
        """Return a problem for every missing root or configuration asset."""
        problems: list[str] = []
        for label, root in [
            ("package root", self.package_root),
            ("configuration directory", self.config_root),
        ]:
            if not root.is_dir():
                problems.append(f"The {label} does not exist: {root}")
        for root in self.sys_path_roots:
            if not root.is_dir():
                problems.append(f"A code directory declared for this run is missing: {root}")
        for role, path in sorted(self.data_assets.items()):
            if not Path(path).is_file():
                problems.append(
                    f"Source data table {role!r} is missing: {path}."
                )
        for role, path in sorted(self.config_assets.items()):
            if not Path(path).is_file():
                problems.append(
                    f"Configuration asset {role!r} is missing: {path}. "
                    "Restore it from the release, or point the settings file at a "
                    "checkout that has it."
                )
        for key, root in sorted(self.repository_roots.items()):
            if not Path(root).is_dir():
                problems.append(
                    f"Repository {key!r} is not at the configured path: {root}. "
                    "Fix the path in your settings file."
                )
        return problems

    def require_ready(self) -> "RuntimeContext":
        problems = self.preflight()
        if problems:
            joined = "\n  - ".join(problems)
            raise FileNotFoundError(
                f"This run cannot start because required locations are missing:\n  - {joined}"
            )
        return self

    def describe(self) -> str:
        lines = [
            f"{self.release_name} {self.release_version} ({self.mode} mode)",
            f"  package root : {self.package_root}",
            f"  config root  : {self.config_root}",
            f"  input root   : {self.input_root}",
            f"  output root  : {self.output_root}",
            f"  log root     : {self.log_root}",
        ]
        if self.sys_path_roots:
            lines.append("  code roots   :")
            for root in self.sys_path_roots:
                lines.append(f"    - {root}")
        elif self.mode == MODE_PORTABLE:
            lines.append("  code         : bundled inside the executable")
        if self.config_assets:
            lines.append("  config assets:")
            for role, path in sorted(self.config_assets.items()):
                lines.append(f"    - {role}: {path}")
        if self.data_assets:
            lines.append("  source tables:")
            for role, path in sorted(self.data_assets.items()):
                size = f"{Path(path).stat().st_size:,} bytes" if Path(path).is_file() else "MISSING"
                lines.append(f"    - {role}: {path}  ({size})")
        if self.repository_roots:
            lines.append("  repositories :")
            for key, root in sorted(self.repository_roots.items()):
                lines.append(f"    - {key}: {root}")
        if self.release_commits:
            lines.append("  built from   :")
            for key, commit in sorted(self.release_commits.items()):
                lines.append(f"    - {key}: {commit}")
        return "\n".join(lines)


@contextmanager
def run_logging(context: RuntimeContext, command: str) -> Iterator[Path]:
    """Write this run's log to ``logs/`` while still printing to the console."""
    context.log_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = context.log_root / f"{command}_{stamp}.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("leap_review_tools")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    original_stdout = sys.stdout

    class _Tee:
        def write(self, data: str) -> int:
            original_stdout.write(data)
            handler.stream.write(data)
            return len(data)

        def flush(self) -> None:
            original_stdout.flush()
            handler.stream.flush()

        def isatty(self) -> bool:
            return False

    sys.stdout = _Tee()  # type: ignore[assignment]
    try:
        logger.info("Starting %s in %s mode", command, context.mode)
        yield log_path
    finally:
        sys.stdout = original_stdout
        logger.removeHandler(handler)
        handler.close()


def build_config_asset_index(
    config_root: Path,
    asset_roles: Mapping[str, str],
) -> dict[str, Path]:
    """Map each declared role to its file under *config_root*."""
    return {role: config_root / relative for role, relative in asset_roles.items()}


def developer_context(
    *,
    release_name: str,
    release_version: str,
    repository_roots: Mapping[str, Path],
    config_root: Path,
    config_assets: Mapping[str, Path],
    sys_path_roots: Sequence[Path],
    output_root: Path,
    input_root: Path,
    log_root: Path,
    data_assets: Mapping[str, Path] | None = None,
) -> RuntimeContext:
    """Build a context that runs against the maintainer's live working copies."""
    return RuntimeContext(
        mode=MODE_DEVELOPER,
        release_name=release_name,
        release_version=release_version,
        package_root=Path(config_root).parent,
        config_root=Path(config_root),
        output_root=Path(output_root),
        log_root=Path(log_root),
        input_root=Path(input_root),
        sys_path_roots=tuple(Path(root) for root in sys_path_roots),
        config_assets=dict(config_assets),
        data_assets=dict(data_assets or {}),
        repository_roots={key: Path(root) for key, root in repository_roots.items()},
    )


def portable_context(
    *,
    release_name: str,
    release_version: str,
    package_root: Path,
    code_root: Path,
    sys_path_stage_dirs: Sequence[str],
    config_assets: Mapping[str, Path],
    release_commits: Mapping[str, str],
    data_assets: Mapping[str, Path] | None = None,
) -> RuntimeContext:
    """Build a context that runs entirely inside a built package."""
    root = Path(package_root)
    return RuntimeContext(
        mode=MODE_PORTABLE,
        release_name=release_name,
        release_version=release_version,
        package_root=root,
        config_root=root / "config",
        output_root=root / "output",
        log_root=root / "logs",
        input_root=root / "input",
        sys_path_roots=tuple(Path(code_root) / name for name in sys_path_stage_dirs),
        config_assets=dict(config_assets),
        data_assets=dict(data_assets or {}),
        repository_roots={},
        release_commits=dict(release_commits),
    )

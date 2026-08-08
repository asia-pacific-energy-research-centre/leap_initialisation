"""Run provenance: file hashes, repository state, and the run manifest.

Every run of a supported command — developer or portable — writes a manifest
that records what produced the output. The manifest answers the questions a
colleague or a maintainer asks weeks later: which release, which mode, when,
which input files (and were they the ones I think they were), which mapping and
configuration files were in force, which repository commits the code came from,
and whether the maintainer's working tree was dirty at the time.

Both a machine-readable JSON manifest and a human-readable text manifest are
written side by side.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RUN_MANIFEST_JSON_NAME = "run_manifest.json"
RUN_MANIFEST_TEXT_NAME = "run_manifest.txt"

_HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FileRecord:
    """One file recorded in a run manifest."""

    role: str
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None
    modified_utc: str | None


def describe_file(path: Path | str, *, role: str, hash_contents: bool = True) -> FileRecord:
    """Describe a file for the run manifest, tolerating a missing file."""
    resolved = Path(path)
    if not resolved.is_file():
        return FileRecord(
            role=role,
            path=str(resolved),
            exists=False,
            size_bytes=None,
            sha256=None,
            modified_utc=None,
        )
    stat = resolved.stat()
    return FileRecord(
        role=role,
        path=str(resolved),
        exists=True,
        size_bytes=stat.st_size,
        sha256=sha256_file(resolved) if hash_contents else None,
        modified_utc=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        ),
    )


def describe_directory_files(
    directory: Path | str,
    *,
    role_prefix: str,
    patterns: Sequence[str] = ("*",),
) -> list[FileRecord]:
    """Describe every matching file directly inside *directory*, sorted by name."""
    root = Path(directory)
    if not root.is_dir():
        return []
    seen: dict[Path, None] = {}
    for pattern in patterns:
        for candidate in sorted(root.glob(pattern)):
            if candidate.is_file():
                seen.setdefault(candidate, None)
    return [
        describe_file(path, role=f"{role_prefix}:{path.name}") for path in sorted(seen)
    ]


@dataclass(frozen=True)
class RepositoryState:
    """Commit and dirty state of one repository at run time (developer mode)."""

    key: str
    path: str
    commit: str | None
    branch: str | None
    dirty: bool | None
    dirty_file_count: int | None
    note: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def describe_repository_state(key: str, root: Path | str) -> RepositoryState:
    """Return the current commit, branch, and dirty state of a repository."""
    path = Path(root)
    if not path.is_dir():
        return RepositoryState(
            key=key,
            path=str(path),
            commit=None,
            branch=None,
            dirty=None,
            dirty_file_count=None,
            note="Directory does not exist.",
        )
    if not (path / ".git").exists():
        return RepositoryState(
            key=key,
            path=str(path),
            commit=None,
            branch=None,
            dirty=None,
            dirty_file_count=None,
            note="Not a Git repository; commit and dirty state are unknown.",
        )
    head = _git(path, "rev-parse", "HEAD")
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(path, "status", "--porcelain")
    if head.returncode != 0:
        return RepositoryState(
            key=key,
            path=str(path),
            commit=None,
            branch=None,
            dirty=None,
            dirty_file_count=None,
            note=f"git rev-parse failed: {head.stderr.strip()}",
        )
    changed = [line for line in status.stdout.splitlines() if line.strip()]
    return RepositoryState(
        key=key,
        path=str(path),
        commit=head.stdout.strip(),
        branch=branch.stdout.strip() or None,
        dirty=bool(changed),
        dirty_file_count=len(changed),
        note=(
            "Working tree has uncommitted changes; this run used code that is not "
            "in any commit."
            if changed
            else ""
        ),
    )


@dataclass
class RunManifest:
    """Everything recorded about one command run."""

    release_name: str
    release_version: str
    mode: str
    command: str
    started_utc: str
    finished_utc: str | None = None
    status: str = "running"
    error: str | None = None
    machine: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    inputs: list[FileRecord] = field(default_factory=list)
    configuration: list[FileRecord] = field(default_factory=list)
    outputs: list[FileRecord] = field(default_factory=list)
    repositories: list[RepositoryState] = field(default_factory=list)
    release_commits: dict[str, str] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "release": {"name": self.release_name, "version": self.release_version},
            "mode": self.mode,
            "command": self.command,
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "status": self.status,
            "error": self.error,
            "machine": self.machine,
            "settings": self.settings,
            "inputs": [asdict(item) for item in self.inputs],
            "configuration": [asdict(item) for item in self.configuration],
            "outputs": [asdict(item) for item in self.outputs],
            "repositories": [asdict(item) for item in self.repositories],
            "release_commits": self.release_commits,
            "validation": self.validation,
            "results": self.results,
        }

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"{self.release_name} {self.release_version} - run manifest")
        lines.append("=" * 72)
        lines.append(f"Command   : {self.command}")
        lines.append(f"Mode      : {self.mode}")
        lines.append(f"Started   : {self.started_utc} (UTC)")
        lines.append(f"Finished  : {self.finished_utc or '(not finished)'} (UTC)")
        lines.append(f"Status    : {self.status}")
        if self.error:
            lines.append(f"Error     : {self.error}")
        lines.append("")
        lines.append("Machine")
        lines.append("-" * 72)
        for key, value in self.machine.items():
            lines.append(f"  {key:<22}: {value}")

        for title, records in [
            ("Inputs", self.inputs),
            ("Configuration and mappings", self.configuration),
            ("Outputs", self.outputs),
        ]:
            lines.append("")
            lines.append(title)
            lines.append("-" * 72)
            if not records:
                lines.append("  (none)")
            for record in records:
                lines.append(f"  {record.role}")
                lines.append(f"    path   : {record.path}")
                if record.exists:
                    lines.append(f"    size   : {record.size_bytes:,} bytes")
                    lines.append(f"    sha256 : {record.sha256}")
                    lines.append(f"    mtime  : {record.modified_utc} (UTC)")
                else:
                    lines.append("    status : MISSING")

        if self.release_commits:
            lines.append("")
            lines.append("Release source commits")
            lines.append("-" * 72)
            for key, commit in sorted(self.release_commits.items()):
                lines.append(f"  {key:<22}: {commit}")

        if self.repositories:
            lines.append("")
            lines.append("Live repository state (developer mode)")
            lines.append("-" * 72)
            for state in self.repositories:
                dirty_label = (
                    "unknown"
                    if state.dirty is None
                    else f"DIRTY ({state.dirty_file_count} changed files)"
                    if state.dirty
                    else "clean"
                )
                lines.append(f"  {state.key}")
                lines.append(f"    path   : {state.path}")
                lines.append(f"    commit : {state.commit or 'unknown'}")
                lines.append(f"    branch : {state.branch or 'unknown'}")
                lines.append(f"    state  : {dirty_label}")
                if state.note:
                    lines.append(f"    note   : {state.note}")

        if self.validation:
            lines.append("")
            lines.append("Validation")
            lines.append("-" * 72)
            lines.append(json.dumps(self.validation, indent=2, default=str))

        if self.results:
            lines.append("")
            lines.append("Results")
            lines.append("-" * 72)
            lines.append(json.dumps(self.results, indent=2, default=str))

        lines.append("")
        return "\n".join(lines)

    def write(self, directory: Path | str) -> dict[str, Path]:
        """Write both manifest forms into *directory* and return their paths."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        json_path = target / RUN_MANIFEST_JSON_NAME
        text_path = target / RUN_MANIFEST_TEXT_NAME
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        text_path.write_text(self.to_text(), encoding="utf-8")
        return {"json": json_path, "text": text_path}


def machine_summary() -> dict[str, Any]:
    """Describe the machine and interpreter, without collecting personal data."""
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - environment without a resolvable user
        user = "unknown"
    try:
        host = socket.gethostname()
    except Exception:  # pragma: no cover
        host = "unknown"
    return {
        "hostname": host,
        "user": user,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
    }


def new_run_manifest(
    *,
    release_name: str,
    release_version: str,
    mode: str,
    command: str,
    settings: Mapping[str, Any] | None = None,
) -> RunManifest:
    """Start a run manifest stamped with the current UTC time."""
    return RunManifest(
        release_name=release_name,
        release_version=release_version,
        mode=mode,
        command=command,
        started_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        machine=machine_summary(),
        settings=dict(settings or {}),
    )


def finish_run_manifest(
    manifest: RunManifest,
    *,
    status: str,
    error: str | None = None,
) -> RunManifest:
    manifest.finished_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest.status = status
    manifest.error = error
    return manifest

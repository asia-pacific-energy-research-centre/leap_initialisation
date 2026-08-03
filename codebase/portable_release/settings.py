"""One explicit local settings file that tells developer mode where things are.

Developer mode must not guess. It reads exactly one TOML file — by default
``%LOCALAPPDATA%\\leap-review-tools\\developer_settings.toml``, overridable with
the ``LEAP_REVIEW_TOOLS_SETTINGS`` environment variable — that names the three
repository roots and the output/input/log folders. Nothing is inferred from the
current working directory, so the launcher behaves the same from a notebook, a
terminal, or an IDE run configuration.

The settings file lives outside the repositories on purpose: it holds
machine-specific absolute paths that must not be committed. A tracked example
lives at ``config/leap_review_tools_settings.example.toml``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SETTINGS_ENV_VAR = "LEAP_REVIEW_TOOLS_SETTINGS"
SETTINGS_FILE_NAME = "developer_settings.toml"
SETTINGS_DIR_NAME = "leap-review-tools"

REQUIRED_REPOSITORY_KEYS = ("leap_initialisation", "leap_mappings", "leap_dashboard")


class DeveloperSettingsError(RuntimeError):
    """Raised when the developer settings file is missing or incomplete."""


@dataclass(frozen=True)
class DeveloperSettings:
    """Resolved developer-mode settings."""

    source_path: Path
    repositories: Mapping[str, Path]
    output_root: Path
    input_root: Path
    log_root: Path

    def describe(self) -> str:
        lines = [f"Developer settings: {self.source_path}", "Repositories:"]
        for key, path in sorted(self.repositories.items()):
            marker = "" if path.is_dir() else "   [MISSING]"
            lines.append(f"  {key:<20}: {path}{marker}")
        lines.append(f"Output root  : {self.output_root}")
        lines.append(f"Input root   : {self.input_root}")
        lines.append(f"Log root     : {self.log_root}")
        return "\n".join(lines)


def default_settings_directory() -> Path:
    """Return the per-user directory that holds the developer settings file."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / SETTINGS_DIR_NAME
    return Path.home() / f".{SETTINGS_DIR_NAME}"


def default_settings_path() -> Path:
    """Return the settings file path, honouring the environment override."""
    override = os.environ.get(SETTINGS_ENV_VAR)
    if override:
        return Path(override.replace("\\", "/"))
    return default_settings_directory() / SETTINGS_FILE_NAME


def _resolve_directory(value: object, *, key: str, source: Path) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise DeveloperSettingsError(f"{source}: {key} must not be blank.")
    path = Path(text)
    if not path.is_absolute():
        raise DeveloperSettingsError(
            f"{source}: {key} must be an absolute path so the launcher does not "
            f"depend on the current working directory, found {text!r}."
        )
    return path


def load_developer_settings(path: Path | str | None = None) -> DeveloperSettings:
    """Read and validate the developer settings file."""
    settings_path = Path(str(path).replace("\\", "/")) if path else default_settings_path()
    if not settings_path.is_file():
        raise DeveloperSettingsError(
            f"No developer settings file at {settings_path}.\n"
            "Create one with:\n"
            "    from codebase.portable_release.settings import write_example_settings\n"
            "    write_example_settings()\n"
            f"or set {SETTINGS_ENV_VAR} to point at an existing file."
        )
    try:
        raw = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DeveloperSettingsError(f"{settings_path} is not valid TOML: {exc}") from exc

    repositories_block = raw.get("repositories") or {}
    missing = [key for key in REQUIRED_REPOSITORY_KEYS if not repositories_block.get(key)]
    if missing:
        raise DeveloperSettingsError(
            f"{settings_path} is missing repository paths for: {', '.join(missing)}."
        )
    repositories = {
        key: _resolve_directory(
            repositories_block[key],
            key=f"repositories.{key}",
            source=settings_path,
        )
        for key in REQUIRED_REPOSITORY_KEYS
    }

    paths_block = raw.get("paths") or {}
    default_workspace = Path.home() / "leap_review_tools"
    output_root = _resolve_directory(
        paths_block.get("output_root") or default_workspace / "output",
        key="paths.output_root",
        source=settings_path,
    )
    input_root = _resolve_directory(
        paths_block.get("input_root") or default_workspace / "input",
        key="paths.input_root",
        source=settings_path,
    )
    log_root = _resolve_directory(
        paths_block.get("log_root") or default_workspace / "logs",
        key="paths.log_root",
        source=settings_path,
    )

    return DeveloperSettings(
        source_path=settings_path,
        repositories=repositories,
        output_root=output_root,
        input_root=input_root,
        log_root=log_root,
    )


def render_settings_template(
    repositories: Mapping[str, Path],
    *,
    workspace: Path,
) -> str:
    """Return the text of a developer settings file."""
    lines = [
        "# Developer-mode settings for the LEAP review tools.",
        "#",
        "# This file is machine-specific and is deliberately kept outside the",
        "# repositories. Every path must be absolute.",
        "",
        "[repositories]",
    ]
    for key in REQUIRED_REPOSITORY_KEYS:
        path = repositories.get(key, Path(f"C:/Users/CHANGE_ME/github/{key}"))
        lines.append(f'{key} = "{Path(path).as_posix()}"')
    lines += [
        "",
        "[paths]",
        f'output_root = "{(workspace / "output").as_posix()}"',
        f'input_root = "{(workspace / "input").as_posix()}"',
        f'log_root = "{(workspace / "logs").as_posix()}"',
        "",
    ]
    return "\n".join(lines)


def detect_repository_roots(start: Path | None = None) -> dict[str, Path]:
    """Guess the three repository roots from this checkout's parent directory.

    Only used to pre-fill a new settings file; the file itself stays the single
    authority once written.
    """
    here = Path(start) if start else Path(__file__).resolve().parents[2]
    parent = here.parent
    detected: dict[str, Path] = {}
    for key in REQUIRED_REPOSITORY_KEYS:
        candidate = here if here.name == key else parent / key
        if (candidate / ".git").exists():
            detected[key] = candidate
    return detected


def write_example_settings(
    path: Path | str | None = None,
    *,
    workspace: Path | str | None = None,
    overwrite: bool = False,
) -> Path:
    """Create a developer settings file pre-filled with detected repositories."""
    target = Path(str(path).replace("\\", "/")) if path else default_settings_path()
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} already exists. Pass overwrite=True to replace it."
        )
    workspace_root = (
        Path(str(workspace).replace("\\", "/"))
        if workspace
        else Path.home() / "leap_review_tools"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_settings_template(detect_repository_roots(), workspace=workspace_root),
        encoding="utf-8",
    )
    return target

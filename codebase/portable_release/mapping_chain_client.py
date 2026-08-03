"""Client side of the portable mapping-chain worker.

The worker (``leap_mappings/codebase/portable_mapping_chain.py``) exists
because ``leap_initialisation.codebase`` and ``leap_mappings.codebase`` both
use absolute ``codebase.x.y`` imports under the same top-level package name
and cannot share a process — see
``leap_initialisation/docs/leap_review_tools_handover_20260803.md`` §1. This
module runs it as a subprocess, passing a JSON job on stdin and reading a JSON
result from stdout, so the two ``codebase`` packages never load together.

Locating the worker differs by mode:

* portable mode: ``mapping-chain/leap-mapping-chain.exe`` beside the main
  executable (built by the two-target builder, §3.3 of the handover);
* developer mode: ``sys.executable -m codebase.portable_mapping_chain`` run
  with ``cwd`` set to the maintainer's ``leap_mappings`` checkout, so its own
  relative-path conventions (``AGENTS.md``: resolve against ``REPO_ROOT``)
  keep working.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from codebase.portable_release.runtime import MODE_PORTABLE, RuntimeContext


class MappingChainError(RuntimeError):
    """The mapping-chain worker could not produce a result."""


def locate_worker(context: RuntimeContext) -> tuple[list[str], Path | None]:
    """Return ``(command_prefix, cwd)`` for invoking the worker.

    ``command_prefix`` is the argv the job JSON gets appended to conceptually
    (the job is actually sent on stdin, so this is just the process to start).
    """
    if context.mode == MODE_PORTABLE:
        exe_path = context.package_root / "mapping-chain" / "leap-mapping-chain.exe"
        if not exe_path.is_file():
            raise MappingChainError(
                f"The mapping-chain worker is missing from this package: {exe_path}.\n"
                "Re-extract the release folder, or ask for a fresh copy."
            )
        return [str(exe_path)], None

    mappings_root = context.repository_roots.get("leap_mappings")
    if mappings_root is None or not Path(mappings_root).is_dir():
        raise MappingChainError(
            "No leap_mappings checkout is configured for this developer settings "
            "file; the mapping-chain worker needs one to run from."
        )
    return (
        [sys.executable, "-m", "codebase.portable_mapping_chain"],
        Path(mappings_root),
    )


def run_mapping_chain(context: RuntimeContext, job: dict[str, Any]) -> dict[str, Any]:
    """Invoke the mapping-chain worker with *job* and return its parsed result.

    Raises :class:`MappingChainError` with a plain-language message on any
    failure — a missing worker, a non-zero exit, an ``{"error": ...}`` result,
    or output that is not valid JSON. Callers never see a raw traceback from
    the worker process.
    """
    command, cwd = locate_worker(context)
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(job),
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
        )
    except OSError as exc:
        raise MappingChainError(f"Could not start the mapping-chain worker: {exc}") from exc

    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")

    stdout = completed.stdout.strip()
    if not stdout:
        raise MappingChainError(
            "The mapping-chain worker produced no output "
            f"(exit code {completed.returncode})."
        )

    try:
        result = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise MappingChainError(
            f"The mapping-chain worker's output was not valid JSON: {exc}\n"
            f"Raw output: {stdout[:2000]}"
        ) from exc

    if "error" in result:
        raise MappingChainError(f"The mapping-chain worker failed: {result['error']}")
    if completed.returncode != 0:
        raise MappingChainError(
            f"The mapping-chain worker exited with code {completed.returncode}."
        )
    return result

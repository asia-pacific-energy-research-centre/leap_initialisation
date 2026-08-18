"""Client side of the portable mapping-chain worker.

The worker (``leap_mappings/codebase/portable_mapping_chain.py``) exists
because ``leap_initialisation.codebase`` and ``leap_mappings.codebase`` both
use absolute ``codebase.x.y`` imports under the same top-level package name
and cannot share a process — see
``leap_initialisation/docs/leap_review_tools_handover_20260803.md`` §1. This
module runs it as a subprocess, passing a JSON job on stdin and reading a JSON
result from stdout, so the two ``codebase`` packages never load together.

The worker's stdout is read line by line rather than captured whole, because
the chain's steps take minutes and it announces each one as it starts (see
``PROGRESS_PREFIX``). Those announcements drive the caller's progress display;
the result is the last line that is not one of them.

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
import threading
from pathlib import Path
from typing import Any

from codebase.portable_release.runtime import MODE_PORTABLE, RuntimeContext


#: Must match ``leap_mappings/codebase/portable_mapping_chain.PROGRESS_PREFIX``.
#: The two live in different repositories and cannot import each other, so this
#: is asserted by a test that reads the worker's source rather than by imports.
PROGRESS_PREFIX = "@@step "

WORKER_LOG_NAME = "mapping_chain_worker.log"


class MappingChainError(RuntimeError):
    """The mapping-chain worker could not produce a result."""


def _run_streaming(
    command: list[str],
    cwd: Path | None,
    job: dict[str, Any],
    cancellation_check: Any = None,
) -> tuple[list[str], str, int]:
    """Run the worker, reporting its steps as they happen.

    Read line by line rather than with ``subprocess.run``: the chain's steps
    take minutes each, and buffering the whole output means the user sees
    nothing at all until the run is over. Progress lines are forwarded to the
    reporter for the command in progress, if any.

    stderr goes to a file rather than a second pipe. Draining two pipes from
    one thread deadlocks as soon as either fills, and the worker can produce a
    lot of pandas warnings on stderr.
    """
    from codebase.portable_release import progress

    work_dir = Path(job.get("work_dir", "."))
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = work_dir / "mapping_chain_worker.stderr.log"
        stderr_file = open(stderr_path, "w", encoding="utf-8", errors="replace")
    except OSError:
        stderr_path = None
        stderr_file = subprocess.DEVNULL

    lines: list[str] = []
    try:
        try:
            worker = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(cwd) if cwd is not None else None,
            )
        except OSError as exc:
            raise MappingChainError(
                f"Could not start the mapping-chain worker: {exc}"
            ) from exc

        stop_watcher = threading.Event()

        def terminate_when_cancelled() -> None:
            while not stop_watcher.wait(0.25):
                if callable(cancellation_check) and cancellation_check():
                    try:
                        worker.terminate()
                    except OSError:
                        pass
                    return

        watcher = threading.Thread(
            target=terminate_when_cancelled,
            name="mapping-chain-cancel-watcher",
            daemon=True,
        )
        watcher.start()
        with worker:
            assert worker.stdin is not None and worker.stdout is not None
            try:
                worker.stdin.write(json.dumps(job))
                worker.stdin.close()
            except OSError:
                # The worker died before reading its job; the exit code and
                # whatever it managed to say are handled by the caller.
                pass
            for raw in worker.stdout:
                line = raw.rstrip("\r\n")
                lines.append(line)
                if line.startswith(PROGRESS_PREFIX):
                    progress.begin_step(line[len(PROGRESS_PREFIX) :].strip())
            returncode = worker.wait()
        stop_watcher.set()
        watcher.join(timeout=1)
    finally:
        if stderr_file is not subprocess.DEVNULL:
            stderr_file.close()

    stderr_text = ""
    if stderr_path is not None:
        try:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stderr_text = ""
    return lines, stderr_text, returncode


def _write_worker_log(job: dict[str, Any], lines: list[str], stderr_text: str) -> None:
    """Keep the worker's full output beside its outputs, best-effort."""
    try:
        work_dir = Path(job.get("work_dir", "."))
        work_dir.mkdir(parents=True, exist_ok=True)
        body = "\n".join(lines)
        if stderr_text:
            body += "\n\n--- stderr ---\n" + stderr_text
        (work_dir / WORKER_LOG_NAME).write_text(body + "\n", encoding="utf-8")
    except OSError:
        pass


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


def run_mapping_chain(
    context: RuntimeContext,
    job: dict[str, Any],
    cancellation_check: Any = None,
) -> dict[str, Any]:
    """Invoke the mapping-chain worker with *job* and return its parsed result.

    Raises :class:`MappingChainError` with a plain-language message on any
    failure — a missing worker, a non-zero exit, an ``{"error": ...}`` result,
    or output that is not valid JSON. Callers never see a raw traceback from
    the worker process.
    """
    command, cwd = locate_worker(context)
    stdout_lines, stderr_text, returncode = _run_streaming(
        command, cwd, job, cancellation_check=cancellation_check
    )

    if stderr_text:
        try:
            print(stderr_text, file=sys.stderr, end="" if stderr_text.endswith("\n") else "\n")
        except (AttributeError, OSError, ValueError):
            # A detached Windows/Gradio process may inherit an invalid stderr
            # handle. Worker diagnostics are already persisted to its log.
            pass

    # The worker's own chatter (and every print the mapping modules make) is
    # kept beside its outputs rather than shown: it is maintainer-facing, and
    # it is what a support bundle needs when a run goes wrong.
    _write_worker_log(job, stdout_lines, stderr_text)

    payload_lines = [
        line for line in stdout_lines if line.strip() and not line.startswith(PROGRESS_PREFIX)
    ]
    if not payload_lines:
        raise MappingChainError(
            "The mapping-chain worker produced no output "
            f"(exit code {returncode})."
        )

    try:
        result = json.loads(payload_lines[-1])
    except json.JSONDecodeError as exc:
        raise MappingChainError(
            f"The mapping-chain worker's output was not valid JSON: {exc}\n"
            f"Raw output: {chr(10).join(payload_lines)[:2000]}"
        ) from exc

    if "error" in result:
        raise MappingChainError(f"The mapping-chain worker failed: {result['error']}")
    if returncode != 0:
        raise MappingChainError(
            f"The mapping-chain worker exited with code {returncode}."
        )
    return result

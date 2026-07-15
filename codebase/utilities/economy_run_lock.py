"""Small cross-process locks for workflows that write economy-specific outputs."""
from __future__ import annotations

import json
import os
import re
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


def _lock_token(value: str) -> str:
    """Return a stable filesystem-safe token for an economy identifier."""
    return _SAFE_TOKEN.sub("_", str(value).strip()).strip("_.") or "unknown"


def _process_is_running(pid: object) -> bool:
    """Return whether a local process still exists; unknown PIDs are treated as live."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, TypeError, ValueError):
        return True
    return True


def _read_lock_metadata(lock_path: Path) -> dict[str, object]:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@contextmanager
def economy_run_locks(
    economies: Iterable[str],
    *,
    lock_directory: Path | str,
    workflow_name: str,
) -> Iterator[None]:
    """Reserve economy outputs for one process and remove the locks on exit.

    Different economies can run in parallel.  A stale lock created on this
    machine by a process that has exited is automatically cleared.  Locks from
    another machine are deliberately retained so shared-drive writes remain
    safe.
    """
    tokens = sorted({_lock_token(economy) for economy in economies if str(economy).strip()})
    if not tokens:
        yield
        return

    directory = Path(lock_directory)
    directory.mkdir(parents=True, exist_ok=True)
    acquired: list[Path] = []
    metadata = {
        "workflow": str(workflow_name),
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        for token in tokens:
            lock_path = directory / f"{token}.lock"
            try:
                fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                existing = _read_lock_metadata(lock_path)
                if (
                    existing.get("host") == socket.gethostname()
                    and not _process_is_running(existing.get("pid"))
                ):
                    lock_path.unlink(missing_ok=True)
                    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                else:
                    owner = ", ".join(
                        f"{key}={existing.get(key, 'unknown')}"
                        for key in ("workflow", "pid", "host", "started_at")
                    )
                    raise RuntimeError(
                        f"Economy '{token}' is already being written by another run ({owner}). "
                        "Wait for that run to finish, or inspect the stale lock at "
                        f"{lock_path}."
                    )
            with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
                json.dump({**metadata, "economy": token}, lock_file, indent=2)
            acquired.append(lock_path)
        yield
    finally:
        for lock_path in reversed(acquired):
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

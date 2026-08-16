#%%
"""Synchronize the read-only Outlook mapping fallback from leap_mappings.

Run this file from a Jupyter notebook after the generated mapping master has
been refreshed and committed in ``leap_mappings``.  The copy is byte-for-byte;
when the source is unchanged, neither the workbook nor its provenance sidecar
is rewritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.utilities.mapping_workbook_resolver import (  # noqa: E402
    FALLBACK_MAPPING_WORKBOOK_PATH,
    FALLBACK_PROVENANCE_PATH,
    LIVE_MAPPING_WORKBOOK_PATH,
    MAPPING_CONTRACT_VERSION,
    sha256_file,
    validate_mapping_workbook,
)


def _source_commit(source_repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sync_outlook_mapping_fallback(
    source_path: Path = LIVE_MAPPING_WORKBOOK_PATH,
    destination_path: Path = FALLBACK_MAPPING_WORKBOOK_PATH,
    provenance_path: Path = FALLBACK_PROVENANCE_PATH,
) -> dict[str, object]:
    """Validate and synchronize the fallback, returning a compact audit."""
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    provenance_path = Path(provenance_path)
    validate_mapping_workbook(source_path)
    source_hash = sha256_file(source_path)
    workbook_changed = not destination_path.is_file() or sha256_file(destination_path) != source_hash

    source_repo_root = source_path.parents[1]
    source_commit = _source_commit(source_repo_root)
    previous: dict[str, object] = {}
    if provenance_path.is_file():
        try:
            previous = json.loads(provenance_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    stable_fields = {
        "contract_version": MAPPING_CONTRACT_VERSION,
        "source_repository_commit": source_commit,
        "source_repository": source_repo_root.name,
        "source_path": source_path.resolve().relative_to(source_repo_root.resolve()).as_posix(),
        "workbook_sha256": source_hash,
    }
    provenance_changed = any(previous.get(key) != value for key, value in stable_fields.items())
    if workbook_changed:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)
    if workbook_changed or provenance_changed:
        payload = {
            **stable_fields,
            "copied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        provenance_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    validate_mapping_workbook(destination_path)
    copied_hash = sha256_file(destination_path)
    if copied_hash != source_hash:
        raise RuntimeError(
            f"Fallback copy hash mismatch: source={source_hash}, destination={copied_hash}"
        )
    audit = {
        "workbook_changed": workbook_changed,
        "provenance_changed": provenance_changed,
        "source_sha256": source_hash,
        "destination_sha256": copied_hash,
        "source_commit": source_commit,
        "destination_path": str(destination_path),
    }
    print(json.dumps(audit, indent=2))
    return audit


# --- Notebook run toggle ---
RUN_FALLBACK_SYNC = False

if RUN_FALLBACK_SYNC:
    SYNC_AUDIT = sync_outlook_mapping_fallback()

#%%

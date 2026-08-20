#%%
"""Build a reviewed, GUI-agent batch register for LEAP seed imports and balance exports.

The normal route stages a clean-slate backup outside LEAP's managed folders,
then opens it through LEAP. The register never writes to or scans C:\\LEAP_Areas
unless an operator explicitly requests an existing-area lookup.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_CLEAN_SLATE_SOURCE = Path(
    r"C:\Users\Work\APERC\Outlook 10 - LEAP modelling_2026\Clean leap models - DO NOT OVERWRITE\Integrated LEAP areas - clean slates"
)
DEFAULT_SEED_RUNS_ROOT = (
    REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "baseline_seed" / "runs"
)
DEFAULT_BATCH_ROOT = REPO_ROOT / "outputs" / "leap_gui_batch"
DEFAULT_EXPORT_DETAIL_LEVEL = 2


@dataclass(frozen=True)
class AreaCandidate:
    path: str
    name: str
    source: str
    modified_at: str
    size_bytes: int | None


def _resolve(path_value: Path | str) -> Path:
    """Resolve a path while accepting Windows-style user input."""
    return Path(str(path_value).replace("\\", "/"))


def _timestamp(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="seconds")


def _safe_area_token(economy: str) -> str:
    """Return the three-letter area token used in current clean-slate names."""
    try:
        return economy.split("_", maxsplit=1)[1].upper()
    except IndexError as error:
        raise ValueError(f"Economy must use the NN_ABC form: {economy!r}") from error


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_clean_slate_candidates(clean_slate_source: Path) -> list[AreaCandidate]:
    """Return all source .leap files, newest first, without copying them."""
    if not clean_slate_source.is_dir():
        raise FileNotFoundError(f"Clean-slate source folder was not found: {clean_slate_source}")

    candidates = [
        AreaCandidate(
            path=str(path),
            name=path.name,
            source="clean_slate_file",
            modified_at=_timestamp(datetime.fromtimestamp(path.stat().st_mtime).astimezone()),
            size_bytes=path.stat().st_size,
        )
        for path in clean_slate_source.glob("*.leap")
        if path.is_file()
    ]
    return sorted(candidates, key=lambda candidate: candidate.modified_at, reverse=True)


def _matching_candidates(candidates: Iterable[AreaCandidate], economy: str) -> list[dict[str, object]]:
    token = _safe_area_token(economy)
    pattern = re.compile(rf"(?<![A-Z]){re.escape(token)}(?![A-Z])", flags=re.IGNORECASE)
    return [asdict(candidate) for candidate in candidates if pattern.search(candidate.name)]


def _find_latest_seed(seed_runs_root: Path, economy: str) -> Path | None:
    """Find a final seed only; preflight-only and aggregate workbooks are excluded."""
    if not seed_runs_root.is_dir():
        return None
    pattern = f"leap_import_baseline_seed_{economy}_*.xlsx"
    candidates = [
        path
        for path in seed_runs_root.rglob(pattern)
        if "preflight_compressed_projection" not in path.parts
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _seed_record(seed_path: Path | None, economy: str, seed_runs_root: Path) -> dict[str, object]:
    expected_pattern = str(seed_runs_root / "<RUN_LABEL>" / f"leap_import_baseline_seed_{economy}_YYYYMMDD.xlsx")
    if seed_path is None:
        return {
            "status": "missing",
            "path": None,
            "sha256": None,
            "modified_at": None,
            "expected_pattern": expected_pattern,
        }
    return {
        "status": "found",
        "path": str(seed_path),
        "sha256": _file_hash(seed_path),
        "modified_at": _timestamp(datetime.fromtimestamp(seed_path.stat().st_mtime).astimezone()),
        "expected_pattern": expected_pattern,
    }


def _job_status(seed: dict[str, object], clean_slate_candidates: list[dict[str, object]]) -> str:
    if seed["status"] != "found":
        return "BLOCKED_SEED_MISSING"
    if not clean_slate_candidates:
        return "BLOCKED_NO_CLEAN_SLATE_FILE"
    return "REQUIRES_OPERATOR_SELECTION"


def build_batch_register(
    economies: list[str],
    clean_slate_source: Path | str = DEFAULT_CLEAN_SLATE_SOURCE,
    seed_runs_root: Path | str = DEFAULT_SEED_RUNS_ROOT,
    export_detail_level: int = DEFAULT_EXPORT_DETAIL_LEVEL,
) -> dict[str, object]:
    """Build a no-side-effect register for one sequential GUI batch."""
    if export_detail_level < 2:
        raise ValueError("Energy Balance exports must use Level 2 or deeper.")

    clean_slate_source = _resolve(clean_slate_source)
    seed_runs_root = _resolve(seed_runs_root)
    clean_slate_candidates = discover_clean_slate_candidates(clean_slate_source)

    jobs = []
    for sequence, economy in enumerate(economies, start=1):
        seed_path = _find_latest_seed(seed_runs_root, economy)
        matching_clean_slates = _matching_candidates(clean_slate_candidates, economy)
        jobs.append(
            {
                "sequence": sequence,
                "economy": economy,
                "area_token": _safe_area_token(economy),
                "status": _job_status(_seed_record(seed_path, economy, seed_runs_root), matching_clean_slates),
                "baseline_seed": _seed_record(seed_path, economy, seed_runs_root),
                "area_selection": {
                    "policy": "REVIEW_REQUIRED",
                    "selected_source": None,
                    "selected_path": None,
                    "clean_slate_candidates": matching_clean_slates,
                    "required_title_match": None,
                    "normal_route": "STAGE_BACKUP_OUTSIDE_LEAP_AREAS_AND_OPEN_IN_LEAP",
                },
                "import": {
                    "policy": "REVIEW_REQUIRED",
                    "allowed_values": ["IMPORT_SEED", "SKIP_SEED_ALREADY_IMPORTED"],
                },
                "export": {
                    "detail_level": export_detail_level,
                    "scenarios": ["Reference", "Target"],
                    "wait_policy": (
                        "POLL_VISIBLE_LEAP_COMPLETION_EVERY_10_MINUTES"
                        if export_detail_level == 2
                        else "POLL_VISIBLE_LEAP_COMPLETION_EVERY_60_MINUTES"
                    ),
                    "output_files": [
                        f"{_safe_area_token(economy)} REF {{YYYYMMDD}} CHATGPT.xlsx",
                        f"{_safe_area_token(economy)} TGT {{YYYYMMDD}} CHATGPT.xlsx",
                    ],
                },
                "gui_checkpoints": [
                    "AREA_TITLE_AND_REGION_CONFIRMED",
                    "SEED_LEAP_SHEET_ACTIVE_BEFORE_IMPORT",
                    "IMPORT_COMPLETE_OR_ERROR_LEFT_VISIBLE",
                    "SCENARIO_AND_DETAIL_CONFIRMED",
                    "DESTINATION_WORKBOOK_ACTIVE_BEFORE_EXPORT",
                    "EXPORT_FINISHED_AND_WORKBOOK_INSPECTED",
                ],
            }
        )

    return {
        "register_version": 1,
        "created_at": _timestamp(datetime.now().astimezone()),
        "execution_rule": "SEQUENTIAL_GUI_ONLY_ONE_ACTIVE_LEAP_AND_EXCEL_JOB",
        "sources": {
            "clean_slate_source": str(clean_slate_source),
            "seed_runs_root": str(seed_runs_root),
        },
        "jobs": jobs,
    }


def stage_reviewed_backup_files(register: dict[str, object], staging_root: Path | str) -> dict[str, object]:
    """Copy only operator-selected clean-slate files into a new staging folder.

    The staging root must be outside LEAP's managed `C:\\LEAP_Areas` location.
    The function never overwrites a file. Call it only after setting each
    selected source/path in the saved register.
    """
    staging_root = _resolve(staging_root)
    if staging_root.drive.upper() == "C:" and staging_root.parts[:2] == ("C:\\", "LEAP_Areas"):
        raise ValueError("Never stage backup files inside C:\\LEAP_Areas.")
    staged_jobs = []
    for job in register["jobs"]:
        selection = job["area_selection"]
        if selection["selected_source"] != "clean_slate_file":
            continue
        source_path = Path(str(selection["selected_path"]))
        if source_path.suffix.lower() != ".leap" or not source_path.is_file():
            raise ValueError(f"Invalid selected clean-slate file for {job['economy']}: {source_path}")
        destination = staging_root / str(job["economy"]) / source_path.name
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite staged file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        staged_jobs.append({"economy": job["economy"], "staged_path": str(destination), "sha256": _file_hash(destination)})
    return {"staging_root": str(staging_root), "staged_jobs": staged_jobs}


def write_batch_register(register: dict[str, object], output_directory: Path | str) -> dict[str, Path]:
    """Write agent-readable JSON plus a concise human review CSV."""
    output_directory = _resolve(output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    json_path = output_directory / "leap_gui_batch_register.json"
    csv_path = output_directory / "leap_gui_batch_register_review.csv"
    json_path.write_text(json.dumps(register, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "sequence", "economy", "status", "seed_status", "seed_path",
                "clean_slate_candidates", "import_policy",
                "export_detail_level", "export_wait_policy",
            ],
        )
        writer.writeheader()
        for job in register["jobs"]:
            writer.writerow(
                {
                    "sequence": job["sequence"],
                    "economy": job["economy"],
                    "status": job["status"],
                    "seed_status": job["baseline_seed"]["status"],
                    "seed_path": job["baseline_seed"]["path"],
                    "clean_slate_candidates": " | ".join(candidate["name"] for candidate in job["area_selection"]["clean_slate_candidates"]),
                    "import_policy": job["import"]["policy"],
                    "export_detail_level": job["export"]["detail_level"],
                    "export_wait_policy": job["export"]["wait_policy"],
                }
            )
    return {"json_path": json_path, "csv_path": csv_path}


#%% Frequently changed settings: edit these in a Jupyter cell before a batch.
ECONOMIES_TO_PREPARE = ["01_AUS", "02_BD", "05_PRC", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "15_PHL", "19_THA", "20_USA", "21_VN"]
EXPORT_DETAIL_LEVEL = 2
CREATE_STAGED_AREA_COPIES = False


#%%
if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    register = build_batch_register(ECONOMIES_TO_PREPARE, export_detail_level=EXPORT_DETAIL_LEVEL)
    output_paths = write_batch_register(register, DEFAULT_BATCH_ROOT / f"preflight_{timestamp}")
    print(f"Wrote register: {output_paths['json_path']}")
    print(f"Wrote review CSV: {output_paths['csv_path']}")
    if CREATE_STAGED_AREA_COPIES:
        print("Set reviewed selection fields in the JSON before staging area files.")

#%%

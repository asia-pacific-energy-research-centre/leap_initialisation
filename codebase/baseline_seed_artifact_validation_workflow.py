#%%
"""Notebook entry point for the baseline-seed final-artifact audit gate."""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions.baseline_seed_artifact_validation import (  # noqa: E402
    DEFAULT_ENFORCEMENT_BY_CHECK,
    run_baseline_seed_artifact_validation,
)


def _resolve(path: Path | str) -> Path:
    candidate = Path(str(path).replace("\\", "/"))
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


# --- Frequently changed notebook controls ---------------------------------

RUN_ARTIFACT_AUDIT = False
RUN_ID = "replace-with-run-id"
EXPECTED_ECONOMIES = ["20_USA"]
CANDIDATE_WORKBOOKS: dict[str, Path | str] = {}
TEMPLATE_PATHS_BY_ECONOMY: dict[str, Path | str] = {}
EXPECTED_SCENARIOS = ["Current Accounts", "Reference", "Target"]
EXPECTED_YEARS_BY_SCENARIO = {
    "Current Accounts": [2022],
    "Reference": list(range(2023, 2061)),
    "Target": list(range(2023, 2061)),
}
EXPECTED_PRODUCERS: list[str] = []
PRODUCER_ARTIFACTS_BY_PRODUCER: dict[str, list[Path | str]] = {}
SOURCE_ROWS_BY_ECONOMY: dict[str, Path | str] = {}
ZERO_SCOPE_MANIFESTS_BY_ECONOMY: dict[str, Path | str] = {}
REQUIRED_DIAGNOSTICS: list[Path | str] = []
OUTPUT_DIR = Path("outputs/leap_exports/baseline_seed_artifact_validation")
ENFORCEMENT_BY_CHECK = dict(DEFAULT_ENFORCEMENT_BY_CHECK)


# --- Run block -------------------------------------------------------------

if RUN_ARTIFACT_AUDIT:
    ARTIFACT_AUDIT_RESULT = run_baseline_seed_artifact_validation(
        run_id=RUN_ID,
        candidate_workbooks={economy: _resolve(path) for economy, path in CANDIDATE_WORKBOOKS.items()},
        expected_economies=EXPECTED_ECONOMIES,
        template_paths_by_economy={economy: _resolve(path) for economy, path in TEMPLATE_PATHS_BY_ECONOMY.items()},
        expected_scenarios=EXPECTED_SCENARIOS,
        expected_years_by_scenario=EXPECTED_YEARS_BY_SCENARIO,
        expected_producers=EXPECTED_PRODUCERS,
        producer_artifacts_by_producer=PRODUCER_ARTIFACTS_BY_PRODUCER,
        source_rows_by_economy=SOURCE_ROWS_BY_ECONOMY,
        zero_scope_manifests_by_economy=ZERO_SCOPE_MANIFESTS_BY_ECONOMY,
        required_diagnostics=[_resolve(path) for path in REQUIRED_DIAGNOSTICS],
        output_dir=_resolve(OUTPUT_DIR),
        enforcement_by_check=ENFORCEMENT_BY_CHECK,
    )
    print(
        f"[INFO] Baseline-seed artifact audit: {ARTIFACT_AUDIT_RESULT.shadow_status}; "
        f"manifest={ARTIFACT_AUDIT_RESULT.manifest_path}"
    )

#%%

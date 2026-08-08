#%%
"""Developer mode: run the review tools against the live working copies.

This is the maintainer's entry point. It resolves ``leap_initialisation``,
``leap_mappings``, and ``leap_dashboard`` from one explicit local settings file
(see :mod:`codebase.portable_release.settings`), never from the current working
directory, and runs the same command implementations the portable release runs.

There is no build step in this mode: an edit in any of the three repositories
takes effect on the next call. The price is that the output is only as
reproducible as the working tree, so every run manifest records each
repository's commit *and* whether its working tree was dirty.

Notebook use::

    from codebase.portable_release import developer_launcher as dev
    dev.print_status()
    result = dev.run_balance_review(
        economy="20_USA", scenario="Target", year=2022,
        balance_export_workbook=r"...\\TGT 0308.xlsx",
        diagnostics_directory=r"...\\results_update_preview_20260803_usa_tgt",
    )
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.portable_release.commands import (  # noqa: E402
    CommandResult,
    run_balance_review as _run_balance_review,
    run_balance_review_from_export as _run_balance_review_from_export,
    run_dashboard as _run_dashboard,
    run_dashboard_from_export as _run_dashboard_from_export,
    write_support_bundle as _write_support_bundle,
)
from codebase.portable_release.manifest import (  # noqa: E402
    ReleaseManifest,
    load_release_manifest,
)
from codebase.portable_release.runtime import (  # noqa: E402
    RuntimeContext,
    developer_context,
    run_logging,
)
from codebase.portable_release.settings import (  # noqa: E402
    DeveloperSettings,
    load_developer_settings,
)


DEFAULT_MANIFEST_PATH = REPO_ROOT / "config" / "portable_release_manifest.toml"


def _resolve(path: Path | str) -> Path:
    raw = Path(str(path).replace("\\", "/"))
    return raw if raw.is_absolute() else REPO_ROOT / raw


def load_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> ReleaseManifest:
    """Load the release manifest, which also defines the configuration roles.

    Developer mode reads the manifest for the *role table* only — which file
    plays which configuration role, and which repository owns it. The pinned
    commits are ignored here on purpose: developer mode runs the working tree.
    """
    return load_release_manifest(_resolve(path))


def build_context(
    *,
    settings: DeveloperSettings | None = None,
    manifest: ReleaseManifest | None = None,
) -> RuntimeContext:
    """Build a developer-mode runtime context from the local settings file."""
    resolved_settings = settings or load_developer_settings()
    resolved_manifest = manifest or load_manifest()

    sys_path_roots: list[Path] = []
    for spec in resolved_manifest.repositories.values():
        root = resolved_settings.repositories.get(spec.key)
        if root is None:
            continue
        sys_path_roots.append(root / spec.strip_prefix if spec.strip_prefix else root)

    config_assets: dict[str, Path] = {}
    for asset in resolved_manifest.config_assets:
        root = resolved_settings.repositories.get(asset.repository)
        if root is not None:
            config_assets[asset.role] = root / asset.path

    data_assets: dict[str, Path] = {}
    for asset in resolved_manifest.data_assets:
        root = resolved_settings.repositories.get(asset.repository)
        if root is not None:
            data_assets[asset.role] = root / asset.path

    return developer_context(
        release_name=resolved_manifest.name,
        release_version=f"{resolved_manifest.version}+dev",
        repository_roots=resolved_settings.repositories,
        config_root=resolved_settings.repositories["leap_initialisation"] / "config",
        config_assets=config_assets,
        data_assets=data_assets,
        sys_path_roots=sys_path_roots,
        output_root=resolved_settings.output_root,
        input_root=resolved_settings.input_root,
        log_root=resolved_settings.log_root,
    )


def _ready_context(context: RuntimeContext | None) -> RuntimeContext:
    resolved = context or build_context()
    resolved.require_ready()
    resolved.activate_sys_path()
    return resolved


# ---------------------------------------------------------------------------
# Status and safe updates
# ---------------------------------------------------------------------------


def repository_status(context: RuntimeContext | None = None) -> list[dict[str, Any]]:
    """Return the commit and dirty state of each configured repository."""
    resolved = context or build_context()
    return [
        {
            "repository": state.key,
            "path": state.path,
            "branch": state.branch,
            "commit": state.commit,
            "dirty": state.dirty,
            "dirty_file_count": state.dirty_file_count,
            "note": state.note,
        }
        for state in resolved.repository_states()
    ]


def print_status(context: RuntimeContext | None = None) -> None:
    """Print where developer mode will read code and configuration from."""
    resolved = context or build_context()
    print(resolved.describe())
    print()
    problems = resolved.preflight()
    if problems:
        print("Problems that will stop a run:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("Preflight: all required repositories and configuration files are present.")
    print()
    print("Repository state")
    print("-" * 72)
    for row in repository_status(resolved):
        dirty = (
            "unknown"
            if row["dirty"] is None
            else f"DIRTY ({row['dirty_file_count']} changed files)"
            if row["dirty"]
            else "clean"
        )
        print(f"  {row['repository']:<20} {str(row['commit'])[:12]}  {row['branch']}  {dirty}")


def plan_repository_update(
    context: RuntimeContext | None = None,
    *,
    repositories: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Describe the pulls :func:`update_repositories` would perform.

    Always call this first. Nothing is fetched or pulled by this function.
    """
    resolved = context or build_context()
    selected = list(repositories) if repositories else sorted(resolved.repository_roots)
    plan: list[dict[str, Any]] = []
    blocked: list[str] = []
    for key in selected:
        root = resolved.repository_roots.get(key)
        if root is None:
            blocked.append(f"{key}: not configured in the settings file.")
            continue
        state = next(
            (item for item in resolved.repository_states() if item.key == key),
            None,
        )
        if state is None or state.commit is None:
            blocked.append(f"{key}: repository state could not be read.")
            continue
        if state.dirty:
            blocked.append(
                f"{key}: working tree has {state.dirty_file_count} uncommitted "
                "changes. Commit or stash them before updating."
            )
            continue
        upstream = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "@{upstream}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if upstream.returncode != 0:
            blocked.append(f"{key}: branch {state.branch!r} has no upstream to pull from.")
            continue
        plan.append(
            {
                "repository": key,
                "path": str(root),
                "branch": state.branch,
                "upstream": upstream.stdout.strip(),
                "current_commit": state.commit,
                "command": f"git -C {root} pull --ff-only",
            }
        )
    return {"plan": plan, "blocked": blocked}


def update_repositories(
    context: RuntimeContext | None = None,
    *,
    repositories: Sequence[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Fast-forward the configured repositories, only when explicitly confirmed.

    This never runs silently: it prints the exact repositories, branches, and
    upstreams it would pull, refuses any repository with a dirty working tree,
    and does nothing at all unless ``confirm=True``. Plain ``git pull`` in each
    checkout remains an equally good option.
    """
    resolved = context or build_context()
    proposal = plan_repository_update(resolved, repositories=repositories)
    print("Proposed updates")
    print("-" * 72)
    for item in proposal["plan"]:
        print(f"  {item['repository']:<20} {item['branch']} <- {item['upstream']}")
        print(f"    {item['command']}")
    for reason in proposal["blocked"]:
        print(f"  [skipped] {reason}")
    if not confirm:
        print()
        print("Nothing was pulled. Re-run with confirm=True to perform these updates.")
        return {**proposal, "performed": []}

    performed: list[dict[str, Any]] = []
    for item in proposal["plan"]:
        result = subprocess.run(
            ["git", "-C", item["path"], "pull", "--ff-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        performed.append(
            {
                "repository": item["repository"],
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )
        print(f"  {item['repository']}: exit {result.returncode}")
    return {**proposal, "performed": performed}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_balance_review(
    *,
    economy: str,
    scenario: str,
    year: int,
    balance_export_workbook: Path | str,
    diagnostics_directory: Path | str,
    run_label: str | None = None,
    context: RuntimeContext | None = None,
) -> CommandResult:
    """Build one balance-review workbook from existing diagnostic artifacts."""
    resolved = _ready_context(context)
    with run_logging(resolved, "balance-review"):
        result = _run_balance_review(
            resolved,
            economy=economy,
            scenario=scenario,
            year=year,
            balance_export_workbook=balance_export_workbook,
            diagnostics_directory=diagnostics_directory,
            run_label=run_label,
        )
        print("\n".join(result.summary_lines()))
    return result


def run_balance_review_from_export(
    *,
    economy: str,
    scenario: str,
    year: int,
    balance_export_workbook: Path | str | None = None,
    esto_table_path: Path | str | None = None,
    run_label: str | None = None,
    context: RuntimeContext | None = None,
) -> CommandResult:
    """Build one balance-review workbook directly from a LEAP export."""
    resolved = _ready_context(context)
    with run_logging(resolved, "balance-review-from-export"):
        result = _run_balance_review_from_export(
            resolved,
            economy=economy,
            scenario=scenario,
            year=year,
            balance_export_workbook=balance_export_workbook,
            esto_table_path=esto_table_path,
            run_label=run_label,
        )
        print("\n".join(result.summary_lines()))
    return result


def run_dashboard(
    *,
    economy: str,
    comparison_data_path: Path | str,
    common_rows_path: Path | str,
    comparison_scope: str = "esto_leap_ninth",
    min_year: int | None = 2010,
    max_year: int | None = 2060,
    run_label: str | None = None,
    context: RuntimeContext | None = None,
) -> CommandResult:
    """Render the Common ESTO dashboard for one economy."""
    resolved = _ready_context(context)
    with run_logging(resolved, "dashboard"):
        result = _run_dashboard(
            resolved,
            economy=economy,
            comparison_data_path=comparison_data_path,
            common_rows_path=common_rows_path,
            comparison_scope=comparison_scope,
            min_year=min_year,
            max_year=max_year,
            run_label=run_label,
        )
        print("\n".join(result.summary_lines()))
    return result


def run_dashboard_from_export(
    *,
    economy: str,
    export_dir: Path | str | None = None,
    comparison_data_path: Path | str | None = None,
    common_rows_path: Path | str | None = None,
    esto_table_path: Path | str | None = None,
    comparison_scope: str = "esto_leap_ninth",
    min_year: int | None = 2010,
    max_year: int | None = 2060,
    run_label: str | None = None,
    context: RuntimeContext | None = None,
) -> CommandResult:
    """Go from a LEAP balance export to a rendered dashboard in one run.

    Runs the leap_mappings mapping chain as a subprocess
    (:mod:`codebase.portable_release.mapping_chain_client`), invoked with
    ``cwd`` set to the maintainer's ``leap_mappings`` checkout - see the
    two-executable decision in
    ``docs/leap_review_tools_handover_20260803.md`` §1.
    """
    resolved = _ready_context(context)
    with run_logging(resolved, "dashboard-from-export"):
        result = _run_dashboard_from_export(
            resolved,
            economy=economy,
            export_dir=export_dir,
            comparison_data_path=comparison_data_path,
            common_rows_path=common_rows_path,
            esto_table_path=esto_table_path,
            comparison_scope=comparison_scope,
            min_year=min_year,
            max_year=max_year,
            run_label=run_label,
        )
        print("\n".join(result.summary_lines()))
    return result


def write_support_bundle(
    result: CommandResult,
    *,
    destination: Path | str | None = None,
    context: RuntimeContext | None = None,
) -> Path:
    """Zip the run manifest, logs, settings, and validation report for support."""
    resolved = context or build_context()
    path = _write_support_bundle(resolved, result, destination=destination)
    print(f"Support bundle written: {path}")
    return path


def default_developer_inputs(
    settings: DeveloperSettings | None = None,
) -> Mapping[str, Path]:
    """Return the live upstream files developer mode normally reads."""
    resolved = settings or load_developer_settings()
    mappings = resolved.repositories["leap_mappings"]
    return {
        "comparison_data_path": mappings / "results" / "common_esto" / "common_esto_comparison_data.csv",
        "common_rows_path": mappings / "results" / "common_esto" / "common_esto_rows.csv",
        "balance_exports_root": resolved.repositories["leap_initialisation"]
        / "data"
        / "leap balances exports",
    }


#%%
# ---------------------------------------------------------------------------
# NOTEBOOK CONTROLS
# ---------------------------------------------------------------------------
RUN_DEVELOPER_LAUNCHER = False

# "status" | "balance-review" | "balance-review-from-export" | "dashboard" |
# "dashboard-from-export"
DEVELOPER_ACTION = "status"

ECONOMY = "20_USA"
SCENARIO = "Target"
YEAR = 2022
BALANCE_EXPORT_WORKBOOK = ""
DIAGNOSTICS_DIRECTORY = ""
EXPORT_DIR: str | None = None
COMPARISON_DATA_PATH = ""
COMMON_ROWS_PATH = ""
RUN_LABEL: str | None = None

if RUN_DEVELOPER_LAUNCHER:
    if DEVELOPER_ACTION == "status":
        print_status()
    elif DEVELOPER_ACTION == "balance-review":
        LAUNCHER_RESULT = run_balance_review(
            economy=ECONOMY,
            scenario=SCENARIO,
            year=YEAR,
            balance_export_workbook=BALANCE_EXPORT_WORKBOOK,
            diagnostics_directory=DIAGNOSTICS_DIRECTORY,
            run_label=RUN_LABEL,
        )
    elif DEVELOPER_ACTION == "balance-review-from-export":
        LAUNCHER_RESULT = run_balance_review_from_export(
            economy=ECONOMY,
            scenario=SCENARIO,
            year=YEAR,
            balance_export_workbook=BALANCE_EXPORT_WORKBOOK or None,
            run_label=RUN_LABEL,
        )
    elif DEVELOPER_ACTION == "dashboard":
        LAUNCHER_RESULT = run_dashboard(
            economy=ECONOMY,
            comparison_data_path=COMPARISON_DATA_PATH,
            common_rows_path=COMMON_ROWS_PATH,
            run_label=RUN_LABEL,
        )
    elif DEVELOPER_ACTION == "dashboard-from-export":
        LAUNCHER_RESULT = run_dashboard_from_export(
            economy=ECONOMY,
            export_dir=EXPORT_DIR or None,
            comparison_data_path=COMPARISON_DATA_PATH or None,
            common_rows_path=COMMON_ROWS_PATH or None,
            run_label=RUN_LABEL,
        )
    else:
        raise ValueError(f"Unknown DEVELOPER_ACTION: {DEVELOPER_ACTION!r}")

#%%

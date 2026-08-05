"""The supported commands, shared by developer mode and portable release mode.

These functions are the single implementation of each supported tool. They take
a :class:`~codebase.portable_release.runtime.RuntimeContext` that says where the
code, configuration, and output folders are, and they behave identically whether
that context was built from the maintainer's live checkouts or from a frozen
package. Nothing here knows which mode it is running in.

Every command follows the same shape:

1. validate the whole input set and stop with a plain-language explanation;
2. run the owning repository's real implementation (never a reimplementation);
3. record inputs, configuration hashes, and outputs in the run manifest.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from codebase.portable_release import esto_vintage, progress, validation, workspace
from codebase.portable_release.provenance import (
    RunManifest,
    describe_directory_files,
    describe_file,
    finish_run_manifest,
    new_run_manifest,
)
from codebase.portable_release.runtime import RuntimeContext


#: Commands this module implements. The release manifest may declare a subset;
#: anything declared but not listed here is rejected by manifest validation.
IMPLEMENTED_COMMANDS = (
    "balance-review",
    "balance-review-from-export",
    "dashboard",
    "dashboard-from-export",
)


@dataclass
class CommandResult:
    """Outcome of one command run."""

    command: str
    ok: bool
    run_directory: Path
    output_directory: Path
    run_manifest: RunManifest
    manifest_paths: dict[str, Path]
    validation_report: validation.ValidationReport
    outputs: dict[str, Any]
    error: str | None = None

    def summary_lines(self) -> list[str]:
        lines = [
            f"Command : {self.command}",
            f"Result  : {'succeeded' if self.ok else 'FAILED'}",
            f"Results : {self.output_directory}",
            f"Run log : {self.run_directory}",
        ]
        if self.error:
            lines.append(f"Error   : {self.error}")
        for key, value in self.outputs.items():
            lines.append(f"  {key}: {value}")
        return lines


def _resolve_user_path(context: RuntimeContext, value: Path | str) -> Path:
    """Turn a user-supplied path into an absolute one, predictably.

    Relative paths must be pinned down here, before anything else sees them.
    The owning repositories resolve relative paths against their own repository
    root — the right convention inside a checkout, and a meaningless one inside
    a package, where it lands in PyInstaller's ``_internal`` bundle. Left alone,
    validation (which checks against the working directory) and the workbook
    resolver (which checks against the repository root) disagree, so a run gets
    past validation and then fails.

    A relative path is taken as relative to the working directory, the way any
    command-line tool behaves. If nothing is there, the package root is tried
    too, so ``--diagnostics-directory input\\foo`` works from anywhere.
    """
    raw = Path(str(value).replace("\\", "/"))
    if raw.is_absolute():
        return raw
    from_cwd = (Path.cwd() / raw).resolve()
    if from_cwd.exists():
        return from_cwd
    from_package = (context.package_root / raw).resolve()
    if from_package.exists():
        return from_package
    # Neither exists: return the working-directory form so the validation
    # message names the path the user actually typed, relative to where they are.
    return from_cwd


def _run_directories(
    context: RuntimeContext,
    *,
    tool: str,
    economy: str | None,
    label: str | None,
) -> tuple[Path, Path]:
    """Return ``(deliverable_dir, record_dir)`` for one run.

    Deliverables are grouped by economy so runs accumulate instead of
    overwriting: a balance-review workbook already carries its scenario and year
    in its filename, so REF/TGT and several years coexist in one folder, and a
    dashboard is replaced in place for the economy it belongs to.

    The run manifest, validation report, and log go in a per-run sub-folder, so
    re-running never destroys the record of the previous run either.
    """
    token = label or datetime.now().strftime("%Y%m%d_%H%M%S")
    if economy:
        deliverable_dir = (
            workspace.economy_output_root(context.output_root, economy) / tool
        )
    else:
        deliverable_dir = context.output_root / tool
    record_dir = deliverable_dir / "run_records" / token
    deliverable_dir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)
    return deliverable_dir, record_dir


def _configuration_records(
    context: RuntimeContext,
    roles: Sequence[str],
    data_roles: Sequence[str] = (),
):
    """Describe the configuration and source tables a command actually used.

    Source tables are hashed like everything else. They are large, so this is
    the slowest part of starting a run that uses them - and it is worth it: it
    is the only way a run manifest can say which ESTO vintage produced its
    numbers.
    """
    records = []
    for role in roles:
        path = context.config_asset(role)
        if path is not None:
            records.append(describe_file(path, role=f"config:{role}"))
    for role in data_roles:
        path = context.data_asset(role)
        if path is not None:
            records.append(describe_file(path, role=f"data:{role}"))
    return records


def timing_store(context: RuntimeContext) -> progress.TimingStore:
    """The recorded run timings for this copy of the tools.

    Kept under ``logs/`` rather than ``config/``: it is a record of what this
    machine has actually done, not a setting anyone edits, and it has to be
    writable — which ``config/`` is not guaranteed to be. The builder seeds it
    from the maintainer's own runs so the first run on a colleague's machine
    can still show an estimate.
    """
    return progress.TimingStore(context.log_root / progress.TIMINGS_FILENAME)


#: The chain steps, in the order the worker announces them. `esto_rows` is
#: skipped unless the user supplied their own ESTO table, so it is declared
#: only by the paths that can produce it.
_CHAIN_STEPS = (
    progress.Step("parse_export", "Reading the LEAP export"),
    progress.Step("convert", "Converting LEAP results to the ESTO structure"),
    progress.Step("compare", "Comparing LEAP, ESTO and the 9th"),
)

_VALIDATE_STEP = progress.Step("validate", "Checking your files")
_ESTO_ROWS_STEP = progress.Step(
    "esto_rows", "Re-deriving the ESTO comparison rows"
)


def _chain_steps(*, supplied_esto: bool, final: progress.Step) -> list[progress.Step]:
    """Assemble the declared steps for one export-driven command."""
    steps = [_VALIDATE_STEP]
    if supplied_esto:
        steps.append(_ESTO_ROWS_STEP)
    steps.extend(_CHAIN_STEPS)
    steps.append(final)
    return steps


def _execute(
    context: RuntimeContext,
    *,
    command: str,
    run_label: str | None,
    validate: Callable[[], validation.ValidationReport],
    config_roles: Sequence[str],
    settings: dict[str, Any],
    work: Callable[[Path], dict[str, Any]],
    output_describer: Callable[[dict[str, Any]], list],
    tool: str,
    economy: str | None = None,
    data_roles: Sequence[str] = (),
    steps: Sequence[progress.Step] = (),
    subject: str | None = None,
) -> CommandResult:
    """Run one command with validation, manifest, and log capture around it.

    ``steps`` declares the progress display for commands long enough to need
    one. Without it the command runs exactly as before, silently.
    """
    deliverable_dir, run_dir = _run_directories(
        context, tool=tool, economy=economy, label=run_label
    )
    reporter = (
        progress.ProgressReporter(
            command=command, steps=list(steps), store=timing_store(context)
        )
        if steps
        else None
    )
    manifest = new_run_manifest(
        release_name=context.release_name,
        release_version=context.release_version,
        mode=context.mode,
        command=command,
        settings=settings,
    )
    manifest.release_commits = dict(context.release_commits)
    manifest.repositories = context.repository_states()
    manifest.configuration = _configuration_records(context, config_roles, data_roles)

    if reporter is not None:
        reporter.start(subject)

    # `progress.active` puts the reporter where the mapping-chain client can
    # find it: the worker's step announcements arrive several frames below
    # here, inside `work`.
    with progress.active(reporter):
        if reporter is not None:
            reporter.begin("validate")
        report = validate()
        manifest.validation = report.as_dict()
        (run_dir / "validation_report.txt").write_text(report.as_text(), encoding="utf-8")

        if not report.ok:
            if reporter is not None:
                reporter.finish(ok=False)
            finish_run_manifest(manifest, status="failed", error=report.failure_message())
            paths = manifest.write(run_dir)
            return CommandResult(
                command=command,
                ok=False,
                run_directory=run_dir,
                output_directory=deliverable_dir,
                run_manifest=manifest,
                manifest_paths=paths,
                validation_report=report,
                outputs={},
                error=report.failure_message(),
            )

        try:
            outputs = work(deliverable_dir)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised to the caller
            if reporter is not None:
                reporter.finish(ok=False)
            finish_run_manifest(manifest, status="failed", error=f"{type(exc).__name__}: {exc}")
            paths = manifest.write(run_dir)
            return CommandResult(
                command=command,
                ok=False,
                run_directory=run_dir,
                output_directory=deliverable_dir,
                run_manifest=manifest,
                manifest_paths=paths,
                validation_report=report,
                outputs={},
                error=f"{type(exc).__name__}: {exc}",
            )

    if reporter is not None:
        # Recorded only on success: a run that failed part-way would drag the
        # estimate down for every run after it.
        reporter.finish(ok=True)
    manifest.inputs = outputs.pop("_input_records", [])
    manifest.outputs = output_describer(outputs)
    manifest.results = outputs
    finish_run_manifest(manifest, status="succeeded")
    paths = manifest.write(run_dir)
    return CommandResult(
        command=command,
        ok=True,
        run_directory=run_dir,
        output_directory=deliverable_dir,
        run_manifest=manifest,
        manifest_paths=paths,
        validation_report=report,
        outputs=outputs,
    )


# ---------------------------------------------------------------------------
# balance-review
# ---------------------------------------------------------------------------


def run_balance_review(
    context: RuntimeContext,
    *,
    economy: str,
    scenario: str,
    year: int,
    balance_export_workbook: Path | str,
    diagnostics_directory: Path | str,
    run_label: str | None = None,
) -> CommandResult:
    """Build one balance-review workbook from existing diagnostic artifacts.

    Input mode: **existing comparison/diagnostic artifacts**. The caller supplies
    the LEAP balance export and a diagnostics directory the balance-diagnostics
    step already produced.

    This command does not run that step. Generating diagnostics from a LEAP
    export needs the mapping codebook and the ESTO and 9th-edition source tables
    (314 MB), so it stays in developer mode
    (``balance_update_workflow._PRESET_REVIEW_ONLY``) rather than shipping in a
    release. A results update / supply reconciliation run is *not* involved in
    producing a review workbook — see ``docs/leap_review_tools.md``.
    """
    workbook_path = _resolve_user_path(context, balance_export_workbook)
    diagnostics_dir = _resolve_user_path(context, diagnostics_directory)

    def validate() -> validation.ValidationReport:
        return validation.validate_balance_review_inputs(
            economy=economy,
            scenario=scenario,
            year=year,
            balance_export_workbook=workbook_path,
            diagnostics_directory=diagnostics_dir,
        )

    def work(run_dir: Path) -> dict[str, Any]:
        from codebase.functions.balance_review_workbook_builder import (
            build_balance_structure_review_workbook,
        )
        from codebase.utilities.leap_balance_export_resolver import (
            normalize_balance_scenario_code,
            select_balance_export_sheets,
        )

        economy_code = validation.normalize_economy(economy)
        scenario_name = validation.normalize_scenario(scenario)
        selected = select_balance_export_sheets(
            workbook_path,
            years=[int(year)],
            scenarios=[scenario_name],
        )[0]
        scenario_token = normalize_balance_scenario_code(scenario_name).lower()
        output_path = (
            run_dir / f"balance_review_{economy_code}_{scenario_token}_{int(year)}.xlsx"
        )
        build_result = build_balance_structure_review_workbook(
            economy=economy_code,
            source_workbook=selected.path,
            source_sheet_name=selected.sheet_name,
            diagnostics_directory=diagnostics_dir,
            output_workbook=output_path,
        )
        # Sample rows are a large debugging aid, not part of the run record.
        build_result.pop("reconciliationSamples", None)
        input_records = [describe_file(workbook_path, role="input:balance_export_workbook")]
        input_records += describe_directory_files(
            diagnostics_dir,
            role_prefix="input:diagnostic_artifact",
            patterns=("leap_balance_*.csv",),
        )
        return {
            "_input_records": input_records,
            "workbook": str(output_path),
            "source_sheet": selected.sheet_name,
            "economy": economy_code,
            "scenario": scenario_name,
            "year": int(year),
            "build_result": build_result,
        }

    def describe_outputs(outputs: dict[str, Any]) -> list:
        return [describe_file(outputs["workbook"], role="output:balance_review_workbook")]

    return _execute(
        context,
        command="balance-review",
        tool=workspace.BALANCE_REVIEW_DIRNAME,
        economy=economy,
        run_label=run_label,
        validate=validate,
        config_roles=(),
        settings={
            "economy": economy,
            "scenario": scenario,
            "year": year,
            "balance_export_workbook": str(workbook_path),
            "diagnostics_directory": str(diagnostics_dir),
            "input_mode": "existing_diagnostic_artifacts",
        },
        work=work,
        output_describer=describe_outputs,
    )


# ---------------------------------------------------------------------------
# balance-review-from-export
# ---------------------------------------------------------------------------

#: Data tables and configuration the balance-diagnostics step reads. Roles are
#: resolved from the package (or the live checkouts in developer mode) and are
#: hashed into the run manifest, so a run always records which source vintage
#: and which synthetic-row rules produced its numbers.
DIAGNOSTICS_DATA_ROLES = ("esto_base_table", "ninth_projection_table")
DIAGNOSTICS_CONFIG_ROLES = (
    "outlook_mappings_master",
    "synthetic_reference_rows",
    "leap_results_sheet_map",
    "leap_explicit_reassignments",
    "balance_error_signal_rules",
)


def resolve_export_for(
    context: RuntimeContext,
    *,
    economy: str,
    scenario: str,
    explicit: Path | str | None = None,
) -> Path:
    """Find the balance export for one economy and scenario.

    An explicit path always wins. Otherwise the workbook is resolved from
    ``input/leap balances exports/<ECONOMY>/`` by the repository's own resolver,
    which picks the newest date id and ignores ``archive/``. That is why a user
    normally passes only ``--economy``: the folder layout carries the rest.
    """
    if explicit:
        return _resolve_user_path(context, explicit)

    from codebase.utilities.leap_balance_export_resolver import (
        resolve_balance_export_workbook,
    )

    exports_root = workspace.balance_exports_root(context.input_root)
    folder = workspace.normalize_economy_folder(economy)
    try:
        return Path(
            resolve_balance_export_workbook(
                economy=folder,
                scenario=scenario,
                exports_root=exports_root,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(
            f"No {scenario} balance export was found for {folder}.\n"
            f"  Looked in: {exports_root / folder}\n"
            f"  {exc}\n"
            "Run 'leap-review-tools.exe list' to see what is available."
        ) from None


def parse_years(value: Any) -> list[int]:
    """Read one year, or several, from what a user typed.

    ``2022``, ``2022,2030``, ``2022, 2030`` and ``2022 2030`` all work. The
    diagnostics workflow has always taken a list of years and built a workbook
    for each; only this command's signature said one, silently discarding the
    rest, so a comma here used to produce a single workbook with no complaint.
    """
    if isinstance(value, int):
        return [value]
    parts = [part for part in re.split(r"[,\s]+", str(value).strip()) if part]
    if not parts:
        raise ValueError("No year given.")
    years: list[int] = []
    for part in parts:
        try:
            year = int(part)
        except ValueError:
            raise ValueError(
                f"{part!r} is not a year. Give a year like 2022, or several "
                "separated by commas: 2022,2030"
            ) from None
        if year not in years:
            years.append(year)
    return years


def run_balance_review_from_export(
    context: RuntimeContext,
    *,
    economy: str,
    scenario: str,
    year: int,
    balance_export_workbook: Path | str | None = None,
    esto_table_path: Path | str | None = None,
    run_label: str | None = None,
) -> CommandResult:
    """Go from a LEAP balance export to a finished review workbook in one run.

    This runs both steps: the balance-diagnostics step
    (``run_baseline_seed_balance_diagnostics``), which compares the export
    against the ESTO and 9th-edition source tables using the canonical mapping,
    and then the workbook build.

    ``esto_table_path`` lets a user substitute their own ESTO base table for the
    one shipped with the release. Whichever table is used, the diagnostics step
    applies the same ``synthetic_reference_rows.csv`` rules the maintainer's
    pipeline applies — the mechanism that adds the zero-valued rows a newer ESTO
    vintage introduced (Datacentres, hydrogen transformation, and so on) when a
    supplied table does not carry them. That behaviour is not reimplemented
    here; it is the same code path and the same rules file.
    """
    review_years = parse_years(year)
    workbook_path = resolve_export_for(
        context,
        economy=economy,
        scenario=scenario,
        explicit=balance_export_workbook,
    )
    supplied_esto = (
        _resolve_user_path(context, esto_table_path) if esto_table_path else None
    )

    def validate() -> validation.ValidationReport:
        return validation.validate_balance_review_from_export_inputs(
            economy=economy,
            scenario=scenario,
            year=review_years[0],
            extra_years=review_years[1:],
            balance_export_workbook=workbook_path,
            esto_table_path=supplied_esto,
            mapping_workbook_path=context.config_asset("outlook_mappings_master"),
            bundled_esto_table=context.data_asset("esto_base_table"),
            projection_table=context.data_asset("ninth_projection_table"),
        )

    def work(run_dir: Path) -> dict[str, Any]:
        from functools import partial

        from codebase.balance_update_workflow import (
            _PRESET_REVIEW_ONLY,
            run_balance_update_workflow,
        )
        from codebase.functions.baseline_seed_balance_diagnostics import (
            run_baseline_seed_balance_diagnostics,
        )

        economy_code = validation.normalize_economy(economy)
        scenario_name = validation.normalize_scenario(scenario)
        esto_table = supplied_esto or context.require_data_asset("esto_base_table")

        # The base year is a property of the ESTO table - its last year column -
        # not a separate setting. Deriving it here means a new ESTO issue moves
        # the base year on its own, instead of needing three hardcoded constants
        # edited in two repositories.
        vintage = esto_vintage.infer_esto_vintage(esto_table)

        diagnostic_paths: dict[str, Any] = {
            "esto_table_path": esto_table,
            "projection_table_path": context.require_data_asset("ninth_projection_table"),
        }
        for role, keyword in [
            ("outlook_mappings_master", "codebook_path"),
            ("synthetic_reference_rows", "synthetic_reference_rows_path"),
            ("leap_results_sheet_map", "sheet_map_path"),
            ("leap_explicit_reassignments", "explicit_reassignments_path"),
            ("balance_error_signal_rules", "balance_variable_rules_path"),
        ]:
            path = context.config_asset(role)
            if path is not None and path.is_file():
                diagnostic_paths[keyword] = path
        mapping_workbook = context.config_asset("outlook_mappings_master")
        if mapping_workbook is not None and mapping_workbook.is_file():
            diagnostic_paths["mapping_pairs_path"] = (
                mapping_workbook,
                "ninth_pairs_to_esto_pairs",
            )

        progress.begin_step("review")
        # run_balance_update_workflow owns the review orchestration and takes no
        # path overrides, but it does expose the diagnostic runner as a seam.
        # Binding the paths there keeps the real workflow in charge - including
        # its synthetic-reference-row handling - rather than reimplementing it.
        outcome = run_balance_update_workflow(
            preset=_PRESET_REVIEW_ONLY,
            economies=[economy_code],
            review_years=review_years,
            review_scenarios=[scenario_name],
            update_scenarios=[],
            output_root=run_dir,
            review_output_label="diagnostics",
            workbook_paths_by_economy={economy_code: workbook_path},
            diagnostic_runner=partial(
                run_baseline_seed_balance_diagnostics,
                base_year=vintage.base_year,
                **diagnostic_paths,
            ),
        )

        diagnostics_dir = run_dir / "diagnostics"
        # One workbook per requested year. This used to take [0] and drop the
        # rest on the floor, so asking for three years quietly produced one.
        produced_all = list(outcome["review_workbooks"])
        for item in produced_all:
            item.pop("reconciliationSamples", None)
        built = produced_all[0]

        # The diagnostics workflow writes the workbook under its own
        # diagnostics/comparison_workbooks/ tree. That is the right shape for a
        # maintainer's run and the wrong one here: the workbook is the whole
        # point of the command, and burying it two folders below the supporting
        # CSVs makes a user hunt for it. Lift it to the deliverable folder and
        # leave the diagnostics beside it.
        workbooks: list[str] = []
        for item in produced_all:
            produced = Path(str(item["outputWorkbook"]))
            if produced.is_file() and produced.parent != run_dir:
                final = run_dir / produced.name
                if final.exists():
                    final.unlink()
                produced.replace(final)
                item["outputWorkbook"] = str(final)
            workbooks.append(str(item["outputWorkbook"]))

        input_records = [describe_file(workbook_path, role="input:balance_export_workbook")]
        if supplied_esto is not None:
            input_records.append(
                describe_file(supplied_esto, role="input:esto_base_table_override")
            )
        return {
            "_input_records": input_records,
            "workbook": built["outputWorkbook"],
            "workbooks": workbooks,
            "diagnostics_directory": str(diagnostics_dir),
            "economy": economy_code,
            "scenario": scenario_name,
            "year": review_years[0],
            "years": review_years,
            "esto_table_used": str(esto_table),
            "esto_table_is_user_supplied": supplied_esto is not None,
            "esto_vintage_years": vintage.label,
            "esto_base_year": vintage.base_year,
            "build_result": built,
        }

    def describe_outputs(outputs: dict[str, Any]) -> list:
        records = [
            describe_file(path, role="output:balance_review_workbook")
            for path in outputs["workbooks"]
        ]
        records += describe_directory_files(
            outputs["diagnostics_directory"],
            role_prefix="output:diagnostic_artifact",
            patterns=("leap_balance_*.csv",),
        )
        return records

    return _execute(
        context,
        command="balance-review-from-export",
        tool=workspace.BALANCE_REVIEW_DIRNAME,
        economy=economy,
        run_label=run_label,
        validate=validate,
        config_roles=DIAGNOSTICS_CONFIG_ROLES,
        data_roles=DIAGNOSTICS_DATA_ROLES,
        settings={
            "economy": economy,
            "scenario": scenario,
            "year": review_years[0],
            "years": review_years,
            "balance_export_workbook": str(workbook_path),
            "esto_table_override": str(supplied_esto) if supplied_esto else "",
            "input_mode": "leap_balance_export",
        },
        work=work,
        output_describer=describe_outputs,
        # Two steps, not five: this command runs inside
        # run_balance_update_workflow, which owns the orchestration and offers
        # no seam between comparing and writing. Announcing steps this code
        # cannot actually observe would put the display out of step with the
        # run, which is worse than a coarse one.
        steps=[
            _VALIDATE_STEP,
            progress.Step("review", "Comparing the balance with ESTO and building the workbook"),
        ],
        subject=(
            f"Building the balance-review workbook for "
            f"{validation.normalize_economy(economy)} {scenario} "
            f"{', '.join(str(y) for y in review_years)}."
        ),
    )


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------


#: Written at the top of a dashboard folder so the pages are one click away.
#: The rendered pages link to each other by bare filename and to
#: ``../chart_bundles/``, so they cannot simply be moved up a level - this
#: points at them instead, which is the same result with none of the risk.
_DASHBOARD_SHORTCUT_NAME = "OPEN THE DASHBOARD.html"
_DASHBOARD_SHORTCUT = """<!doctype html>
<meta charset="utf-8">
<title>Opening the dashboard...</title>
<meta http-equiv="refresh" content="0; url=dashboards/index.html">
<p style="font-family: Segoe UI, Arial, sans-serif">
Opening the dashboard. If nothing happens,
<a href="dashboards/index.html">click here</a>.
</p>
"""


def _flatten_dashboard_output(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Lift the rendered dashboard out of its redundant economy sub-folder.

    The renderer writes into ``<output_root>/<ECONOMY>/``, which is the right
    shape when one root holds every economy. Here the folder above it is already
    that economy, so the result was
    ``output/20_USA/dashboard/20USA/dashboards/index.html`` - five levels down,
    with the economy named twice, to reach the one file anyone wants.

    The pages themselves are left exactly as rendered: they link to each other
    by bare filename and reach their charts through ``../chart_bundles/``, so
    moving individual files would break them. Only the duplicated directory
    level is removed, and a one-line page at the top points at the index.
    """
    rendered_root = Path(result.get("output_root", "")) if result.get("output_root") else None
    if rendered_root is None or not rendered_root.is_dir() or rendered_root == run_dir:
        return result
    for item in list(rendered_root.iterdir()):
        destination = run_dir / item.name
        if destination.exists():
            shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        shutil.move(str(item), str(destination))
    rendered_root.rmdir()

    moved = dict(result)
    for key, value in result.items():
        if isinstance(value, (str, Path)) and str(value).startswith(str(rendered_root)):
            moved[key] = str(run_dir / Path(str(value)).relative_to(rendered_root))
    moved["output_root"] = str(run_dir)

    shortcut = run_dir / _DASHBOARD_SHORTCUT_NAME
    shortcut.write_text(_DASHBOARD_SHORTCUT, encoding="utf-8")
    moved["open_this"] = str(shortcut)
    return moved


def _missing_leap_demand_branches(context: RuntimeContext, economy: str) -> list[str]:
    """Ask leap_mappings which demand sectors have no separately modelled detail.

    The answer is owned by ``leap_mappings``
    (``config/all_demand_aggregated_components.json``). When that configuration
    asset is not present, every sector page is rendered and the run manifest
    records that the coverage filter was skipped.
    """
    components_path = context.config_asset("all_demand_aggregated_components")
    if components_path is None or not components_path.is_file():
        return []
    from mapping_tools.source_branch_preflight import (
        get_demand_sectors_without_detail,
        load_all_demand_aggregated_components,
    )

    components = load_all_demand_aggregated_components(components_path)
    compact = validation.normalize_economy(economy).replace("_", "")
    return list(get_demand_sectors_without_detail(components, compact))


def run_dashboard(
    context: RuntimeContext,
    *,
    economy: str,
    comparison_data_path: Path | str,
    common_rows_path: Path | str,
    comparison_scope: str = "esto_leap_ninth",
    wide_file_scope: str = "esto_leap_ninth",
    min_year: int | None = 2010,
    max_year: int | None = 2060,
    include_ninth_pre_base_year_data: bool = False,
    run_label: str | None = None,
) -> CommandResult:
    """Render the Common ESTO dashboard for one economy.

    Input mode: **existing Common ESTO comparison data**. The comparison data is
    produced by the ``leap_mappings`` pipeline and is far too large to bundle, so
    it is a run input rather than part of the package.
    """
    comparison_path = _resolve_user_path(context, comparison_data_path)
    rows_path = _resolve_user_path(context, common_rows_path)
    template_path = context.config_asset("dashboard_template")
    series_config_path = context.config_asset("dashboard_series_config")

    def validate() -> validation.ValidationReport:
        return validation.validate_dashboard_inputs(
            economy=economy,
            comparison_data_path=comparison_path,
            common_rows_path=rows_path,
            template_path=template_path,
            series_config_path=series_config_path,
            comparison_scope=comparison_scope,
        )

    def work(run_dir: Path) -> dict[str, Any]:
        from common_esto_dashboard_portable import render_common_esto_dashboard

        missing_branches = _missing_leap_demand_branches(context, economy)
        result = render_common_esto_dashboard(
            economy=economy,
            comparison_data_path=comparison_path,
            common_rows_path=rows_path,
            template_path=template_path,
            series_config_path=series_config_path,
            code_colors_path=context.config_asset("dashboard_code_colors"),
            output_root=run_dir,
            comparison_scope=comparison_scope,
            wide_file_scope=wide_file_scope,
            min_year=min_year,
            max_year=max_year,
            include_ninth_pre_base_year_data=include_ninth_pre_base_year_data,
            missing_leap_demand_branches=missing_branches,
            dashboard_updated_label=datetime.now().astimezone().strftime(
                "%Y-%m-%d %H:%M %Z"
            ),
            clear_existing=True,
        )
        return {
            "_input_records": [
                describe_file(comparison_path, role="input:comparison_data"),
                describe_file(rows_path, role="input:common_rows"),
            ],
            **result,
        }

    def describe_outputs(outputs: dict[str, Any]) -> list:
        return [
            describe_file(outputs["dashboard_index"], role="output:dashboard_index"),
            describe_file(outputs["chart_manifest"], role="output:chart_manifest"),
            describe_file(
                outputs["sign_semantics_summary"],
                role="output:sign_semantics_summary",
            ),
        ]

    return _execute(
        context,
        command="dashboard",
        tool=workspace.DASHBOARD_DIRNAME,
        economy=economy,
        run_label=run_label,
        validate=validate,
        config_roles=(
            "dashboard_template",
            "dashboard_series_config",
            "dashboard_code_colors",
            "all_demand_aggregated_components",
        ),
        settings={
            "economy": economy,
            "comparison_data_path": str(comparison_path),
            "common_rows_path": str(rows_path),
            "comparison_scope": comparison_scope,
            "wide_file_scope": wide_file_scope,
            "min_year": min_year,
            "max_year": max_year,
            "include_ninth_pre_base_year_data": include_ninth_pre_base_year_data,
            "input_mode": "existing_common_esto_comparison_data",
        },
        work=work,
        output_describer=describe_outputs,
    )


# ---------------------------------------------------------------------------
# dashboard-from-export
# ---------------------------------------------------------------------------

#: Pre-built mapping artifacts the chain needs (§2 of the handover): outputs of
#: the mapping workbook and source tables, not of any model run, so they ship
#: as regenerated data assets rather than being recomputed per dashboard run.
MAPPING_CHAIN_DATA_ROLES = (
    "mapping_chain_relationships",
    "mapping_chain_esto_exact_rows",
    "mapping_chain_ninth_converted",
    "mapping_chain_common_esto_rows",
)
MAPPING_CHAIN_CONFIG_ROLES = (
    "outlook_mappings_master",
    "source_branch_fallback_rules",
    "all_demand_aggregated_components",
)


def run_dashboard_from_export(
    context: RuntimeContext,
    *,
    economy: str,
    comparison_data_path: Path | str | None = None,
    common_rows_path: Path | str | None = None,
    export_dir: Path | str | None = None,
    esto_table_path: Path | str | None = None,
    comparison_scope: str = "esto_leap_ninth",
    wide_file_scope: str = "esto_leap_ninth",
    min_year: int | None = 2010,
    max_year: int | None = 2060,
    include_ninth_pre_base_year_data: bool = False,
    run_label: str | None = None,
) -> CommandResult:
    """Go from a LEAP balance export to a rendered dashboard in one run.

    Input mode: **a LEAP balance export directory**. Runs the leap_mappings
    mapping chain (parse -> convert -> Common ESTO fast path) as a subprocess
    via :mod:`codebase.portable_release.mapping_chain_client`, then the same
    ``render_common_esto_dashboard`` call :func:`run_dashboard` uses.

    ``comparison_data_path`` (with ``common_rows_path``) is an escape hatch: if
    supplied, the mapping chain is skipped entirely and this behaves like
    :func:`run_dashboard` against the supplied files.
    """
    from codebase.portable_release import mapping_chain_client

    if comparison_data_path is not None:
        return run_dashboard(
            context,
            economy=economy,
            comparison_data_path=comparison_data_path,
            common_rows_path=common_rows_path,
            comparison_scope=comparison_scope,
            wide_file_scope=wide_file_scope,
            min_year=min_year,
            max_year=max_year,
            include_ninth_pre_base_year_data=include_ninth_pre_base_year_data,
            run_label=run_label,
        )

    resolved_export_dir = (
        _resolve_user_path(context, export_dir)
        if export_dir is not None
        else workspace.balance_exports_root(context.input_root)
        / workspace.normalize_economy_folder(economy)
    )
    template_path = context.config_asset("dashboard_template")
    series_config_path = context.config_asset("dashboard_series_config")

    def validate() -> validation.ValidationReport:
        return validation.validate_dashboard_from_export_inputs(
            economy=economy,
            export_dir=resolved_export_dir,
            template_path=template_path,
            series_config_path=series_config_path,
            mapping_workbook_path=context.config_asset("outlook_mappings_master"),
            source_branch_fallback_rules_path=context.config_asset(
                "source_branch_fallback_rules"
            ),
            all_demand_components_path=context.config_asset(
                "all_demand_aggregated_components"
            ),
            mapping_chain_data_assets={
                role: context.data_asset(role) for role in MAPPING_CHAIN_DATA_ROLES
            },
        )

    supplied_esto = (
        _resolve_user_path(context, esto_table_path) if esto_table_path else None
    )

    def work(run_dir: Path) -> dict[str, Any]:
        from common_esto_dashboard_portable import render_common_esto_dashboard

        economy_code = validation.normalize_economy(economy)
        chain_job = {
            "economy": economy_code,
            "export_dir": str(resolved_export_dir),
            "work_dir": str(run_dir / "mapping_chain"),
            "artifacts": {
                "relationships_path": str(context.require_data_asset("mapping_chain_relationships")),
                "esto_exact_rows_path": str(context.require_data_asset("mapping_chain_esto_exact_rows")),
                "ninth_converted_path": str(context.require_data_asset("mapping_chain_ninth_converted")),
                "common_esto_rows_path": str(context.require_data_asset("mapping_chain_common_esto_rows")),
            },
            "config": {
                "mapping_workbook_path": str(context.require_config_asset("outlook_mappings_master")),
                "source_branch_fallback_rules_path": str(
                    context.require_config_asset("source_branch_fallback_rules")
                ),
                "all_demand_components_path": str(
                    context.require_config_asset("all_demand_aggregated_components")
                ),
            },
        }
        # Only send the ESTO base table when the user supplied one. The worker
        # re-extracts exact rows whenever it receives a table, which takes about
        # two minutes; the shipped exact rows already match the shipped table, so
        # an ordinary run must not pay that cost to arrive back where it started.
        if supplied_esto is not None:
            chain_job["config"]["esto_base_table_path"] = str(supplied_esto)
            rules = context.config_asset("synthetic_reference_rows")
            if rules is not None:
                chain_job["config"]["synthetic_reference_rows_path"] = str(rules)
        chain_result = mapping_chain_client.run_mapping_chain(context, chain_job)

        missing_branches = _missing_leap_demand_branches(context, economy)
        progress.begin_step("render")
        result = render_common_esto_dashboard(
            economy=economy_code,
            comparison_data_path=Path(chain_result["comparison_data_path"]),
            common_rows_path=Path(chain_result["common_rows_path"]),
            template_path=template_path,
            series_config_path=series_config_path,
            code_colors_path=context.config_asset("dashboard_code_colors"),
            output_root=run_dir,
            comparison_scope=comparison_scope,
            wide_file_scope=wide_file_scope,
            min_year=min_year,
            max_year=max_year,
            include_ninth_pre_base_year_data=include_ninth_pre_base_year_data,
            missing_leap_demand_branches=missing_branches,
            dashboard_updated_label=datetime.now().astimezone().strftime(
                "%Y-%m-%d %H:%M %Z"
            ),
            clear_existing=True,
        )
        return {
            "_input_records": describe_directory_files(
                resolved_export_dir, role_prefix="input:balance_export", patterns=("*.xlsx",)
            ),
            # Promoted out of the chain result so they are readable rather than
            # buried in it. These say whether the ESTO rows were re-derived and
            # how many synthetic rows were injected — the two facts that explain
            # why a number differs from the previous run.
            "esto_source_notes": list(chain_result.get("notes", [])),
            "mapping_chain": chain_result,
            **_flatten_dashboard_output(run_dir, result),
        }

    def describe_outputs(outputs: dict[str, Any]) -> list:
        return [
            describe_file(outputs["dashboard_index"], role="output:dashboard_index"),
            describe_file(outputs["chart_manifest"], role="output:chart_manifest"),
            describe_file(
                outputs["sign_semantics_summary"],
                role="output:sign_semantics_summary",
            ),
        ]

    return _execute(
        context,
        command="dashboard-from-export",
        tool=workspace.DASHBOARD_DIRNAME,
        economy=economy,
        run_label=run_label,
        validate=validate,
        config_roles=(
            "dashboard_template",
            "dashboard_series_config",
            "dashboard_code_colors",
        )
        + MAPPING_CHAIN_CONFIG_ROLES,
        data_roles=MAPPING_CHAIN_DATA_ROLES,
        settings={
            "economy": economy,
            "export_dir": str(resolved_export_dir),
            "comparison_scope": comparison_scope,
            "wide_file_scope": wide_file_scope,
            "min_year": min_year,
            "max_year": max_year,
            "include_ninth_pre_base_year_data": include_ninth_pre_base_year_data,
            "input_mode": "leap_balance_export",
        },
        work=work,
        output_describer=describe_outputs,
        steps=_chain_steps(
            supplied_esto=supplied_esto is not None,
            final=progress.Step("render", "Drawing the charts"),
        ),
        subject=f"Building the dashboard for {validation.normalize_economy(economy)}.",
    )


# ---------------------------------------------------------------------------
# Support bundle
# ---------------------------------------------------------------------------


def write_support_bundle(
    context: RuntimeContext,
    result: CommandResult,
    *,
    destination: Path | str | None = None,
) -> Path:
    """Zip the run manifest, logs, effective settings, and validation report.

    Raw input data is never added: a support bundle is meant to be emailed, and
    the inputs are both large and potentially confidential. The manifest records
    their paths and SHA-256 values, which is what a diagnosis needs.
    """
    import zipfile

    target = (
        Path(str(destination).replace("\\", "/"))
        if destination is not None
        else context.output_root
        / f"support_bundle_{result.command}_{result.run_directory.name}.zip"
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    effective_settings = {
        "release": {
            "name": context.release_name,
            "version": context.release_version,
            "mode": context.mode,
        },
        "package_root": str(context.package_root),
        "config_root": str(context.config_root),
        "output_root": str(context.output_root),
        "log_root": str(context.log_root),
        "sys_path_roots": [str(path) for path in context.sys_path_roots],
        "config_assets": {
            role: str(path) for role, path in sorted(context.config_assets.items())
        },
        "command_settings": result.run_manifest.settings,
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, path in result.manifest_paths.items():
            if path.is_file():
                bundle.write(path, arcname=f"run/{path.name}")
        validation_path = result.run_directory / "validation_report.txt"
        if validation_path.is_file():
            bundle.write(validation_path, arcname="run/validation_report.txt")
        bundle.writestr(
            "run/effective_settings.json",
            json.dumps(effective_settings, indent=2, default=str),
        )
        if context.log_root.is_dir():
            for log_path in sorted(context.log_root.glob("*.log")):
                bundle.write(log_path, arcname=f"logs/{log_path.name}")
        bundle.writestr(
            "README.txt",
            "This support bundle contains the run manifest, the validation "
            "report, the effective settings, and the run logs.\n\n"
            "It deliberately does NOT contain any input data. The run manifest "
            "records each input's path, size, and SHA-256 so the exact files can "
            "be identified without sending them.\n",
        )
    return target

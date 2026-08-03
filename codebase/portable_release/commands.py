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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from codebase.portable_release import validation
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
IMPLEMENTED_COMMANDS = ("balance-review", "dashboard")


@dataclass
class CommandResult:
    """Outcome of one command run."""

    command: str
    ok: bool
    run_directory: Path
    run_manifest: RunManifest
    manifest_paths: dict[str, Path]
    validation_report: validation.ValidationReport
    outputs: dict[str, Any]
    error: str | None = None

    def summary_lines(self) -> list[str]:
        lines = [
            f"Command : {self.command}",
            f"Result  : {'succeeded' if self.ok else 'FAILED'}",
            f"Run dir : {self.run_directory}",
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


def _run_directory(context: RuntimeContext, command: str, label: str | None) -> Path:
    token = label or datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = context.output_root / f"{command}_{token}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _configuration_records(context: RuntimeContext, roles: Sequence[str]):
    """Describe the configuration assets a command actually used."""
    records = []
    for role in roles:
        path = context.config_asset(role)
        if path is not None:
            records.append(describe_file(path, role=f"config:{role}"))
    return records


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
) -> CommandResult:
    """Run one command with validation, manifest, and log capture around it."""
    run_dir = _run_directory(context, command, run_label)
    manifest = new_run_manifest(
        release_name=context.release_name,
        release_version=context.release_version,
        mode=context.mode,
        command=command,
        settings=settings,
    )
    manifest.release_commits = dict(context.release_commits)
    manifest.repositories = context.repository_states()
    manifest.configuration = _configuration_records(context, config_roles)

    report = validate()
    manifest.validation = report.as_dict()
    (run_dir / "validation_report.txt").write_text(report.as_text(), encoding="utf-8")

    if not report.ok:
        finish_run_manifest(manifest, status="failed", error=report.failure_message())
        paths = manifest.write(run_dir)
        return CommandResult(
            command=command,
            ok=False,
            run_directory=run_dir,
            run_manifest=manifest,
            manifest_paths=paths,
            validation_report=report,
            outputs={},
            error=report.failure_message(),
        )

    try:
        outputs = work(run_dir)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised to the caller
        finish_run_manifest(manifest, status="failed", error=f"{type(exc).__name__}: {exc}")
        paths = manifest.write(run_dir)
        return CommandResult(
            command=command,
            ok=False,
            run_directory=run_dir,
            run_manifest=manifest,
            manifest_paths=paths,
            validation_report=report,
            outputs={},
            error=f"{type(exc).__name__}: {exc}",
        )

    manifest.inputs = outputs.pop("_input_records", [])
    manifest.outputs = output_describer(outputs)
    manifest.results = outputs
    finish_run_manifest(manifest, status="succeeded")
    paths = manifest.write(run_dir)
    return CommandResult(
        command=command,
        ok=True,
        run_directory=run_dir,
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
# dashboard
# ---------------------------------------------------------------------------


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

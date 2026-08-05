#%%
"""Gradio web application for the complete LEAP balance-review workflow.

The app calls the repository's existing ``balance-review-from-export``
orchestration. It does not reimplement diagnostics or workbook construction.
"""

from __future__ import annotations

import json
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
HF_BUNDLE_ROOT = Path(
    os.getenv("HF_BUNDLE_ROOT", str(REPO_ROOT / "hf_bundle"))
)
INITIALISATION_ROOT = (
    HF_BUNDLE_ROOT / "leap_initialisation"
    if (HF_BUNDLE_ROOT / "leap_initialisation").is_dir()
    else REPO_ROOT
)
ARCHIVE_ROOT = Path(
    os.getenv(
        "LEAP_REVIEW_ARCHIVE_ROOT",
        str(Path.home() / "leap_review_tools" / "archives"),
    )
)
if str(INITIALISATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INITIALISATION_ROOT))

from codebase.portable_release import developer_launcher  # noqa: E402
from codebase.portable_release.settings import DeveloperSettings  # noqa: E402


def _path_from_gradio_file(value: object, *, description: str) -> Path:
    """Return a validated local path from a Gradio File component value."""
    if value is None or str(value).strip() == "":
        raise ValueError(f"Please upload {description}.")
    raw_path = getattr(value, "name", value)
    path = Path(str(raw_path))
    if not path.is_file():
        raise FileNotFoundError(f"Uploaded file was not found: {path.name}")
    return path


def _safe_filename_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip())
    return token.strip("_") or "unknown"


def _source_commit() -> str:
    """Return the current source commit for the run summary."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
        if result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return "source checkout commit unavailable"


def _repository_roots() -> dict[str, Path]:
    """Resolve the three live source repositories for developer-style runs.

    Hugging Face or Docker deployments can mount/clone the sibling repositories
    elsewhere by setting the two optional environment variables.
    """
    if (HF_BUNDLE_ROOT / "leap_mappings").is_dir() and (
        HF_BUNDLE_ROOT / "leap_dashboard"
    ).is_dir():
        return {
            "leap_initialisation": INITIALISATION_ROOT,
            "leap_mappings": HF_BUNDLE_ROOT / "leap_mappings",
            "leap_dashboard": HF_BUNDLE_ROOT / "leap_dashboard",
        }
    parent = REPO_ROOT.parent
    return {
        "leap_initialisation": INITIALISATION_ROOT,
        "leap_mappings": Path(
            os.getenv("LEAP_MAPPINGS_ROOT", str(parent / "leap_mappings"))
        ),
        "leap_dashboard": Path(
            os.getenv("LEAP_DASHBOARD_ROOT", str(parent / "leap_dashboard"))
        ),
    }


def _build_context(run_root: Path):
    """Build the same live-repository context used by developer mode."""
    settings = DeveloperSettings(
        source_path=INITIALISATION_ROOT
        / "config"
        / "portable_release_manifest.toml",
        repositories=_repository_roots(),
        output_root=run_root / "output",
        input_root=run_root / "input",
        log_root=run_root / "logs",
    )
    context = developer_launcher.build_context(settings=settings)
    context.require_ready()
    context.activate_sys_path()
    return context


def _copy_input(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    copied = destination / source.name
    shutil.copy2(source, copied)
    return copied


def _write_diagnostics_bundle(
    *,
    bundle_path: Path,
    workbook_paths: list[Path],
    diagnostics_directory: Path,
    run_directory: Path,
    dashboard_directory: Path | None = None,
    log_directory: Path | None = None,
) -> None:
    """Package derived diagnostics and the workbook for optional download."""
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for workbook_path in workbook_paths:
            bundle.write(workbook_path, arcname=f"workbooks/{workbook_path.name}")
        if diagnostics_directory.is_dir():
            for path in sorted(diagnostics_directory.rglob("*.csv")):
                bundle.write(path, arcname=f"diagnostics/{path.name}")
        for name in ("validation_report.txt", "run_manifest.json", "run_manifest.txt"):
            path = run_directory / name
            if path.is_file():
                bundle.write(path, arcname=name)
        if dashboard_directory is not None and dashboard_directory.is_dir():
            for path in sorted(dashboard_directory.rglob("*")):
                if path.is_file():
                    bundle.write(path, arcname=f"dashboard/{path.relative_to(dashboard_directory)}")
        if log_directory is not None and log_directory.is_dir():
            for path in sorted(log_directory.glob("*.log")):
                bundle.write(path, arcname=f"logs/{path.name}")


def _dashboard_pages(dashboard_directory: Path) -> list[str]:
    """Return dashboard page filenames suitable for the page selector."""
    return sorted(
        path.name
        for path in dashboard_directory.glob("*.html")
        if path.name != "index.html"
    )


def _dashboard_archive_records() -> list[dict[str, object]]:
    """Read persisted dashboard metadata, newest first."""
    if not ARCHIVE_ROOT.is_dir():
        return []
    records: list[dict[str, object]] = []
    for metadata_path in ARCHIVE_ROOT.glob("*/metadata.json"):
        try:
            record = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (metadata_path.parent / "dashboard").is_dir():
            records.append(record)
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _dashboard_archive_choices() -> list[tuple[str, str]]:
    """Return friendly labels and stable archive IDs for a Gradio dropdown."""
    choices = []
    for record in _dashboard_archive_records():
        archive_id = str(record.get("archive_id", ""))
        label = (
            f"{record.get('economy', 'unknown')} / "
            f"{record.get('scenario', 'unknown')} / "
            f"{record.get('years', '')} ({record.get('created_at', '')})"
        )
        if archive_id:
            choices.append((label, archive_id))
    return choices


def _dashboard_archive_record(archive_id: str | None) -> dict[str, object] | None:
    if not archive_id:
        return None
    return next(
        (record for record in _dashboard_archive_records()
         if record.get("archive_id") == archive_id),
        None,
    )


def _persist_dashboard_archive(
    *,
    economy: str,
    scenario: str,
    years: object,
    dashboard_directory: Path | None,
    workbook_paths: list[Path],
    diagnostics_directory: Path,
    run_directory: Path,
    log_directory: Path,
) -> tuple[Path, dict[str, object]]:
    """Persist a complete derived run for later dashboard comparison."""
    if dashboard_directory is None or not dashboard_directory.is_dir():
        raise FileNotFoundError("Dashboard output was not available to archive.")
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    archive_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{_safe_filename_token(economy)}_{_safe_filename_token(scenario)}_"
        f"{uuid4().hex[:8]}"
    )
    archive_directory = ARCHIVE_ROOT / archive_id
    archive_directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(dashboard_directory, archive_directory / "dashboard")
    persistent_workbooks = []
    for workbook_path in workbook_paths:
        target = archive_directory / "workbooks" / workbook_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workbook_path, target)
        persistent_workbooks.append(target)
    bundle_path = ARCHIVE_ROOT / f"{archive_id}.zip"
    _write_diagnostics_bundle(
        bundle_path=bundle_path,
        workbook_paths=workbook_paths,
        diagnostics_directory=diagnostics_directory,
        run_directory=run_directory,
        dashboard_directory=archive_directory / "dashboard",
        log_directory=log_directory,
    )
    record = {
        "archive_id": archive_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "economy": economy,
        "scenario": scenario,
        "years": years,
        "dashboard_directory": str(archive_directory / "dashboard"),
        "bundle_path": str(bundle_path),
        "dashboard_pages": _dashboard_pages(archive_directory / "dashboard"),
    }
    (archive_directory / "metadata.json").write_text(
        json.dumps(record, indent=2, default=str), encoding="utf-8"
    )
    return bundle_path, record


def _inline_dashboard_chart_bundle(page_path: Path, page_html: str) -> str:
    """Inline the page's generated chart bundle for iframe rendering."""
    marker = 'src="../chart_bundles/'
    rendered = page_html
    while marker in rendered:
        start = rendered.index(marker) + len(marker)
        end = rendered.index('"', start)
        bundle_name = rendered[start:end]
        bundle_path = page_path.parent.parent / "chart_bundles" / bundle_name
        if not bundle_path.is_file():
            break
        bundle_text = bundle_path.read_text(encoding="utf-8")
        script_tag = f"<script>\n{bundle_text}\n</script>"
        old_tag = f'<script src="../chart_bundles/{bundle_name}"></script>'
        rendered = rendered.replace(old_tag, script_tag, 1)
    return rendered


def _dashboard_iframe_html(
    dashboard_directory: Path,
    page_name: str,
    economy: str,
    scenario: str,
) -> str:
    """Render a generated dashboard page inside an isolated iframe."""
    page_path = dashboard_directory / page_name
    if not page_path.is_file():
        return "<p>Choose a generated dashboard page.</p>"
    page_html = _inline_dashboard_chart_bundle(
        page_path,
        page_path.read_text(encoding="utf-8"),
    )
    scenario_mode = {"reference": "ref", "target": "tgt"}.get(
        scenario.casefold(), ""
    )
    context_banner = (
        '<div style="font:600 14px system-ui,sans-serif;padding:10px 14px;'
        'margin:0 0 12px;border:1px solid #c5ccd3;border-radius:8px;'
        'background:#f6f8fa;color:#24292f">'
        f"Economy: {html.escape(economy)} &nbsp;|&nbsp; "
        f"Scenario: {html.escape(scenario)}"
        "</div>"
    )
    locked_controls = """
<style>
  .dashboard-switcher, .scenario-toggle { display:none !important; }
</style>
<script>
  (function () {
    var mode = %s;
    if (mode) {
      try { localStorage.setItem('common-esto-scenario-mode', mode); } catch (e) {}
      if (window.applyScenarioMode) {
        document.querySelectorAll('[data-plot-id]').forEach(function (plot) {
          window.applyScenarioMode(plot);
        });
      }
    }
  }());
</script>
""" % json.dumps(scenario_mode)
    if "</body>" in page_html:
        page_html = page_html.replace(
            "</body>", context_banner + locked_controls + "</body>", 1
        )
    else:
        page_html = context_banner + locked_controls + page_html
    escaped = html.escape(page_html, quote=True)
    return (
        '<iframe title="Generated LEAP dashboard" '
        'sandbox="allow-scripts" '
        'style="width:100%;height:900px;border:1px solid #d8dee4;border-radius:8px;" '
        f'srcdoc="{escaped}"></iframe>'
    )


def build_review_from_export(
    economy: str,
    scenario: str,
    year: object,
    balance_export_workbook: object,
    esto_table: object,
    dashboard_min_year: float,
    dashboard_max_year: float,
) -> tuple[str, str, object, str | None, str, object, object, object, str | None]:
    """Run diagnostics and workbook construction from one LEAP export."""
    persistent_bundle: Path | None = None
    try:
        economy_value = str(economy or "").strip()
        scenario_value = str(scenario or "").strip()
        if not economy_value:
            raise ValueError("Enter an economy code, for example 20_USA.")
        if not scenario_value:
            raise ValueError("Enter the scenario, for example Target.")
        year_value = str(year or "").strip()
        if not year_value:
            raise ValueError("Enter one or more review years, for example 2022,2030.")
        dashboard_min_year_value = int(dashboard_min_year)
        dashboard_max_year_value = int(dashboard_max_year)
        if dashboard_min_year_value > dashboard_max_year_value:
            raise ValueError("Dashboard minimum year must not exceed maximum year.")

        export_path = _path_from_gradio_file(
            balance_export_workbook,
            description="the LEAP Energy Balance export workbook",
        )
        esto_path = None
        if esto_table is not None and str(esto_table).strip() != "":
            esto_path = _path_from_gradio_file(
                esto_table,
                description="the optional ESTO base-table CSV",
            )

        run_root = Path(tempfile.mkdtemp(prefix="leap_balance_review_web_"))
        local_export = _copy_input(export_path, run_root / "uploads")
        local_esto = _copy_input(esto_path, run_root / "uploads") if esto_path else None
        export_directory = run_root / "exports" / _safe_filename_token(economy_value)
        export_directory.mkdir(parents=True, exist_ok=True)
        _copy_input(local_export, export_directory)
        context = _build_context(run_root)
        result = developer_launcher.run_balance_review_from_export(
            context=context,
            economy=economy_value,
            scenario=scenario_value,
            year=year_value,
            balance_export_workbook=local_export,
            esto_table_path=local_esto,
            run_label="web",
        )
        if not result.ok:
            raise RuntimeError(result.error or "The balance-review workflow failed.")

        workbook_paths = [Path(path) for path in result.outputs["workbooks"]]
        if not workbook_paths or not all(path.is_file() for path in workbook_paths):
            raise FileNotFoundError("The workflow completed without producing a workbook.")
        diagnostics_directory = Path(result.outputs["diagnostics_directory"])

        dashboard_result = developer_launcher.run_dashboard_from_export(
            context=context,
            economy=economy_value,
            export_dir=export_directory,
            esto_table_path=local_esto,
            min_year=dashboard_min_year_value,
            max_year=dashboard_max_year_value,
            run_label="web",
        )
        dashboard_error = None
        dashboard_directory: Path | None = None
        dashboard_page_names: list[str] = []
        dashboard_html = "<p>No dashboard was generated.</p>"
        if dashboard_result.ok:
            dashboard_index = Path(dashboard_result.outputs["dashboard_index"])
            dashboard_directory = dashboard_index.parent
            dashboard_page_names = _dashboard_pages(dashboard_directory)
            if dashboard_page_names:
                dashboard_html = _dashboard_iframe_html(
                    dashboard_directory,
                    dashboard_page_names[0],
                    economy_value,
                    scenario_value,
                )
        else:
            dashboard_error = dashboard_result.error or "Dashboard generation failed."

        if dashboard_directory is not None:
            persistent_bundle, archive_record = _persist_dashboard_archive(
                economy=economy_value,
                scenario=scenario_value,
                years=result.outputs.get("years", year_value),
                dashboard_directory=dashboard_directory,
                workbook_paths=workbook_paths,
                diagnostics_directory=diagnostics_directory,
                run_directory=result.run_directory,
                log_directory=run_root / "logs",
            )
            persistent_workbooks = [
                Path(archive_record["dashboard_directory"]).parent.parent
                / "workbooks"
                / workbook_path.name
                for workbook_path in workbook_paths
            ]
        else:
            persistent_dir = Path(tempfile.mkdtemp(prefix="leap_balance_review_download_"))
            persistent_workbooks = []
            for workbook_path in workbook_paths:
                target = persistent_dir / workbook_path.name
                shutil.copy2(workbook_path, target)
                persistent_workbooks.append(target)
            persistent_bundle = persistent_dir / (
                f"{_safe_filename_token(economy_value)}_"
                f"{_safe_filename_token(scenario_value)}_{year_value}_diagnostics.zip"
            )
            _write_diagnostics_bundle(
                bundle_path=persistent_bundle,
                workbook_paths=workbook_paths,
                diagnostics_directory=diagnostics_directory,
                run_directory=result.run_directory,
                log_directory=run_root / "logs",
            )
            archive_record = {
                "archive_id": None,
                "dashboard_directory": None,
                "dashboard_pages": [],
            }

        build_result = result.outputs.get("build_result", {})
        summary = {
            "status": "succeeded",
            "source_commit": _source_commit(),
            "economy": economy_value,
            "scenario": scenario_value,
            "years": result.outputs.get("years", year_value),
            "dashboard_min_year": dashboard_min_year_value,
            "dashboard_max_year": dashboard_max_year_value,
            "esto_table_used": result.outputs.get("esto_table_used"),
            "esto_table_is_user_supplied": result.outputs.get(
                "esto_table_is_user_supplied", False
            ),
            "esto_base_year": result.outputs.get("esto_base_year"),
            "diagnostics_directory": str(diagnostics_directory),
            "comparison_state_counts": build_result.get("comparisonStateCounts", {}),
            "missing_audit_rows": build_result.get("missingAuditRows"),
            "formula_error_cells": build_result.get("formulaErrorCells", []),
            "dashboard_status": "succeeded" if dashboard_result.ok else "failed",
            "dashboard_error": dashboard_error,
            "dashboard_pages": dashboard_page_names,
            "dashboard_archive_id": archive_record["archive_id"],
            "dashboard_archive_root": str(ARCHIVE_ROOT),
        }
        archive_choices = _dashboard_archive_choices()
        return (
            json.dumps(summary, indent=2, default=str),
            (
                "Diagnostics, review workbook, and dashboard created."
                if dashboard_result.ok
                else "Diagnostics and review workbook created; dashboard failed."
            ),
            [str(path) for path in persistent_workbooks],
            str(persistent_bundle),
            dashboard_html,
            {
                "choices": dashboard_page_names,
                "value": dashboard_page_names[0] if dashboard_page_names else None,
            },
            {
                "dashboard_directory": archive_record["dashboard_directory"],
                "economy": economy_value,
                "scenario": scenario_value,
            },
            {
                "choices": archive_choices,
                "value": archive_record["archive_id"] if archive_record["archive_id"] else None,
            },
            str(persistent_bundle),
        )
    except Exception as error:  # Gradio should show a plain-language failure.
        return (
            "", f"Build failed: {error}", [], None, "",
            {"choices": [], "value": None},
            None,
            {"choices": _dashboard_archive_choices(), "value": None},
            None,
        )


def render_dashboard_page(page_name: str, dashboard_state: dict[str, object] | None) -> str:
    """Render a selected generated dashboard page in the embedded view."""
    if not page_name or not dashboard_state:
        return "<p>Run the workflow to generate a dashboard.</p>"
    return _dashboard_iframe_html(
        Path(str(dashboard_state["dashboard_directory"])),
        Path(page_name).name,
        str(dashboard_state.get("economy", "")),
        str(dashboard_state.get("scenario", "")),
    )


def select_dashboard_archive(
    archive_id: str | None,
) -> tuple[object, str, str | None, dict[str, object] | None]:
    """Load a previously persisted dashboard into the embedded viewer."""
    record = _dashboard_archive_record(archive_id)
    if record is None:
        return {"choices": [], "value": None}, "<p>Select a saved dashboard.</p>", None, None
    pages = [str(page) for page in record.get("dashboard_pages", [])]
    state = {
        "dashboard_directory": record["dashboard_directory"],
        "economy": record.get("economy", ""),
        "scenario": record.get("scenario", ""),
    }
    rendered = render_dashboard_page(pages[0], state) if pages else "<p>No dashboard pages were saved.</p>"
    return (
        {"choices": pages, "value": pages[0] if pages else None},
        rendered,
        str(record.get("bundle_path")) if record.get("bundle_path") else None,
        state,
    )


def create_app():
    """Create the web interface for local or Hugging Face execution."""
    import gradio as gr

    with gr.Blocks(title="LEAP Balance Review") as app:
        gr.Markdown(
            """# LEAP Balance Review

Upload one LEAP Energy Balance export. The app runs the complete diagnostics
workflow, creates the five-sheet review workbook, and renders the dashboard
pages below. Optionally upload a replacement ESTO base-table CSV; otherwise the
configured pinned ESTO table is used.
"""
        )
        with gr.Row():
            economy = gr.Textbox(label="Economy", value="20_USA")
            scenario = gr.Textbox(label="Scenario", value="Target")
            year = gr.Textbox(
                label="Review year(s)",
                value="2022",
                info="Use commas for multiple workbooks, e.g. 2022,2030,2040.",
            )
        with gr.Row():
            dashboard_min_year = gr.Number(
                label="Dashboard minimum year", value=2010, precision=0
            )
            dashboard_max_year = gr.Number(
                label="Dashboard maximum year", value=2060, precision=0
            )
        balance_export_workbook = gr.File(
            label="LEAP Energy Balance export workbook (.xlsx)",
            file_types=[".xlsx", ".xlsm"],
            type="filepath",
        )
        esto_table = gr.File(
            label="Optional ESTO base-table override (.csv)",
            file_types=[".csv"],
            type="filepath",
        )
        run_button = gr.Button("Calculate diagnostics and build review", variant="primary")
        status = gr.Textbox(label="Status", interactive=False)
        summary = gr.Code(label="Run summary", language="json", interactive=False)
        output = gr.File(
            label="Download review workbook(s)",
            file_count="multiple",
        )
        diagnostics_bundle = gr.File(
            label="Download current full run archive (dashboard and subfolders)"
        )
        gr.Markdown(
            "## Dashboards\n\n"
            "The embedded dashboard is locked to the economy and scenario entered above. "
            "Each run is saved locally so you can compare earlier runs."
        )
        dashboard_archive = gr.Dropdown(
            label="Saved dashboard archive",
            choices=_dashboard_archive_choices(),
            value=None,
            interactive=True,
        )
        dashboard_page = gr.Dropdown(
            label="Dashboard page",
            choices=[],
            value=None,
            interactive=True,
        )
        dashboard_html = gr.HTML(value="<p>Run the workflow to generate a dashboard.</p>")
        dashboard_bundle = gr.File(label="Download selected full dashboard archive")
        dashboard_state = gr.State(value=None)
        run_button.click(
            fn=build_review_from_export,
            inputs=[
                economy,
                scenario,
                year,
                balance_export_workbook,
                esto_table,
                dashboard_min_year,
                dashboard_max_year,
            ],
            outputs=[
                summary,
                status,
                output,
                diagnostics_bundle,
                dashboard_html,
                dashboard_page,
                dashboard_state,
                dashboard_archive,
                dashboard_bundle,
            ],
        )
        dashboard_archive.change(
            fn=select_dashboard_archive,
            inputs=dashboard_archive,
            outputs=[dashboard_page, dashboard_html, dashboard_bundle, dashboard_state],
        )
        dashboard_page.change(
            fn=render_dashboard_page,
            inputs=[dashboard_page, dashboard_state],
            outputs=dashboard_html,
        )
    return app


#%%
if __name__ == "__main__":
    APP = create_app()
    APP.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )

#%%

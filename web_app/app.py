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
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    parent = REPO_ROOT.parent
    return {
        "leap_initialisation": REPO_ROOT,
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
        source_path=REPO_ROOT / "web_app" / "runtime_settings.toml",
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


def _dashboard_pages(dashboard_directory: Path) -> list[str]:
    """Return dashboard page filenames suitable for the page selector."""
    return sorted(
        path.name
        for path in dashboard_directory.glob("*.html")
        if path.name != "index.html"
    )


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


def _dashboard_iframe_html(dashboard_directory: Path, page_name: str) -> str:
    """Render a generated dashboard page inside an isolated iframe."""
    page_path = dashboard_directory / page_name
    if not page_path.is_file():
        return "<p>Choose a generated dashboard page.</p>"
    page_html = _inline_dashboard_chart_bundle(
        page_path,
        page_path.read_text(encoding="utf-8"),
    )
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
    year: float,
    balance_export_workbook: object,
    esto_table: object,
) -> tuple[str, str, str | None, str | None, str, object, str | None]:
    """Run diagnostics and workbook construction from one LEAP export."""
    persistent_output: Path | None = None
    persistent_bundle: Path | None = None
    try:
        economy_value = str(economy or "").strip()
        scenario_value = str(scenario or "").strip()
        if not economy_value:
            raise ValueError("Enter an economy code, for example 20_USA.")
        if not scenario_value:
            raise ValueError("Enter the scenario, for example Target.")
        if year is None or int(year) != year:
            raise ValueError("Enter a four-digit review year, for example 2022.")
        year_value = int(year)

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
                )
        else:
            dashboard_error = dashboard_result.error or "Dashboard generation failed."

        persistent_dir = Path(tempfile.mkdtemp(prefix="leap_balance_review_download_"))
        persistent_output = persistent_dir / workbook_paths[0].name
        shutil.copy2(workbook_paths[0], persistent_output)
        persistent_bundle = persistent_dir / (
            f"{_safe_filename_token(economy_value)}_"
            f"{_safe_filename_token(scenario_value)}_{year_value}_diagnostics.zip"
        )
        _write_diagnostics_bundle(
            bundle_path=persistent_bundle,
            workbook_paths=workbook_paths,
            diagnostics_directory=diagnostics_directory,
            run_directory=result.run_directory,
            dashboard_directory=dashboard_directory,
        )

        build_result = result.outputs.get("build_result", {})
        summary = {
            "status": "succeeded",
            "source_commit": _source_commit(),
            "economy": economy_value,
            "scenario": scenario_value,
            "year": year_value,
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
        }
        return (
            json.dumps(summary, indent=2, default=str),
            (
                "Diagnostics, review workbook, and dashboard created."
                if dashboard_result.ok
                else "Diagnostics and review workbook created; dashboard failed."
            ),
            str(persistent_output),
            str(persistent_bundle),
            dashboard_html,
            {
                "choices": dashboard_page_names,
                "value": dashboard_page_names[0] if dashboard_page_names else None,
            },
            str(dashboard_directory) if dashboard_directory else None,
        )
    except Exception as error:  # Gradio should show a plain-language failure.
        return "", f"Build failed: {error}", None, None, "", {"choices": [], "value": None}, None


def render_dashboard_page(page_name: str, dashboard_directory: str | None) -> str:
    """Render a selected generated dashboard page in the embedded view."""
    if not page_name or not dashboard_directory:
        return "<p>Run the workflow to generate a dashboard.</p>"
    return _dashboard_iframe_html(Path(dashboard_directory), Path(page_name).name)


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
            year = gr.Number(label="Review year", value=2022, precision=0)
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
        output = gr.File(label="Download review workbook")
        diagnostics_bundle = gr.File(label="Download diagnostics bundle")
        gr.Markdown("## Generated dashboard")
        dashboard_page = gr.Dropdown(
            label="Dashboard page",
            choices=[],
            value=None,
            interactive=True,
        )
        dashboard_html = gr.HTML(value="<p>Run the workflow to generate a dashboard.</p>")
        dashboard_directory = gr.State(value=None)
        run_button.click(
            fn=build_review_from_export,
            inputs=[economy, scenario, year, balance_export_workbook, esto_table],
            outputs=[
                summary,
                status,
                output,
                diagnostics_bundle,
                dashboard_html,
                dashboard_page,
                dashboard_directory,
            ],
        )
        dashboard_page.change(
            fn=render_dashboard_page,
            inputs=[dashboard_page, dashboard_directory],
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

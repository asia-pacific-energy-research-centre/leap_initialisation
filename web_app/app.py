#%%
"""Gradio web application for the complete LEAP balance-review workflow.

The app calls the repository's existing ``balance-review-from-export``
orchestration. It does not reimplement diagnostics or workbook construction.
"""

from __future__ import annotations

import json
import html
import base64
import gzip
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
DEFAULT_DASHBOARD_MIN_YEAR = 2010
DEFAULT_DASHBOARD_MAX_YEAR = 2060
# Keep the browser-local payload within common localStorage quotas while still
# allowing comparison between several recent economy/scenario runs.
MAX_BROWSER_DASHBOARDS = 3
HF_BUNDLE_ROOT = Path(
    os.getenv("HF_BUNDLE_ROOT", str(REPO_ROOT / "hf_bundle"))
)
INITIALISATION_ROOT = (
    HF_BUNDLE_ROOT / "leap_initialisation"
    if (HF_BUNDLE_ROOT / "leap_initialisation").is_dir()
    else REPO_ROOT
)
if str(INITIALISATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INITIALISATION_ROOT))


APP_CSS = """
/* A warm, quiet workspace instead of Gradio's default technical form. */
.gradio-container {
  --body-background-fill: #f5f7f3;
  --body-text-color: #253530;
  --block-background-fill: #ffffff;
  --block-border-color: #dfe6df;
  --input-background-fill: #fbfcfa;
  --input-border-color: #d9e2da;
  max-width: 1180px !important;
  width: calc(100% - 2rem) !important;
  margin: 0 auto !important;
  padding: 1.5rem 0 4rem !important;
  color: #253530 !important;
}
body, .gradio-container { background: #f5f7f3 !important; }
.gradio-container .prose, .gradio-container label, .gradio-container span {
  color: inherit;
}
#app-hero {
  position: relative;
  overflow: hidden;
  margin-bottom: 1rem;
  padding: 2rem 2.1rem;
  border: 1px solid #dce7df;
  border-radius: 24px;
  background: linear-gradient(135deg, #ffffff 0%, #eef8f2 100%);
  box-shadow: 0 16px 42px rgba(40, 74, 61, 0.08);
}
#app-hero::after {
  content: "";
  position: absolute;
  right: -55px;
  top: -70px;
  width: 210px;
  height: 210px;
  border-radius: 50%;
  background: rgba(67, 148, 111, 0.1);
}
.hero-eyebrow {
  display: inline-flex;
  margin-bottom: 0.6rem;
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  background: #dff3e7;
  color: #216347;
  font-size: 0.75rem;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
#app-hero h1 {
  position: relative;
  z-index: 1;
  margin: 0 0 0.55rem;
  color: #173b30;
  font-size: clamp(2rem, 4vw, 3.1rem);
  line-height: 1.03;
  letter-spacing: -0.04em;
}
#app-hero p {
  position: relative;
  z-index: 1;
  max-width: 700px;
  margin: 0;
  color: #587068;
  font-size: 1rem;
  line-height: 1.6;
}
.step-heading { margin: 1.5rem 0 0.65rem; }
.step-heading .step-number {
  display: inline-grid;
  width: 1.75rem;
  height: 1.75rem;
  margin-right: 0.5rem;
  place-items: center;
  border-radius: 50%;
  background: #27765a;
  color: white;
  font-size: 0.8rem;
  font-weight: 800;
}
.step-heading strong { color: #203f35; font-size: 1.1rem; }
.step-heading p { margin: 0.2rem 0 0 2.3rem; color: #6c7d77; font-size: 0.88rem; }
#details-card, #upload-card, #run-card, #results-card, #dashboard-card {
  gap: 0.8rem;
  padding: 1rem !important;
  border: 1px solid #dfe7e1 !important;
  border-radius: 18px !important;
  background: #ffffff !important;
  box-shadow: 0 5px 18px rgba(43, 68, 58, 0.045);
}
#input-row, #upload-row, #action-row, #download-row, #dashboard-controls { gap: 0.8rem; }
#input-row .gr-form, #upload-row .gr-form { padding: 0.65rem 0.75rem; }
.gradio-container input, .gradio-container textarea, .gradio-container select {
  border-radius: 10px !important;
}
.gradio-container span[data-testid="block-info"] {
  padding: 0 0 0.35rem !important;
  border: 0 !important;
  background: transparent !important;
  color: #43574f !important;
  font-weight: 700 !important;
}
#balance-upload .file-preview, #balance-upload .upload-container,
#balance-upload .file-upload { min-height: 104px !important; }
#balance-upload .file-upload { padding: 0.75rem !important; border-radius: 13px !important; }
#advanced-options { margin-top: 0.8rem; border-radius: 14px !important; }
#advanced-options > button { color: #526b62 !important; font-weight: 650; }
#esto-note {
  margin: 0;
  padding: 0.65rem 0.8rem;
  border-radius: 10px;
  background: #f2f6f3;
  color: #62756e;
  font-size: 0.82rem;
  line-height: 1.45;
}
#run-button { min-width: 320px; min-height: 48px; border-radius: 12px !important; font-weight: 750; }
#run-button button { box-shadow: 0 7px 18px rgba(39, 118, 90, 0.2); }
#run-status textarea, #run-status input { font-size: 0.88rem; }
#results-empty, #dashboard-empty {
  padding: 1.1rem;
  border: 1px dashed #cad7ce;
  border-radius: 12px;
  background: #fafcf9;
  color: #6d7c76;
  text-align: center;
}
#results-card .file-preview, #dashboard-card .file-preview { min-height: 52px !important; }
#results-card:has(a[download]) #results-empty { display: none; }
#clear-dashboards { align-self: end; max-width: 210px; }
#dashboard-viewer iframe { border-color: #dce4de !important; border-radius: 14px !important; }
#calculator-animation { display: none; align-items: center; gap: 0.65rem;
  min-height: 62px; margin: 0.25rem 0; padding: 0.55rem 0.8rem;
  border-radius: 12px; background: linear-gradient(90deg, #fff8df, #eff8f2);
  border: 1px solid #e9dfb8; }
#calculator-animation.is-running { display: flex; }
.calc-machine { position: relative; width: 54px; height: 48px; padding: 5px;
  border: 3px solid #34495e; border-radius: 8px; background: #f8fbff;
  box-shadow: 3px 3px 0 #34495e; transform: rotate(-3deg); }
.calc-display { height: 13px; padding: 1px 3px; overflow: hidden; border-radius: 3px;
  background: #bde8c1; color: #214a2a; font: 700 8px/11px monospace; }
.calc-keys { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px; margin-top: 5px; }
.calc-key { height: 6px; border-radius: 2px; background: #f2a65a; }
.calc-key:nth-child(2n) { background: #72b7d8; }
.calc-key:nth-child(3n) { background: #e76f51; }
.calc-caption { font-size: 0.86rem; color: #39485a; }
.calc-caption span { display: inline-block; width: 1.2em; text-align: left; }
#calculator-animation.is-running .calc-machine { animation: calculator-wobble 0.65s ease-in-out infinite alternate; }
#calculator-animation.is-running .calc-key { animation: calculator-blink 0.8s steps(2, end) infinite; }
#calculator-animation.is-running .calc-key:nth-child(2) { animation-delay: 0.15s; }
#calculator-animation.is-running .calc-key:nth-child(3) { animation-delay: 0.3s; }
@keyframes calculator-wobble { from { transform: rotate(-5deg) translateY(1px); }
  to { transform: rotate(5deg) translateY(-2px); } }
@keyframes calculator-blink { 50% { filter: brightness(1.45); transform: scale(0.85); } }
@media (max-width: 760px) {
  .gradio-container { width: calc(100% - 1rem) !important; padding-top: 0.5rem !important; }
  #app-hero { padding: 1.45rem; border-radius: 18px; }
  #input-row, #upload-row, #action-row, #download-row, #dashboard-controls { flex-direction: column; }
  #input-row > div, #run-button { min-width: 100%; }
  #clear-dashboards { align-self: stretch; max-width: none; }
}
"""

APP_JS = """
() => {
  const install = () => {
    const button = document.querySelector('#run-button button');
    const animation = document.querySelector('#calculator-animation');
    const status = document.querySelector('#run-status textarea, #run-status input');
    if (!button || !animation || button.dataset.calculatorBound === '1') return;
    button.dataset.calculatorBound = '1';
    let running = false;
    let timer = null;
    const stop = () => {
      running = false;
      animation.classList.remove('is-running');
      if (timer) window.clearInterval(timer);
      timer = null;
    };
    button.addEventListener('click', () => {
      const initialStatus = status ? (status.value || '') : '';
      running = true;
      animation.classList.add('is-running');
      timer = window.setInterval(() => {
        const rawValue = status ? (status.value || '') : '';
        const value = rawValue.toLowerCase();
        if (rawValue && rawValue !== initialStatus &&
            !value.includes('running') && !value.includes('starting')) stop();
      }, 300);
      window.setTimeout(() => { if (running) stop(); }, 900000);
    });
  };
  window.setTimeout(install, 150);
  new MutationObserver(install).observe(document.body, { childList: true, subtree: true });
}
"""

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


def _compress_dashboard_html(page_html: str) -> str:
    compressed = gzip.compress(page_html.encode("utf-8"), compresslevel=9)
    return base64.b64encode(compressed).decode("ascii")


def _decompress_dashboard_html(encoded_html: str) -> str:
    compressed = base64.b64decode(encoded_html.encode("ascii"))
    return gzip.decompress(compressed).decode("utf-8")


def _browser_dashboard_choices(records: object) -> list[tuple[str, str]]:
    if not isinstance(records, list):
        return []
    choices = []
    for record in records:
        if not isinstance(record, dict) or not record.get("archive_id"):
            continue
        choices.append(
            (
                f"{record.get('economy', 'unknown')} / "
                f"{record.get('scenario', 'unknown')} / "
                f"{record.get('years', '')} ({record.get('created_at', '')})",
                str(record["archive_id"]),
            )
        )
    return choices


def _browser_dashboard_record(
    archive_id: str | None,
    records: object,
) -> dict[str, object] | None:
    if not archive_id or not isinstance(records, list):
        return None
    return next(
        (
            record
            for record in records
            if isinstance(record, dict) and record.get("archive_id") == archive_id
        ),
        None,
    )


def _dashboard_snapshot(
    dashboard_directory: Path,
    *,
    economy: str,
    scenario: str,
    years: object,
) -> dict[str, object]:
    """Create a compressed browser-local snapshot of every dashboard page."""
    pages = {}
    for page_name in _dashboard_pages(dashboard_directory):
        page_path = dashboard_directory / page_name
        page_html = _inline_dashboard_chart_bundle(
            page_path,
            page_path.read_text(encoding="utf-8"),
        )
        pages[page_name] = _compress_dashboard_html(page_html)
    return {
        "archive_id": f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "economy": economy,
        "scenario": scenario,
        "years": years,
        "pages": pages,
        "storage": "browser-local",
    }


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


def _dashboard_iframe_from_html(page_html: str, economy: str, scenario: str) -> str:
    """Render dashboard HTML inside an isolated, run-locked iframe."""
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
    return _dashboard_iframe_from_html(page_html, economy, scenario)


def build_review_from_export(
    economy: str,
    scenario: str,
    year: object,
    balance_export_workbook: object,
    esto_table: object,
    browser_archives: object = None,
    dashboard_min_year: float = DEFAULT_DASHBOARD_MIN_YEAR,
    dashboard_max_year: float = DEFAULT_DASHBOARD_MAX_YEAR,
) -> tuple[str, str, object, str | None, str, object, object, object, str | None, object]:
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
            dashboard_directory=dashboard_directory,
            log_directory=run_root / "logs",
        )
        snapshot = (
            _dashboard_snapshot(
                dashboard_directory,
                economy=economy_value,
                scenario=scenario_value,
                years=result.outputs.get("years", year_value),
            )
            if dashboard_directory is not None
            else None
        )
        existing_archives = browser_archives if isinstance(browser_archives, list) else []
        browser_archive_records = (
            [snapshot, *existing_archives[: MAX_BROWSER_DASHBOARDS - 1]]
            if snapshot is not None
            else existing_archives[:MAX_BROWSER_DASHBOARDS]
        )

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
            "dashboard_archive_id": snapshot["archive_id"] if snapshot else None,
            "dashboard_storage": "browser-local",
        }
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
            _dropdown_update(
                dashboard_page_names,
                dashboard_page_names[0] if dashboard_page_names else None,
            ),
            {
                "pages": snapshot["pages"] if snapshot else {},
                "economy": economy_value,
                "scenario": scenario_value,
            },
            _dropdown_update(
                _browser_dashboard_choices(browser_archive_records),
                snapshot["archive_id"] if snapshot else None,
            ),
            str(persistent_bundle),
            browser_archive_records,
        )
    except Exception as error:  # Gradio should show a plain-language failure.
        return (
            "", f"Build failed: {error}", [], None, "",
            _dropdown_update([], None),
            None,
            _dropdown_update(_browser_dashboard_choices(browser_archives), None),
            None,
            browser_archives if isinstance(browser_archives, list) else [],
        )


def render_dashboard_page(page_name: str, dashboard_state: dict[str, object] | None) -> str:
    """Render a selected generated dashboard page in the embedded view."""
    if not page_name or not dashboard_state:
        return "<p>Run the workflow to generate a dashboard.</p>"
    pages = dashboard_state.get("pages")
    if isinstance(pages, dict) and page_name in pages:
        try:
            return _dashboard_iframe_from_html(
                _decompress_dashboard_html(str(pages[page_name])),
                str(dashboard_state.get("economy", "")),
                str(dashboard_state.get("scenario", "")),
            )
        except (OSError, ValueError, UnicodeDecodeError) as error:
            return f"<p>Could not restore this browser-local dashboard page: {html.escape(str(error))}</p>"
    if not dashboard_state.get("dashboard_directory"):
        return "<p>This saved dashboard has no page data.</p>"
    return _dashboard_iframe_html(
        Path(str(dashboard_state["dashboard_directory"])),
        Path(page_name).name,
        str(dashboard_state.get("economy", "")),
        str(dashboard_state.get("scenario", "")),
    )


def _dropdown_update(choices: list[object], value: object) -> object:
    """Return a real Dropdown component update for Gradio 5."""
    import gradio as gr

    return gr.Dropdown(choices=choices, value=value)


def select_dashboard_archive(
    archive_id: str | None,
    browser_archives: object,
) -> tuple[object, str, str | None, dict[str, object] | None]:
    """Load a previously saved browser-local dashboard into the viewer."""
    record = _browser_dashboard_record(archive_id, browser_archives)
    if record is None:
        return _dropdown_update([], None), "<p>Select a saved dashboard.</p>", None, None
    pages = sorted(str(page) for page in (record.get("pages") or {}))
    state = {
        "pages": record.get("pages", {}),
        "economy": record.get("economy", ""),
        "scenario": record.get("scenario", ""),
    }
    rendered = render_dashboard_page(pages[0], state) if pages else "<p>No dashboard pages were saved.</p>"
    return (
        _dropdown_update(pages, pages[0] if pages else None),
        rendered,
        None,
        state,
    )


def load_browser_archives(browser_archives: object) -> object:
    """Populate the archive selector from the user's local browser state."""
    choices = _browser_dashboard_choices(browser_archives)
    return _dropdown_update(choices, choices[0][1] if choices else None)


def clear_browser_archives() -> tuple[list[object], object, object, str, None, None]:
    """Clear only this browser's saved dashboard snapshots."""
    return (
        [],
        _dropdown_update([], None),
        _dropdown_update([], None),
        "<p>Browser-saved dashboards cleared.</p>",
        None,
        None,
    )


def create_app():
    """Create the web interface for local or Hugging Face execution."""
    import gradio as gr

    theme = gr.themes.Soft(
        primary_hue="emerald",
        secondary_hue="amber",
        neutral_hue="slate",
        radius_size="lg",
    )
    with gr.Blocks(
        title="LEAP Balance Review",
        theme=theme,
        css=APP_CSS,
        js=APP_JS,
    ) as app:
        gr.HTML(
            """<header id="app-hero">
              <span class="hero-eyebrow">LEAP review workspace</span>
              <h1>Check your energy balance with confidence.</h1>
              <p>Upload a LEAP export and we’ll prepare the diagnostics,
              review workbooks, and visual dashboards for you.</p>
            </header>"""
        )

        gr.HTML(
            """<div class="step-heading"><span class="step-number">1</span>
              <strong>Tell us what you’re reviewing</strong>
              <p>These details keep the results focused on the right model run.</p>
            </div>"""
        )
        with gr.Column(elem_id="details-card"):
            with gr.Row(elem_id="input-row"):
                economy = gr.Textbox(
                    label="Economy code",
                    value="20_USA",
                    placeholder="e.g. 20_USA",
                )
                scenario = gr.Textbox(
                    label="Scenario",
                    value="Target",
                    placeholder="e.g. Target",
                )
                year = gr.Textbox(
                    label="Review year(s)",
                    value="2022",
                    placeholder="2022 or 2022, 2030, 2040",
                    info="Separate multiple years with commas.",
                )

        gr.HTML(
            """<div class="step-heading"><span class="step-number">2</span>
              <strong>Add your LEAP export</strong>
              <p>An Excel Energy Balance export is the only file you need.</p>
            </div>"""
        )
        with gr.Column(elem_id="upload-card"):
            balance_export_workbook = gr.File(
                label="Energy Balance export",
                file_types=[".xlsx", ".xlsm"],
                type="filepath",
                height=132,
                elem_id="balance-upload",
            )
            with gr.Accordion(
                "Advanced: compare against a different ESTO dataset",
                open=False,
                elem_id="advanced-options",
            ):
                esto_table = gr.File(
                    label="ESTO base-table override (optional)",
                    file_types=[".csv"],
                    type="filepath",
                    height=96,
                    elem_id="esto-upload",
                )
                gr.Markdown(
                    "This replaces the pinned ESTO comparison table for this run. "
                    "The latest year in your CSV becomes the dashboard base year.",
                    elem_id="esto-note",
                )

        gr.HTML(
            """<div class="step-heading"><span class="step-number">3</span>
              <strong>Build your review</strong>
              <p>The full run can take several minutes. You can leave this tab open.</p>
            </div>"""
        )
        with gr.Column(elem_id="run-card"):
            with gr.Row(elem_id="action-row"):
                run_button = gr.Button(
                    "Start balance review",
                    variant="primary",
                    elem_id="run-button",
                )
                status = gr.Textbox(
                    label="Run status",
                    value="Ready when you are",
                    interactive=False,
                    elem_id="run-status",
                )
            gr.HTML(
                """<div id="calculator-animation" role="status" aria-live="polite">
                  <div class="calc-machine" aria-hidden="true">
                    <div class="calc-display">CALCULATING</div>
                    <div class="calc-keys"><i class="calc-key"></i><i class="calc-key"></i><i class="calc-key"></i><i class="calc-key"></i><i class="calc-key"></i><i class="calc-key"></i></div>
                  </div>
                  <div class="calc-caption">Checking balances and preparing your files<span>...</span></div>
                </div>"""
            )
            with gr.Accordion("Technical run details", open=False):
                summary = gr.Code(
                    label="Run summary",
                    language="json",
                    interactive=False,
                )

        gr.HTML(
            """<div class="step-heading"><span class="step-number">✓</span>
              <strong>Your results</strong>
              <p>Workbooks and full diagnostic files will appear here when ready.</p>
            </div>"""
        )
        with gr.Column(elem_id="results-card"):
            gr.HTML(
                "<div id='results-empty'>Nothing to download yet — start a review above.</div>"
            )
            with gr.Row(elem_id="download-row"):
                output = gr.File(
                    label="Review workbook(s)",
                    file_count="multiple",
                )
                diagnostics_bundle = gr.File(label="Complete run archive")

        gr.HTML(
            """<div class="step-heading"><span class="step-number">↗</span>
              <strong>Explore the dashboard</strong>
              <p>Saved views stay private in this browser and are not stored on the server.</p>
            </div>"""
        )
        browser_archives = gr.BrowserState(
            default_value=[],
            storage_key="leap_balance_review_dashboard_archives",
        )
        with gr.Column(elem_id="dashboard-card"):
            with gr.Row(elem_id="dashboard-controls"):
                dashboard_archive = gr.Dropdown(
                    label="Saved review",
                    choices=[],
                    value=None,
                    interactive=True,
                    scale=2,
                )
                dashboard_page = gr.Dropdown(
                    label="Dashboard page",
                    choices=[],
                    value=None,
                    interactive=True,
                    scale=2,
                )
                clear_dashboard_button = gr.Button(
                    "Clear saved views",
                    size="sm",
                    elem_id="clear-dashboards",
                    scale=1,
                )
            dashboard_html = gr.HTML(
                value=(
                    "<div id='dashboard-empty'>Your charts will appear here after "
                    "the review finishes.</div>"
                ),
                elem_id="dashboard-viewer",
            )
            dashboard_bundle = gr.File(label="Download dashboard archive")
            dashboard_state = gr.State(value=None)
        run_button.click(
            fn=build_review_from_export,
            inputs=[
                economy,
                scenario,
                year,
                balance_export_workbook,
                esto_table,
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
                browser_archives,
            ],
        )
        dashboard_archive.change(
            fn=select_dashboard_archive,
            inputs=[dashboard_archive, browser_archives],
            outputs=[dashboard_page, dashboard_html, dashboard_bundle, dashboard_state],
        )
        dashboard_page.change(
            fn=render_dashboard_page,
            inputs=[dashboard_page, dashboard_state],
            outputs=dashboard_html,
        )
        clear_dashboard_button.click(
            fn=clear_browser_archives,
            outputs=[
                browser_archives,
                dashboard_archive,
                dashboard_page,
                dashboard_html,
                dashboard_bundle,
                dashboard_state,
            ],
        )
        app.load(
            fn=load_browser_archives,
            inputs=browser_archives,
            outputs=dashboard_archive,
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

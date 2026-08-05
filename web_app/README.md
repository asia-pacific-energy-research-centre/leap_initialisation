# LEAP Balance Review web app

This is a thin Gradio wrapper around the existing
`balance-review-from-export` orchestration. It is not a second implementation
of the diagnostics or workbook logic.

## Run locally

From the `leap_initialisation` repository root:

```powershell
python -m pip install -r web_app/requirements.txt
python web_app/app.py
```

Open `http://127.0.0.1:7860`.

The app accepts:

- one LEAP balance export workbook;
- one review year or a comma-separated list such as `2022,2030,2040`;
- optionally, an ESTO base-table CSV override.
- dashboard minimum and maximum years.

It runs the diagnostics internally using the configured ESTO and 9th-edition
source tables, then returns the same five-sheet balance-review workbook as the
desktop release. It also runs the dashboard workflow, displays the generated
interactive dashboard pages in the app, and offers a ZIP containing the full
dashboard folder/subfolders, workbook, diagnostics, and logs. The embedded
dashboard is fixed to the submitted economy and scenario; use the saved archive
dropdown to reopen earlier runs for comparison.

Archives are stored outside the repository by default at
`~/leap_review_tools/archives`. Set `LEAP_REVIEW_ARCHIVE_ROOT` to a persistent
mounted directory when deploying to Hugging Face if archives must survive Space
restarts.

## Hugging Face deployment

Use this repository as the source checkout for the Space, or copy `app.py` and
`requirements.txt` into the Space while preserving the `codebase/` package.
The app imports the orchestration from this repository at runtime. Rebuild the
Space from the latest repository commit whenever the workflow changes; no
bundled EXE or pre-existing diagnostics folder is required.

For a Space whose working directory is the repository root, set the Space SDK
to Gradio and use `web_app/app.py` as the application file, or place the file
at the Space root as `app.py`.

The complete workflow requires the sibling `leap_mappings` and
`leap_dashboard` source repositories plus the configured ESTO/9th-edition data
assets. For local runs, the app expects the sibling repositories by default:

```text
github/
  leap_initialisation/
  leap_mappings/
  leap_dashboard/
```

For another deployment layout, set `LEAP_MAPPINGS_ROOT` and
`LEAP_DASHBOARD_ROOT` before starting the app. The run preflight fails clearly
if those repositories or required source assets are absent.

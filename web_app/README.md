# LEAP Balance Review web app

This is a thin Gradio wrapper around the existing
`codebase.functions.balance_review_workbook_builder` function. It is not a
second implementation of the workbook logic.

## Run locally

From the `leap_initialisation` repository root:

```powershell
python -m pip install -r web_app/requirements.txt
python web_app/app.py
```

Open `http://127.0.0.1:7860`.

The app accepts:

- one LEAP balance export workbook;
- `leap_balance_source_differences.csv`;
- `leap_balance_source_review.csv`;
- optional `leap_balance_mapping_issues.csv` and
  `ninth_projection_allocation_diagnostics.csv`.

It returns the same five-sheet balance-review workbook as the desktop release.

## Hugging Face deployment

Use this repository as the source checkout for the Space, or copy `app.py` and
`requirements.txt` into the Space while preserving the `codebase/` package.
The app imports the builder from this repository at runtime. Rebuild the Space
from the latest repository commit whenever the builder changes; no bundled EXE
is required.

For a Space whose working directory is the repository root, set the Space SDK
to Gradio and use `web_app/app.py` as the application file, or place the file
at the Space root as `app.py`.

The current wrapper implements the existing-diagnostics workflow. It does not
run the upstream diagnostic-generation pipeline, which requires the much larger
ESTO/9th-edition source data and mapping repositories.

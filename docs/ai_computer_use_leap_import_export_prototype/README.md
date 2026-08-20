# AI Computer Use LEAP import-export prototype

This folder is the self-contained record of the first controlled LEAP GUI
pilot. It is deliberately narrow: one imported Australian clean-slate backup,
one baseline-seed import, one complete Target Energy Balance export, and the
evidence needed to resume with Reference.

## Contents

- `artifacts/aus_pilot_register.json` -- frozen batch register used to select
  the local staged backup, seed, scenarios, detail level, and filenames.
- `artifacts/aus_pilot_register_review.csv` -- human-readable view of that
  register.
- `artifacts/AUS TGT 20260820 CHATGPT.xlsx` -- completed Target Energy Balance
  export. It has 40 sheets: 2022--2060 and `LEAP`.
- [run_record.md](run_record.md) -- what was actually done, result, safety
  boundaries, and precise next steps.

The maintained reusable components remain in their normal locations; this
prototype package intentionally references rather than duplicates them:

- `codebase/leap_gui_batch_preflight_workflow.py`
- `docs/leap_gui_batch_preflight.md`
- `docs/leap_gui_balance_export_dashboard_runbook.md`

## Safety boundary

Only the repository-local `LEAP_backups/` folder is permitted for `.leap`
backup selection. LEAP itself may install and save an area through its normal
GUI, but this prototype does not manually copy, create, or edit anything in
`C:\LEAP_Areas`. It does not read or modify the OneDrive clean-slate source.

The original seed, staged backup, and ordinary output are retained in their
existing locations. This folder contains portable evidence and a copy of the
completed Target result, not replacement source files.

# Balance-review web app

The `web_app/` directory contains a thin Gradio wrapper around
`codebase/functions/balance_review_workbook_builder.py`.

## Scope

The app replaces the balance-review part of the portable Windows release:

1. upload one LEAP balance export workbook;
2. enter one review year or a comma-separated year list;
3. optionally upload an ESTO base-table CSV override;
4. choose dashboard minimum and maximum years;
5. run the existing diagnostics workflow;
6. run the existing Python workbook builder;
7. run the existing dashboard-from-export workflow;
8. view the generated dashboard pages in the app and download the five-sheet
   `.xlsx` result plus a combined diagnostic/dashboard bundle;
9. reopen saved dashboards from previous economy/scenario runs.

The configured pinned ESTO table is used when no override is supplied. An
override changes the active ESTO vintage for that run; the existing synthetic
reference-row rules still apply.

The embedded dashboard is intentionally a single-run view. Its generated
economy selector and Reference/Target toggle are hidden, and the submitted
economy/scenario are shown in a fixed banner. The downloadable archive retains
the complete generated dashboard directory and its chart-bundle subfolder.
Each run is persisted under `LEAP_REVIEW_ARCHIVE_ROOT` (default:
`~/leap_review_tools/archives`) with metadata so it can be selected again after
the page is refreshed or the app is restarted, subject to the deployment's
filesystem persistence.

## Source-of-truth rule

The web app imports the existing `balance-review-from-export` orchestration from
this repository. It does not copy the diagnostics or builder into a second
implementation and it does not invoke the packaged EXE. A local run reports
the current Git commit when Git is available. A deployment must be rebuilt from
the updated source checkout whenever the workflow changes.

The full workflow uses the exact live `leap_initialisation`, `leap_mappings`,
and `leap_dashboard` checkouts through the same developer-mode context used by
the release tooling. Set `LEAP_MAPPINGS_ROOT` and `LEAP_DASHBOARD_ROOT` when the
siblings are mounted somewhere other than the default sibling directories.

## Parity notes

The web flow preserves the main guided-flow behavior: one export is enough,
multiple review years can be entered as `2022,2030,2040`, each requested year
produces its own workbook, the optional ESTO table is passed to both diagnostics
and dashboard generation, and dashboard year bounds are configurable.

The old CLI-only `info`, `list`, `selfcheck`, repository-update, and
existing-diagnostics/comparison-data escape-hatch commands are not separate web
buttons. Repository preflight runs automatically at submission, and the web
flow intentionally starts from a LEAP export rather than requiring users to
manage diagnostic folders or large precomputed comparison files.

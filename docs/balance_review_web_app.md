# Balance-review web app

The `web_app/` directory contains a thin Gradio wrapper around
`codebase/functions/balance_review_workbook_builder.py`.

## Scope

The app replaces the balance-review part of the portable Windows release:

1. upload one LEAP balance export workbook;
2. optionally upload an ESTO base-table CSV override;
3. run the existing diagnostics workflow;
4. run the existing Python workbook builder;
5. download the five-sheet `.xlsx` result and derived diagnostic bundle.

The configured pinned ESTO table is used when no override is supplied. An
override changes the active ESTO vintage for that run; the existing synthetic
reference-row rules still apply.

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

# Balance-review web app

The `web_app/` directory contains a thin Gradio wrapper around
`codebase/functions/balance_review_workbook_builder.py`.

## Scope

The app replaces the workbook-building part of the portable Windows release:

1. upload one LEAP balance export workbook;
2. upload `leap_balance_source_differences.csv` and
   `leap_balance_source_review.csv`;
3. optionally upload mapping/projection diagnostic CSVs;
4. run the existing Python builder;
5. download the five-sheet `.xlsx` result.

The upstream diagnostic-generation pipeline is intentionally outside this
minimal app. That pipeline needs the larger ESTO/9th-edition data and mapping
repositories and should be added only as a separately tested workflow.

## Source-of-truth rule

The web app imports the builder directly from this repository. It does not copy
the builder into a second implementation or invoke the packaged EXE. A local
run reports the current Git commit when Git is available; a packaged release
manifest is used as a fallback. A Hugging Face deployment must be rebuilt from
the updated source checkout whenever the builder changes.

The current builder workflow does not import `leap_dashboard` or
`leap_mappings`; those repositories are used by upstream diagnostic-generation
and dashboard workflows, not by the workbook construction function itself.

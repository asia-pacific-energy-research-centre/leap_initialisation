# Raw LEAP balance-export centralisation audit

## Policy

Raw Energy Balance workbooks are owned by this repository at
`data/leap balances exports/<economy>/`. `leap_mappings` resolves that directory
as the sibling path `../leap_initialisation/data/leap balances exports/` and
reports missing economy/scenario combinations before parsing. A non-standard
checkout may set `LEAP_BALANCE_EXPORTS_ROOT`; no repository-local copy is
selected implicitly.

Generated mapping artifacts remain in `leap_mappings/results/`. Generated LEAP
import/export products remain in `leap_initialisation/outputs/leap_exports/`.
The dashboard consumes `leap_mappings/results/common_esto/` and may read the
derived capacity-unmet convergence CSV under initialisation outputs; that file
is diagnostic output, not a raw balance input.

## References audited

| Previous reference | Replacement/status |
| --- | --- |
| `leap_mappings/codebase/run_mapping_pipeline.py` local-first `data/leap balances exports/20_USA` | Uses canonical sibling root; local-first fallback removed. |
| `leap_mappings/codebase/mapping_tools/parse_leap_balance_export.py` local path then sibling fallback | Uses canonical sibling root; missing economy remains a reported, non-fatal absence during the pipeline stage. |
| `leap_mappings/codebase/leap_mapping_refresh_workflow.py` and balance utilities | Resolve through the shared resolver, whose default is now canonical. |
| `leap_mappings/results/mapping_relationships/raw_leap_results.csv` | Retained as a generated mapping artifact. It is not a raw workbook location. |
| `leap_mappings/results/mapping_relationships/leap_results_converted_to_esto.csv` | Retained as a generated mapping artifact. |
| `leap_dashboard` Common ESTO inputs | Retained as the production input boundary. |
| `leap_dashboard` capacity-unmet convergence input under `leap_initialisation/outputs/` | Intentionally retained as an optional derived diagnostic dependency. |
| `leap_initialisation/outputs/leap_exports/` | Retained for generated LEAP products; not mixed with raw workbook ownership. |

The legacy `leap_mappings/data/leap balances exports/` folder was not deleted or
moved. It is therefore available for migration comparison, but the new resolver
does not read it implicitly.

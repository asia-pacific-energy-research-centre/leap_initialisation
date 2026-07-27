# Results-update dry-run preview

## Purpose

The active `results_update` method uses observed LEAP-versus-baseline import
gaps as an unmet-energy proxy. It then proposes one or more of:

- primary-production increases;
- transformation output/capacity increases;
- additional exports for negative import gaps;
- clipped amounts where configured caps restrict an increase; or
- unresolved amounts handled or blocked by the configured policy.

`run_results_update_allocation_preview()` in
`codebase/functions/results_update_preview.py` now runs those same allocation
rules without:

- updating the iterative state JSON;
- updating the caller's runtime allocation ledger;
- writing convergence history;
- writing a convergence manifest; or
- writing unresolved-residual artifacts.

It may write one review CSV only when the caller explicitly supplies
`output_path`.

## Preview table

`build_results_update_preview_table()` converts the allocator's pass summary
into a narrow table containing:

- economy, scenario, year, and ESTO product;
- the baseline and observed import values and their difference;
- proposal type;
- LEAP branch hint and variable;
- allocated output uplift, capacity increment, exports, clipping, or unresolved
  amount;
- `safe_to_apply`; and
- a blocked reason.

`safe_to_apply=True` currently means only that the existing allocator would
apply the row under its present caps and unresolved-residual policy. The table
marks this explicitly with `safety_scope=current_allocator_only`.

It does **not** yet prove that:

- the underlying LEAP/source difference is a baseline-seed defect;
- the LEAP-to-ESTO or ESTO-to-9th mapping is one-to-one;
- an aggregate 9th difference has a reviewed allocation rule;
- the hinted branch resolves to the final workbook row; or
- the proposed value agrees with the current post-boundary baseline-seed rule.

Those checks require integration with the AUS balance investigation and the
final generated import rows. Until then, the table is a faithful preview of
current allocator behavior, not approval to write or import the changes.

## Notebook-oriented use

The preview accepts the same in-memory reconciliation table, transformation
process records, scenario resolver, current balance-table results, and existing
state path as `_run_capacity_unmet_iterative_balanced_pass`.

```python
#%%
from codebase.functions.results_update_preview import (
    run_results_update_allocation_preview,
)

PREVIEW_RESULT = run_results_update_allocation_preview(
    reconciliation_table=RECONCILIATION_TABLE,
    process_records=TRANSFORMATION_PROCESS_RECORDS,
    economies=["01_AUS"],
    scenarios=["Reference"],
    resolve_scenario_key=RESOLVE_SCENARIO_KEY,
    results_dir=BALANCE_TABLE_PATHS,
    state_path=CAPACITY_UNMET_STATE_PATH,
    output_path=(
        "outputs/leap_exports/supply_reconciliation/supporting_files/"
        "baseline_seed_balance_diagnostics/results_update_allocation_preview.csv"
    ),
)

PREVIEW_TABLE = PREVIEW_RESULT["preview_table"]
#%%
```

This callable is intentionally below the full results-linked workflow for the
first checkpoint. The next integration step is to expose it through the
limited-year diagnostic workflow after the AUS investigation has committed its
direct-workbook support and classified findings.

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

Before diagnostic triage, `safe_to_apply=True` means only that the existing
allocator would apply the row under its present caps and unresolved-residual
policy. The table marks this with `safety_scope=current_allocator_only`.

It does **not** yet prove that:

- the underlying LEAP/source difference is a baseline-seed defect;
- the LEAP-to-ESTO or ESTO-to-9th mapping is one-to-one;
- an aggregate 9th difference has a reviewed allocation rule;
- the hinted branch resolves to the final workbook row; or
- the proposed value agrees with the current post-boundary baseline-seed rule.

Those checks require integration with the AUS balance investigation and the
final generated import rows. Until then, the table is a faithful preview of
current allocator behavior, not approval to write or import the changes.

## Balance-review safety gate

`apply_balance_review_safety()` applies the balance-variable contract from
`config/runtime_tables/balance_error_signal_rules.csv` at the flow used by each
proposal: imports for positive-gap capacity/production proposals and exports
for additional-export proposals. This avoids blocking an import proposal
because an unrelated final-demand diagnostic is wrong.

The contract is the primary gate:

- imports are initially the default allowed `imports_gap` error signal;
- exports and every other unlisted direct flow are protected by default;
- protected-flow differences raise an issue rather than becoming numeric
  updates;
- total primary supply and total final energy consumption are derived checks;
- aggregate/cardinality warnings remain blocked until an allocation rule is
  reviewed;
- allocator clipping and fatal residuals remain blocked;
- explicitly approved rows are labelled `approved_update_candidate`; and
- eligible imports-gap rows remain visible as `provisional_update_candidate`.

Provisional means suitable for exercising and reviewing the updater, not proof
that the change should be imported. A stale export is recorded as provenance
(`predates_known_seed_fix`) rather than used as a global veto.

Reviewed decisions are a secondary override for proven upstream defects. The
tracked `config/runtime_tables/results_update_issue_decisions.csv` records the
AUS 2022 thermal-coal cluster as a baseline-seed defect fixed by `778f649`,
even when an imports difference would otherwise be an eligible error signal. The
public preview runner loads this table automatically when a balance review is
provided. Pass an explicit empty DataFrame only when deliberately testing
without reviewed decisions.

Known placeholder/interim sectors are labelled in the diagnostic, but are not
blanket-excluded. A future exclusion must define a placeholder/replacement
group and prove that the combined boundary conserves energy. This prevents a
sector substitution from creating false alarms without hiding fuel-allocation
bugs inside the placeholder.

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
    require_fresh_leap_cycle=True,
)

PREVIEW_TABLE = PREVIEW_RESULT["preview_table"]
#%%
```

This callable is intentionally below the full results-linked workflow for the
first checkpoint. The next integration step is to expose it through the
limited-year diagnostic workflow after the AUS investigation has committed its
direct-workbook support and classified findings.

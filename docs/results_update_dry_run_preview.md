# Results-update dry-run preview

## Purpose

The active `results_update` method uses observed LEAP-versus-baseline import
gaps as an unmet-energy proxy. It then proposes one or more of:

- primary-production increases;
- transformation output/capacity increases;
- additional exports for negative import gaps;
- clipped amounts where configured caps restrict an increase; or
- unresolved amounts handled or blocked by the configured policy.

The import gap is the **error signal**, not a command that every other balance
flow must be restored to its original value. A reviewed response may instead
change domestic supply, transformation output/capacity, or electricity/heat
provision and let imports absorb only the residual. For other products or
cycles, leaving the complete difference in imports may be the intended result.

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
- the future-year comparator reused the baseline seed's canonical
  9th-to-ESTO allocation and provenance;
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
- current raw-cardinality warnings remain blocked until the comparator is
  connected to the canonical allocated ESTO projection;
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
group and pass a signed, fuel-specific replacement-boundary reconciliation.
This prevents a sector substitution from creating false alarms without hiding
fuel-allocation bugs inside the placeholder.

## Error signals versus permitted adjustment strategies

Two decisions must remain separate:

1. `config/runtime_tables/balance_error_signal_rules.csv` identifies the
   observed residual variable. Imports are currently the default
   `imports_gap` signal.
2. A results-update strategy decides which model levers may respond to that
   signal.

The existing balanced allocator already approximates one strategy for a
positive imports gap:

```text
increase eligible primary production
then increase eligible transformation output/capacity
then leave any unresolved residual to imports
```

Its product-specific module priorities, capacity caps, production caps, and
production-only products determine which levers are eligible. Negative gaps
are not symmetric: the current code can route them to exports only when exports
are not pinned, and it does not yet safely decrease production or
transformation capacity/output.

Add a separate, most-specific-match configuration table when this behavior is
connected to the diagnostic, proposed as
`config/runtime_tables/results_update_adjustment_strategy_rules.csv`. It should
select, by economy/scenario/ESTO product:

- positive-gap strategy:
  `residual_only`, `configured_levers_then_residual`, or `review_required`;
- negative-gap strategy:
  `residual_only`, `configured_decrease_then_residual`,
  `exports_then_residual`, or `review_required`;
- the residual error signal (normally imports); and
- a reviewed reason and enabled flag.

Do not duplicate module lists or numeric caps in that table. Those remain the
lever catalogue used by the allocator; the strategy table decides whether the
catalogue may be used for this product and direction.

Each cycle should also write an execution ledger, separate from configuration,
with the signal before the update, chosen strategy, proposed and applied lever,
signed change, residual left to imports, next-cycle signal, decision status,
and reason. This is especially important for electricity/heat adjustments:
changing their provision changes transformation fuel use and can create a
second-order import gap that is only visible after recalculation.

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

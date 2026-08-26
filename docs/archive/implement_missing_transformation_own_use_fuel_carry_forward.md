# Carry forward missing transformation own-use fuel projections

Type: focused implementation prompt. Status: active. Created 2026-08-26.

## Objective

Extend the existing missing-Ninth projection system so a transformation-owned
own-use fuel is carried forward at its signed ESTO base-year energy value when
that fuel has no nonzero Ninth projection anywhere in the projection horizon.

This is a projection-gap rule, not a mapping correction. Do not edit mapping
workbooks unless investigation proves an actual missing or incorrect semantic
relationship.

## User-selected rule

For an economy-specific `(own-use flow, fuel)` pair:

1. If its ESTO base-year value is nonzero; and
2. its complete Ninth projection series is absent or all zero; and
3. the corresponding transformation process owns that own-use flow;

then carry the signed ESTO base-year energy value forward unchanged through
the projection horizon.

If any projection year contains a nonzero Ninth value, retain the complete
Ninth series unchanged. Do not fill individual zero years around a real Ninth
projection, because those zeros may represent an intentional change or
phase-out.

## Read first

Follow `AGENTS.md`, including the referenced global balance-table and LEAP
export instructions. Then read:

- `docs/special_rules_and_design_decisions.md`, especially INIT-017 and the
  existing all-zero own-use/loss carry-forward rules;
- work-queue item `[20]` in `docs/work_queue.md`;
- `codebase/functions/ninth_projection_mapping.py`;
- `codebase/functions/transformation_analysis_utils.py`;
- `codebase/functions/transformation_sector_analysis.py`;
- `codebase/functions/transformation_record_builder.py`;
- `codebase/functions/other_loss_own_use_proxy_utils.py`, especially the
  `carry_base_target_forward_when_all_zero` implementation;
- `codebase/other_loss_own_use_proxy_workflow.py`; and
- the relevant tests in `tests/test_ninth_projection_profiles.py` and
  `tests/test_other_loss_own_use_proxy_workflow.py`.

Before editing, run `git status --short`. Preserve all unrelated changes,
especially the existing modification to
`config/baseline_seed_validation_exception_sets.xlsx`.

## Existing behavior to preserve

Two related mechanisms already exist:

1. `FILL_IN_MISSING_9TH_SECTORS` reconstructs reviewed, base-year-active
   children beneath the `09.06 Gas processing plants` and `09.08 Coal
   transformation` parents. It uses a flat base-year carry when no parent
   projection exists and a parent-residual allocation when a projected parent
   exists.
2. The other-loss/own-use proxy can carry a nonzero ESTO base-year fuel target
   when its entire Ninth projection is zero. This is already used for selected
   flows such as `10.01.17 Non-specified own uses` and `10.02 Transmission and
   distribution losses`.

Do not replace or duplicate either mechanism. Reuse their established
all-zero detection, signed-value preservation, provenance, ownership, and
diagnostic concepts.

## Confirmed PRC example

For `10.01.02 Gas works plants`, the PRC Target source contains these nonzero
2022 values followed by zeros through 2060:

| Fuel | 2022 ESTO value (PJ) | 2023-2060 Ninth |
| --- | ---: | ---: |
| Coal products | -1.163344 | all zero |
| Gas works gas | -0.264522 | all zero |
| Electricity | -69.472800 | all zero |
| Heat | -49.066621 | all zero |

The resulting seed currently writes zero Target Auxiliary Fuel Use for
Electricity and Heat from 2023 onward. This proves a projection gap; the fuel
mapping itself exists and works.

Use the configured source tables and mappings for executable regression
fixtures rather than reading values from dashboard HTML.

## Required investigation before editing

Produce a compact candidate inventory from the configured ESTO and Ninth
source tables for every economy and scenario. Include only pairs with a
nonzero ESTO base-year value and an absent/all-zero Ninth projection.

The inventory must include at least:

- economy and scenario;
- ESTO own-use flow and product;
- LEAP process/fuel label after canonical mapping;
- signed base-year value;
- whether a Ninth row exists but is all zero, or is absent;
- the workflow/process that owns the pair;
- whether that owner currently writes it as transformation Auxiliary Fuel Use
  or through the other-loss/own-use proxy;
- whether process output is nonzero in every projection year; and
- the proposed action: carry, leave to another owner, or review/block.

Keep this as a narrow diagnostic artifact, not a large debug dump. The
inventory must be generated from source data and must not change model inputs.

## Required implementation

Implement the rule at the energy-series boundary, before Auxiliary Fuel Use
ratios are calculated:

1. Identify the transformation-owned own-use flows from the maintained process
   configuration/ownership, rather than introducing an unrelated hard-coded
   list in a second location.
2. For each eligible `(economy, scenario, own-use flow, fuel)` pair, carry its
   signed ESTO base-year value into every projection year only when the entire
   Ninth projection is absent or all zero.
3. Preserve the filled energy series in the normal transformation loss/own-use
   path so existing process builders convert it to LEAP Auxiliary Fuel Use.
4. Record provenance such as `esto_base_year_carry_forward` and a specific
   diagnostic reason such as
   `transformation_own_use_ninth_projection_all_zero`.
5. Keep this behavior under the existing missing-Ninth feature gate if that can
   be done cleanly. Do not create a second overlapping policy switch without a
   demonstrated need.
6. Keep direct `09.06` and `09.08` parent/child projection reconstruction on
   the existing path. The new logic is for missing fuel energy in
   transformation-owned own-use flows, not a replacement for parent residual
   allocation.

### Ownership requirements

Do not apply the rule indiscriminately to every `10.01` flow.

- Gas works own use is transformation-owned and should feed its Auxiliary Fuel
  Use rows.
- Coke ovens and Blast furnaces should be eligible when their configured
  transformation modules own the own-use rows.
- Oil Refining should be eligible, subject to its net-output boundary and
  existing refinery tests.
- LNG own use is intentionally owned by
  `Demand\Other loss and own use\Liquefaction and regasification plants`; do
  not also create transformation auxiliary rows for it.
- Non-specified own use and any other proxy-owned flows must remain with the
  other-loss/own-use workflow.
- Check Coal mines carefully because configuration exists in more than one
  area. Exactly one workflow may write each logical seed key.

If ownership is ambiguous, stop that pair with a review diagnostic rather than
allowing duplicate output.

## Ratio handling

Carry forward **energy**, not a historical ratio.

For each year, let the existing process-specific builder calculate the
Auxiliary Fuel Use ratio from:

```text
carried own-use energy / that year's applicable process denominator
```

For a module configured to apply auxiliary use per output, use that year's
output. If another module's LEAP template applies auxiliary use to throughput,
retain its proven process-specific denominator. Do not assume every
transformation module has the same LEAP unit semantics.

If carried own-use energy is nonzero while the required denominator is zero,
do not divide by zero, silently discard the energy, or invent activity. Emit a
blocking/review diagnostic naming the economy, process, fuel, year, carried
energy, and missing denominator.

## Required tests

Add focused tests proving all of the following:

1. PRC Gas works Electricity and Heat retain `-69.472800 PJ` and
   `-49.066621 PJ` respectively in every projection year when their Ninth
   series are all zero.
2. The other two PRC Gas works candidates, Coal products and Gas works gas,
   follow the same rule.
3. The carried signed energy becomes the correct positive auxiliary-energy
   magnitude downstream and reconstructs exactly from the written ratio and
   denominator.
4. A fuel with any nonzero Ninth projection remains completely unchanged,
   including any zero years within that supplied series.
5. A zero or absent ESTO base-year value is not invented.
6. A proxy-owned own-use flow is not also written as transformation auxiliary
   use.
7. A nonzero carried value with zero process output/denominator produces a
   review/blocking diagnostic instead of an invalid ratio.
8. Existing `09.06` and `09.08` parent/child projection tests remain unchanged
   and pass.
9. Existing non-specified-own-use and transmission-loss carry-forward tests
   remain unchanged and pass.
10. No duplicate `(Branch Path, Variable, Scenario, Region)` seed keys are
    introduced.

Include at least one coal-transformation own-use fixture and one Oil Refining
fixture in addition to Gas works, even if the current PRC source does not have
an eligible Coke ovens or Blast furnaces example.

## Verification

Run the narrow tests first, including:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests/test_ninth_projection_profiles.py -q
C:\Users\Work\miniconda3\python.exe -m pytest tests/test_transformation_efficiency_feedstock_only.py -q
C:\Users\Work\miniconda3\python.exe -m pytest tests/test_other_loss_own_use_proxy_workflow.py -q
```

Then run any directly affected transformation export/writer tests. Do not run
the full all-economy supply-reconciliation workflow solely for this task.

If practical, generate one controlled PRC baseline seed and verify:

- Gas works Target Electricity and Heat Auxiliary Fuel Use are nonzero from
  2023 onward;
- their reconstructed energy equals the flat carried values;
- existing nonzero Ninth gas-works own-use fuels remain unchanged;
- no proxy-owned duplicate rows appear; and
- no branches outside the declared transformation-own-use scope change.

A workbook comparison is sufficient to establish code/seed correctness. A
fresh LEAP import/export is still required before claiming the final model
result is fully verified.

## Documentation

Update the existing INIT-017 decision in
`docs/special_rules_and_design_decisions.md` rather than creating a duplicate
rule. Update work-queue item `[20]` or add a narrowly linked follow-up so the
documentation accurately distinguishes:

- missing direct transformation children under `09.06`/`09.08`; and
- missing fuels inside transformation-owned own-use flows.

If a new validation check or diagnostic is registered, update
`docs/check_registry.md` as required by `tests/test_check_registry.py`.

## Non-goals and safeguards

- Do not edit canonical mappings merely because Ninth values are zero.
- Do not carry forward ratios.
- Do not overwrite any nonzero Ninth projection.
- Do not fill isolated zero years inside an otherwise nonzero Ninth series.
- Do not add own use to process capacity.
- Do not change process efficiency definitions.
- Do not duplicate proxy-owned own-use rows in transformation modules.
- Do not generalize this into demand, supply, transfers, or every `10.01` flow
  without explicit ownership and tests.
- Do not include unrelated pre-existing changes in the commit.

## Completion criteria

The task is complete when:

1. The all-economy candidate inventory is retained and clearly classifies
   ownership and proposed action.
2. Eligible transformation-owned own-use fuel gaps carry their signed ESTO
   base-year energy forward when the full Ninth projection is absent/all zero.
3. Ratios are recalculated from yearly process denominators and reconstruct the
   carried energy exactly.
4. Nonzero Ninth projections, parent/child reconstruction, and proxy-owned
   flows remain unchanged.
5. Zero-denominator and ownership conflicts fail visibly.
6. Focused tests pass and the agent reports exactly what was run.
7. Code, tests, diagnostics documentation, and the existing decision record
   agree on the same rule.
8. The agent commits only its own coherent changes and reports the commit hash.


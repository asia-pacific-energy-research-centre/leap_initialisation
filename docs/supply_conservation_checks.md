# Supply preservation and reconciliation closure checks

Both checks are diagnostic-only while real-run tolerances are established.

## Baseline-seed supply source preservation

This check applies only to `baseline_seed`. It compares raw, pre-fuel-mapping
source totals with the mapped tables used to build the reconciliation table.
The comparison unit is `economy + flow + year`, with separate rows for:

- production;
- imports; and
- exports.

The base year comes from non-subtotal ESTO rows. Projection years come from the
reference-scenario 9th Outlook rows used by the supply pipeline. Exports are
normalised to positive magnitudes on both sides. The resolved side sums
`production`, `projected_imports`, or `projected_exports` only across products
whose LEAP supply branches were actually written to the generated supply
workbook. Internal aggregate rows without a target LEAP branch are excluded.

This deliberately checks total energy before and after fuel mapping. It detects
dropped source products, duplicated mappings, and sign loss without treating a
valid redistribution between mapped fuel labels as a conservation failure.

Output:
`supporting_files/checks/supply_reconciliation_baseline_supply_source_preservation.csv`

## Results-update reconciliation closure

This check applies only to `results_update`. It does not compare updated supply
with ESTO/9th because divergence is expected after LEAP modelling and iterative
adjustments.

For every `economy + scenario + esto_product + year`, the check independently
recomputes:

```text
resolved supply
  = adjusted imports
  - adjusted exports
  + constrained transformation output
  + constrained production
  + stock changes

resolved requirement
  = transformation input
  + transformation losses
  + demand

closure residual = resolved supply - resolved requirement
```

A row is closed when the absolute residual is within the configured tolerance.
Cap-bound or otherwise unresolved rows remain visible as mismatches. The check
uses the post-trade-split reconciliation table, although the split itself does
not change total adjusted imports or exports.

Output:
`supporting_files/checks/supply_reconciliation_results_update_closure.csv`

## Blocking policy

Neither diagnostic blocks workbook generation or LEAP import. A diagnostic
calculation failure is logged as a warning. Blocking thresholds should be added
only after representative baseline-seed and results-update runs establish which
small residuals are numerical noise and which indicate modelling errors.

## Initial 20_USA results

The baseline-seed source-preservation run produced 117 rows (39 years for each
of production, imports, and exports), and every row mismatched. Resolved values
are above the raw source totals by:

- production: 23,108.875786 to 33,340.412996 PJ;
- imports: 12,115.485621 to 15,059.161880 PJ; and
- exports: 3,154.249009 to 7,507.250257 PJ.

Restricting the resolved side to products actually written to the LEAP supply
workbook removes non-exported aggregate rows but does not remove the mismatch.
The remaining excess is consistent with overlapping source selection among
exported products; for example, `06.05 Other hydrocarbons` receives the same
source total used by the crude-oil/NGL parent family. These are actionable
mapping/selection findings, not tolerance noise.

The results-update closure run produced 9,094 rows, zero mismatches, and a
maximum absolute residual of `1.0914e-11` PJ. Because the current live
results-update loader is blocked by subtotal-mismatch validation, this run used
the newest cached 20_USA demand input containing LEAP/base/projection sources,
combined with the current transformation and supply tables. A fresh live run is
still required after the subtotal validation issue is resolved.

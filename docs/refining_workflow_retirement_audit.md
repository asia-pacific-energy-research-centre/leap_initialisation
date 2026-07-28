# Refining workflow retirement audit

Date: 2026-07-28

Implementation status: completed 2026-07-28.

## Decision

Retire `codebase/refining_workflow.py` from the active workflow surface and
preserve it under `codebase/old_workflows/` for historical reference. Do not
merge its workbook-mutating implementation into the shared transformation
pipeline, and do not replace it with another refining-specific thin wrapper.

Oil refining is already an ordinary configured sector in the active
transformation pipeline. The notebook-friendly wrapper already exists in
`codebase/transformation_entry.py`. Keeping a second wrapper would preserve two
ways to calculate and import the same LEAP module.

Retirement should happen only after the shared LEAP process-boundary
normalization is implemented and verified for oil refining.

## Evidence

### No production caller

- `run_with_config()` is called only by the module's own
  `if __name__ == "__main__"` block
  (`codebase/refining_workflow.py:434-554`).
- The only Python import outside that file is
  `tests/test_refining_capacity_policy.py`, which tests one private helper.
- The strings returned as `"refining_workflow"` by
  `baseline_seed_comparison_workflow.py` and `supply_leap_io.py` are diagnostic
  ownership labels. They do not import or run the module.
- The baseline-seed producer map in
  `codebase/functions/supply_results_saver.py:4233-4241` has no refining
  producer. Oil refining arrives in the `transformation_workflow` workbook.
- Repository history shows no change to the standalone workflow after
  `e5335fb` on 2026-07-03. The active reconciliation work has continued through
  the shared transformation path.

### The configured source is unavailable

The workflow hard-codes `../data/refining model export.xlsx`, `20_USA`, and
`United States` independently (`codebase/refining_workflow.py:58-69`). The
workbook is absent from both the active checkout and this worktree. It is
gitignored, so no reproducible input is available in version control.

The optional `config/refining_fuel_mapping.csv` and generated
`intermediate_data/refining_fuel_remap_report.csv` are also absent. The fuel
remap implementation itself is already separated in
`codebase/functions/transformation_fuel_remap.py`; archiving the entry script
does not remove that reusable helper.

### Oil refining is already in the shared transformation pipeline

- `MAJOR_SECTOR_CONFIG["oil_refineries"]` selects ESTO flow
  `09.07 Oil refineries`, auxiliary-own-use flow
  `10.01.11 Oil refineries`, and multi-output handling
  (`transformation_analysis_utils.py:371-377`).
- `transformation_workflow.ANALYSIS_REGISTRY` routes `oil_refineries` through
  the same `run_flow_sector_analysis` callback as other flow-based
  transformation modules (`transformation_workflow.py:80-93`).
- `summarize_transformation_flows()` builds standard process records containing
  outputs, feedstocks, loss/own-use values, auxiliary ratios, efficiency, and
  trade targets (`transformation_sector_analysis.py:1300-1665`).
- `build_process_record()` canonicalizes Process Efficiency from output and
  feedstock only (`transformation_record_builder.py:912-965`).
- `save_transformation_export()` emits the shared LEAP workbook through
  `build_transformation_log_rows()` and the common share, capacity, auxiliary,
  zero-fill, template-ID, and validation machinery
  (`transformation_record_builder.py:1644-2025,2745+`).
- Baseline-seed runs call
  `save_transformation_exports_with_split_targets()` for the per-economy
  process records (`supply_results_saver.py:3859-3876`).
- Direct notebook export/import is already provided by
  `transformation_entry.run_transformation_workflow()` and
  `run_leap_import()` (`transformation_entry.py:35-87`).

## Unique behavior in the standalone workflow

| Standalone behavior | Disposition |
|---|---|
| Read a hand-maintained prebuilt workbook | Legacy-only. The configured workbook is unavailable and is not a reproducible baseline-seed source. Do not merge this route. |
| Remap Output/Feedstock/Auxiliary fuel branch leaves and blank IDs | Preserve the reusable `transformation_fuel_remap.py` helper. The active process-record path maps source codes before export and resolves IDs from the economy template. |
| Remove aggregate/subtotal fuel branch rows | The active data pipeline filters total/subtotal energy rows before process records are built. Add/retain a shared emitted-leaf assertion rather than copy the workbook mutation. |
| Copy missing Target rows from Reference, with first-available fallback | Do not migrate. Active exporters generate every requested scenario explicitly. The order-dependent fallback is unsafe and is not a general modelling rule. |
| Copy Historical Production to Exogenous Capacity and set `Million Gigajoules/Year` metadata | Retire. This gross-output heuristic becomes incorrect when same-module auxiliary fuels must be netted from deliverable capacity. Replace the documented rule with the shared process-boundary rule. |
| Create and fill branches through LEAP COM, including Current Accounts on the first pass | Already covered by `transformation_workflow.import_transformation_workbook_to_leap()` and the shared LEAP import adapter. |
| Skip dispatch/optimization variables during direct fill | Legacy workbook behavior. The shared exporter only emits owned variables, so it does not need a skip list. |
| Prompt before deleting stale child branches | Do not merge into automated baseline-seed generation. If still useful for manual maintenance, it remains recoverable in `old_workflows` and git history. |

## Effect of shared process-boundary normalization

The proposed normalization belongs in the common process-record/export path,
not in the standalone workbook mutator:

1. Preserve gross output for Process Efficiency:
   `gross output / feedstock`.
2. Identify auxiliary fuels that are also module outputs.
3. Derive deliverable output by fuel:
   `gross output - same-module auxiliary`.
4. Use deliverable output for Exogenous Capacity and Output Share.
5. Use total deliverable output as the denominator for Auxiliary Fuel Use.
6. Cap same-module auxiliary at the matching fuel's gross output, retain any
   excess as external auxiliary input, and assert that deliverable output plus
   same-module auxiliary reconstructs gross output.

Oil refining will receive the rule because it creates ordinary process records
and calls the common exporter. Transfers, interim electricity/heat, hydrogen,
and other transformation records will receive the same normalization when they
use the common exporter; records without output/auxiliary overlap must remain
numerically unchanged.

`refining_workflow.py` bypasses process records and
`save_transformation_export()`. It would not receive this correction. Its
Historical Production to Exogenous Capacity copy would continue exporting
gross output as capacity, preserving the defect that prompted this review.

## Migration sequence

1. Implement and test the shared process-boundary normalization first.
2. Generate one AUS 2022 Current Accounts transformation workbook and verify:
   gross-output efficiency, net deliverable capacity, net output shares, and
   auxiliary/net-output ratios for Oil Refining.
3. Verify a module with no output/auxiliary overlap is unchanged and run the
   transformation back-calculation and baseline-seed validators.
4. Update `SEED-C025` to describe the shared boundary rule. Remove the legacy
   refining capacity flag and migrate its test coverage to the shared
   normalization tests.
5. Remove `_ensure_export_contains_scenarios` from the active check registry;
   generated scenario coverage and the final seed scenario validator are the
   active checks.
6. Move `codebase/refining_workflow.py` to
   `codebase/old_workflows/refining_workflow.py`. Do not leave an active thin
   wrapper; direct users should use `codebase/transformation_entry.py`.
7. Correct `docs/workflow_inventory.md`,
   `docs/supply_reconciliation_workflow_guide.md`,
   `docs/system_overview_for_rewrite.md`,
   `docs/special_rules_and_design_decisions.md`, `data/README.md`, and stale
   references that imply the standalone script feeds baseline seeds.
8. Run the focused and registry tests, then run an AST/import search proving no
   production dependency remains.

## Verification checklist

- Oil Refining contains `09.07` outputs/feedstocks and `10.01.11` auxiliary
  own use.
- Process Efficiency equals gross output divided by feedstock.
- Exogenous Capacity equals total deliverable output.
- Output Shares use deliverable output and sum to 100%.
- Auxiliary Fuel Use uses the deliverable-output denominator.
- Gross output equals deliverable output plus overlapping auxiliary use.
- An overlapping auxiliary greater than its matching output is split between
  same-module use and explicit external auxiliary energy.
- Non-overlap transformation modules are unchanged.
- Current Accounts, Reference, and Target scenario coverage remains complete.
- Template IDs, units, scale, and `Per...` metadata pass final seed validation.
- No production import/caller of the archived workflow remains.

## Rollback

The source file remains in `codebase/old_workflows/` and in git history. If a
human-only prebuilt-workbook use case is later demonstrated, restore it as an
explicitly named legacy conversion tool with a supplied input workbook and
tests. Do not restore it as a second source of baseline-seed Oil Refining data.

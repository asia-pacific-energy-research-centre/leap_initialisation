# 12_NZ baseline-seed hardening and readiness — 2026-07-17

## Decision

**Conditional go for one `12_NZ` baseline-seed run, after explicit user
authorization.** No run was started in this work. The comparison baseline is:

`outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_21ECON_0E555F_TGT_REF_CA/leap_import_baseline_seed_12_NZ_20260716.xlsx`

The finished seed must be compared with that file only after
`prepare_seed_rows_for_write` / final emit. Do not compare raw producer output.

## Routing hardening completed

- Commit `23aac52` makes reset scope source-path keyed and threads the resolved
  economy template through the reset and capacity target paths. Multi-economy
  reset tables are partitioned by economy before scope is derived.
- Commit `53bb11c` makes demand-zeroing enumerate branches from each economy's
  resolved template, rather than the USA export.
- Focused regression coverage uses deliberately different USA/NZ-like branch
  sets, proves cache entries do not cross template paths, and proves a
  multi-economy reset/zeroing pass uses each template. The focused suite passed
  **72 tests** (`test_reset_scope_template_routing`, template resolver, and
  check registry).

## Template and prior-seed audit

| Category | Finding | Validation outcome | Recommended action |
|---|---|---|---|
| NZ template | `data/leap_export_templates/leap_export_template 12_NZ.xlsx` exists; 8,319 rows and 646 branch paths. | Readable. | Use this resolved template only. |
| USA comparison | USA has 714 branch paths; 634 paths are shared, 12 NZ-only, and 80 USA-only. | Structural difference is expected. | Never substitute USA paths or IDs. |
| Prior NZ seed | The comparison baseline above exists (950,626 bytes, written 2026-07-16 16:29 JST). | Readable. | Keep unchanged as the post-boundary comparison reference. |
| USA-only demand/own-use branches in old NZ seed | 156 seed rows across 32 paths are absent from the NZ template, including `Demand\\Other loss and own use\\Oil refineries...`. Every expression encodes zero values. | Warning/review finding; no nonzero unresolved value. | Preserve diagnostics; do not add NZ branches or introduce fallback logic. |
| Current reconciliation artifact | `supply_recon_run_baseline_seed_12_NZ_tgt_ref_ca.xlsx` exists in the same run directory. | Historical artifact only; no new producer data was fabricated. | Regenerate only through the authorized run. |

The explicit structural scan treats `Data(...)` and `Interp(...)` expressions
as value series, not as nonzero merely because their year tokens are numeric.
It found **0 nonzero** rows targeting a branch absent from the NZ template.

## Remaining `full model export.xlsx` routes

| Route | Classification after audit | Status |
|---|---|---|
| Reset scope (`supply_preflight` / reconciliation / results saver / LEAP I/O) | Must resolve per economy. | Routed in `23aac52`. |
| Demand zeroing (`supply_leap_io`) | Must resolve per economy. | Routed in `53bb11c`. |
| Aggregated-demand writer | Must resolve per economy. | Existing caller already passes `_leap_export_template_for_economy`; verified no pinned-ID bypass remains. |
| Supply branch classification | Must resolve per economy. | Already routed and source-keyed in `3756ccb`. |
| Transformation, transfers, electricity/heat interim, and other-loss defaults | Standalone-only compatibility defaults for the current baseline-seed path: combine fills IDs from the resolved template and producers intentionally leave ID fields empty. | Do not broaden this hardening slice; route their standalone entry points before the first real non-`COMP_GEN` export makes them live. |
| `patch_baseline_seeds.FULL_MODEL_EXPORT_PATH` | Standalone/aggregate fallback only. | Per-economy seed writing and validation already call `_template_for_economy`. |
| `baseline_seed_comparison_workflow.template_path` | Standalone comparison default. | Pass the resolved NZ template explicitly for the future comparison if template-backed validation is enabled. |
| Analysis-input canonical template list | Deliberate shared discovery/reference list, not an economy ID source. | Leave unchanged. |
| `GLOBAL_REGION`, `fuel_catalog_preflight` | Explicitly outside this task. | No change. |

## Authorized-run checklist

1. Re-check `git status --short` and confirm the resolved NZ template still
   exists.
2. Restrict the current baseline-seed preset to `ECONOMIES=["12_NZ"]`; do not
   alter modelling settings to obtain a clean result.
3. Start the run in the background and poll no more than once every 10 minutes.
4. Validate the final emitted seed against the NZ template. A nonzero
   unresolved-ID/path row is a stop condition.
5. Compare the final emitted seed to the recorded baseline on branch path,
   variable, scenario, region, expression, IDs, and metadata. Classify each
   difference before any code change.

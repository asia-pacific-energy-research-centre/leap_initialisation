# Workflow Inventory

Last reviewed: 2026-07-07

This is a cleanup-oriented inventory of the active workflow entry scripts in
`codebase/`. It is meant to answer two questions:

1. What does each workflow do?
2. Which scripts are still part of the active runtime surface?

Old/probe/scaffold workflows live in `codebase/old_workflows/` and are listed
separately below.

## Active Entry Points

| Script | Purpose |
|---|---|
| `supply_reconciliation_workflow.py` | Main linked supply/reconciliation loop. It compares LEAP balance results with the expected supply/transformation baseline and iteratively adjusts supply, transformation, transfers, and proxy branches. |
| `supply_workflow.py` | Standalone supply export/import wrapper. It delegates to the supply data pipeline and is the simplest way to build supply workbooks without the full reconciliation loop. |
| `transformation_workflow.py` | Main transformation export workflow for non-hydrogen transformation sectors. Builds LEAP-ready workbooks and can optionally import them into LEAP. |
| `hydrogen_transformation_workflow.py` | Hydrogen-specific transformation workflow. Uses the shared transformation helpers but keeps hydrogen configuration and filenames separate from the main transformation workflow. |
| `transfers_workflow.py` | Transfer-sector workflow. Converts ESTO transfer flows into LEAP transformation-style process records and exports them for import into LEAP. |
| `aggregated_demand_workflow.py` | Builds the `Demand\All demand aggregated` placeholder branch from ESTO and 9th inputs. Used while detailed demand sectors are still being developed or when a combined demand proxy is needed. |
| `electricity_heat_interim_workflow.py` | Builds interim electricity, CHP, and heat transformation modules from ESTO power-sector data and 9th projections. |
| `other_loss_own_use_proxy_workflow.py` | Builds proxy demand branches for losses and own-use flows that do not fit cleanly in transformation modules. |
| `refining_workflow.py` | Builds and imports LEAP refining branches from export data, including refitting/remapping of fuels where needed. |
| `minor_demand_workflow.py` | Draft scaffold for Agriculture, Fishing, and Non-specified others. It is used by `full_model_workflow_notebook.py` and is not part of the supply reconciliation loop. |
| `baseline_seed_comparison_workflow.py` | Compares generated baseline seed workbooks with reviewed references and separates structural, metadata, expression, duplicate-key, and share-total differences. |
| `outlook_mapping_maintenance_workflow.py` | Maintenance workflow for the Outlook mapping workbook. It recomputes audit columns and produces mapping QA outputs. |
| `transformation_entry.py` | Convenience entrypoint used by the full-model notebook to run transformation-related workflow pieces together. |

## Workflow Buckets

### 1. Reconciliation Loop

These workflows are part of the supply reconciliation cycle itself.

- `supply_reconciliation_workflow.py`

### 2. Initialisation-Only, But Required

These workflows are not iterated inside the reconciliation loop, but their
outputs are part of the supply-reconciliation initialization chain and final
baseline seed.

- `supply_workflow.py`
- `transformation_workflow.py`
- `hydrogen_transformation_workflow.py`
- `transfers_workflow.py`
- `aggregated_demand_workflow.py`
- `electricity_heat_interim_workflow.py`
- `other_loss_own_use_proxy_workflow.py`
- `refining_workflow.py`

### 3. Standalone / Convenience / QA

These are useful supporting workflows, but they are not part of the main
supply-reconciliation loop.

- `baseline_seed_comparison_workflow.py`
- `outlook_mapping_maintenance_workflow.py`
- `transformation_entry.py`
- `minor_demand_workflow.py`

### 4. Legacy / Archive

These are retained for reference only.

## Archived Or Legacy Workflows

These are retained for reference, but they are no longer the preferred active
entry points.

- `codebase/old_workflows/aperc_reference_aggregation_workflow.py`
- `codebase/old_workflows/detailed_balance_from_esto_workflow.py`
- `codebase/old_workflows/energy_balance_template_extract_workflow.py`
- `codebase/old_workflows/leap_favorites_transplant_workflow.py`
- `codebase/old_workflows/leap_results_extraction_replica_workflow.py`
- `codebase/old_workflows/leap_results_template_year_axis_audit_workflow.py`
- `codebase/old_workflows/ninth_to_esto_mapping_coverage_workflow.py`
- `codebase/old_workflows/leap_transformation_losses_own_use_workflow.py`
- `codebase/old_workflows/synthetic_reference_mapping_suggestions_workflow.py`
- `codebase/old_workflows/leap_balance_mapping_scaffold_workflow.py`
- `codebase/old_workflows/leap_individual_mapping_scaffold_workflow.py`
- `codebase/old_workflows/leap_results_variable_probe_workflow.py`
- `codebase/old_workflows/transformation_leap_probe_workflow.py`
- `codebase/old_workflows/unmet_requirements_results_probe_workflow.py`

## Layout Note

Several of these workflows are imported directly by tests, notebooks, and
supporting modules. Moving them into a new subfolder would require a
compatibility plan, not just a file move, because the current module names are
part of the runtime contract.

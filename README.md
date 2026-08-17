# LEAP initialisation

This repository owns LEAP area initialisation, supply reconciliation, and the
generation and validation of LEAP import workbooks. It consumes reviewed
mapping semantics from the sibling `leap_mappings` repository; it does not own
mapping relationships or dashboard presentation.

## Start here

Begin with the connected-system route in
[`leap_mappings/docs/start_here.md`](../leap_mappings/docs/start_here.md).

| Need | Authoritative route |
|---|---|
| understand or run supply reconciliation | [`docs/handover/supply_reconciliation_guide.md`](docs/handover/supply_reconciliation_guide.md) |
| execute safely as an agent | [`docs/handover/supply_reconciliation_agent_guide.md`](docs/handover/supply_reconciliation_agent_guide.md) |
| interpret readiness and validation checks | [`docs/check_registry.md`](docs/check_registry.md) |
| understand placeholder/interim branches | [`docs/placeholder_branches_and_interim_models.md`](docs/placeholder_branches_and_interim_models.md) |
| choose current work | [`docs/handover_work_queue_20260728.md`](docs/handover_work_queue_20260728.md) |
| inspect detailed engineering history and traps | [`docs/work_queue.md`](docs/work_queue.md) |
| find a workflow | [`docs/workflow_inventory.md`](docs/workflow_inventory.md) |

The primary entry point is
`codebase/supply_reconciliation_workflow.py`. It is notebook-style: edit the
explicit constants/preset blocks in the repository, then run it with the pinned
Windows interpreter described in `AGENTS.md`.

## Mapping boundary

Researchers edit independent axis relationships in:

```text
../leap_mappings/config/outlook_mappings_single_axis.xlsx
```

The mappings pipeline must run its `generate` stage (the separate-axis refresh)
before Stages 1–3. This repository consumes the generated compatibility
workbook `../leap_mappings/config/outlook_mappings_master.xlsx`. Do not edit its
generated pair sheets or repair mappings in copied initialisation workbooks.

## Main workflow surface

- `supply_reconciliation_workflow.py` — linked baseline-seed/results-update
  orchestration and per-economy execution.
- `supply_workflow.py` — standalone supply preparation.
- `transformation_workflow.py` and `hydrogen_transformation_workflow.py` —
  transformation preparation.
- `transfers_workflow.py` — transfer processes.
- `aggregated_demand_workflow.py` — temporary aggregated demand placeholder.
- `electricity_heat_interim_workflow.py` — interim electricity/CHP/heat model.
- `other_loss_own_use_proxy_workflow.py` — losses and own-use proxy branches.
- `balance_update_workflow.py` and the baseline-seed diagnostic/validation
  workflows — review and iterative update support.

See `docs/workflow_inventory.md` for the full current classification.

## Required inputs

The maintained workflow expects reviewed local data, including:

- `data/00APEC_2024_low_with_subtotals.csv` — configured ESTO base table;
- `data/merged_file_energy_ALL_20251106.csv` — 9th Outlook projections;
- `data/leap_export_templates/*.xlsx` — per-economy branch/ID templates, resolved
  through the template resolver rather than filename construction; and
- `data/leap balances exports/<economy>/` — current manually exported LEAP
  Energy Balance workbooks.

See [`data/README.md`](data/README.md) for the exact current file contracts.

## Running and safety

Use Windows because the optional LEAP COM integration depends on `pywin32`, but
ordinary production transfer is workbook-first and does not require enabling
the retired API write path. From the repository root:

```powershell
C:\Users\Work\miniconda3\python.exe codebase\supply_reconciliation_workflow.py
```

Before a run, check the active preset, economy/scenario scope, explicit run
label, resolved templates, current LEAP exports, and mapping generation. Long
runs must follow the launch, lock, isolation and polling rules in `AGENTS.md`.
Generated outputs stay under `outputs/` and must not be treated as current only
because an old file exists.

## Review tools and historical material

The web/release application moved to the sibling
`C:\Users\Work\github\leap_review_tools` repository on 5 August 2026. The
`docs/leap_review_tools*.md` files and `codebase/portable_release/` retained here
describe the original packaging and handover boundary; use the sibling
repository for current web-app implementation and deployment.

`leap_utilities`, old setup commands, the retired LEAP API-first workflow,
`config/leap_mappings.xlsx`, and `config/master_config.xlsx` are historical or
compatibility context. They are not current authorities. Current legacy and
archive classifications are documented in `docs/workflow_inventory.md`,
`codebase/old_workflows/README.md`, and the dated documentation audits.

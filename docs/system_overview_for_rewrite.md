# LEAP Initialisation System Overview

This document explains the current `leap_initialisation` system before any major rewrite or modularisation work. Its purpose is to keep the rewrite aligned with the existing modelling process, preserve the parts that already work, and make handover easier.

The repo is not just a Python package. It is a set of notebook-safe workflow scripts, shared data-processing functions, mapping maintenance tools, LEAP import/export helpers, and human-run LEAP steps. A rewrite should preserve that operating model unless the modelling workflow itself changes.

## 1. What This Repo Is For

This repo prepares LEAP import workbooks and diagnostics used to initialise new LEAP economy areas.

The active scope is:

- Demand placeholders and selected minor demand branches.
- Transformation modules outside the main power/demand models.
- Hydrogen transformation.
- Transfers.
- Supply/resources, including production, imports, exports, and unmet-requirement handling.
- Other loss and own-use proxy branches.
- LEAP balance/result mapping and reconciliation diagnostics.

The repo is not the active home for:

- LEAP dashboard implementation. Use `C:\Users\Work\github\leap_dashboard`.
- Mapping-only workbook maintenance. Use `C:\Users\Work\github\leap_mappings`.
- Legacy cleanup in `leap_utilities`, unless explicitly comparing or migrating old behaviour.

## 2. Operating Model

The system is built around a manual LEAP loop:

1. Python reads ESTO, 9th Outlook, mappings, and LEAP export templates.
2. Python generates one or more LEAP import workbooks.
3. The modeller imports those workbooks into LEAP.
4. LEAP is recalculated manually.
5. The modeller exports LEAP balance/results workbooks.
6. Python reads those exports and builds diagnostics or the next-pass workbook.

The code has some LEAP COM/API helpers, but the preferred path is workbook-based because direct API automation has been unreliable.

The loop normally needs several passes. The first pass establishes a baseline and exposes major gaps; later passes test whether production, transformation capacity, export, and proxy adjustments moved the recalculated LEAP balance in the intended direction. The process is finished only when base-year balances are aligned with ESTO, projected supply/trade paths are plausible, remaining gaps are small and explainable, and no unexplained unmet requirements remain.

## 2.1 LEAP Modelling Controls To Preserve

The Python workflows exist to populate and reconcile specific LEAP modelling controls. These controls are methodology, not incidental implementation details.

| Control | Main location | Modelling role |
|---|---|---|
| `Maximum Production` | Resources / primary fuels | Controls annual indigenous production and prevents unlimited domestic supply. |
| `Base Year Reserves` | Resources / primary fuels | Usually set to `Unlimited` in Current Accounts so APERC areas avoid reserve-depletion accounting unless a researcher deliberately models reserves. |
| `Exogenous Capacity` | Transformation processes | Limits how much a transformation process can produce. Used as the practical capacity/activity control in reconciliation. |
| `Process Efficiency` | Transformation processes | Converts feedstock and auxiliary inputs into output fuel requirements/production. |
| `Output Shares` | Multi-output transformation modules | Splits output across co-products and can create unavoidable surplus. |
| `Surplus Rule` | Transformation modules | Controls what happens when output exceeds requirements. `SurplusExported` is often used so unavoidable co-products become visible exports. |
| `Shortfall Rule` | Transformation modules | Controls what happens when a module cannot meet requirements. `ImportToMeetShortfall` can hide domestic supply issues if used too early. |
| Imports | Resources / fuels | Often treated as a residual/error signal during initial reconciliation rather than the first value to hard-code. |
| Exports | Resources / fuels | Can preserve intended trade assumptions or absorb transformation surplus. |

Base-year and projection-year expectations differ:

- Base year should reproduce the ESTO balance as closely as possible. Large differences usually indicate a mapping, branch, input, or LEAP setting problem.
- Early projection years should remain close to the 9th Outlook path unless there is a deliberate modelling reason to diverge.
- Later projection years may diverge more if the story is plausible and documented.

Module ordering also matters. LEAP passes requirements upstream through the tree, so the module that produces the demand-facing fuel should generally be above the module that produces that module's feedstock. For example, LNG regasification should be demand-facing relative to natural gas liquefaction: regasification sees natural gas requirements, creates LNG requirements, and liquefaction can then see the upstream LNG requirement.

## 3. Main Data Sources

### ESTO Historical Data

The ESTO table is the main historical/base-year energy balance source. In the current shared config, this is controlled by `codebase/configuration/workflow_config.py`.

Important structure:

- `economy`
- `flows`
- `products`
- year columns such as `1990` through the base year

ESTO rows are usually cleaned by dropping subtotal rows and aggregate products before calculations.

### 9th Outlook Projection Data

The 9th Outlook table is the main projection source.

Important structure:

- `scenarios`
- `economy`
- sector hierarchy: `sectors`, `sub1sectors`, `sub2sectors`, `sub3sectors`, `sub4sectors`
- fuel hierarchy: `fuels`, `subfuels`
- subtotal flags
- year columns through the projection horizon

Most transformation and supply workflows allocate 9th Outlook projections onto ESTO-shaped flow/product rows using the 9th-to-ESTO mapping tables.

### LEAP Export Templates

LEAP export workbooks provide branch paths, variable names, IDs, units, region metadata, and the workbook shape required for LEAP import.

The most important template is:

```text
data/full model export.xlsx
```

Do not treat generated workbooks as schema authorities if a fresh full-model export is available. LEAP import rows with missing IDs can be silently skipped by LEAP, so branch-path/template alignment is a high-risk area.

## 4. Mapping Sources

The system currently has several overlapping mapping sources. This is one of the main rewrite risks.

Important files and concepts:

- `config/master_config.xlsx`
  Consolidated workbook for many code/name and 9th-to-ESTO tables.

- `config/leap_mappings.xlsx`
  LEAP-to-ESTO and LEAP-to-9th mapping workbook used by balance/dashboard/reconciliation paths.

- `config/leap_export_workbook_mappings.xlsx`
  Analysis-view field mapping used to align generated workbooks with LEAP export metadata.

- `config/supply_reconciliation_config.json`
  Capacity-unmet priority and cap configuration for the iterative supply reconciliation workflow.

- `C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx`
  External mapping-maintenance source used by some mapping tools.

The rewrite should create one mapping access layer and route all active workflows through it. Until that exists, changing a mapping in only one workbook may not affect every workflow.

## 5. Current Code Areas

### Workflow Entry Scripts

These scripts are notebook-safe user-facing runners. They should stay small after the rewrite.

- `codebase/supply_reconciliation_workflow.py`
- `codebase/supply_workflow.py`
- `codebase/transformation_workflow.py`
- `codebase/transfers_workflow.py`
- `codebase/hydrogen_transformation_workflow.py`
- `codebase/minor_demand_workflow.py`
- `codebase/aggregated_demand_workflow.py`
- `codebase/other_loss_own_use_proxy_workflow.py`
- `codebase/electricity_heat_interim_workflow.py`

Current issue: some entry scripts contain too much business logic and mutable run config.

### Shared Function Modules

These modules hold most of the current reusable logic:

- `codebase/functions/transformation_analysis_utils.py`
- `codebase/functions/supply_data_pipeline.py`
- `codebase/functions/ninth_projection_mapping.py`
- `codebase/functions/leap_excel_io.py`
- `codebase/functions/leap_exports.py`
- `codebase/functions/leap_core.py`
- `codebase/functions/patch_baseline_seeds.py`
- `codebase/functions/analysis_input_write_dispatcher.py`

Current issue: some modules mix configuration, source loading, modelling rules, calculations, diagnostics, and export writing.

### Mapping Tools

Mapping tools build relationship tables and QA outputs. They are important, but some point to external mapping workbooks directly.

- `codebase/mapping_tools/`
- `codebase/mappings/canonical_mapping.py`
- `codebase/utilities/master_config.py`

Current issue: active workflow code and mapping-maintenance code do not yet share one clean config/mapping API.

### Utilities

General helpers live under:

- `codebase/utilities/`

Useful examples:

- `workflow_common.py`
- `output_paths.py`
- `leap_balance_export_resolver.py`
- `fuel_catalog_preflight.py`
- `energy_balance_template_extractor.py`

These are better rewrite candidates for preservation and light cleanup than replacement.

## 6. Main Workflow: Supply Reconciliation

`codebase/supply_reconciliation_workflow.py` is the integrated workflow. It links demand, transformation, transfers, other loss/own-use, supply, LEAP balance results, and LEAP import workbook generation.

Conceptually it does this:

```text
ESTO + 9th + mappings + LEAP balance exports
        -> reconciliation ledger
        -> transformation/supply/transfer adjustments
        -> LEAP import workbooks
        -> manual LEAP import/recalculate/export
        -> next reconciliation pass
```

The active important mode is the capacity-unmet iterative path:

- `baseline_seed`
  First pass. Writes initial supply/transformation setup and lets LEAP reveal unmet requirements or imports.

- `results_update`
  Later pass. Reads refreshed LEAP balance exports and allocates gaps to production, transformation capacity, exports, or import fallback.

This workflow is the strongest candidate for modularisation because it currently contains:

- runtime toggles and notebook presets;
- config loading;
- LEAP balance/result loading;
- direct demand mapping;
- transformation and transfer record collection;
- reconciliation ledger building;
- iterative capacity-unmet state handling;
- workbook merge/export logic;
- diagnostics and formatted balance tables;
- optional auxiliary workflows.

Important scope boundary:

- Demand and power gaps should usually be fixed in their own workflows/processes, not hidden inside supply reconciliation.
- Refining initialisation can be included, but later refining capacity/output-share adjustments should be reviewed separately.
- Transfers and minor transformation sectors can contain balance-structure relationships that are not clean physical technologies. Preserve unusual relationships unless they create material balance problems or a modeller deliberately changes the methodology.

## 7. Transformation, Transfers, and Supply

### Transformation

Transformation logic mostly lives in:

- `codebase/functions/transformation_analysis_utils.py`
- `codebase/transformation_workflow.py`
- `codebase/hydrogen_transformation_workflow.py`

It builds process records with output fuels, feedstocks, losses, auxiliary fuel ratios, process shares, efficiencies, and capacity-related fields.

Rewrite risk:

- process definitions are currently embedded in Python dictionaries;
- source loading and calculation rules are mixed in the same module;
- global mutable settings are changed by caller workflows.

### Transfers

Transfers are transformation-like processes based on ESTO `08 Transfers` rows (`08.01 Recycled products`, `08.02 Interproduct transfers`, `08.03 Products transferred`, `08.99 Transfers nonspecified`, or the aggregate `08 Transfers` when subflows are empty).

ESTO organises transfer flows by the administrative type of reclassification. LEAP instead groups them by fuel-level function: upstream liquids movements, refinery and blending activity, and an unallocated remainder. This design creates more meaningful differentiation within LEAP for each economy. It also means LEAP transfer categories cannot be mapped directly to individual ESTO `08.xx` subflows — they are structurally different categorisations of the same underlying reclassification activity. For comparison with ESTO, all LEAP transfer categories roll up to the parent `08 Transfers`. See `docs/mappings_system.md` for the rollup rule definition.

The economy-specific grouping of input and output fuels into the three transfer process categories is defined in `TRANSFER_PROCESS_CONFIG` inside `codebase/transfers_workflow.py`. This config is maintained per economy by running `codebase/scrapbook/transfers_mapping_exploration.py` and reviewing the output before updating the config.

Current issue:

- `TRANSFER_PROCESS_CONFIG` is inline in `codebase/transfers_workflow.py`;
- the maintenance loop asks users to run an exploration script and paste config back into source code.

This should become external config loaded by a transfer config reader.

### Supply

Supply logic mostly lives in:

- `codebase/functions/supply_data_pipeline.py`
- `codebase/supply_workflow.py`

It builds resources workbooks for imports, exports, and production-related rows.

Rewrite risk:

- branch-root classification uses both workbook-derived lookup and legacy ESTO-based fallback;
- source constants and export settings are still spread across module globals and workflow config.

## 8. Demand, Minor Demand, and Proxies

### Aggregated Demand

`codebase/aggregated_demand_workflow.py` can write Demand\\All demand aggregated branches. It is used for first-pass baseline seed runs where full LEAP balance results may not yet exist.

### Minor Demand

`codebase/minor_demand_workflow.py` handles a limited set of minor demand branches such as agriculture, fishing, and non-specified others.

Current issue:

- it is described as a scaffold;
- it contains future calibration placeholders;
- it has its own local config constants even though it now uses shared energy source config.

### Other Loss and Own-Use Proxy

`codebase/other_loss_own_use_proxy_workflow.py` writes proxy demand rows for transformation losses/own-use that are not modelled directly elsewhere.

This workflow is active and has relatively strong tests. It should be modularised carefully rather than rewritten from scratch.

## 9. Output Structure

Primary outputs should stay under `outputs/`.

High-level output categories are defined in:

```text
codebase/utilities/output_paths.py
```

Important categories:

- `outputs/leap_exports/standalone`
- `outputs/leap_exports/supply_reconciliation`
- `outputs/leap_exports/combined`
- `outputs/balance_tables`
- `outputs/mappings`
- `outputs/leap_results`

Rewrite rule:

Do not add more output roots unless there is a strong reason. Prefer clearer subfolders under the existing roots.

## 10. Workflow Methodology Notes

This section records what each active workflow is trying to put into LEAP and how those values are derived. During a rewrite, this is modelling methodology, not just implementation detail.

### `supply_reconciliation_workflow.py`

Purpose:

This is the integrated initialisation and reconciliation workflow. It combines demand, transformation, transfer, loss/own-use, and supply information into LEAP-ready workbooks, then uses later LEAP balance exports to iteratively close supply gaps.

Writes to LEAP:

- Supply/resource rows, mainly imports, exports, production-related values, and optional reset rows.
- Transformation rows from the transformation workflow, with process shares, efficiencies, feedstock shares, auxiliary use, output targets, and capacity-related values.
- Transfer rows from the transfers workflow.
- Other loss/own-use proxy rows, when enabled.
- Electricity/heat interim transformation rows, when enabled.
- Aggregated demand and demand-zeroing rows, when enabled for baseline seed runs.
- Combined full-model import workbooks aligned to `data/full model export.xlsx`.

Method:

- In `baseline_seed` mode, it writes initial supply/transformation assumptions and usually leaves imports as a signal for LEAP to reveal after recalculation.
- In `results_update` mode, it reads LEAP balance exports from the previous run, compares observed LEAP supply/trade behaviour against expected ESTO/9th-derived values, and allocates remaining gaps.
- Positive gaps can be routed to primary production, eligible transformation capacity, or import fallback depending on product type, caps, priority rules, and configuration.
- Capacity and production caps are loaded from `config/supply_reconciliation_config.json`.
- Cumulative iterative additions are persisted in a JSON state file so each pass builds on previous passes.
- Before LEAP import, the workflow tries to align generated rows to the full-model export so BranchID/VariableID/ScenarioID/RegionID are preserved.
- The main error signal is the difference between observed LEAP imports/exports after recalculation and expected imports/exports from the ESTO/9th-derived supply baseline.
- For positive import gaps, primary production headroom is tried first for primary products where allowed; remaining gaps can be allocated to transformation capacity in priority-module order; anything still unresolved is handled by the configured unresolved-positive policy, usually import fallback.
- Negative import gaps or export differences are interpreted as possible over-production, surplus transformation output, or trade-path differences. In the current setup, exports can be pinned to 9th projections unless that option is changed.
- Reset and zero-fill logic is part of the methodology. It explicitly clears stale supply import/export targets, transformation import/export targets, auxiliary fuel use, and feedstock shares for owned branches so old LEAP values do not survive unnoticed across passes.
- The zero-fill branch catalog is built from the full model export first, then optional live LEAP probe outputs, then prior generated workbooks. Branches missing from all catalog sources may not receive zero-fill rows.
- LEAP balance exports are preferred over older Results-view workbooks for observed trade and demand signals where the current workflow supports them.

Sector coverage:

- Inputs are the union of the workflow-specific inputs listed below: aggregated demand, transformation, hydrogen transformation, transfers, supply/resources, other loss and own-use proxy, and optional electricity/heat interim.
- Outputs are combined LEAP import workbooks containing rows under `Demand`, `Transformation`, and `Resources`, but only for branches owned by the active sub-workflows.
- It does not own detailed demand, the full power model, or post-initialisation refining methodology, even though it may include placeholder/zeroing/interim rows that affect those areas.

Important modelling assumption:

Imports should not be hard-coded first when a gap might be resolved by domestic production or transformation output. Imports are often used as the residual or fallback after more meaningful domestic levers have been tried.

How to interpret common gaps:

- LEAP imports more than expected: check `Maximum Production`, transformation `Exogenous Capacity`, module priority/order, shortfall rules, and fuel mappings.
- LEAP imports less than expected: check whether domestic production or transformation output is too high, or whether intended imports have become exports/surplus.
- LEAP exports more than expected: check output shares, `SurplusExported`, transformation over-production, and fixed export assumptions.
- Unmet requirements: check production/capacity caps, shortfall rules, module order, and missing input/output fuel mappings.

Verification:

- Automated tests: `tests/test_supply_reconciliation_capacity_unmet_iterative.py` and `tests/test_iterative_pass_archive_simulation.py`.
- Key behaviours covered: balance-demand workbook resolution, workbook-mode guardrails, export pinning, observed-trade collection from balance tables, capacity-unmet state persistence, same-results guard, baseline-seed state reset, and positive-gap allocation.
- Manual checks before LEAP import: inspect unmatched ID rows, metadata mismatches, source diagnostics, balance-demand issues, and any `BranchID=-1` nonzero rows. Nonzero rows without valid LEAP IDs must be fixed before import because LEAP can skip them.
- Manual checks after LEAP recalculation: export fresh balance results, rerun the workflow in `results_update`, and confirm large import/export gaps move in the expected direction.
- Completion check: the final pass should leave only small residuals that are deliberately assigned and explainable to the modeller who inherits the economy.

### `transformation_workflow.py`

Purpose:

Builds LEAP transformation import workbooks for non-hydrogen transformation modules using shared transformation analysis helpers.

Writes to LEAP:

- Transformation process branches.
- Output fuel rows.
- Feedstock fuel rows.
- Auxiliary fuel rows where applicable.
- Process Share.
- Feedstock Share.
- Efficiency.
- Optional output import/export target rows.
- Capacity-related variables when called by supply reconciliation modes that need them.

Method:

- Reads ESTO historical/base-year rows and 9th Outlook projection rows.
- For most transformation sectors, ESTO `09.*` transformation flows identify positive output rows and negative input rows.
- Loss/own-use flows can be used to build auxiliary fuel ratios or efficiency adjustments depending on the process.
- 9th projections are allocated onto ESTO flow/product rows using the 9th-to-ESTO mapping.
- Process records are built first, then converted into LEAP workbook rows.
- Feedstock shares and efficiencies are calculated from process input/output totals by year.
- The current default feedstock approach is the multi-feedstock single-process style: all input fuels are represented as feedstocks in one process, while auxiliary fuels come from own-use/loss data rather than from every negative input row.
- Some minor or non-specified transformation sectors may produce unusual efficiencies or input/output relationships because they preserve balance-table structure rather than represent a clean physical technology.
- Where transformation own-use cannot be cleanly represented as process auxiliary fuel, it may be routed to `Demand\Other loss and own use` by the proxy workflow.

Sector coverage:

- ESTO transformation flow inputs currently configured: `09.04 Electric boilers`, `09.05 Chemical heat for electricity production`, `09.06.01 Gas works plants`, `09.06.03 Natural gas blending plants`, `09.06.04 Gas-to-liquids plants`, `09.07 Oil refineries`, `09.08.01 Coke ovens`, `09.08.02 Blast furnaces`, `09.08.03 Patent fuel plants`, `09.08.04 BKB/PB plants`, `09.08.05 Liquefaction (coal to oil)`, `09.09 Petrochemical industry`, `09.10 Biofuels processing`, `09.11 Charcoal processing`, and `09.12 Non-specified transformation`.
- 9th transformation inputs currently configured: `09_06_02_liquefaction_regasification_plants` for LNG/liquefaction-regasification and `09_13_hydrogen_transformation` for hydrogen when the hydrogen analysis is included.
- Loss/own-use inputs used by configured sectors include `10.01.02 Gas works plants`, `10.01.03 Liquefaction/regasification plants`, `10.01.05 Coke ovens`, `10.01.06 Coal mines`, `10.01.07 Blast furnaces`, `10.01.11 Oil refineries`, and `10.01.17 Non-specified own uses`.
- LEAP outputs are under `Transformation\{module}`, with modules such as `NG Liquefaction`, `LNG regasification`, `Gas works plants`, `Natural gas blending plants`, `Coke ovens`, `Blast furnaces`, `Patent fuel plants`, `BKB and PB plants`, `Liquefaction (coal to oil)`, `Electric boilers`, `Chemical heat for electricity production`, `Petrochemical industry`, `Gas to liquids plants`, `Biofuels processing`, `Charcoal processing`, `Non-specified transformation`, `Oil Refining`, and optionally `Hydrogen transformation`.

Important modelling assumption:

Transformation outputs are positive and inputs are negative in the source balance tables. LEAP requires these to be expressed as process outputs, feedstock shares, auxiliary inputs, and efficiencies rather than as signed balance rows.

Verification:
- No dedicated direct test file currently covers the full main transformation workflow.
- Related automated tests: `tests/test_hydrogen_transformation_workflow.py`, `tests/test_transfers_template_coverage.py`, `tests/test_series_adapter_and_remaps.py`, and supply-reconciliation tests that consume transformation process records.
- Manual checks: run the transformation export for a small economy, inspect process summary/detail CSVs, confirm feedstock shares sum sensibly by process/year, confirm efficiencies are plausible, and verify the generated workbook branch paths exist in `data/full model export.xlsx` or the current LEAP export template.
- For rewrite work, add focused tests around process-record construction, sign handling, efficiency calculation, feedstock-share sums, and output workbook uniqueness before changing this module.

### `hydrogen_transformation_workflow.py`

Purpose:

Builds hydrogen-specific transformation workbooks separately from the broader transformation workflow.

Writes to LEAP:

- Hydrogen transformation process rows.
- Hydrogen, ammonia, and efuel output fuel rows.
- Feedstock rows such as electricity or natural gas inputs, depending on process.
- Process shares, efficiencies, feedstock shares, and optional output targets.

Method:

- Reuses `transformation_analysis_utils.py`.
- Runs only the hydrogen transformation analysis registry.
- Applies hydrogen display-name overrides so raw 9th codes become LEAP-readable fuel names such as `Hydrogen`, `Ammonia`, and `Efuel`.
- Deduplicates sector-level output import/export targets so one output fuel does not receive duplicate target rows.

Sector coverage:

- 9th process inputs currently configured: `09_13_01_electrolysers`, `09_13_03_smr_w_ccs`, and `09_13_02_smr_wo_ccs`.
- Feedstock fuel inputs currently configured: green electricity for electrolysers and natural gas for SMR with/without CCS. A non-green electricity electrolyser config exists but is disabled.
- Output subfuels currently configured: `16_x_hydrogen`, `16_x_ammonia`, and `16_x_efuel`, written to LEAP as `Hydrogen`, `Ammonia`, and `Efuel`.
- LEAP output module: `Transformation\Hydrogen transformation`.

Important modelling assumption:

Hydrogen is kept separate because it may need independent review and import timing from the rest of transformation, even though the underlying process-record logic is shared.

Verification:

- Automated tests: `tests/test_hydrogen_transformation_workflow.py`.
- Key behaviours covered: modelled hydrogen outputs match the 9th source, log rows are unique for export pivoting, and boolean aggregate labels resolve to the all-economies name rather than leaking `True`/`False` into outputs.
- Manual checks: inspect hydrogen process and detail summaries, confirm output labels are `Hydrogen`, `Ammonia`, and `Efuel`, and confirm duplicate import/export target rows are not produced for the same output fuel.

### `transfers_workflow.py`

Purpose:

Converts ESTO transfer flows into LEAP transformation-style transfer processes.

Writes to LEAP:

- Transfer transformation process branches.
- Output fuel rows.
- Feedstock fuel rows.
- Feedstock shares.
- Efficiencies.
- Optional output import/export targets.

Method:

- Reads ESTO `08 Transfers` rows and subflows such as recycled products, interproduct transfers, products transferred, and transfers nonspecified.
- Prefers detailed subflows when they have nonzero data; otherwise falls back to aggregate `08 Transfers`.
- Uses economy-specific transfer process config to group input and output products into LEAP process names such as `Upstream liquids transfers`, `Refinery & blending transfers`, or `Transfers unallocated`.
- Negative source rows become feedstock/input fuels.
- Positive source rows become output fuels.
- When ratios are implausible or configured process mappings do not cover the data well, an unallocated transfer process can be used.

Sector coverage:

- ESTO transfer flow inputs: `08 Transfers`, `08.01 Recycled products`, `08.02 Interproduct transfers`, `08.03 Products transferred`, and `08.99 Transfers nonspecified`.
- The workflow prefers nonzero subflows (`08.01`, `08.02`, `08.03`, `08.99`) over aggregate `08 Transfers`.
- LEAP output process groups currently used: `Upstream liquids transfers`, `Refinery & blending transfers`, `Transfers unallocated`, and economy-specific combined labels such as `Upstream & refinery transfers`. These should be treated as config-driven transfer process names.
- Fuel-level inputs and outputs are economy-specific and come from the configured transfer process mappings plus the sign of the ESTO transfer rows.

Important modelling assumption:

Transfers are not supply imports/exports. They represent reclassification or movement between fuel products and are therefore modelled as transformation-like processes.

Rewrite note:

The economy-specific transfer process config is currently inline in Python. It should become external reviewed config, because it is modelling methodology.

Verification:

- Automated tests: `tests/test_transfers_template_coverage.py`.
- Key behaviour covered: transfer category templates cover all labels if used.
- Manual checks: run `codebase/scrapbook/transfers_mapping_exploration.py` after changing transfer categories, review the candidate process config, inspect transfer process efficiencies and input/output ratios, and verify no unexpected legacy generic `Transfers` branch paths are produced in integrated exports.
- For rewrite work, add tests around detailed-subflow preference, aggregate-flow fallback, unallocated-policy triggering, and duplicate-row merge behaviour before moving config out of Python.

### `supply_workflow.py` and `supply_data_pipeline.py`

Purpose:

Build standalone LEAP supply/resource workbooks from ESTO and 9th supply data.

Writes to LEAP:

- Resource import rows.
- Resource export rows.
- Optional unmet-requirement rows.
- Production-related rows used by supply reconciliation or standalone supply setup.

Method:

- Reads ESTO and 9th source tables.
- Uses flow codes for production, imports, exports, stock changes, and total primary energy supply.
- Normalises signs so LEAP receives positive magnitudes for output-style values such as exports.
- Maps ESTO/9th product labels to LEAP fuel branch names.
- Classifies fuels under primary or secondary resources using the full-model export workbook where possible, with legacy fallback classification.
- Writes scenario-specific workbook rows for the selected economies and scenarios.
- Primary fuel production is controlled through annual `Maximum Production`, not through reserve depletion in the normal APERC setup.
- Current Accounts `Base Year Reserves` are generally treated as `Unlimited` unless a modeller intentionally adds economy-specific reserve/depletion assumptions.
- Secondary fuels are usually controlled through transformation capacity and output settings, though they may also have import/export rows in Resources.

Sector coverage:

- ESTO supply flow inputs: `01 Production`, `02 Imports`, `03 Exports`, `06 Stock changes`, and `07 Total primary energy supply`.
- 9th supply sector inputs: `01_production`, `02_imports`, `03_exports`, `06_stock_changes`, and `07_total_primary_energy_supply`.
- LEAP outputs are under `Resources\Primary` or `Resources\Secondary`, with branch root selected from the full-model export where possible.
- Measures written by default include `Imports` and `Exports`; `Unmet Requirements` is optional and currently controlled by `SUPPLY_INCLUDE_UNMET_REQUIREMENTS`.

Important modelling assumption:

Supply/resource branches should reflect energy balance supply concepts, but LEAP branch roots must match the model fuel structure. Fuel branch classification is therefore both a data task and a LEAP-model-structure task.

Verification:

- No dedicated direct test file currently covers the standalone supply workflow end to end.
- Related automated tests: `tests/test_supply_reconciliation_capacity_unmet_iterative.py`, `tests/test_leap_exports_api.py`, `tests/test_analysis_input_write_dispatcher.py`, and `tests/test_series_adapter_and_remaps.py`.
- Manual checks: inspect the generated supply workbook for correct Resources primary/secondary roots, confirm exports are positive magnitudes, confirm scenario names and region are present, and compare production/import/export totals against ESTO/9th source extracts for a small economy.
- Before LEAP import, run or review fuel catalog preflight output and check missing primary/secondary branch summaries.

### `aggregated_demand_workflow.py`

Purpose:

Builds a simplified demand representation as one aggregated demand branch per LEAP fuel.

Writes to LEAP:

- `Demand\All demand aggregated\{fuel}` rows.
- Usually `Activity Level = 1` and `Final Energy Intensity = total energy`, so LEAP-calculated total energy equals the desired fuel demand.
- Can also write direct `Total Energy` rows depending on mode.

Method:

- Base year uses ESTO demand-sector rows.
- Projection years use 9th Outlook rows filtered to demand-relevant sector hierarchy.
- Values are converted to positive magnitudes.
- Fuel mappings from LEAP-to-ESTO and LEAP-to-9th mapping sheets convert source fuel labels into LEAP fuel names.
- Can exclude selected demand sectors or loss/own-use sectors to avoid double counting when other workflows handle those separately.

Sector coverage:

- ESTO base-year demand inputs include selected `10_01_own_use` children, plus `04_international_marine_bunkers`, `05_international_aviation_bunkers`, `14_industry_sector`, `15_transport_sector`, `16_other_sector`, and `17_nonenergy_use`.
- Included ESTO own-use children are currently `10_01_01_electricity_chp_and_heat_plants`, `10_01_03_liquefaction_regasification_plants`, `10_01_06_coal_mines`, `10_01_11_oil_refineries`, `10_01_12_oil_and_gas_extraction`, and `10_01_13_pump_storage_plants`.
- 9th projection top-level sector inputs are `10_losses_and_own_use`, `14_industry_sector`, `16_other_sector`, `17_nonenergy_use`, `15_transport_sector`, `04_international_marine_bunkers`, and `05_international_aviation_bunkers`.
- 9th projection sub1 inputs include own-use, T&D losses, mining and quarrying, construction, manufacturing, buildings, agriculture and fishing, non-specified others, and the domestic air/road/rail/navigation/pipeline/non-specified transport branches.
- 9th projection sub2 inputs include detailed manufacturing, buildings, agriculture/fishing, transport passenger/freight, and selected own-use children. Electricity is excluded from T&D losses.
- LEAP outputs are under `Demand\All demand aggregated\{fuel}`.

Important modelling assumption:

This is a first-pass or simplified demand representation. It is useful when supply/transformation initialisation needs a demand signal before the full demand model is ready or before LEAP balance exports are available.

Verification:

- No dedicated direct test file currently covers aggregated demand end to end.
- Related automated tests: supply-reconciliation tests cover the integrated path that can call aggregated demand during baseline seed setup.
- Manual checks: compare generated fuel totals against the selected ESTO base-year demand rows and 9th projection filters; confirm excluded sectors are actually excluded; confirm own-use/T&D loss exclusions line up with the other-loss/own-use proxy setting; and inspect that generated branches use `Demand\All demand aggregated\{fuel}`.
- Before import, verify Activity Level and Final Energy Intensity pairing when `USE_INTENSITY_ACTIVITY_MODE=True`.

### `minor_demand_workflow.py`

Purpose:

Builds LEAP import rows for selected minor demand sectors, especially agriculture, fishing, and non-specified others.

Writes to LEAP:

- Demand sector Activity Level rows.
- Fuel-level Activity Level rows, depending on fuel activity mode.
- Fuel-level Final Energy Intensity rows.
- Optional Intensity Adjustment rows if enabled.

Method:

- Loads filtered ESTO data and 9th projection data.
- Filters the 9th-to-ESTO mapping to the configured minor demand ESTO flows.
- Allocates 9th projections to ESTO flow/product rows using base-year shares.
- Adds ESTO base-year values to anchor the projection series.
- Supports two main fuel activity interpretations:
  - energy-valued fuel activity with intensity set to one;
  - fuel activity as sector share, with intensity set to one.
- Writes expressions into a LEAP workbook aligned to a demand export template.

Sector coverage:

- ESTO flow inputs currently configured: `16.03 Agriculture`, `16.04 Fishing`, and `16.05 Non-specified others`.
- Expected 9th sector inputs: `16_02_agriculture_and_fishing` for agriculture/fishing and `16_05_nonspecified_others` for non-specified others.
- LEAP outputs are under the configured demand root, currently `Demand\Other sector\Agriculture`, `Demand\Other sector\Fishing`, and `Demand\Other sector\Non-specified others`, with fuel child branches below each sector.

Important modelling assumption:

Minor demand is intentionally simple. It uses ESTO base-year fuel splits and 9th projections to create plausible branch-level LEAP inputs where detailed sector models are not yet represented.

Verification:

- Automated tests: `tests/test_minor_demand_workflow.py`.
- Key behaviours covered: sector-share activity alignment, fuel activity units, energy-activity mode, legacy `fuel_share` alias, fallback when allocated projections are missing, passed mapping scope, and ESTO-share base-year fuel activity.
- Manual checks: inspect the generated workbook for sector Activity Level rows, fuel Activity Level rows, fuel Final Energy Intensity rows, and expected branch root under `Demand\Other sector` unless configured otherwise.
- Check that fuel activities sum or share back to sector totals according to the selected fuel activity mode.

### `other_loss_own_use_proxy_workflow.py`

Purpose:

Builds demand-side proxy branches for transformation losses and own-use that are not represented cleanly inside transformation modules.

Writes to LEAP:

- `Demand\Other loss and own use\{process}\{fuel}` branches.
- Activity Level rows for proxy activity.
- Final Energy Intensity rows for fuel-specific loss/own-use intensity.

Method:

- For each configured proxy process, builds a proxy activity series.
- Pulls target loss/own-use energy by fuel.
- Calculates intensity as `abs(target loss or own-use energy) / proxy activity`.
- In first-stage mode, activity and target energy come from ESTO base year plus 9th projections.
- In second-stage mode, activity can come from LEAP balance exports, so the proxy follows the recalculated model state.
- Output fuel validation filters out fuels that are not active for the relevant economy/model scope.
- Generated rows are aligned to the full-model export where possible so LEAP IDs are preserved.

Sector coverage:

- Enabled proxy outputs currently include `Coal mines`, `Electricity, CHP and heat plants`, `Liquefaction/regasification plants`, `Oil and gas extraction`, `Pump storage plants`, `Nuclear industry`, `Gasification plants for biogases`, and `Transmission and distribution loss`.
- Disabled scaffold proxy configs currently include `Gas works plants`, `Gas-to-liquids plants`, `Coke ovens`, `Blast furnaces`, `Patent fuel plants`, `BKB/PB plants`, `Liquefaction plants (Coal to Oil)`, `Oil Refining`, `Charcoal production plants`, `Non-specified own uses`, and `CCS`.
- Target ESTO loss/own-use inputs include `10.01.01 Electricity, CHP and heat plants`, `10.01.02 Gas works plants`, `10.01.03 Liquefaction/regasification plants`, `10.01.04 Gas-to-liquids plants`, `10.01.05 Coke ovens`, `10.01.06 Coal mines`, `10.01.07 Blast furnaces`, `10.01.08 Patent fuel plants`, `10.01.09 BKB/PB plants`, `10.01.10 Liquefaction plants (Coal to Oil)`, `10.01.11 Oil refineries`, `10.01.12 Oil and gas extraction`, `10.01.13 Pump storage plants`, `10.01.14 Nuclear industry`, `10.01.15 Charcoal production plants`, `10.01.16 Gasification plants for biogases`, `10.01.17 Non-specified own uses`, and `10.02 Transmission and distribution losses`.
- LEAP outputs are under `Demand\Other loss and own use\{process}\{fuel}`.

Important modelling assumption:

Some loss/own-use quantities behave like energy demand from the system rather than transformation process feedstocks. The proxy makes those quantities visible and controllable in LEAP demand branches.

Verification:

- Automated tests: `tests/test_other_loss_own_use_proxy_workflow.py`.
- Key behaviours covered: proxy config coverage, detailed 9th activity before parent fallback, ESTO/ninth activity fallback, target-energy filtering, intensity calculation as absolute target over activity, zero-target rows, parent activity sums, output fuel validation, export ID merging, zero rows for unset values, LEAP balance activity mode, fuel-set verification, and T&D loss treatment.
- Manual checks: inspect proxy detail CSVs, fuel validation reports, activity-source fallback warnings, and final workbook ID merge results.
- For second-stage runs, verify the resolved LEAP balance workbook is the intended scenario/date and that selected LEAP fuels drive proxy activity correctly.

### `electricity_heat_interim_workflow.py`

Purpose:

Builds simplified interim transformation modules for electricity, CHP, and heat plants when the full power model is not ready.

Writes to LEAP:

- `Transformation\Electricity interim\Processes\Electricity interim`
- `Transformation\CHP interim\Processes\CHP interim`
- `Transformation\Heat plant interim\Processes\Heat plant interim`
- Output fuel rows for electricity and/or heat.
- Feedstock fuel rows for all negative source rows.
- Process shares, feedstock shares, and efficiencies.

Method:

- Uses ESTO power-sector transformation flows for base-year/historical data.
- Uses 9th power-sector sub1sector rows for projections.
- All negative rows are treated as feedstocks.
- Auxiliary fuel use is excluded because own-use and losses are handled separately by the other-loss/own-use proxy.
- Writes a single interim export workbook per economy.

Sector coverage:

- `Electricity interim` source inputs: ESTO `09.01.01 Electricity plants` and `09.02.01 Electricity plants`; 9th `09_01_electricity_plants`; output fuel `Electricity`.
- `CHP interim` source inputs: ESTO `09.01.02 CHP plants` and `09.02.02 CHP plants`; 9th `09_02_chp_plants`; output fuels `Electricity` and `Heat`.
- `Heat plant interim` source inputs: ESTO `09.01.03 Heat plants` and `09.02.03 Heat plants`; 9th `09_x_heat_plants`; output fuel `Heat`.
- LEAP outputs are under `Transformation\Electricity interim`, `Transformation\CHP interim`, and `Transformation\Heat plant interim`.

Important modelling assumption:

This is a temporary bridge, not the final power methodology. It allows the broader supply/transformation reconciliation loop to run before the full power model is available.

Verification:

- No dedicated direct test file currently covers the interim electricity/heat workflow.
- Related automated tests: `tests/test_power_workflow.py` covers the fuller power workflow, and supply-reconciliation tests cover the integrated ability to include interim workbooks.
- Manual checks: inspect the interim fuel validation report, confirm only the three interim modules are emitted, confirm electricity/heat output rows are present as expected, and confirm auxiliary fuels are not included.
- After LEAP import/recalculation, verify that interim modules do not conflict with the full power model if both are present.

### `refining_workflow.py`

Purpose:

Builds and optionally imports refining branch data from a refining model export workbook.

Writes to LEAP:

- Oil refining transformation branches.
- Output fuel rows.
- Feedstock fuel rows.
- Auxiliary fuel rows.
- Scenario rows for selected refining variables.

Method:

- Starts from `data/refining model export.xlsx`.
- Can remap transformation fuel names before import.
- Ensures requested scenarios exist in the export.
- Can create branches and fill values through the same workbook/API dispatch pattern used elsewhere.
- Some refining variables are intentionally skipped or left for manual review.

Sector coverage:

- Source workbook: `data/refining model export.xlsx`, sheet `refining`.
- LEAP output scope: `Transformation\Oil Refining`, especially process, output fuel, feedstock fuel, and auxiliary fuel branch groups.
- Fuel branch groups handled by the workflow are `Output Fuels`, `Feedstock Fuels`, and `Auxiliary Fuels`.

Important modelling assumption:

Refining initialisation is part of the transformation/supply setup, but later refining model adjustments should be reviewed separately rather than hidden inside the supply reconciliation loop.

Verification:

- No dedicated direct test file currently covers `refining_workflow.py` end to end.
- Related automated tests: `tests/test_series_adapter_and_remaps.py` covers expression/year-column handling for remap helpers; supply-reconciliation tests cover some downstream refining/supply interactions.
- Manual checks: verify the source `data/refining model export.xlsx` has the expected scenarios and sheet, inspect remapped fuel names, confirm skipped variables are intentional, and review output/feedstock/auxiliary fuel branch groups before import.
- After import, check refining outputs and feedstocks in LEAP balance results before relying on supply reconciliation to close residual supply gaps.

### `outlook_mapping_maintenance_workflow.py`

Purpose:

Refreshes maintenance and audit columns in `config/leap_mappings.xlsx`.

Writes to LEAP:

- Nothing directly. This is a mapping maintenance workflow, not a LEAP import workflow.

Method:

- Reads `leap_combined_esto` and `leap_combined_ninth`.
- Reads ESTO and 9th source tables.
- Reads code/name tables from `master_config.xlsx`.
- Uses LEAP balance export structure to identify mapping coverage and conflicts.
- Produces researcher-facing mapping outputs, missing-pair reports, duplicate checks, trio-presence checks, and mapping conflict workbooks.

Important modelling assumption:

Mapping rows marked removed may be deliberate guardrails, especially where detail levels differ and active rows would create many-to-many relationships. Refresh outputs should be reviewed before reactivating or adding mappings.

Verification:

- Automated tests: `tests/test_outlook_mapping_maintenance_workflow.py`.
- Key behaviours covered: refreshed sheets keep cardinality while dropping deprecated many-to-many flags, active counterpart gaps, active target conflicts, non-strict cardinality review labels, and implied missing crosswalk pair suggestions.
- Manual checks: review `outputs/mappings/mapping_checks/`, especially missing-pair summaries, duplicate mappings, trio-presence checks, mapping conflicts, and researcher mapping outputs.
- Do not reactivate removed-only rows without checking many-to-many consequences and rollup intent.

### Mapping Relationship Tools

Purpose:

Build compiled relationship tables between LEAP, ESTO, and 9th structures for comparison and dashboard-style aggregation.

Writes to LEAP:

- Nothing directly.

Method:

- Reads authored mapping sheets and rollup rules.
- Applies rollups before cardinality checks.
- Preserves removed rows as excluded relationships.
- Writes relationship catalogues, rolled mapping rows, and QA outputs under `results/mapping_relationships`.

Important modelling assumption:

Many-to-many relationships before rollup may be acceptable. Many-to-many relationships after rollup are high-risk and usually need mapping or rollup review.

Verification:

- Automated tests: `tests/test_mapping_rollups.py`, `tests/test_energy_balance_template_extractor_descendants.py`, `tests/test_leap_results_dashboard_balance_crosswalk.py`, and `tests/test_leap_balance_total_checks.py`.
- Key behaviours covered: rollup sheets, rollups before cardinality, many-to-many after rollup severity, reverse ninth-to-LEAP checks, recorded exceptions, subtotal alignment, descendant mapping expansion, active balance crosswalk loading, and signed TPES total checks.
- Manual checks: review `results/mapping_relationships/qa/qa_many_to_many_after_rollup.csv`, `relationship_catalogue.csv`, `rolled_mapping_rows.csv`, and any subtotal-alignment warnings before treating relationship outputs as authoritative.
- For dashboard/comparison uses, also run or inspect LEAP series comparison outputs where relevant.

### Minimal Post-Recalculation QA

After each full LEAP recalculation in the initialisation loop, check these before deciding the next adjustment:

| Check | Question | Typical response if failed |
|---|---|---|
| Final demand | Does final demand match expected sector results? | Fix demand model/imports before supply reconciliation hides the issue. |
| Major transformation output | Are power, refining, and other transformation outputs plausible? | Review module settings, capacities, process shares, or branch mappings. |
| Transfers | Are transfer flows plausible and stable? | Review transfer grouping, unallocated transfers, and upstream/refinery assumptions. |
| Domestic production | Is production close to intended ESTO/9th path? | Adjust `Maximum Production` or production caps. |
| Imports | Are imports close to intended values after domestic routes are used? | Treat the difference as a supply/capacity signal, not automatically as a value to hard-code. |
| Exports | Are exports plausible and explainable? | Check fixed exports, output shares, and `SurplusExported` co-product surplus. |
| Losses and own-use | Are energy-sector own-use and losses plausible? | Check auxiliary fuel use and proxy demand branches. |
| Unmet requirements | Are any unmet requirements unexplained? | Identify fuel/year/scenario and adjust supply route, capacity, production, or shortfall rule. |
| Module ordering | Do conversion chains run from demand-facing modules to upstream modules? | Reorder modules if LEAP is asking the wrong supply route first. |

## 11. Current Pain Points

These are the problems a rewrite should solve.

### Oversized Modules

The largest active files combine too many concerns:

- `supply_reconciliation_workflow.py`
- `transformation_analysis_utils.py`
- `other_loss_own_use_proxy_workflow.py`
- `supply_data_pipeline.py`
- `minor_demand_workflow.py`
- `transfers_workflow.py`

The rewrite should split these by responsibility, not just by file size.

### Scattered Config

Config currently exists in:

- Python globals;
- JSON;
- Excel workbooks;
- hard-coded paths;
- notebook runtime blocks;
- environment variables;
- external sibling repos.

The rewrite should separate:

- user-run settings;
- model/method settings;
- source data settings;
- mapping source settings;
- output path settings;
- LEAP import/export schema settings.

### Inconsistent Mapping Access

Some code uses `read_config_table()` and can transparently read from `master_config.xlsx`. Some code reads Excel/CSV files directly. Some mapping tools point to `leap_mappings` outside the repo.

The rewrite should provide one mapping API and make direct mapping workbook reads the exception.

### Mutable Globals

Several workflows change globals in imported modules during a run. This makes behaviour hard to reason about and hard to test.

The rewrite should pass explicit config objects into functions and return explicit outputs.

### Notebook Runtime Blocks Mixed With Logic

The user-facing notebook pattern is useful and should remain. But editable run blocks should live in thin workflow scripts, not in modules that also contain calculation logic.

### Legacy Compatibility Layers

There are many compatibility aliases, fallback paths, and old modes. Some are still useful; others are probably only preserving historical behaviour.

The rewrite should list every legacy mode before deleting or changing it.

## 12. What Should Be Preserved

Preserve these behaviours unless there is an explicit modelling decision to change them:

- workbook-first LEAP import/export workflow;
- notebook-safe execution with editable constants at the bottom of workflow scripts;
- `#%%` cell separators in runnable workflow scripts;
- explicit run flags and presets for major workflow modes;
- LEAP export workbook structure and ID preservation;
- ESTO/9th sign conventions;
- subtotal filtering before most balance calculations;
- current output root structure;
- daily config archiving where workflows mutate or depend on config;
- diagnostics for missing mappings, missing branch IDs, and source coverage gaps;
- tests that protect current behaviour.

## 13. Proposed Rewrite Shape

A safer modular structure would look like this:

```text
codebase/
  configuration/
    run_config.py
    source_config.py
    path_config.py
    leap_schema_config.py
  sources/
    esto_loader.py
    ninth_loader.py
    reference_tables.py
  mappings/
    mapping_store.py
    code_labels.py
    leap_esto.py
    ninth_esto.py
  transformation/
    process_registry.py
    process_builder.py
    process_math.py
    export_builder.py
  transfers/
    transfer_config.py
    transfer_builder.py
  supply/
    supply_builder.py
    resource_classification.py
  reconciliation/
    demand_inputs.py
    ledger.py
    capacity_unmet.py
    iterative_state.py
    diagnostics.py
  exports/
    leap_workbook_builder.py
    combined_workbook.py
  workflows/
    supply_reconciliation_workflow.py
    transformation_workflow.py
    supply_workflow.py
```

This is a target shape, not a requirement for the first rewrite pass. The first pass should extract only the modules needed to reduce risk.

## 14. Rewrite Guardrails

Use these rules during the rewrite:

1. Preserve current outputs for one small golden economy before changing logic.
2. Move config out of code before changing calculations.
3. Create a mapping/source access layer before touching every workflow.
4. Extract pure functions from large modules without changing signatures where possible.
5. Keep old workflow entrypoints callable until replacement outputs are verified.
6. Add tests around newly extracted modules before deleting old code paths.
7. Do not remove legacy fallbacks until there is evidence they are unused.
8. Keep workbook output compatibility with LEAP import/export rules.

## 15. Suggested Rewrite Order

### Phase 0: Document and Freeze

- Record the active workflow inventory.
- Choose a small golden run, probably one economy and two scenarios.
- Save expected key outputs and diagnostics.
- Identify files that are generated versus authored.

### Phase 1: Config and Mapping Layer

- Define a typed run/source/path config.
- Route ESTO/9th source paths through one config object.
- Route mapping reads through one mapping store.
- Move transfer process config out of Python source.

### Phase 2: Source Loaders

- Extract ESTO loader and 9th loader.
- Centralise year-column normalization.
- Centralise subtotal filtering.
- Centralise aggregate economy handling.

### Phase 3: Transformation and Supply Extraction

- Extract transformation process record building.
- Extract supply resource row building.
- Keep existing workflow scripts as wrappers.
- Compare outputs against the golden run.

### Phase 4: Reconciliation Extraction

- Split `supply_reconciliation_workflow.py` into:
  - demand input loading;
  - transformation/supply ledger;
  - capacity-unmet allocation;
  - state persistence;
  - workbook packaging;
  - diagnostics.

### Phase 5: Cleanup

- Remove duplicated helpers.
- Remove dead legacy modes only after tests and output comparison pass.
- Update user-facing docs and workflow inventory.

## 16. Handover Notes

For a new maintainer, the minimum reading order is:

1. `README.md`
2. this document
3. `docs/supply_reconciliation_workflow_guide.md`
4. `data/README.md`
5. `AGENTS.md`
6. `config/supply_reconciliation_config.json`
7. `codebase/configuration/workflow_config.py`

For a rewrite maintainer, also inspect:

- `tests/test_supply_reconciliation_capacity_unmet_iterative.py`
- `tests/test_iterative_pass_archive_simulation.py`
- `tests/test_other_loss_own_use_proxy_workflow.py`
- `tests/test_minor_demand_workflow.py`
- `tests/test_mapping_rollups.py`
- `tests/test_analysis_input_write_dispatcher.py`

These tests describe several behaviours that should not be broken casually.

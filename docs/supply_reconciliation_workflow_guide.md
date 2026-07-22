# `supply_reconciliation_workflow.py` Guide

> **Purpose note**  
> This document explains the role of `codebase/supply_reconciliation_workflow.py` in the APERC LEAP workflow. It focuses on the process around the script: why it is needed, how it fits around LEAP, what it compares, and how modellers should interpret its outputs.

This guide is based on the documented workflow logic. It should be checked against the current Python file before being treated as a complete code reference.

## Contents

### Overview

- [0. Where this fits in](#0-where-this-fits-in)
- [1. Why this workflow exists](#1-why-this-workflow-exists)

### How it works

- [2. What the workflow does conceptually](#2-what-the-workflow-does-conceptually)
- [3. The main error signal](#3-the-main-error-signal)
- [4. Active mode: `capacity_unmet_iterative_balanced`](#4-active-mode-capacity_unmet_iterative_balanced)
- [4a. The three run modes: `baseline_seed`, `results_update`, `patch_baseline_seeds`](#4a-the-three-run-modes-baseline_seed-results_update-patch_baseline_seeds)
- [4c. Other settings with real operational impact](#4c-other-settings-with-real-operational-impact)
- [4d. Major sub-workflows this file drives](#4d-major-sub-workflows-this-file-drives)
- [4e. Checks and validation (link to the check registry)](#4e-checks-and-validation-link-to-the-check-registry)
- [6. Why production and transformation are linked](#6-why-production-and-transformation-are-linked)

### Reference

- [5. Main LEAP variables affected](#5-main-leap-variables-affected)
- [7. Expected inputs](#7-expected-inputs)
  - [Source data files](#source-data-files)
- [8. Expected outputs](#8-expected-outputs)

### Running the workflow

- [9. Manual run loop](#9-manual-run-loop)
- [10. Why the LEAP API is not used as the main method](#10-why-the-leap-api-is-not-used-as-the-main-method)
- [11. How many iterations are expected](#11-how-many-iterations-are-expected)
- [Concurrent runs](#concurrent-runs)

### Interpreting results

- [12. How to interpret the reconciliation results](#12-how-to-interpret-the-reconciliation-results)
  - [Large positive import gap](#large-positive-import-gap)
  - [Large negative import gap](#large-negative-import-gap)
  - [Large export gap](#large-export-gap)
  - [Unmet requirements](#unmet-requirements)

### Guidelines

- [13. What not to do](#13-what-not-to-do)
- [14. Practical checklist before running](#14-practical-checklist-before-running)
- [15. Practical checklist after running](#15-practical-checklist-after-running)
- [16. When the process is finished](#16-when-the-process-is-finished)
- [17. How to use the rule findings files](#17-how-to-use-the-rule-findings-files)

### Code reference

- [18. Code reference](#18-code-reference)

---

## 0. Where this fits in

This workflow is one tool used during the **LEAP initialisation process** — the stage where a new economy/scenario area is first built up and reconciled before it is handed over for scenario work within LEAP. `LEAP initialisation guide.docx` is the overall guide to that initialisation process; it explains where this workflow (and the other initialisation steps, including demand and power) fit in the sequence. Read that guide first for the end-to-end picture; this document only covers the supply/transformation reconciliation step.

The data this workflow reconciles against, and the modelling logic it is trying to keep consistent with, is described in `supply_side_modelling_overview.md`. That document explains the LEAP-side modelling logic (transformation modules, transfers, supply/resources, losses and own-use); this guide explains the Python tool that helps reconcile those branches against expected supply/trade outcomes.

**Sector scope — important limitation.** This workflow can only initialise and adjust the sectors covered by `supply_side_modelling_overview.md`: other transformation (LNG regasification, natural gas liquefaction, coal transformation, blast furnace gas, coke ovens, patent fuel plants, non-specified transformation, etc.), transfers, supply/resources (production, imports, exports), and losses/own-use. This is because those are the only branches this codebase builds workbooks for.

- **Demand** and **Power** are initialised by separate workflows/processes (not this one) — this workflow writes placeholder/zero rows for those branches where needed, but does not set them up.
- **Refining** is a special case: this workflow does perform the *initialisation* of refining (it is part of the same transformation/transfers codebase), but any *adjustments* to refining assumptions after that initial setup (capacity, output shares, etc.) should be handled separately from this reconciliation loop, not through this workflow's iterative gap-filling logic. This same principle applies to all processes initialised by this workflow — it is the right place for initialisation and reconciliation against the supply/trade baseline, but not for making targeted adjustments to individual process assumptions after that initial setup. Refining is the most likely process to need such post-initialisation adjustment, because its capacity, output shares, and feedstock splits are more economy-specific and more likely to be revised; for other processes this is less common, but the same rule applies if it does arise.

In short: this workflow only initialises and adjusts supply, transformation, and transfers. Demand and power are present as placeholders during this step and are not adjusted by this workflow. If placeholder branches produce unexpected values, that most likely indicates a bug in the placeholder workbook rather than something to address here. Demand and power are initialised separately after supply reconciliation is complete — see `LEAP initialisation guide.docx` for where those steps fit in the overall sequence.

Once initialisation is complete, no sector is adjusted through this workflow — all further changes are made directly in LEAP. Only if a sector becomes significantly muddled would reinitialisation be worth considering, and even then the most practical approach is usually to apply the latest initialisation workflow output for the affected sectors and fuels rather than re-running the full process.

**Mapping reference.** The fuel and sector mappings used to connect LEAP outputs to ESTO and 9th Outlook comparison data are maintained in the `leap_mappings` repository. See `leap_mappings/docs/mappings_system.md` for the canonical reference on how LEAP branches, ESTO flows, and 9th Outlook sectors correspond to each other. Workflow scripts in this repository should draw on those mappings rather than defining fuel or sector relationships internally.

For LEAP-side terminology and modelling semantics, use the local reference clone at `C:\Users\Work\github\LEAP_manual` as the secondary reference. In practice, the sections that matter most for this workflow are `08 - Transformation`, `10 - Resources`, `18 - Expressions`, and `21.1 - API`.

### The initialisation workflow scripts

Before supply reconciliation can begin, the LEAP area must be populated with initial supply, transformation, and transfers data. This is done by a set of workflow scripts that read ESTO and 9th Outlook source data and produce LEAP import workbooks. Together their outputs form the **baseline seed** — the starting point imported into a new LEAP economy area before any reconciliation passes are run.

| Script | What it produces |
|---|---|
| `aggregated_demand_workflow.py` | The `Demand\All demand aggregated` placeholder branch. Aggregates expected demand across all sectors (using 9th Outlook projections as a proxy) into a single branch used while individual demand sector models are still being developed. Can be configured to exclude sectors that have already been modelled. |
| `electricity_heat_interim_workflow.py` | Interim electricity, CHP, and heat transformation modules. Uses only signed `09_*` transformation rows: positive values supply outputs and negative values supply feedstocks. `18_*`/`19_*` accounting sectors are prohibited. |
| `other_loss_own_use_proxy_workflow.py` | The `Demand\Other losses and own use` branches. Captures own-use and losses associated with supply processes and transformation modules that cannot be assigned to a specific transformation module's auxiliary fuel use. |
| `refining_workflow.py` | Refining transformation data — input/output relationships, process efficiency, and exogenous capacity for the refining module — drawn from ESTO historical relationships and 9th Outlook projections. |
| `supply_workflow.py` | Supply and resources data — domestic production (`Maximum Production`), imports, and exports for primary and secondary fuels — drawn from ESTO and 9th Outlook baselines. |
| `transformation_workflow.py` | Other transformation sector data — LNG regasification, gas liquefaction, coal transformation, coke ovens, blast furnaces, patent fuel plants, non-specified transformation, and related modules — including exogenous capacity and process efficiency. |
| `transfers_workflow.py` | Transfers data for the upstream liquids, refinery and blending, and transfers unallocated modules. |

`supply_reconciliation_workflow.py` then uses the outputs of `supply_workflow.py` and `transformation_workflow.py` as its baseline reference and iteratively adjusts them based on LEAP results. The other scripts (`aggregated_demand_workflow.py`, `electricity_heat_interim_workflow.py`, `other_loss_own_use_proxy_workflow.py`) are run once at initialisation and are not part of the reconciliation loop.

The final baseline seed combines the current run's supply, transformation
(including oil refining), transfers, interim electricity/CHP/heat,
loss/own-use proxy, aggregated-demand, and demand-zeroing workbooks. Every
configured producer must supply a readable workbook for each requested
economy. The writer validates all economies before replacing any final seed.
Default scenario coverage is Current Accounts 2022 and Reference/Target
2023–2060; both endpoints are configurable in `workflow_config.py`.

Mapping inputs for supporting producers and reconciliation now come from
`leap_mappings/config/outlook_mappings_master.xlsx`. Operational configuration
that is not a semantic mapping is stored in `config/runtime_tables/`. Treat a clean
non-importing `20_USA` qualification run as the final gates before declaring
the baseline seed fully canonical.

## 1. Why this workflow exists

The APERC LEAP model needs to combine:

- demand model results;
- transformation inputs and outputs;
- losses and own-use;
- domestic production assumptions;
- imports and exports;
- 9th Outlook / ESTO supply projections;
- LEAP's own internal balancing behaviour.

Once all these pieces are inside LEAP, the model may not produce the same import/export/supply balance that was expected from the original 9th Outlook supply projections. This is normal, because the move into LEAP changes how different parts of the system interact.

For example:

- transformation output can replace domestic production;
- domestic production can replace imports;
- output shares can create surplus co-products;
- capacity limits can create shortfalls;
- losses and own-use create extra upstream fuel requirements;
- LEAP may allocate balancing gaps to imports, exports, or unmet requirements.

`supply_reconciliation_workflow.py` is designed to help reduce these unintended gaps.

## 2. What the workflow does conceptually

At a high level, the workflow compares what LEAP is doing with what the supply projection expected.

```mermaid
flowchart TD
    A[LEAP recalculated area]
    B[Export LEAP energy balance results]
    C[supply_reconciliation_workflow.py]
    D[Combine demand, transformation, losses, supply, production, imports, exports]
    E[Compare LEAP observed trade with expected 9th/ESTO supply baseline]
    F[Calculate import/export gaps]
    G[Allocate gaps to production, transformation capacity, or exports]
    H[Generate updated LEAP import workbook]
    I[Import workbook into LEAP]
    J[Recalculate LEAP]

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> B
```

The workflow is iterative. It is not expected to solve the whole system perfectly in one run.

The key idea is that demand is taken as given, then the workflow watches how much import LEAP needs to satisfy that demand after recalculation. Imports are therefore treated as an observable signal of imbalance, not as a number to hard-code upfront.

On the first pass (`baseline_seed`), the workflow does not try to solve that imbalance directly. It writes the supply export with imports set to zero, lets LEAP recalculate, and uses the resulting import requirement as the signal for where domestic supply or transformation output is missing. On later passes (`results_update`), the workflow reads LEAP's balance results back and compares the observed import/export pattern with the expected 9th Outlook / ESTO baseline, then adjusts the supply-side levers accordingly.

```mermaid
flowchart TD
    A[Demand and baseline supply assumptions]
    B[baseline_seed]
    C[Write imports = 0]
    D[LEAP recalculates]
    E[Read balance tables]
    F[Observed import gap]
    G[results_update]
    H[Adjust production, capacity, or exports]
    I[Next import workbook]

    A --> B --> C --> D --> E --> F --> G --> H --> I --> D
```

## 3. The main error signal

The main error signal is the difference between:

- the imports/exports LEAP is producing after recalculation; and
- the imports/exports expected from the 9th Outlook / ESTO supply projection baseline.

A simple way to interpret this is:

| Gap type | Interpretation | Possible response |
|---|---|---|
| LEAP imports more than expected | The model needed more imported fuel than the reconciliation baseline expected, which usually means domestic production or transformation output is too low. | Increase primary `Maximum Production` or transformation `Exogenous Capacity`, where plausible. If reserves are used for the primary fuel, also increase reserve levels by a corresponding amount, if necessary (it is unlikely they will be on initialisation). |
| LEAP imports less than expected | The model may have too much domestic production or transformation output, or may need more exports. | Reduce production/capacity or route surplus to exports. |
| LEAP exports more than expected | Transformation surplus or over-production may be occurring. | Check output shares, `SurplusExported`, capacity, and export settings. |
| LEAP exports less than expected | Production or transformation output may be too low, or domestic demand may be absorbing more fuel. | Check production, transformation output, and demand. |
| LEAP unmet requirements | LEAP is not meeting all demand. | Check production, transformation output, and capacity limits or investigate further as it could be due to a mistakenly set parameter, or LEAP system issue/bug. |

In the current documented setup, positive import gaps are especially important because they indicate cases where LEAP is importing more fuel than intended. The update pass does not rewrite demand to make that disappear; it changes supply-side settings so the same demand can be met with a smaller unexplained import gap.

## 4. Active mode: `capacity_unmet_iterative_balanced`

The documented active mode is:

```text
capacity_unmet_iterative_balanced
```

In this mode, the workflow uses the latest LEAP supply results and compares observed imports and exports with the expected reconciliation baseline.

The import gap is used as the main signal because it is the clearest indication that the current supply and transformation setup is not meeting demand in the way the baseline expects.

The documented allocation logic is:

1. Positive import gaps are allocated first to primary `Maximum Production` for primary fuels where this is allowed. If reserves are used for the primary fuel, the workflow also increases reserve levels by a corresponding amount, if necessary (it is unlikely reserves will be enacted on initialisation).
2. Remaining positive import gaps are allocated to eligible transformation processes using `Exogenous Capacity`.
3. Negative import gaps can be routed to extra exports, depending on settings.
4. In the current documented setup, exports are pinned to the 9th Outlook projections unless the relevant option is changed.

This means the workflow is mainly trying to answer:

> If LEAP is importing more than expected, where should extra domestic production or transformation output be added so the model can satisfy the same demand with less unexplained importing?

One important nuance: the workflow does not assume imports are always an error in the real-world sense. It uses the difference between expected and observed imports as a reconciliation signal. If your detailed interim or placeholder sectors change demand, fuel inputs, or transformation output, the next `results_update` pass should respond to those new values, but only by adjusting the supply-side levers that the workflow controls.

## 4a. The three run modes: `baseline_seed`, `results_update`, `patch_baseline_seeds`

`supply_reconciliation_workflow.py` runs in one of three modes. The first two are full runs of the supply/transformation/transfers pipeline, distinguished by `CAPACITY_UNMET_PASS_MODE`; the third bypasses that pipeline entirely and edits existing seed files in place.

| | `baseline_seed` | `results_update` | `patch_baseline_seeds` |
|---|---|---|---|
| Selected by | `CAPACITY_UNMET_PASS_MODE = "baseline_seed"` (`_PRESET_BASELINE_SEED`, ~line 670) | `CAPACITY_UNMET_PASS_MODE = "results_update"` (`_PRESET_RESULTS_UPDATE`, ~line 798) | `RUN_MODE = "patch_baseline_seeds"` (`_PRESET_PATCH_BASELINE_SEEDS`, ~line 775) |
| When to use it | First pass for an economy/scenario, before any LEAP run exists | Every pass after LEAP has been recalculated and re-exported | Fixing/refreshing one already-verified sub-module of an existing seed without re-running the whole pipeline |
| What it reads | ESTO/9th Outlook baseline only — no LEAP results yet | Real LEAP Energy Balance export (REF/TGT balance workbooks) | Existing `leap_import_baseline_seed_*.xlsx` files, plus (if `PATCH_RUN_WORKFLOW=True`) a fresh regen of the target module's source workbook |
| Imports | Zeroed on write, so LEAP's own recalculation reveals the true import gap (`RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT = True`) | Computed as the gap between observed LEAP imports/exports and the 9th/ESTO baseline | Untouched except within the patched module's own rows |
| Demand source | `USE_AGGREGATED_DEMAND_AS_DUMMY = True` — ESTO/9th aggregated demand stands in for LEAP demand results (single-economy runs only) | Same aggregated-demand toggles remain on in the current preset (still initialisation, not yet handed to per-sector demand models) | Not applicable — no demand recompute |
| Own-use/losses proxy | `OTHER_LOSS_OWN_USE_PROXY_STAGE = "first"` (ESTO/9th activity) | `OTHER_LOSS_OWN_USE_PROXY_STAGE = "second"` (LEAP-balance activity) | Only touched if `PATCH_MODULE` includes `"losses_own_use"`, in which case the patcher resolves the stage from the active pass config itself |
| Electricity/heat interim | `RUN_ELECTRICITY_HEAT_INTERIM = True` — generates the three placeholder power modules | `RUN_ELECTRICITY_HEAT_INTERIM = False` — assumes the real power model is in place | Only touched if `PATCH_MODULE` includes `"power_interim"` |
| Key settings unique to this mode | Demand-source and interim-power toggles above | Results-update readiness preflight (~line 991) must pass before running | `PATCH_MODULE`, `PATCH_ECONOMIES`, `PATCH_RUN_WORKFLOW` |
| Output | Full new baseline seed workbook set | Updated seed reflecting the latest gap-closing pass | The same seed files, with only the patched module's rows replaced |

**`patch_baseline_seeds` in detail.** When `RUN_MODE == "patch_baseline_seeds"`, `_run_with_config_inner()` skips `run_results_linked_transformation_supply_workflow` entirely and instead calls `codebase/functions/patch_baseline_seeds.py::run_patch()` once per module in `PATCH_MODULE`:

- **`PATCH_MODULE`** — a module name (or list of names) from `patch_baseline_seeds.MODULE_REGISTRY`. Patchable today: `"supply"`, `"transfers"`, `"power_interim"`, `"aggregated_demand"`, `"losses_own_use"` — all spot-verified against a full-run seed with zero row/expression diffs (see the "Audited 2026-07-XX" comment blocks above `_PRESET_PATCH_BASELINE_SEEDS`, ~lines 727-774, for the verification history). The transformation auto-regen sectors (`"oil_refineries"`, `"lng"`, `"hydrogen"`, `"gas_processing"`, `"coal_transformation"`, `"petrochemical"`, `"charcoal"`, `"biofuels"`, `"nonspecified_transformation"`, `"transformation"` — anything with `auto_sector_keys` set in `MODULE_REGISTRY`) are gated: `run_patch()` raises `NotImplementedError` for them, because the simplified auto-regen path was found to change process-efficiency and auxiliary-fuel expressions relative to a genuine full run (`patch_baseline_seeds.py:1024-1032`). Refresh those sectors via a full `baseline_seed`/`results_update` run instead.
- **`PATCH_ECONOMIES`** — `None` patches every economy found in the baseline-seed directory; otherwise a list of economy tokens (e.g. `["20_USA", "01_AUS"]`) limits scope.
- **`PATCH_RUN_WORKFLOW`** — `True` (default) re-runs the module's upstream source workflow fresh before patching, so workbook-based modules (`power_interim`, `transfers`, `aggregated_demand`, `supply`, `losses_own_use`) always patch from current data rather than whatever happens to be on disk. Set `False` only when you deliberately want to patch from already-generated workbooks.
- The patcher still crosses the same F2 emit-boundary validator (`prepare_seed_rows_for_write`) as a full run — see [4e](#4e-checks-and-validation-link-to-the-check-registry).

## 4b. Module and production growth caps (upper limits)

When the allocator adds output to close a positive import gap, two configuration
dicts in `codebase/supply_reconciliation_config.py` cap how far each lever may
grow:

- `CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS` — the ceiling on transformation
  module growth (`Exogenous Capacity`).
- `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS` — the ceiling on primary production
  growth (`Maximum Production`).

Both are keyed `economy -> scenario ("reference" | "target") -> {name: cap}`. The
`reference` and `target` sub-dicts are independent on purpose: they govern
different 9th Outlook scenarios, so their ceilings are free to diverge (today
they happen to hold the same policy, but nothing requires that).

Caps are written with self-documenting sentinels rather than raw numbers:

| Sentinel | Effect |
| --- | --- |
| `KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT` | Lock at base-year (ESTO baseline) output — no growth. |
| `KEEP_PRODUCTION_AT_BASE_YEAR` | Lock production at the base-year constrained level. |
| `INCREASE_BY_PCT(p)` / `INCREASE_PRODUCTION_BY_PCT(p)` | Allow up to `p`% above base year. |
| `DECREASE_BY_PCT(p)` / `DECREASE_PRODUCTION_BY_PCT(p)` | Cap at `(1 - p/100)` of base year. |
| `DECREASE_TO_ZERO` / `DECREASE_PRODUCTION_TO_ZERO` | No headroom at all. |
| `SET_CAP_TO(v)` / `SET_PRODUCTION_CAP_TO(v)` | Explicit numeric ceiling. |
| `UNLIMITED` / `UNLIMITED_PRODUCTION` | No cap (same effect as omitting the entry). |

Resolution semantics that matter when reading results:

- A module/product **absent** from the dict, or set to `UNLIMITED`, has **no
  cap** — it can grow without limit to absorb a gap. An economy that is not a
  key in the dict is therefore fully unconstrained.
- Because `UNLIMITED` == absent, the functional content of a block is only its
  *non-unlimited* entries. `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS` is currently
  a scaffold of `UNLIMITED_PRODUCTION` entries (a no-op that lists which products
  *could* be capped later); the real constraint today lives in the module dict.

### Fixed-technology modules locked at base-year output

The following legacy / fixed-technology transformation modules are locked at
base-year output (`KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT`), so the
gap-filler may not expand them to close a shortfall — a residual gap spills to
the next lever (imports fallback) instead:

- Blast furnaces
- BKB and PB plants
- Charcoal processing
- Coke ovens
- Gas works plants
- Liquefaction coal to oil
- Natural gas blending plants
- Non-specified transformation
- Patent fuel plants
- Petrochemical industry
- Refinery and blending transfers
- Transfers unallocated
- Upstream liquids transfers

All other modules are allowed to grow freely (`UNLIMITED`). See decision
`INIT-007` in `docs/special_rules_and_design_decisions.md` for why these modules
are locked and the policy for applying the lock across all economies.

Note: LEAP uses no hyphens in module names. Config keys must match exactly —
`"Non specified transformation"` (no hyphen) is the correct key; a hyphenated
variant will never match and silently acts as dead code.

**Verified 2026-07-16:** `codebase/supply_reconciliation_config.py` contains
**only** the no-hyphen key `"Non specified transformation"` — a `grep` for both
the hyphenated and non-hyphenated strings across the file finds zero matches
for `"Non-specified transformation"`. It always appears in the locked
(`KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT`) group, both for
`reference` and `target` (`supply_reconciliation_config.py:641`, `:669`), and
also in the legacy fallback reset list (`:857`). There is **no** hyphenated
duplicate entry anywhere in the file, so this is not a stray-typo/duplicate-key
bug — it is a single, consistently-spelled, consistently-locked key. Any
paraphrase suggesting the hyphenated and non-hyphenated forms are two distinct,
differently-capped keys is incorrect as of this file; treat the warning above
(hyphenated variants are dead code if ever introduced) as the operative risk,
not an existing bug.

## 4c. Other settings with real operational impact

These settings are not part of the mode presets above, but each has a real, easy-to-get-wrong effect on results. The terse code-reference bullets in [18](#18-code-reference) restate what each setting does; this section explains what breaks if it is set wrong.

- **`CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY`** (`"imports_fallback"` default | `"fail"` | `"track_only"`). This is what happens once neither production headroom nor transformation capacity can close a positive import gap. `"imports_fallback"` is the normal setting — the residual quietly becomes an import, which is exactly the diagnostic signal the next pass is meant to react to. `"fail"` raises immediately instead, which is useful when you are debugging why a gap won't close and want the run to stop the moment it hits the wall, rather than silently absorbing it into imports and moving on. `"track_only"` records the residual in the CSV/JSON diagnostics but takes no allocation action at all — leaving the underlying LEAP branch untouched. Leaving `"track_only"` set during a normal production run is the failure mode to watch for: gaps will look "resolved" in the reconciliation table's bookkeeping sense while the actual LEAP branch never received a value, so nothing in LEAP changes and the same gap reappears next pass with no visible explanation unless you specifically check for `track_only` residuals.

- **`CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS`** (`True` by default). When `True`, a negative import gap (LEAP importing less than expected) is never converted into extra exports — exports stay pinned at the 9th Outlook projection regardless of how large the negative gap is. If this is left `True` when it shouldn't be, negative gaps that should legitimately become exports (e.g. genuine surplus production) instead sit unresolved or get absorbed elsewhere, understating exports relative to what the model is actually producing. If it is set to `False` without meaning to, negative gaps will start silently inflating exports pass over pass, which can look like a plausible trend but is actually an artefact of this switch rather than a genuine trade signal — always check this setting first when an export series looks like it's drifting upward for no obvious reason.

- **`CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS`** (currently `{"08.01 Natural gas"}`). This is a product-level switch, not a module-level one: for a listed product, the allocator skips the transformation lever entirely and goes straight from production headroom to the unresolved-positive policy. This exists so that, for a primary fuel like natural gas, a gap is never closed by growing a downstream transformation module (e.g. LNG regasification) when physically the gap should be closed by the well (production) or left as an explicit import/unresolved signal. Getting this wrong in either direction is a real bug: omitting a fuel that should be here lets transformation capacity silently substitute for production growth (masking a production-side problem behind an implausible transformation build-out); adding a fuel that shouldn't be here removes a legitimate transformation-side lever and can push otherwise-closeable gaps straight to the unresolved policy.

- **Module/production growth caps** (`CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS` / `..._PRODUCTION_UPPER_LIMITS`, see [4b](#4b-module-and-production-growth-caps-upper-limits)). The `KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT` sentinel is doing real work for legacy/fixed-technology modules: it is the mechanism that prevents the gap-filler from "solving" a shortfall by inventing implausible growth in a module that should not be expanding (e.g. blast furnaces, coke ovens). If a module is wrongly left `UNLIMITED` when it should be locked, gaps will close on paper by expanding a technology that has no real capacity to grow, and that inflated capacity then persists across passes via the cumulative state file. If a module is wrongly locked when it should be `UNLIMITED`, legitimate growth is blocked and the residual spills to the imports-fallback lever instead, showing up as an import gap that looks like a production/transformation shortfall but is actually just a cap that needs relaxing.

- **Aggregated-demand toggles** (`USE_AGGREGATED_DEMAND_AS_DUMMY`, `AGGREGATED_DEMAND_EXCLUDED_SECTORS`, `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES` — all set together in the `baseline_seed`/`results_update` presets, ~lines 681-713 and ~809-831). `USE_AGGREGATED_DEMAND_AS_DUMMY=True` substitutes ESTO/9th aggregated demand totals for LEAP balance-export demand, and is documented as **single-economy runs only** — leaving it `True` for a multi-economy run risks mixing an aggregated proxy that wasn't built per-economy into a run that expects per-economy demand, producing wrong or misleading totals rather than an outright crash. `AGGREGATED_DEMAND_EXCLUDED_SECTORS` must be kept in sync with whichever sectors already have a live, direct demand model — forgetting to add a sector here once its own model goes live double-counts that sector's demand (once via the aggregated dummy, once via the real model); conversely excluding a sector that has no live model yet leaves a demand hole. `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES=True` writes per-sector branches (`Demand\All demand aggregated\{SectorLabel}\{fuel}`) instead of the flat branch — turning this on when LEAP doesn't actually have those per-sector sub-branches yet will write rows LEAP cannot resolve, so this should only be flipped once the LEAP area has those branches prepared.

- **`RUN_ELECTRICITY_HEAT_INTERIM`**. When `True`, three placeholder power modules (Electricity interim, CHP interim, Heat plant interim) are generated via `electricity_heat_interim_workflow.py` so the reconciliation loop has *something* representing power before the real power model exists. Leaving this `True` after the real power model is in place double-writes power-sector branches that the real model now owns, creating a conflict between placeholder and real values; leaving it `False` too early (before the real power model exists) leaves the power branches with no representation at all during supply reconciliation, which can distort the transformation-fuel balance the reconciliation loop is solving against, since power transformation consumes and produces fuels other sectors depend on.

## 4d. Major sub-workflows this file drives

`supply_reconciliation_workflow.py` is an orchestrator — most of the actual computation happens in sub-workflows it calls, configures, and sequences. This section summarizes what each is responsible for and anything non-obvious about how this file drives it.

- **`other_loss_own_use_proxy_workflow.py`** — produces the `Demand\Other losses and own use` branches: own-use and losses associated with supply/transformation processes that cannot be attributed to a specific module's auxiliary fuel use. `supply_reconciliation_workflow.py` selects its activity source via `OTHER_LOSS_OWN_USE_PROXY_STAGE`: `"first"` (ESTO/9th activity) in `baseline_seed`, `"second"` (LEAP-balance activity, read back from the real export) in `results_update`. Both stages are still "initialisation" in the sense that target energy is matched rather than anchored-intensity modelled. In `patch_baseline_seeds` mode this workflow is only invoked if `PATCH_MODULE` includes `"losses_own_use"`, in which case the patcher resolves the stage from the active pass config and reports which mode was actually used.

- **`electricity_heat_interim_workflow.py`** — builds the three interim power placeholder modules (Electricity interim, CHP interim, Heat plant interim) from signed `09_*` transformation rows only (positive = output, negative = feedstock; `18_*`/`19_*` accounting-sector rows are prohibited as inputs). Driven by `RUN_ELECTRICITY_HEAT_INTERIM`, on in `baseline_seed` and off in `results_update` once the real power model exists. In `patch_baseline_seeds` mode it's only touched if `PATCH_MODULE` includes `"power_interim"`.

- **`transformation_workflow.py`** — produces the "other transformation" sector data (LNG regasification, gas liquefaction, coal transformation modules, coke ovens, blast furnaces, patent fuel plants, non-specified transformation, etc.), including exogenous capacity and process efficiency, from ESTO historical relationships and 9th Outlook projections. Its projection conservation check (F5 — see [4e](#4e-checks-and-validation-link-to-the-check-registry)) is no longer self-bypassing: the hand-rolled catch-and-retry was replaced by the repo-wide `functions/conservation_policy.py`, which warns by default and raises when `CONSERVATION_FAILURES_ARE_ERRORS=True`. The check always runs; only the severity is policy. A conservation failure still lets the non-strict allocation reach the output by default, so **read the `[WARN] … strict conservation check failed` line rather than treating a green run as proof it held**. This is the module gated out of `patch_baseline_seeds` for its auto-regen sectors (see [4a](#4a-the-three-run-modes-baseline_seed-results_update-patch_baseline_seeds)) — its output has not been reproduced row-for-row through the simplified patch path.

- **`transfers_workflow.py`** — produces transfers data for the upstream liquids, refinery and blending, and transfers-unallocated modules. Unlike the other transformation sectors, this module's patch path has been verified end-to-end (see [4a](#4a-the-three-run-modes-baseline_seed-results_update-patch_baseline_seeds)): a patched seed reproduces the full workflow's transfer rows exactly, so `"transfers"` is one of the safely patchable `PATCH_MODULE` values.

- **`supply_data_pipeline`** — assembles the supply/resources side (domestic production, imports, exports) that `supply_reconciliation_workflow.py` reconciles against, and is the source of `EXPORT_FINAL_YEAR`/related settings the workflow clamps against `LEAP_IMPORT_MAX_YEAR` at run start. It underlies the `"supply"` patch module (verified end-to-end for 20_USA via `supply_workflow.assemble_supply_workbooks`).

- **`patch_baseline_seeds.py`** — not a computation workflow in its own right but the alternate orchestration path selected by `RUN_MODE = "patch_baseline_seeds"`. It re-runs (optionally) a single named module's own source workflow, strips that module's existing rows from the current baseline seed, and splices in freshly generated rows — going through the same `prepare_seed_rows_for_write` emit boundary as a full run. See [4a](#4a-the-three-run-modes-baseline_seed-results_update-patch_baseline_seeds) for the gating rules (which modules are safely patchable vs. gated).

## 4e. Checks and validation (link to the check registry)

`docs/check_registry.md` is the canonical directory of every readiness/validation/fill mechanism across the initialisation codebase, organized into five families. It intentionally does not want its tables duplicated elsewhere, so this section only summarizes the five families and calls out which of them `supply_reconciliation_workflow.py` itself triggers or crosses — see that document for full detail.

| Family | One-line summary |
|---|---|
| **F1** Enumeration: gap-fill / reset | Invents missing rows (gap-fill, e.g. zeroed aux-fuel rows) or overwrites existing rows (reset, e.g. zeroing supply/transformation import-export before a fresh baseline-seed pass) |
| **F2** Artifact invariants | Structural rules the emitted rows must satisfy — shares, IDs, coverage, capacity gate — enforced once, at the `prepare_seed_rows_for_write` emit boundary |
| **F3** LEAP-import readiness | The workbook will actually import into LEAP cleanly (region present, scenarios present, sheet shape correct) |
| **F4** Preflight | Inputs are present and current enough to compute at all, before spending the time to compute |
| **F5** Conservation / numeric | Energy balances and activity/target totals actually reconcile, as a numeric (not structural) property |

Checks specifically exercised from within this file:

- **F4 — results-update readiness check** (`supply_reconciliation_workflow.py`, `_run_results_update_readiness_check`, ~lines 991-1032). Runs only when `CAPACITY_UNMET_PASS_MODE == "results_update"`; for every economy it confirms the REF/TGT LEAP balance export workbooks exist and, if `REQUIRE_LEVEL2_BALANCE_EXPORT_DETAIL` is set, that they were exported at least at Level 2 detail (see [9b](#9b-how-to-export-leap-energy-balance-results)). This is the check registry's "results-update readiness" F4 row and the "level-2 export readiness" F4 row.
- **F4 — the two compressed preflights** (`run_preflight_compressed_projection`, `run_preflight_compressed_results_update`), run from `_run_with_config_locked()` per the `RUN_PREFLIGHT_COMPRESSED_*` toggles — see [9c](#9c-fast-preflight-checks).
- **F2 — the emit boundary**, `prepare_seed_rows_for_write`, is crossed both by a full-run seed assembly and by the patcher (`patch_baseline_seeds.py:940`-ish, per the check registry's F2 table) — meaning both `baseline_seed`/`results_update` runs and `patch_baseline_seeds` runs get the same share/ID/coverage validation, which is why the patcher is trusted to reproduce full-run rows exactly for its verified modules.
- **F5 — the self-bypassing projection strict-conservation check** lives inside `transformation_workflow.py` (called from this file's transformation step) — see [4d](#4d-major-sub-workflows-this-file-drives) above. Its silent-retry-non-strict behaviour is a known gap flagged in the check registry's "Known hotspots" section, not something this workflow currently guards against.
- **F1 — the reset toggle this file owns directly**: `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT`, `True` in the `baseline_seed` preset and `False` in `results_update`, which is the `reset_supply_and_transformation_import_export_to_zero` row in the registry's F1 table.

For rule-level detail on any SEED-C0xx finding these checks can produce, use `docs/baseline_seed_rule_inventory.md` and section [17](#17-how-to-use-the-rule-findings-files) above, not this section.

## 5. Main LEAP variables affected

The workflow supports the same control variables used in the modeller guide.

| LEAP variable | Used for | Why the script adjusts or prepares it |
|---|---|---|
| `Maximum Production` | Primary resources | Controls domestic production and prevents unlimited over-production. |
| `Exogenous Capacity` | Transformation processes | Controls how much secondary fuel can be produced by transformation. |
| Exports | Resources | Can absorb surplus or preserve intended trade assumptions. |
| Imports | Resources | Usually treated as a residual signal rather than the first thing to hard-code. |
| Reserves | Primary resources | Can be used to increase domestic production if the primary fuel is a reserve-based resource. NOT IMPLEMENTED YET |

## 6. Why production and transformation are linked

Production and transformation are linked because both can satisfy fuel requirements.

Example:

- Natural gas demand can be met by indigenous natural gas production.
- Natural gas can also be produced by LNG regasification.
- LNG regasification requires LNG.
- LNG may come from imports or from natural gas liquefaction.

So a change in one part of the chain can change the apparent need for another part of the chain.

This is why the workflow should not treat supply and transformation independently. It needs to consider both domestic production and transformation capacity when trying to reduce import/export gaps.

## 7. Expected inputs

The exact file names and paths should be checked against the current script. Conceptually, the workflow needs:

1. **LEAP results exports**  
   Energy balance outputs exported from LEAP after recalculation.

2. **9th Outlook / ESTO supply projection baseline**  
   Expected domestic production, imports, exports, and supply-side totals.

3. **Transformation input/output mappings**  
   Information showing which transformation modules produce and consume which fuels. The canonical definitions of how LEAP branches, ESTO flows, and 9th Outlook sectors correspond are maintained in `leap_mappings` — see `leap_mappings/docs/mappings_system.md`. Workflow scripts should use those mappings rather than defining fuel or sector relationships internally.

4. **Losses and own-use data**  
   Energy-sector own-use and losses that affect upstream requirements.

5. **Production and capacity caps**  
   Optional per-module and per-product limits to prevent unrealistic production or transformation output. These are configured in `codebase/supply_reconciliation_config.py`.

6. **LEAP import workbook template or structure**  
   The workbook format needed to import updated expressions back into LEAP.

### Source data files

Three source data files underpin the mapping and comparison steps used by this workflow:

- **`data/00APEC_2025_low_with_subtotals.csv`** — ESTO historical energy balance for all 21 APEC member economies. Covers 1990 to the latest available year, which is always two years behind the release year. Rows are structured as flow/product pairs. Subtotals are flagged with a single `is_subtotal` boolean column. This is the canonical ESTO reference for balance comparisons.

- **`data/merged_file_energy_ALL_20251106.csv`** — 9th Outlook projection data for all 21 APEC member economies and both scenarios (reference and target). Covers 1980–2070. Sector and fuel codes use underscores (e.g. `09_06_gas_processing_plants`). Subtotals are tracked with two columns: `subtotal_layout` marks aggregate rows in historical years (pre-2022), and `subtotal_results` marks aggregate rows generated by the 9th Outlook model in projection years. This is the primary source for balance comparisons and supply baseline targets.

- **`data/merged_file_energy_00_APEC_20251106.csv`** — A subset of the above containing only the APEC aggregate economy (`00_APEC`) in the reference scenario. Useful for aggregate-level checks without the full dataset volume.

The date suffix in the 9th Outlook filenames (e.g. `20251106`) records when the file was produced. When a new 9th Outlook vintage is released both files should be updated together and the suffix updated to match.

### Per-economy LEAP export templates

`data/leap_export_templates/` is the structural reference used to turn generated
values into LEAP-importable rows. The retired `data/full model export.xlsx` is
not a runtime dependency. Each real economy should resolve its own
`leap_export_template <economy>.xlsx`; the USA template is only a documented
fallback for aggregate/no-template cases. The templates supply branch, variable,
scenario, and region IDs; validate branch existence and metadata; identify
Resources roots and transformation fuel leaves; and define reset/zeroing scope.
They are not the source of generated energy values.

Refresh the affected economy's template after a structural LEAP-area change: a
branch, process, module, output/feedstock/auxiliary-fuel leaf, variable,
scenario, or Resources root is added, removed, renamed, moved, or deleted and
recreated. A data-value or projection update with no LEAP structure change does
not normally require a refresh. Preserve the `Export` sheet, LEAP
preamble/header layout, all relevant branches and variables, Current
Accounts/Reference/Target scenarios, ID columns, metadata, and hierarchy
columns. Do not copy IDs between economies; a missing branch must be migrated
in the real LEAP area and re-exported, not fabricated in Python.

Treat `-1` as an unresolved-ID sentinel, not a valid ordinary branch ID. Nonzero missing-ID rows cannot be relied on to import. Zero missing-ID rows also require review when they are intended to clear an existing value. Resolve duplicate `Branch Path + Variable + Scenario + Region` keys before share-total checks or import; conflicting duplicate expressions are invalid even if one duplicate is currently skipped because its ID is `-1`. See `data/README.md` and `CROSS-001` in `docs/special_rules_and_design_decisions.md` for the complete lifecycle and validation rule.

## 8. Expected outputs

The exact output file names should be checked against the current script. Conceptually, the workflow should produce:

1. **Updated LEAP import workbook**  
   A workbook containing revised `Maximum Production`, `Exogenous Capacity`, exports, or other relevant values.

2. **Reconciliation table**  
   A table showing observed LEAP results, expected supply values, calculated gaps, and allocated adjustments.

3. **Diagnostic outputs**  
   Tables that help identify fuels, years, and scenarios where gaps remain large.

4. **Optional logs/checks**  
   Information showing whether caps, eligibility rules, or allocation settings affected the result.

## 9. Manual run loop

The workflow currently relies on a manual LEAP import/recalculate/export loop.

```text
1. Run supply_reconciliation_workflow.py.
2. Open the generated LEAP import workbook.
3. Import the workbook into the correct LEAP area.
4. Recalculate LEAP.
5. Export the LEAP energy balance results again.
6. Re-run supply_reconciliation_workflow.py.
7. Repeat until import/export gaps are small and explainable.
```

This loop is needed because the script cannot reliably force LEAP to recalculate and export results automatically.

## 9b. How to export LEAP energy balance results

Exporting results is required before every reconciliation pass. Results must be re-exported after each LEAP recalculation before re-running the workflow.

1. Open LEAP and ensure the area has been fully recalculated.
2. Navigate to the **Results** view and select **Energy Balance**.
3. Set **Units** to **Petajoules**.
4. Set the **Detail** level:

   | Level | What is included | When to use |
   |---|---|---|
   | Level 1 | Balance totals; no transformation activity by process | Not usually sufficient for reconciliation |
   | Level 2 | Sector-level demand; transformation by module | Sufficient for most reconciliation passes |
   | Level 4 | All detail including demand sub-sector end-uses | Use when you also need detailed demand sector outputs |

   Malaysia (`10_MAS`) is the main exception: it needs Level 2 balance detail when running `results_update`, because the hydrogen transformation sector can use both `Electrolysers` and `SMR with CCS` and the workflow checks for those process rows explicitly.

5. Click the **Excel symbol** and select **All** to export all results.
6. Wait for the export to complete. A full area at Level 2 covering 2022–2060 typically takes **3–4 hours**. Higher detail levels or more years will take longer. This is best run on a spare machine or out of hours.
7. Place the exported file in the directory expected by `supply_reconciliation_workflow.py` — check the script's input path settings to confirm the correct location.

> If you are exporting for the first time, choose Level 2 unless there is a specific reason to need Level 4. Level 4 significantly increases export time and file size.

## 9c. Fast preflight checks

The full `baseline_seed` and `results_update` runs are slow: every economy runs the
whole supply/transformation/transfers pipeline across all projection years, and a
full LEAP energy-balance export alone typically takes **3–4 hours** (§9b). A code or
data regression that only surfaces late in a full run is expensive to discover. Two
complementary *compressed* preflights exercise most of the major code paths in a few
minutes each, so run them before committing to the long runs. **Neither preflight
performs any LEAP import, branch creation/fill, or live LEAP results scraping**, and
both isolate all state and outputs from production.

### The two preflights

**1. Compressed projection preflight** (`run_preflight_compressed_projection`)

A fast approximation of the **baseline-seed** integration path.

- Uses `00_APEC` and the configured ESTO base year plus one compressed future year
  (`BASE_YEAR + 1`), where the future year is the signed sum of every 9th Outlook
  projection year and scenario.
- Exercises source mappings, transformations, transfers, supply workflows, workbook
  construction, and future-only category coverage.
- Uses projection-only demand; does **not** read real LEAP balance exports and does
  **not** validate real LEAP results or per-economy/year behaviour.

**2. Compressed results-update preflight** (`run_preflight_compressed_results_update`)

A fast approximation of the **results-update** integration path.

- Uses `20_USA` and the base year plus one compressed future year.
- Reads temporary **reduced** LEAP REF/TGT balance workbooks built from the real
  `20_USA` balance-export structure: `EBal|<base>` copied verbatim, and a synthetic
  `EBal|<base+1>` that is the signed sum of every post-base-year source sheet (the
  REF synthetic sheet is built only from REF, the TGT only from TGT — and the Target
  workbook not having a literal `EBal|2023` does not matter because the synthetic
  sheet is constructed from all post-base-year sheets).
- Exercises real LEAP balance conversion, balance-demand mapping, results-update
  demand sourcing, issue classification, and downstream reconciliation wiring.
- Does **not** verify individual-year trajectories and does **not** replace a
  complete results-update run.

> The results-update preflight uses the *existing* real `20_USA` balance-export
> structure, **not** a newly recalculated LEAP model corresponding to the compressed
> inputs. It is therefore a strong structural and integration test, not a numerical
> reproduction of a genuine two-year LEAP run.

### Recommended order before full runs

```text
Compressed projection preflight
→ compressed results-update preflight
→ full baseline_seed when needed
→ import / recalculate / export in LEAP
→ full results_update
```

### Notebook toggles

In `supply_reconciliation_workflow.py`:

| Toggle | Default | Effect |
|---|---|---|
| `RUN_PREFLIGHT_COMPRESSED_PROJECTION` | `True` | Run the projection preflight before the main run |
| `PREFLIGHT_COMPRESSED_PROJECTION_ONLY` | `False` | Stop after the preflights (skip the main run) |
| `PREFLIGHT_COMPRESSED_FAIL_FAST` | `False` | Raise immediately if the projection preflight fails |
| `RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE` | `False` | Run the results-update preflight before the main run |
| `PREFLIGHT_COMPRESSED_RESULTS_UPDATE_ONLY` | `False` | Stop after the preflights (skip the main run) |
| `PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST` | `False` | Raise immediately if the results-update preflight fails |
| `TEST_HORIZON_BASE_YEAR_PLUS_ONE` | `False` | Run the selected real main-workflow scope for `BASE_YEAR` and `BASE_YEAR + 1` only |

Either preflight can be enabled independently, run in preflight-only mode, and be
configured fail-fast or warning-and-continue. The results-update preflight is off by
default so it does not lengthen every run; enable it (ideally right before a full
`results_update`) when you want the balance-export integration check.

### Two-year main-workflow iteration mode

`TEST_HORIZON_BASE_YEAR_PLUS_ONE=True` is a separate, notebook-only iteration aid.
It runs the selected real economies, scenarios, source files, and normal output
layout, but temporarily limits supply, transformation, demand, balance-table, and
baseline-seed validation horizons to `BASE_YEAR` through `BASE_YEAR + 1`. The
workflow restores its module configuration afterwards, including after an error.

Use a unique `RUN_OUTPUT_LABEL` for this mode and set the toggle back to `False`
before a normal run. It is useful for quickly catching integration and workbook
construction failures, but it is **not** a sparse final-year mode and it must never
replace the final full-horizon verification (including compressed projection
preflight, which still exercises the `00_APEC` aggregate sentinel path).

### Output locations

Each preflight writes only under its own isolated root; production outputs and the
production source workbooks/iterative state are never touched:

- Projection: `outputs/leap_exports/supply_reconciliation/baseline_seed/preflight_compressed_projection/`
- Results-update: `outputs/leap_exports/supply_reconciliation/results_update/preflight_compressed_results_update/`
  (temporary reduced REF/TGT workbooks under `runtime/reduced_balance_workbooks/`,
  compressed sources under `runtime/compressed_sources/`, and the balance-demand
  issue report under `checks/`). The results-update preflight always writes a
  deterministic issue report — all issue rows if any exist, otherwise a header-only
  CSV showing zero issues — and prints a compact summary (total, actionable, ignored,
  counts by reason, unique sector/fuel keys, `Total` fuel rows, and unresolved rows).

### How failures affect continuation

With `*_FAIL_FAST = False` (default), a failing preflight prints a warning, the main
run still proceeds, and the deferred preflight error is re-raised after the main run
completes so it cannot be silently ignored. With `*_FAIL_FAST = True` (or either
`*_ONLY` toggle set), a failing preflight raises immediately. A failed preflight
always restores normal state. Unresolved demand-relevant leaf mapping rows keep the
results-update preflight failing whenever `BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES` is
`True`.

> Together these are the recommended fast integration checks before the long-running
> full baseline-seed and results-update runs. They verify most major code paths, but
> they do **not** prove every economy, year, economy-specific rule, LEAP import, or
> iterative convergence behaviour.

## 10. Why the LEAP API is not used as the main method

The preferred workflow is still the workbook import/export method. Direct LEAP API automation has been investigated, but the API has been unreliable enough that it can create difficult-to-diagnose problems.

For now, the safer process is:

- use Python to prepare workbooks;
- import the workbooks manually into LEAP;
- recalculate LEAP manually;
- export results manually;
- use Python to process the exported results.

This is slower, but more transparent and less risky.

## 11. How many iterations are expected

A single run will usually not be enough.

For each economy, expect several passes:

- the first pass identifies large gaps;
- the second pass checks whether the first set of adjustments worked;
- later passes reduce remaining gaps or reveal secondary issues caused by transformation interactions;
- the final pass should leave only small residuals that can be allocated deliberately, usually to imports or another clearly documented balancing item.

This process can take a long time because each pass requires LEAP recalculation and results export. In iterative capacity-unmet modes, each pass summary now reports convergence metrics such as the current gap, percent closure, and trend. A running CSV is also appended under the active pass subtree at `outputs/leap_exports/supply_reconciliation/<pass_mode>/supporting_files/runtime/capacity_unmet_convergence.csv`.

## Concurrent runs

Full workbook-mode runs can proceed at the same time when their economy scopes do not overlap. The workflow automatically creates a run label from its pass type, economy scope, and scenarios (for example, `UPDATE_20_USA_TGT_REF_CA`) and writes its workbooks, balance tables, diagnostics, runtime state, timing, and loss/own-use proxy artifacts below that labelled run folder.

Each economy has a cross-process lock. A second run that includes an economy already being written stops with a clear error rather than overwriting files. Therefore, it is safe to run a baseline seed for one economy while patching or updating another economy, but it is not safe to run a patch, baseline seed, or results-update pass concurrently for the same economy.

Keep `RUN_OUTPUT_LABEL = "auto"` for the normal isolated layout. A literal label is allowed for deliberate manual grouping. Do not run LEAP API imports concurrently: the protection covers workbook files and workflow state, not concurrent writes to the same LEAP application or area.

## 12. How to interpret the reconciliation results

### Large positive import gap

LEAP is importing more than expected.

Check:

- Is primary `Maximum Production` too low?
- Is transformation `Exogenous Capacity` too low?
- Is a transformation module using `ImportToMeetShortfall` where it should use `RequirementsRemainUnmet`? If a module resolves shortfalls through imports before domestic production or other transformation routes have been used, changing the shortfall rule may allow the requirement to pass upstream to the intended supply route instead. See [LEAP balancing rules](#12b-leap-balancing-rules).
- Is the transformation module ordering correct? A module appearing too early in the order may import at that stage rather than passing the requirement upstream. See [LEAP balancing rules](#12b-leap-balancing-rules).
- Is a fuel mapping missing or wrong?

### Large negative import gap

LEAP is importing less than expected.

Check:

- Is domestic production too high?
- Is transformation capacity too high?
- Is expected import being replaced by transformation output?
- Should the difference become exports? If a module is set to `SurplusAvailable`, excess output stays in the domestic pool and offsets other supply — it will not automatically become exports. If the surplus should be exported, check whether `SurplusExported` is appropriate for that module.
- Is the 9th Outlook projection still the right target after demand changes?

### Large export gap

Check:

- Is a transformation module creating surplus co-product output?
- Is `SurplusExported` set on a module that is also producing more than expected? Combined with planned exports in Resources, `SurplusExported` can push total exports above the intended level. Check the two sources separately.
- Are output shares plausible?
- Are exports set in Resources higher than intended?

### Unmet requirements

Check:

- Is production or capacity capped too tightly?
- Is `RequirementsRemainUnmet` set on a transformation module but the corresponding Resources branch is not set to `MeetWithImports`? The usual pattern is transformation modules use `RequirementsRemainUnmet` and Resources uses `MeetWithImports` — if the Resources side is not set correctly, the unmet requirement may not be resolved at all.
- Should the unmet requirement be resolved by production, transformation, or imports?
- Is the module order correct?

## 12b. LEAP balancing rules

The way LEAP resolves fuel requirements depends on shortfall rules, surplus rules, module ordering, and Resources settings working together. Understanding these is essential for diagnosing gaps correctly. Unexpected imports, exports, or unmet requirements are almost always a signal that one of these settings needs review — not simply a sign that trade assumptions need hard-coding.

### Shortfall rules

The shortfall rule on a transformation module controls what happens when the module cannot produce enough output to meet the requirement it sees.

**`RequirementsRemainUnmet` — use this as the default.** This allows the unresolved requirement to pass upstream rather than being immediately satisfied through imports at the transformation module. In practice this means primary production in Resources has a chance to supply the remaining requirement. Despite the name, this setting does not leave demand permanently unsatisfied — it depends on the Resources branch being set to `MeetWithImports` to close the final gap.

**`ImportToMeetShortfall` — use sparingly.** This allows a module to resolve its own shortfall through imports. It is only appropriate where a module is explicitly the intended import-backed supply route for a fuel. There should normally be at most one such module per fuel, to avoid competing import pathways. Using `ImportToMeetShortfall` too broadly is the most common cause of unexpected imports — the module imports before domestic production or another intended supply route has been tried.

> **Worked example — Natural Gas imports despite unlimited reserves.** In a test case, Natural Gas was being imported even though Base Year Reserves were set to Unlimited and import costs were set very high. The cause was transformation ordering and shortfall rules, not the Resources branch. Electricity generation required a very large Natural Gas input. At that point only a small amount of Natural Gas had been made available through earlier transformation steps. With `ImportToMeetShortfall` set on upstream modules, LEAP imported the remaining shortfall instead of using domestic production. Changing those modules to `RequirementsRemainUnmet` caused LEAP to pass the requirement back to Resources, and domestic production supplied it instead. The lesson: for fuels that can be supplied by domestic production, `ImportToMeetShortfall` on transformation modules can cause imports to appear even when domestic supply is abundant.

### Surplus rules

The surplus rule controls what happens when a transformation module produces more output than is needed.

**`SurplusAvailable` — use this as the default.** Keeps excess output in the domestic fuel pool, where it can offset other domestic supply. This is the safest default because it does not hide oversupply or artificially inflate exports.

**`SurplusExported` — use only where surplus output is realistically exported.** This is often appropriate for refineries, where co-product surplus is commonly traded. For most other modules, surplus should remain in the domestic pool.

**Watch for combined export inflation.** If a module is set to `SurplusExported` and planned exports are also set in Resources for the same fuel, the two sources can combine to produce more total exports than intended. Check both separately when diagnosing a large export gap.

**`SurplusWasted` — use only where curtailment, flaring, or dumping needs to be explicitly represented.**

### Module ordering

LEAP calculates transformation modules in order. Modules closer to final demand should appear higher in the sequence; modules that produce feedstocks for other modules should appear lower. Note that in the LEAP interface, "higher in the order" means *lower* visually in the branch list.

A practical rule: if you do not want one module's shortfall to be met by another module, place the supplying module *after* it in the order. If ordering is wrong, LEAP may import at an early stage rather than passing the requirement upstream to the intended domestic supply route.

Ordering should always be checked together with shortfall rules, `Exogenous Capacity`, and Resources settings. Unexpected imports are often a combined ordering and shortfall problem, not a Resources problem.

### Resources and unmet requirements

**For tradeable fuels**, set the Resources `Unmet Requirements` branch to `MeetWithImports`. This makes Resources the final balancing point after domestic production and transformation have been applied.

**The standard pattern is:**

```text
Transformation modules  →  RequirementsRemainUnmet
Resources               →  MeetWithImports
```

This combination lets domestic production and transformation run first and leaves imports as the residual. Deviating from this pattern — especially by setting `ImportToMeetShortfall` in transformation modules — can cause imports to appear much earlier in the chain than intended.

**Avoid setting explicit import values.** Imports are usually the best diagnostic of whether production, capacity, exports, ordering, and shortfall settings are correct. Hard-coding imports early hides the underlying issue and will be overwritten on the next reconciliation pass anyway.

---

## 13. What not to do

Do not immediately fix every gap by hard-coding imports. That hides the modelling issue rather than solving it. They will also be overwritten on the next pass, so the modeller will not see whether the underlying issue was resolved.

Do not assume that every difference from the 9th Outlook is wrong. Some differences may be caused by improved demand modelling or by a better representation of transformation interactions.

Do not treat the script output as final without checking LEAP. The script suggests adjustments, but LEAP's recalculated balance is the source of truth for whether those adjustments worked.

The last two points raise the usefulness of checking results in the `leap_dashboard`. The dashboard helps identify whether script adjustments are working, whether remaining differences from ESTO or the 9th Outlook are deliberate or a modelling issue, and whether converging values look plausible over the projection period — for example, spotting if repeated iterations are pushing a fuel trend in an implausible direction.

Do not use the LEAP API for direct writes unless the team has explicitly decided that the API issues have been resolved.

## 14. Practical checklist before running

Before running the script:

- Confirm the LEAP area has been recalculated.
- Export the latest energy balance results.
- Confirm the expected supply baseline is up to date.
- Confirm the correct economy and scenario are selected in the script settings.
- Confirm any hard caps or override dictionaries are intentional.
- Confirm the surplus and shortfall rules in LEAP are set correctly.
- Confirm the output workbook will target the correct LEAP branch/variable structure.

## 15. Practical checklist after running

After running the script:

- Open the reconciliation outputs.
- Identify the largest remaining import/export gaps by fuel and year.
- Check whether the allocated adjustment went to the expected place.
- Check whether any cap prevented the expected allocation.
- Import the generated workbook into LEAP;
- Recalculate LEAP.
- Export the new balances.
- Compare whether gaps improved.
- consider using the `leap_dashboard` to check whether adjustments are working, whether remaining differences are deliberate, and whether converged values look plausible over the projection period.

## 16. When the process is finished

The process is finished when:

- base-year balances are aligned with ESTO;
- major projected supply, import, export, and transformation paths are plausible;
- remaining gaps are small or explainable;
- remaining residuals are deliberately assigned;
- there are no unexplained unmet requirements;
- the modeller can explain the main differences from the 9th Outlook.

The final model should be usable by other researchers without needing them to understand every detail of the reconciliation loop.

## 17. How to use the rule findings files

The baseline-seed validation step writes rule findings files that are meant to be read, filtered, and fixed. They are not just audit output. If a run fails late in the process, these files are usually the fastest way to find the exact branches, workbooks, and workflows that need attention.

The main location is:

- `outputs/leap_exports/supply_reconciliation/baseline_seed/preflight_compressed_projection/workbooks/supporting_files/baseline_seed_validation/`

For a specific economy, look for files named like:

- `combined_st_00_APEC_Target_Reference_Current_Accounts_rule_findings.csv`

The short `combined_st_...` stem is the per-economy combined seed workbook stem. The validation folder may also contain related helper files such as duplicate-group diagnostics and documented exclusions, depending on the run mode and what the validator needed to write.

### What the files mean

- `*_rule_findings.csv` is the main file to inspect first. It lists every rule hit, with one row per finding.
- `*_duplicate_groups.csv` groups logical duplicates that need attention together.
- `*_issue_groups.csv` groups downstream symptoms that share the same missing canonical branch root cause. This is the clearest file when `SEED-011` and `SEED-003`/`SEED-004`/`SEED-005` all point at the same branch.
- `*_documented_exclusions.csv` records rows that were explicitly excluded from blocking because a documented exception or ignore rule applied.
- `baseline_seed_*_consolidated_rule_findings.csv` combines the findings from all economies and producers into one run-level report.
- `baseline_seed_*_consolidated_issue_groups.csv` is the run-level grouped summary for the same root-cause cases.

The most useful columns are:

- `rule_id` - the validation rule that fired, such as `SEED-003`, `SEED-004`, `SEED-011`, or `SEED-012`.
- `blocking` - whether the finding prevents final import workbook creation.
- `branch` or `Branch Path` - the LEAP branch that needs attention.
- `variable` or `Variable` - the LEAP variable on that branch.
- `scenario` - `Current Accounts`, `Reference`, or `Target`.
- `region` - the economy code.
- `source_workflow` - the workflow that wrote the row, which tells you where to fix the source logic.
- `source_file` - the exact workbook that produced the row.
- `evidence` - the key clue used by the validator, such as the ID pair, duplicate signature, or missing producer path.
- `message` - the human-readable reason for the finding.

### How to triage them

Start with the consolidated report if you want the run-wide picture, then drop into the per-economy `*_rule_findings.csv` files for the actual fix work.

1. Filter to `blocking = True`.
2. Group by `rule_id` so you can see which rules dominate the failure.
3. Sort by `source_workflow` and `source_file` to find the upstream workbook that owns the problem.
4. Use `branch` and `variable` to locate the exact LEAP path.
5. If the problem is a duplicate, use the duplicate-group file rather than trying to fix rows one by one.
6. If the problem is coverage-related, check whether the workflow was expected to produce that economy or scenario at all.

For quick inspection in Excel or a notebook, the same pattern works well:

```python
#%%
import pandas as pd

path = r"C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\baseline_seed\preflight_compressed_projection\workbooks\supporting_files\baseline_seed_validation\combined_st_00_APEC_Target_Reference_Current_Accounts_rule_findings.csv"
df = pd.read_csv(path)

blocking = df[df["blocking"] == True]
top_rules = blocking.groupby("rule_id").size().sort_values(ascending=False)
top_sources = blocking.groupby(["source_workflow", "source_file"]).size().sort_values(ascending=False)
#%%
```

### Rule-specific guidance

`SEED-003` and `SEED-004` are the first place to look when a row is clearly on the right branch but still fails validation. They usually mean the workflow wrote a branch with missing canonical IDs, and the `source_workflow` / `source_file` columns tell you which generator produced it. `SEED-003` is the missing-ID case; `SEED-004` is the same row class when the expression is nonzero or unparseable, so it needs a source fix rather than a data patch.

`SEED-005` is the zero-expression version of the missing-ID problem. These rows often look harmless, but they still need review because they are usually reset rows or placeholders that must be traced back to the owning workflow.

`SEED-006`, `SEED-007`, and `SEED-008` are share-group rules. If these fire, the issue is usually not in the reconciliation step itself. It is normally in the workflow that assembled the output/process/feedstock share table. The useful clue is the `branch` plus the `source_workflow`, which points to the specific sector workflow that needs a logic fix.

`SEED-011` means the branch path is not present in the canonical full-model export. For these rows, do not start by editing the seed file. First confirm whether the branch should exist at all. If it should, the issue is usually an upstream model-structure gap or a naming mismatch. If it should not, the row belongs in the ignore or exclusion path instead.

`SEED-012` is a producer/economy coverage rule. It means a configured producer workflow did not provide a readable workbook for that economy. The `source_workflow` and `source_file` columns are the first check, but the real fix is usually to confirm whether that workflow is supposed to run for the economy and whether its output was produced in the normal location.

### Where to inspect the exact issue

The exact issue is usually not in the combined findings file itself. Use it as the index, then jump to the source workbook named in `source_file`.

For example, when the findings show rows like:

- `Transformation\CHP interim\Processes\CHP interim\Feedstock Fuels\Ammonia`
- `Transformation\Electricity interim\Processes\Electricity interim\Feedstock Fuels\Ammonia`
- `Transformation\Electricity interim\Processes\Electricity interim\Feedstock Fuels\Other hydrocarbons`

the problem is usually in `electricity_heat_interim_workflow.py` or its generated workbook, not in the reconciliation writer. The findings tell you which branch is bad; the source workbook shows the bad row and its expression.

For `SEED-011`, compare the branch name against the canonical full-model export. For `SEED-012`, compare the configured producer list against the actual per-economy workbook inventory. Those two rules are often “system-level” failures that explain many downstream rows at once.

If you want a fast workflow, use this order:

1. Open the consolidated findings file.
2. Filter to the top blocking `rule_id`.
3. Open the per-economy findings file for the same rule.
4. Use `source_workflow` and `source_file` to open the producing workbook.
5. Fix the producing workflow, rerun, and confirm the finding disappears.

See also `docs/baseline_seed_rule_inventory.md` for the canonical rule descriptions and the validation implementation in `codebase/functions/baseline_seed_validation.py` for the exact rule logic.

## 18. Code reference

```text
Main settings in supply_reconciliation_workflow.py

- ECONOMIES: list of economies to run (defaults via workflow_common.normalize_economies).
- SCENARIOS: ["Target", "Current Accounts"].
- RUN_MODE: "full" by default; "patch_baseline_seeds" is a separate preset path.
- ACTIVE_SUPPLY_LINK_METHOD: "capacity_unmet_iterative_balanced".
- CAPACITY_UNMET_PASS_MODE: "baseline_seed" (first run, imports zeroed so LEAP reveals
  the gap) or "results_update" (later runs, reads LEAP balance tables and computes the
  gap directly).
- CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS: True by default — negative import gaps
  are NOT routed to extra exports unless this is set to False.
- CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS / CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS:
  per-module/per-product caps (defined in codebase/supply_reconciliation_config.py),
  expressed with sentinel helpers such as KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT,
  INCREASE_BY_PCT(), DECREASE_BY_PCT(), SET_CAP_TO(), and UNLIMITED.
- CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY: "imports_fallback" by default (fail|imports_fallback|track_only)
  — controls what happens when neither production nor transformation can close a positive gap.
- CAPACITY_UNMET_PRODUCTION_ONLY_PRODUCTS: products that skip the transformation lever entirely
  (e.g. so an LNG regasification module never absorbs a natural-gas gap that should come from the well).

Allocation order for a positive (LEAP-imports-more-than-expected) gap, per the actual code:

1. For primary products, primary production headroom (`max_production` / `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS`) is tried first.
2. Any remaining gap (or any gap for a non-primary/secondary product) goes to transformation
   capacity headroom (`CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS`), in priority-module order.
3. Anything still unresolved is handled per `CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY`
   (defaults to falling back to imports).

Note: the script's own top-of-file docstring describes this order the other way round
(transformation first, then production) — that comment is stale relative to the actual
implementation, so trust the code/this guide over that comment.

Main outputs

- Updated LEAP import workbooks (supply, transformation, transfers, combined) in EXPORT_OUTPUT_DIR.
- A JSON state file (CAPACITY_UNMET_STATE_PATH) tracking cumulative capacity/production/export
  additions across passes, so each pass builds on the last rather than starting over.
- Unresolved-residual and clipping reports (CSV/JSON) when caps prevent a gap from being fully allocated.

Known caveats

- REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS is currently False — LEAP COM API
  read-back of transformation measures is disabled due to reliability issues.
- CONSTRAINT_TEMPLATE_PATHS-based fuel-level capacity caps are currently dormant (empty list).
```

---

## Planned improvements

Code improvements planned for this workflow and its supporting scripts. Mirrored in `AGENTS.md`.

### ~~Move config into the workflow file; extract functions to a functions folder~~ COMPLETE

Caps and override settings (`CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS`, `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS`, and related sentinels) are now defined in `codebase/supply_reconciliation_config.py` (Python, not JSON). Supporting functions have been extracted to modules in `codebase/functions/` and `codebase/`, reducing `supply_reconciliation_workflow.py` from 13,794 LOC to ~637 LOC (imports and notebook config block only). See Phase 4 of the refactor for details.

### Shared workflow utilities — partially complete

`codebase/utilities/workflow_utils.py` is now the shared home for repository
path resolution, economy-code normalization, year-column normalization, and
process-level ESTO/9th CSV loading. The reconciliation/configuration modules
and own-use proxy already use it, and `tests/test_workflow_utils.py` protects
the utility contract.

The remaining Phase 1 work is migration and hardening rather than a new
utility module:

- move the remaining safe full-table ESTO/9th readers to the shared loaders;
- add file-signature cache invalidation and an explicit notebook cache-clear
  helper, so a changed source file cannot be silently reused by a long-lived
  Python process;
- retain selective-column readers where loading the complete 9th Outlook CSV
  would materially worsen memory or runtime, unless a measured replacement is
  better;
- add focused regression tests before each workflow migration.

### Convergence rate reporting and run history tracking

Iterative capacity-unmet passes now calculate convergence metrics from the saved pass history. The pass summary includes the run id, pass count, first and current gap, gap closure percentage, last-pass gap delta, unresolved fuel count, and trend. Each pass also appends one row to `outputs/leap_exports/supply_reconciliation/<pass_mode>/supporting_files/runtime/capacity_unmet_convergence.csv`.

The convergence history now has modeller-facing diagnostics helpers:

```python
# Print and write the latest run's per-fuel diagnostics CSV.
from codebase.functions.capacity_unmet_convergence_diagnostics import (
    build_capacity_unmet_run_diagnostics,
    compare_capacity_unmet_runs,
)

latest_report = build_capacity_unmet_run_diagnostics()

# Compare the latest two run ids in capacity_unmet_convergence.csv.
comparison = compare_capacity_unmet_runs()

# Remove convergence-history rows for a deliberately reverted run.
from codebase.supply_reconciliation_history import remove_convergence_run

remove_convergence_run(run_id="capacity_unmet_20260710T010203456789Z")
```

`build_capacity_unmet_run_diagnostics()` prints a short summary and writes `capacity_unmet_run_diagnostics_<run_id>.csv` to the runtime supporting-files folder. The CSV shows per-fuel start/end gap, gap delta, allocation split across primary production, transformation capacity, imports fallback, clipped amount, and whether the fuel remains unresolved. `compare_capacity_unmet_runs()` reports side-by-side gap trajectories, closure and pass-count deltas, unresolved-set differences, and warns when the two runs used different `mode` / `iteration_run_mode` values.

**Files:** `codebase/supply_reconciliation_allocation.py`, `codebase/functions/capacity_unmet_convergence_diagnostics.py`, `codebase/supply_reconciliation_history.py`, `outputs/leap_exports/supply_reconciliation/<pass_mode>/supporting_files/runtime/capacity_unmet_convergence.csv`

### All demand aggregated output improvements

Three related improvements to `aggregated_demand_workflow.py`:

- **Per-sector filename IDs** — output filenames should encode which demand branches are included, so it is clear which branch is being excluded when a sector becomes ready for replacement.
- **Pre-generate all unique combinations** — generate all filename/file combinations for every possible demand branch subset upfront, so the modeller can select the right one for the current LEAP area without re-running the workflow.
- **Sectoral branches within the aggregated output** — record individual demand branch contributions within the all-demand-aggregated file, so the modeller can subtract a branch's energy themselves with no additional calculation.

**Files:** `codebase/aggregated_demand_workflow.py`

### Standardise all initialisation workflow scripts

The seven core workflow scripts should be reviewed and standardised:

- `codebase/aggregated_demand_workflow.py`
- `codebase/electricity_heat_interim_workflow.py`
- `codebase/other_loss_own_use_proxy_workflow.py`
- `codebase/refining_workflow.py`
- `codebase/supply_workflow.py`
- `codebase/transformation_workflow.py`
- `codebase/transfers_workflow.py`

Target state: consistent config style at the top of each file or near `if __name__ == "__main__"`; common structure across scripts; mappings sourced from `leap_mappings` rather than defined internally; shared supporting functions moved to a common functions folder.

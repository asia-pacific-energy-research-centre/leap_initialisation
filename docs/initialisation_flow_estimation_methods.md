# LEAP initialisation flow estimation methods

> **Status:** current code reference, reviewed 2026-08-17. This file describes
> how `leap_initialisation` currently derives values. It does not define the
> semantic mappings, which remain owned by the canonical mapping workbook in
> `leap_mappings`.

## Purpose and scope

This is the consolidated answer to: **for each energy-balance flow represented
by the initialisation code, where does its value come from and how is it
estimated?**

The word *estimated* is used broadly here. A value can be:

- copied directly from ESTO or the 9th Outlook;
- allocated from a coarser 9th Outlook series using historical shares;
- calculated from other energy series, such as process efficiency or proxy
  intensity;
- deliberately set to zero so LEAP reveals the balancing requirement; or
- left for LEAP to dispatch, then adjusted by the results-update loop.

The normal time boundary is:

- **Current Accounts:** the configured ESTO base year only;
- **Reference and Target:** 9th Outlook projection years, currently beginning
  in the year after the ESTO base year and ending at the configured final year.

The source paths and years are controlled by
[`codebase/configuration/workflow_config.py`](../codebase/configuration/workflow_config.py),
not by this document.

## Method labels used below

| Label | Meaning |
|---|---|
| **Direct** | The source value is used without estimating a split. Signs or units can still be converted for LEAP. |
| **ESTO-share allocation** | A coarse 9th Outlook value is split among mapped ESTO flow/product rows in proportion to the selected economy's absolute ESTO base-year values. |
| **APEC-share fallback** | If an economy has no usable base-year split, the corresponding APEC historical shares are used. |
| **Equal-split fallback** | If neither economy nor APEC shares are available, the value is divided equally among eligible mapped targets. Protected gas/coal transformation parents are instead left unallocated and reported when an arbitrary split would be unsafe. |
| **Derived ratio** | A LEAP parameter is calculated from energy series, for example output divided by feedstock. |
| **Proxy** | A hard-to-isolate flow is represented as activity multiplied by an intensity calibrated to reproduce its target energy. |
| **LEAP dispatch / reconciliation** | LEAP calculates the balance; the workflow reads the result and changes permitted production, capacity, or export levers. |

For 9th-to-ESTO allocations, every original `(economy, 9th sector, 9th fuel)`
total is conservation-checked against its allocated children. The allocator
and its exact fallback labels are in
[`codebase/functions/ninth_projection_mapping.py`](../codebase/functions/ninth_projection_mapping.py).

## Balance-flow summary

| Balance flow | Current Accounts method | Reference / Target method | LEAP representation and important rules |
|---|---|---|---|
| **01 Production** | Direct ESTO production, converted to a non-negative quantity. | Direct 9th series where the mapping is one-to-one; otherwise ESTO-share allocation, then APEC/equal fallback where allowed. | Written primarily as Resources **Maximum Production**. The economy's actual LEAP template determines whether a fuel sits under primary or secondary resources. Production can subsequently be increased within configured limits by results-update reconciliation. |
| **02 Imports** | Direct ESTO value in a standalone source export. | 9th import series, with the same mapped allocation rules as production. | Stored as a non-negative Resources **Imports** quantity. In the linked baseline seed and active iterative-balanced loop, imports are deliberately written as zero so LEAP's calculated imports become the error signal; they are not treated as a fixed first-choice input. |
| **03 Exports** | Direct ESTO value, converted to a non-negative quantity. | 9th export series, using mapped allocation where required. | Written as non-negative Resources **Exports** or as transformation output-fuel **Export Target** where trade is assigned to a transformation module. The current iterative-balanced policy normally pins exports to the projected baseline; if unpinned, a negative import gap may become extra exports. |
| **04 Marine bunkers** and **05 Aviation bunkers** | Direct ESTO demand-side use for the base year when included in the aggregate placeholder scope. | Direct/mapped 9th demand projections, allocated to detailed ESTO products when a 9th fuel is coarser. | Treated as positive demand magnitude after taking the absolute balance value. They are demand/bunker requirements, not negative resource exports. They disappear from the aggregate placeholder when their source scope is owned by an active detailed demand branch. |
| **06 Stock changes** | Direct ESTO base-year value with its balance sign retained. | Zero by design. | Written only when the economy template contains the separate **Stock Changes** branch. No projection method is asserted because there is no maintained projection basis. |
| **07 Total primary energy supply** | Source/checking aggregate, not independently estimated. | Source/checking aggregate, not independently estimated. | Not written as a separate LEAP assumption. Reconciliation reconstructs and compares the balance boundary from component flows; writing the source subtotal as well would double count it. |
| **08 Transfers** and children | Direct signed ESTO transfer rows; active subflows `08.01`, `08.02`, `08.03`, and `08.99` are preferred over the aggregate. | Signed 9th transfer projections are allocated with base-year product profiles and conservation checking. A generic `08 Transfers` projection is routed to the economy's largest active base-year subflow. | Modelled as transformation-style processes. Negative products are feedstocks and positive products are outputs. Economy configuration divides them into upstream liquids, refining/blending, or unallocated processes. |
| **08.04 Gas separation** | Not selected by the active transfer workflow. | Not selected by the active transfer workflow. | The flow exists in the source catalog and balance-result comparison code, but it is absent from `TRANSFER_FLOW_CODES`; there is currently no seed estimation method for it. |
| **09 Transformation inputs** | Direct negative ESTO transformation rows, converted to positive feedstock quantities. | Signed 9th transformation series allocated to the mapped ESTO process/product context. | Feedstock Fuel Share is each input divided by total feedstock. The default is one multi-feedstock process, not one process per fuel. Auxiliary fuel is kept outside the process-efficiency denominator. |
| **09 Transformation outputs** | Direct positive ESTO transformation rows. | Signed 9th transformation projections after mapped allocation. | Output fuels, output shares, Historical Production and Exogenous Capacity are built from the resulting positive output series. Process Efficiency is `total output / total exported feedstock`, capped by configured safeguards. |
| **09 transformation parent/subtotal rows** | Filtering and allocation context, not additional process energy. | Filtering and allocation context, not additional process energy. | Parents such as `09 Total transformation sector`, `09.01`, `09.02`, `09.06`, and `09.08` are not added on top of their active children. Parent projections are disaggregated only under the explicit child-profile rules described below. |
| **10.01 Energy-sector own use** | Direct target energy from the ESTO child flow. The representation is either transformation Auxiliary Fuel Use or a demand proxy, according to the ownership table below. | Direct/mapped 9th child-flow target. Proxy-owned flows use activity from ESTO+9th in the baseline seed or from a LEAP balance in results-update. | A proxy writes `Activity Level` and `Final Energy Intensity`, where initialisation intensity is `abs(target energy) / proxy activity`. Transformation-owned flows become auxiliary ratios relative to process output. A flow must have one owner to avoid double counting. |
| **10.02 Transmission and distribution losses** | Direct ESTO target energy by fuel. | Direct/mapped 9th loss target by fuel, including projection-only fuels where configured. | Demand proxy. Default activity is total positive production including electricity. If that entire process activity is unavailable, a fuel-specific total-demand series is tried. Initialisation intensity matches target energy year by year. |
| **10 Losses & own use** and **10.01 Own Use** parents | Source/checking subtotals, not independently estimated. | Source/checking subtotals, not independently estimated. | Values come from the owned `10.01.*` children and `10.02`; adding the parent rows would duplicate them. |
| **11 Statistical discrepancy** | Direct ESTO base-year value with the sign reversed for LEAP **Statistical Differences** semantics. | Zero by design. | Written only when the economy template contains the separate **Statistical Differences** branch. |
| **12 Total final consumption** and **13 Total final energy consumption** | Source/checking subtotals, not independently estimated. | Source/checking subtotals, not independently estimated. | Excluded from aggregate-demand value construction. Demand is built from the `04`, `05`, and `14–17` components so these parent totals are not added a second time. |
| **14–17 Final demand families** | Absolute ESTO base-year demand, grouped to the maintained placeholder sector and LEAP fuel. | 9th demand values allocated within the same mapped sector/fuel context using economy ESTO shares, then APEC/equal fallback. | Written under `Demand\All demand aggregated`. Source sectors owned by active detailed demand models are excluded, so the placeholder is a residual by source scope; detailed LEAP results are not subtracted. |
| **18 Electricity output in GWh** and **19 Heat output in PJ** | Accounting/output checks, not transformation feedstock estimates. | Accounting/output checks, not transformation feedstock estimates. | The interim power builder explicitly prohibits these output-accounting sectors as inputs and derives energy outputs from signed `09.*` transformation rows. This avoids mixing GWh accounting rows with the energy-balance process representation. |
| **Unmet requirements** | Normally not seeded as an energy estimate. | Normally not seeded as an energy estimate. | Supply policy is generally **MeetWithImports**. Unmet requirements are a LEAP result/diagnostic, not a source-data flow that this repository projects. |

The supply sign rules and the special base-year-only treatment of stock changes
and statistical differences are implemented in
[`supply_value_series.py`](../codebase/functions/supply_value_series.py) and
[`supply_export_builder.py`](../codebase/functions/supply_export_builder.py).

## Supply and trade in the linked reconciliation runs

The standalone supply workflow can export projected imports, exports, and
production. The combined reconciliation workflow intentionally changes how
those values are used:

1. **Baseline seed:** imports are written as zero, while projected exports and
   initial production/capacity are retained. LEAP recalculates the balance.
2. **Observed gap:** the results-update pass compares LEAP imports with the
   projected import baseline. The primary signal is
   `observed imports - projected imports`.
3. **Positive gap:** eligible primary-fuel Maximum Production headroom is used
   first; eligible transformation Exogenous Capacity is used next; any
   permitted residual falls through to imports.
4. **Negative gap:** it may become an explicit export adjustment, but the
   current pinned-export setting keeps exports at their 9th projection instead.
5. **Production-only products:** products such as natural gas can be configured
   to skip transformation capacity and use production headroom only.

This is why a generated zero import is not evidence that projected imports are
unknown. It is an experimental control used to measure LEAP's endogenous
requirement. See
[`supply_reconciliation/allocation.py`](../codebase/supply_reconciliation/allocation.py)
and the [workflow guide](supply_reconciliation_workflow_guide.md).

## Transformation methods by flow family

### Shared calculation

Except where a specialised module is described below, transformation flows use
the same balance-to-LEAP conversion:

1. Retain signed, non-subtotal source rows for the selected `09.*` process.
2. Interpret positive values as outputs and the absolute values of negative
   rows as feedstocks.
3. Preserve each mapped fuel series across the export horizon.
4. Calculate each feedstock share as
   `feedstock fuel / total feedstock` for that year.
5. Calculate Process Efficiency as
   `total output / total exported feedstock`. Auxiliary/own-use energy is not
   included in the denominator.
6. Calculate output shares from the positive output-fuel series.
7. Use positive output as Historical Production and, where the workflow
   supplies it, as the initial Exogenous Capacity basis.
8. Write a zero-capacity skeleton when a configured process has no usable
   input/output balance, preventing stale values from surviving an import.

The default feedstock structure is `multi_feedstock_single_process`. Empty
share groups receive a deterministic inert share only when the process has zero
capacity; a process with capacity is not allowed to hide behind a placeholder
efficiency. The shared implementation is in
[`transformation_series_utils.py`](../codebase/functions/transformation_series_utils.py)
and
[`transformation_record_builder.py`](../codebase/functions/transformation_record_builder.py).

### Process coverage and exceptions

| Flow/process | Method or exception |
|---|---|
| `09.01.*` / `09.02.*` electricity, CHP and heat plants | In a baseline seed, the temporary Electricity interim, CHP interim and Heat plant interim modules use the shared signed-flow method. Electricity/heat are the only allowed positive outputs. Exogenous Capacity equals total output in PJ/year (exported as million GJ/year). Auxiliary use is excluded because the proxy workflow owns `10.01.01`. Disable these modules when the full power model owns the scope. |
| `09.03 Heat pumps` | Excluded from transformation record export: it is not currently represented as a maintained LEAP transformation flow here. |
| `09.04` Electric boilers; `09.05` chemical heat | Shared signed-flow method. |
| `09.06.01` Gas works; `09.06.03` natural-gas blending; `09.06.04` gas-to-liquids | Shared method with process-specific input/output labels. Gas parent projections require economy child-flow evidence; unsafe parent splits are reported rather than divided arbitrarily. |
| `09.06.02` LNG liquefaction/regasification | Classified separately for every economy-year. Natural gas output with LNG input is regasification; LNG output with natural-gas input is liquefaction. Ambiguous years are excluded. `10.01.03` is proxy-owned rather than added as auxiliary use. |
| `09.07` Oil refineries | Shared multi-output method. Petroleum-product output shares, feedstock shares, efficiency, capacity and output trade targets are derived from the signed source balance. Refinery-gas or other same-module auxiliary use remains on a consistent gross-output basis. |
| `09.08.01–09.08.05` coal transformation children | Shared signed-flow method with sign-stable allocation. Coke ovens, blast furnaces, patent fuel, BKB/PB and coal-to-oil retain their child process context. A coarse parent projection is split only with historical child evidence; zero-net profiles use a gross sign-stable fallback. |
| `09.08.06 Coal mines` | Present in sector configuration but commented out of the active transformation analysis registry. `10.01.06` mine own-use/loss is proxy-owned using coal production activity. |
| `09.09` Petrochemical industry; `09.11` charcoal processing; `09.12` non-specified transformation | Shared signed-flow method. `10.01.17` is not tied to `09.12`; it is proxy-owned using total transformation throughput. |
| `09.10 Biofuels processing` | Excluded from transformation record naming/export because the current ESTO scope is zero and the process lacks a maintained LEAP display mapping. |
| `09.13.01–09.13.03` hydrogen transformation | 9th Outlook process rows supply electrolysers and SMR with/without CCS. Green electricity feeds the enabled electrolyser process; natural gas feeds SMR processes; hydrogen, ammonia and efuel are outputs. Ordinary-electricity electrolysers are currently disabled. |

The interim power details are in
[`placeholder_branches_and_interim_models.md`](placeholder_branches_and_interim_models.md).

## Transfers

Transfers use the shared transformation calculation but have additional
routing rules:

- use nonzero detailed subflows in preference to `08 Transfers`;
- roll detailed base-year rows to the parent temporarily so a coarse 9th fuel
  can be split using the economy's actual product profile;
- route the resulting parent projection back to the economy's largest active
  base-year transfer subflow;
- assign configured negative/positive products to **Upstream liquids
  transfers**, **Refinery and blending transfers**, or **Transfers
  unallocated**;
- if the explicit economy mapping is absent, try the maintained category
  templates; the final fallback treats all negative products as inputs and all
  positive products as outputs;
- merge to the unallocated process under its configured outlier/coverage
  policy when a process cannot be represented safely.

All transfer projections use sign-stable allocation. See
[`codebase/transfers_workflow.py`](../codebase/transfers_workflow.py) and
[`codebase/functions/transfers_utils.py`](../codebase/functions/transfers_utils.py).

## Own-use and loss flow ownership

This table covers every configured `10.01` child, including disabled proxies.
“Transformation auxiliary” means the target can be represented with the
corresponding module's Auxiliary Fuel Use rather than a separate demand proxy.

| ESTO / 9th flow | Current owner/status | Activity or estimation method |
|---|---|---|
| `10.01.01` Electricity, CHP and heat plants | **Proxy enabled** | Positive electricity plus heat output from electricity, CHP and heat plants; results-update reads the matching LEAP balance rows. |
| `10.01.02` Gas works plants | Proxy disabled; **transformation auxiliary configured** | If the proxy were enabled, its activity would be positive gas-works-gas output. The active transformation configuration instead assigns this target flow to Gas works Auxiliary Fuel Use. |
| `10.01.03` Liquefaction/regasification plants | **Proxy enabled** | Positive natural-gas and LNG output/throughput. If unavailable, configured ESTO/9th trade/production fallback tiers are tried; LEAP-balance mode uses liquefaction and regasification output rows. |
| `10.01.04` Gas-to-liquids plants | Proxy disabled; no target loss flow configured on the transformation record | The disabled proxy definition would use positive petroleum-product output from GTL. The code comment identifies auxiliary use as the intended representation, but the current GTL transformation configuration has an empty `loss_flow_codes` list. |
| `10.01.05` Coke ovens | Proxy disabled; **transformation auxiliary configured** | The active transformation configuration assigns this target flow to Coke ovens Auxiliary Fuel Use. The disabled proxy definition would use positive coke, coke-oven-gas and coal-tar output, with broader parent 9th activity as a fallback. |
| `10.01.06` Coal mines | **Proxy enabled** | Positive production of primary coal and coal products. |
| `10.01.07` Blast furnaces | Proxy disabled; **transformation auxiliary configured** | The active transformation configuration assigns this target flow to Blast furnaces Auxiliary Fuel Use. The disabled proxy definition would use positive blast-furnace-gas output, with broader parent 9th activity as a fallback. |
| `10.01.08` Patent fuel plants | Proxy disabled; no target loss flow configured on the transformation record | The disabled proxy definition would use positive patent-fuel output. The code comment identifies auxiliary use as the intended representation, but the current transformation configuration has no loss flow for this process. |
| `10.01.09` BKB/PB plants | Proxy disabled; no target loss flow configured on the transformation record | The disabled proxy definition would use positive BKB/PB output. The code comment identifies auxiliary use as the intended representation, but the current transformation configuration has no loss flow for this process. |
| `10.01.10` Coal-to-oil liquefaction | Proxy disabled; no target loss flow configured on the transformation record | The disabled proxy definition would use positive petroleum-product output. The code comment identifies auxiliary use as the intended representation, but the current transformation configuration has no loss flow for this process. |
| `10.01.11` Oil refineries | Proxy disabled; **transformation auxiliary configured** | The active transformation configuration assigns this target flow to Oil Refining Auxiliary Fuel Use. The disabled proxy definition would use positive petroleum-product refinery output. |
| `10.01.12` Oil and gas extraction | **Proxy enabled** | Positive primary production of crude oil, NGL, other hydrocarbons, natural gas and related gas products. |
| `10.01.13` Pump storage plants | **Proxy enabled** | Positive pumped-storage electricity output from the 9th data. If detailed activity is empty, positive hydro electricity output is tried. Because no isolated ESTO history exists, a zero base-year activity can borrow the first nonzero projection-year activity; target-matching intensity absorbs that scale. |
| `10.01.14` Nuclear industry | **Proxy enabled** | Positive primary nuclear production. |
| `10.01.15` Charcoal production plants | Proxy disabled; no target loss flow configured on the transformation record | The disabled proxy definition would use positive charcoal-processing output. The code comment identifies auxiliary use as the intended representation, but the current charcoal transformation configuration has no loss flow for this process. |
| `10.01.16` Gasification plants for biogases | **Proxy enabled** | Positive primary biogas production; there is no direct ESTO `09` gasification activity row. |
| `10.01.17` Non-specified own uses | **Proxy enabled** | Absolute total transformation throughput: inputs plus outputs across the maintained leaf `09.*` flows. It intentionally does not use only `09.12`. |
| `10.01.18` CCS | Disabled / not currently estimated | The 9th has a CCS own-use sector, but the configured ESTO source has no matching `10.01.18` flow and no accepted proxy method has been enabled. |
| `10.01.19` Hydrogen transformation | Not currently estimated | The flow exists in the current ESTO/9th source vocabulary, but it has no proxy entry and Hydrogen transformation has no configured own-use/loss source. Hydrogen process inputs and outputs are initialised; this own-use child is not. |
| `10.02` Transmission and distribution losses | **Proxy enabled** | Positive total production including electricity. If the complete process activity is unavailable, same-fuel total demand is tried separately for each target fuel. |

### Proxy formula and source hierarchy

For each enabled process and target fuel:

```text
target energy = abs(10.01/10.02 source flow for that fuel)
initialisation intensity(year) = target energy(year) / proxy activity(year)
LEAP energy(year) = proxy activity(year) * intensity(year)
```

The hierarchy is:

1. **Baseline seed activity:** ESTO activity through the base year plus the
   corresponding 9th activity in projection years. If an ESTO activity leg is
   defined but is completely zero, its 9th leg is not accepted silently.
2. **Configured fallback tiers:** alternative source series are ranked by
   projection-year coverage, then historical coverage. Detailed 9th activity
   can also climb to a broader parent sector where configured.
3. **Base-year backfill:** if activity exists only in projections, the first
   nonzero projection activity can be copied to the base year. Only the scale
   is borrowed; the target-matching formula still exactly matches base-year
   target energy.
4. **Results-update activity:** the same proxy is rebuilt from selected rows
   and fuels in a LEAP balance export.
5. **Consistency gate:** positive target energy with zero activity at or after
   the export base year is an error in strict mode.

Both baseline-seed and results-update are *target-matching initialisation*:
intensity changes by year to reproduce the external target. The separate
post-initialisation mode holds the first valid calibrated intensity constant;
it is not the normal seed/update behavior.

The authoritative configuration and formulas are in
[`other_loss_own_use_proxy_workflow.py`](../codebase/other_loss_own_use_proxy_workflow.py)
and
[`other_loss_own_use_proxy_utils.py`](../codebase/functions/other_loss_own_use_proxy_utils.py).

## Aggregated demand placeholder

The maintained placeholder branches are Road, Transport non road,
International transport, Industry, Other sector, and Buildings.

- Base-year demand is the absolute value of non-subtotal ESTO demand rows,
  grouped to LEAP sector and fuel. Its provenance method is `direct`.
- Projection demand comes from the mapped 9th sector/fuel series. A coarse
  source pair is split across detailed ESTO targets using same-sector,
  same-economy base-year shares. APEC and equal fallbacks are reported.
- Own use and T&D losses are excluded whenever the proxy workflow owns them.
- Activating a detailed demand group excludes its equivalent **source-data
  scope** from the placeholder. The workflow does not estimate a residual by
  subtracting detailed LEAP results.
- Output is normally represented as Activity Level `1` multiplied by Final
  Energy Intensity equal to the required total energy. This is an encoding
  choice, not a behavioral demand model.
- A first-projection-year bridge exists, but it is disabled by default. If
  enabled, it moves the first projection toward the base year and carries the
  same absolute offset through later years, clipped at zero.
- Branches that are zero across every requested scenario/year are omitted;
  retained branches receive a complete scenario/year grid.

See
[`codebase/aggregated_demand_workflow.py`](../codebase/aggregated_demand_workflow.py).

## Results-update-specific re-estimation

The results-update pass does not replace every source method. It updates the
parts that depend on LEAP's recalculated system:

| Item | Results-update method |
|---|---|
| Imports/exports | Read observed LEAP balance trade, compare with projected trade, and form the import-gap signal. |
| Primary production | Add permitted positive gap to Maximum Production, bounded by production headroom and product/economy caps. |
| Transformation output | Allocate remaining positive gap to eligible processes and convert required output uplift to Exogenous Capacity using the process/output relationship and caps. |
| Own-use proxy activity | Replace ESTO/9th activity with selected LEAP balance activity; retain target-matching intensity against the external 10.01/10.02 target. |
| Transformation auxiliary use | Where a fuel is both feedstock and own use, reconstruct estimated own use from LEAP feedstock readback using `feedstock * ratio / (1 - ratio)`, then recalibrate the auxiliary relationship. |
| Demand | Treated as given. The reconciliation loop does not rewrite demand to remove a supply gap. |

## Known limits and review points

- This document records the code, not a claim that every proxy is the best
  possible causal model. The enabled proxy list contains deliberate modelling
  choices that should be revisited when detailed sector models are available.
- Disabled proxy entries are scaffolding, not duplicate live estimates.
- `10.01.18 CCS` remains unestimated rather than receiving an invented
  fallback.
- Stock changes and statistical differences have no maintained projection
  method and therefore remain zero outside Current Accounts.
- Protected gas/coal aggregate transformation projections can remain
  unallocated when there is no economy history. Diagnostics are preferred to
  an arbitrary split.
- Interim power and aggregated demand are temporary ownership boundaries. They
  must be disabled or source-excluded when detailed models take over.
- The exact mapping from source codes to LEAP branches must be reviewed in the
  canonical `leap_mappings` workbook. Do not add a second semantic crosswalk
  to this repository or to this file.

## Code-to-method index

| Area | Primary implementation |
|---|---|
| Source configuration | [`codebase/configuration/workflow_config.py`](../codebase/configuration/workflow_config.py) |
| 9th-to-ESTO allocation and conservation | [`codebase/functions/ninth_projection_mapping.py`](../codebase/functions/ninth_projection_mapping.py) |
| Supply series and signs | [`codebase/functions/supply_value_series.py`](../codebase/functions/supply_value_series.py) |
| Supply workbook rows | [`codebase/functions/supply_export_builder.py`](../codebase/functions/supply_export_builder.py) |
| Transformation flow analysis | [`codebase/functions/transformation_sector_analysis.py`](../codebase/functions/transformation_sector_analysis.py) |
| Transformation formulas and records | [`codebase/functions/transformation_series_utils.py`](../codebase/functions/transformation_series_utils.py), [`codebase/functions/transformation_record_builder.py`](../codebase/functions/transformation_record_builder.py) |
| Transfers | [`codebase/transfers_workflow.py`](../codebase/transfers_workflow.py) |
| Interim power | [`codebase/electricity_heat_interim_workflow.py`](../codebase/electricity_heat_interim_workflow.py) |
| Loss/own-use proxy | [`codebase/other_loss_own_use_proxy_workflow.py`](../codebase/other_loss_own_use_proxy_workflow.py) |
| Aggregated demand | [`codebase/aggregated_demand_workflow.py`](../codebase/aggregated_demand_workflow.py) |
| Results-update gap allocation | [`codebase/supply_reconciliation/allocation.py`](../codebase/supply_reconciliation/allocation.py) |

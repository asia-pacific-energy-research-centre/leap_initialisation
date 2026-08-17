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
- left for LEAP to dispatch.

> **Operational scope:** the main table describes the normal combined
> **baseline-seed** workflow. The implemented `results_update` process is
> optional, is under review, and may be deactivated; it is documented
> separately so it is not mistaken for a required initialisation stage.
> Standalone producer behavior is mentioned only as an exception.

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
| **LEAP dispatch** | LEAP calculates the balance from the seeded assumptions, including the imports required when seed imports are zero. |
| **Optional results update** | Implemented, under-review behavior that reads LEAP results and changes permitted production, capacity, or export levers. It is not part of the normal baseline-seed method. |

For 9th-to-ESTO allocations, every original `(economy, 9th sector, 9th fuel)`
total is conservation-checked against its allocated children. The allocator
and its exact fallback labels are in
[`codebase/functions/ninth_projection_mapping.py`](../codebase/functions/ninth_projection_mapping.py).

## Normal baseline-seed flow summary

| Balance flow | External reference series | Normal baseline-seed behavior | Notes / exceptions |
|---|---|---|---|
| **01 Production** | ESTO base-year production; direct or allocated 9th production for projection years. | Write the non-negative series primarily as Resources **Maximum Production**. | The economy's LEAP template determines whether the fuel is a primary or secondary resource. |
| **02 Imports** | ESTO base-year and 9th projection imports are retained as reference series. | **Write imports as zero in every seeded scenario/year.** LEAP then calculates the imports required to balance the seeded model. | Source imports are comparison data, not seeded import assumptions. The standalone supply exporter can write them, but that is not the normal combined baseline-seed method. |
| **03 Exports** | ESTO base-year exports; direct or allocated 9th exports for projection years. | Write the non-negative projected export series to Resources **Exports**, or to transformation output-fuel **Export Target** where that module owns the trade. | Unlike imports, exports are preserved in the normal baseline seed. |
| **04 Marine bunkers** and **05 Aviation bunkers** | ESTO base-year use and direct/mapped 9th demand projections. | Write positive demand magnitudes within the aggregate placeholder when that source scope is not owned by a detailed branch. | These are demand/bunker requirements, not resource exports. |
| **06 Stock changes** | ESTO base-year stock change with its balance sign retained. | Write the Current Accounts value where the template has **Stock Changes**; write zero in Reference/Target. | There is no maintained projection method. |
| **07 Total primary energy supply** | Source/checking aggregate. | Do not write it as a separate LEAP assumption. | It is reconstructed from component flows; adding the subtotal would double count it. |
| **08 Transfers** and children | Signed ESTO base-year rows and signed, allocated 9th projections. | Build transformation-style transfer processes: negative products are feedstocks and positive products are outputs. | Active `08.01`, `08.02`, `08.03`, and `08.99` subflows are preferred over the parent and assigned to configured upstream, refining/blending, or unallocated processes. |
| **08.04 Gas separation** | Present in the source vocabulary. | Do not write it; there is currently no seed estimation method. | It is absent from active `TRANSFER_FLOW_CODES`. |
| **09 Transformation inputs** | Negative ESTO/9th process rows after mapped projection allocation. | Write their absolute values as feedstocks; calculate each Feedstock Fuel Share against total feedstock. | The default is one multi-feedstock process. Auxiliary energy is outside the efficiency denominator. |
| **09 Transformation outputs** | Positive ESTO/9th process rows after mapped projection allocation. | Build output fuels, output shares, Historical Production, Process Efficiency, and initial Exogenous Capacity where supported. | Process Efficiency is `total output / total exported feedstock`, subject to configured safeguards. |
| **09 transformation parent/subtotal rows** | Filtering and allocation context. | Do not add parents on top of active children. | Parent projections are disaggregated only under explicit child-profile rules. |
| **10.01 Energy-sector own use** | ESTO child-flow targets in the base year and direct/mapped 9th child-flow targets in projections. | Write each flow through its single current owner: transformation Auxiliary Fuel Use or an enabled demand proxy. Proxy activity comes from ESTO plus 9th data. | Proxy intensity is `abs(target energy) / proxy activity`, so the seed matches target energy year by year. See the ownership table below. |
| **10.02 Transmission and distribution losses** | ESTO base-year target by fuel and direct/mapped 9th projection targets. | Write an enabled demand proxy using total positive production, including electricity, as the normal activity series. | If the whole process activity is unavailable, try fuel-specific total demand. |
| **10 Losses & own use** and **10.01 Own Use** parents | Source/checking subtotals. | Do not write the parents separately. | Values come from the owned `10.01.*` children and `10.02`. |
| **11 Statistical discrepancy** | ESTO base-year statistical discrepancy. | Write the sign-reversed Current Accounts value where the template has **Statistical Differences**; write zero in Reference/Target. | There is no maintained projection method. |
| **12 Total final consumption** and **13 Total final energy consumption** | Source/checking subtotals. | Do not write the parent totals. | Demand is built from `04`, `05`, and `14–17` components. |
| **14–17 Final demand families** | Absolute ESTO base-year demand and allocated 9th projections. | Write the maintained `Demand\All demand aggregated` residual branches after excluding source sectors owned by active detailed demand models. | Detailed LEAP results are not subtracted; ownership is controlled by source-scope exclusion. |
| **18 Electricity output in GWh** and **19 Heat output in PJ** | Output-accounting/checking rows. | Do not use them as transformation inputs; derive interim power energy output from signed `09.*` rows. | This avoids mixing accounting rows and units with the energy-balance process representation. |
| **Unmet requirements** | No external seed estimate. | Do not seed it as an energy flow; use the normal **MeetWithImports** policy where configured. | Unmet requirements are a LEAP result/diagnostic. |

The supply sign rules and the special base-year-only treatment of stock changes
and statistical differences are implemented in
[`supply_value_series.py`](../codebase/functions/supply_value_series.py) and
[`supply_export_builder.py`](../codebase/functions/supply_export_builder.py).

## Supply and trade in the normal baseline seed

The combined baseline seed keeps projected production and exports but writes
imports as zero. LEAP therefore receives the domestic supply and export
assumptions while retaining responsibility for calculating whatever imports
are needed to balance the model.

The source import series is still built and retained for comparison and audit.
It is not the value written into the normal baseline seed. This distinction is
easy to miss because the standalone supply exporter can write source imports;
standalone capability does not define the combined baseline-seed behavior.

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
| `10.01.01` Electricity, CHP and heat plants | **Proxy enabled** | Positive electricity plus heat output from electricity, CHP and heat plants. The optional results-update implementation can instead read matching LEAP balance rows. |
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
4. **Consistency gate:** positive target energy with zero activity at or after
   the export base year is an error in strict mode.

The baseline seed uses *target-matching initialisation*: intensity changes by
year to reproduce the external target. The separate post-initialisation mode
holds the first valid calibrated intensity constant; it is not the normal
baseline-seed behavior. The optional results-update implementation also uses
target-matching intensity when it is explicitly run.

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

## Optional results-update process — under review

`results_update` is implemented, but its continued use is under review and it
may be deactivated. It is **not assumed to be part of the normal
initialisation method** in this document. Do not run it merely because a
baseline seed has been produced; use it only when the run plan explicitly
calls for it.

The behavior below is retained as implementation and maintenance reference. If
the optional process is run, it updates the parts that depend on LEAP's
recalculated system:

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

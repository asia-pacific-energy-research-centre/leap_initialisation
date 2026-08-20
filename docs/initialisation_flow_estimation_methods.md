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
| **Base-year carry-forward** | The base-year value is held flat across the projection horizon because the source supplies no projection for that flow. It is a deliberate placeholder, not an estimate of how the flow evolves. |
| **LEAP dispatch** | LEAP calculates the balance from the seeded assumptions, including the imports required when seed imports are zero. |
| **Optional results update** | Implemented, under-review behavior that reads LEAP results and changes permitted production, capacity, or export levers. It is not part of the normal baseline-seed method. |

For 9th-to-ESTO allocations, every original `(economy, 9th sector, 9th fuel)`
total is conservation-checked against its allocated children. The allocator
and its exact fallback labels are in
[`codebase/functions/ninth_projection_mapping.py`](../codebase/functions/ninth_projection_mapping.py).

## Normal baseline-seed flow summary

> **Important:** not every detailed flow is projected separately in the 9th
> Outlook. Detailed transfers and some gas- and coal-processing flows are
> estimated by splitting a broader 9th total using the economy's ESTO history.

| Balance flow | Where future values come from | Normal baseline-seed behavior | Notes / exceptions |
|---|---|---|---|
| **01 Production** | **Taken from the 9th.** Broader fuel totals can be split using ESTO history. | Write the non-negative series primarily as Resources **Maximum Production**. | The economy's LEAP template determines whether the fuel is a primary or secondary resource. |
| **02 Imports** | **Taken from the 9th for comparison only.** | **Write imports as zero in every seeded scenario/year.** LEAP then calculates the imports required to balance the seeded model. | The standalone supply exporter can write source imports, but that is not the normal combined baseline-seed method. |
| **03 Exports** | **Taken from the 9th.** Broader fuel totals can be split using ESTO history. | Write the non-negative projected export series to Resources **Exports**, or to transformation output-fuel **Export Target** where that module owns the trade. | Unlike imports, exports are preserved in the normal baseline seed. |
| **04 Marine bunkers** and **05 Aviation bunkers** | **Taken from the 9th.** Broader totals can be split using ESTO history. | Write positive demand values within the aggregate placeholder when that source scope is not owned by a detailed branch. | These are demand/bunker requirements, not resource exports. |
| **06 Stock changes** | **Set to zero in future years.** | Write the ESTO Current Accounts value where the template has **Stock Changes**; write zero in Reference/Target. | There is no maintained projection method. |
| **07 Total primary energy supply** | **Not included separately.** | Do not write it as a separate LEAP assumption. | LEAP reconstructs it from component flows; adding the total would double count it. |
| **08 Transfers** and children | **Split from a 9th total. Detailed transfer flows are estimated using the economy's ESTO history.** | Build transformation-style transfer processes: negative products are feedstocks and positive products are outputs. | Active `08.01`, `08.02`, `08.03`, and `08.99` subflows are preferred over the parent and assigned to configured upstream, refining/blending, or unallocated processes. |
| **08.04 Gas separation** | **Not included.** | Do not write it; there is currently no seed estimation method. | It is absent from active `TRANSFER_FLOW_CODES`. |
| **09 Transformation inputs and outputs** | **Usually taken from the 9th.** Broader fuel or process totals can be split using ESTO history. | Write inputs as feedstocks. Use outputs to build output shares, Historical Production, Process Efficiency and initial Exogenous Capacity where supported. | The rows below highlight the gas- and coal-processing exceptions. |
| **09.06.01–09.06.04 Gas processing** | **Not all projected separately in the 9th. Missing flows are estimated from the broader gas-processing total and the economy's ESTO history.** | Keep any direct 9th child values and split the remaining broader total among missing flows that were active in the ESTO base year. | If there is no broader projected total, the normal configuration does not automatically invent a new projection. |
| **09.08.01–09.08.05 Coal transformation** | **Not all projected separately in the 9th. The broader coal-transformation total is split using the economy's ESTO history.** | Build the detailed coke-oven, blast-furnace, patent-fuel, BKB/PB and coal-to-oil flows while preserving the broader 9th total. | If the economy's history cannot support a safe split, leave it unresolved and report it. |
| **09 transformation parent/subtotal rows** | **Used only when a broader 9th total must be split.** | Do not add parents on top of active children. | Adding both parent and child values would double count the flow. |
| **10.01 Energy-sector own use** | **Usually taken from the 9th, but represented using a related activity.** | Write each flow through its single current owner: transformation Auxiliary Fuel Use or an enabled demand proxy. | The related activity and calculated intensity reproduce the own-use target. See the ownership table below. |
| **10.02 Transmission and distribution losses** | **Taken from the 9th, but represented using a related activity.** | Use total positive production as the normal activity series. | If that activity is unavailable, try fuel-specific total demand. |
| **10 Losses & own use** and **10.01 Own Use** parents | **Not included separately.** | Do not write the parents separately. | Values come from the owned `10.01.*` children and `10.02`. |
| **11 Statistical discrepancy** | **Set to zero in future years.** | Write the sign-reversed ESTO Current Accounts value where the template has **Statistical Differences**; write zero in Reference/Target. | There is no maintained projection method. |
| **12 Total final consumption** and **13 Total final energy consumption** | **Not included separately.** | Do not write the parent totals. | Demand is built from `04`, `05`, and `14–17` components. |
| **14–17 Final demand families** | **Taken from the 9th.** Broader totals are split using ESTO history. | Write the maintained `Demand\All demand aggregated` branches after excluding source sectors owned by active detailed demand models. | Detailed LEAP results are not subtracted; ownership is controlled by source-scope exclusion. |
| **18 Electricity output in GWh** and **19 Heat output in PJ** | **Not included as input flows.** | Derive interim power energy output from signed `09.*` rows instead. | This avoids mixing accounting rows and units with the energy-balance process representation. |
| **Unmet requirements** | **Calculated by LEAP.** | Do not seed it as an energy flow; use the normal **MeetWithImports** policy where configured. | Unmet requirements are a LEAP result/diagnostic. |

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

### One-sided transfer flows

Some economies record a transfer flow with products leaving and nothing
arriving, or the reverse. A LEAP transformation process needs both a feedstock
and an output, so such a flow used to produce **no process at all** — silently,
with no error. `05_PRC` lost 5,228 PJ of 2022 transfers this way.

**Method: keep the measured side exactly as ESTO records it and add a
counterpart on the empty side, carried on a dedicated synthetic fuel, in each
year that is one-sided.** This is the smallest addition that makes a valid LEAP
process while leaving every measured value untouched. The imbalance ESTO already
carries then surfaces as process loss instead of being papered over.

The counterpart fuel is **`99 AUTO BALANCE`** — a real LEAP fuel named
`AUTO BALANCE`, but deliberately *not* a real ESTO product. Code `99` sits
outside the ESTO product vocabulary (which runs `01`–`21`), and the all-caps
name makes it unmistakable in branch listings and balance outputs. Attributing
the balancing quantity to a real product such as refinery feedstocks would put
invented energy onto a fuel that downstream balances treat as genuine; keeping
it on its own fuel means every consumer can identify and exclude it.

**Sizing.** The counterpart is 1 PJ (the floor) except where that would push a
process past the efficiency ceiling. For an *inflow-only* flow the counterpart
becomes the feedstock, so the implied efficiency is
`measured_output / counterpart` — at a fixed 1 PJ that exceeds the default
`TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT` of 1000% for any flow above
10 PJ, and clipping is on by default. The counterpart is therefore raised to
`peak_measured_output / (ceiling / 100)` whenever that exceeds the floor, so
the ceiling holds by construction rather than by an operator noticing a warning.
Outflow-only flows put the counterpart on the output side, where the implied
efficiency is very small rather than very large, and always take the floor.

Configuration is `ONE_SIDED_TRANSFER_BALANCE_POLICY` in
[`transfers_workflow.py`](../codebase/transfers_workflow.py); every synthesized
counterpart is announced on the run log with its value and year span.

Affected base years in the active 2024 vintage: `05_PRC` (outflow-only, both
`08.02` and `08.03`) and `13_PNG` (outflow-only). `21_VN` is inflow-only in
1998-2016 but two-sided in the base year. Outside seed scope, `04_CHL` is
inflow-only in 2024 only, and `07_INA` becomes outflow-only from the 2025
vintage. Rolling up to the `08 Transfers` parent does not resolve any of them —
the one-sidedness is present at leaf, subflow-sum and parent level alike.

### Projection availability and the base-year carry-forward

The 9th Outlook supplies post-base-year transfer values for only four APEC
economies — `01_AUS`, `03_CDA`, `09_ROK` and `20_USA`. For every other economy
with real base-year transfers the 9th holds exactly `0.0` in all projection
years, in both scenarios. Measured across the eleven active seed economies as of
2026-08-20: `01_AUS` and `20_USA` have projections; `02_BD`, `05_PRC`, `11_MEX`,
`12_NZ`, `13_PNG` and `21_VN` have a non-zero base year and an all-zero
projection; `19_THA` is zero in the base year too; `10_MAS` and `15_PHL` have no
9th transfer rows at all.

**Method: where the 9th supplies a projection it is used as-is, including
genuine zeros. Where it supplies none, the ESTO base-year value is carried
forward flat across the horizon** (see the **Base-year carry-forward** label).
Current Accounts remains base-year only and is unaffected.

The state is decided per `(economy, scenario)` before the projection is merged
into ESTO, because the merge in
[`ninth_projection_mapping.py`](../codebase/functions/ninth_projection_mapping.py)
fills unmatched projection years with `0.0` and after that point an absent
projection is indistinguishable from a supplied zero:

```text
projection_unavailable :=
      ESTO base-year transfer mass for the economy  >  tolerance
  AND 9th rows exist for (economy, scenario)
  AND every 9th projection year is exactly 0.0   (not NaN, not near-zero)
```

with `projection_supplied` (any non-zero projection year), `structural_zero`
(the base year is itself zero, so there is nothing to carry) and `no_ninth_rows`
as the complementary states. The "exactly `0.0`" test is deliberate — a
near-zero tolerance here would reclassify small real forecasts as missing.

**Why carry-forward rather than zero.** Zero is definitely wrong: it asserts
that transfers cease the year after the base year, which no source claims. The
honest reading of an all-zero projection is that the 9th has no transfer
projection for that economy, and this repository has neither the information nor
the remit to estimate how transfers should evolve — that belongs in the detailed
modelling. A flat carry-forward is the placeholder that looks reasonable in the
seed, keeps the base-year boundary continuous, and can be replaced by real
modelling later. It is recorded as a placeholder precisely so it is visible as
one.

This is the opposite treatment from stock changes and statistical differences,
which stay zero outside Current Accounts. Those are balancing residuals with no
projection meaning; transfers are a real physical flow that four economies do
project.

**Nice to have — proxy-based transfer projections.** The better long-term method
is the one already used for own-use and losses: drive each transfer process from
a related activity series rather than holding it flat. The natural pairing is
upstream transfers on fossil-fuel production, refinery and blending transfers on
refinery and petrochemical activity, and transfers unallocated on a mix of the
two. That would need its own activity configuration, fallback tiers and
conservation treatment, so it is out of scope for now and recorded here as a
future improvement rather than a planned change. See
[Proxy formula and source hierarchy](#proxy-formula-and-source-hierarchy) for
the pattern it would follow.

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
  method and therefore remain zero outside Current Accounts. Transfers are
  deliberately treated differently: they carry the base year forward rather than
  going to zero, because they are a real flow rather than a balancing residual.
- The transfer base-year carry-forward is a placeholder, not a projection. The
  intended replacement is activity-driven proxies on the own-use/loss pattern
  (fossil-fuel production, refinery and petrochemical activity, and a mix for
  the unallocated process). Revisit when detailed transfer modelling exists.
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

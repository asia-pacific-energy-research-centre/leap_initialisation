# PRC gas-works and refining dispatch / own-use findings

**Date:** 2026-08-26
**Status:** diagnosis complete; no implementation change made

## Executive conclusion

The two PRC Target differences do **not** have one root cause.

- **Gas works:** `Exogenous Capacity` is available capacity, not an output
  target. In 2023 LEAP dispatches exactly the 704.408210 PJ of gas-works-gas
  required by final demand plus the electricity- and heat-interim modules,
  which is only 91.3499% of the seeded 771.109586 PJ capacity. In addition,
  this gas-works template applies `Auxiliary Fuel Use` per unit of feedstock
  throughput, while the seed ratios were calculated per unit of gross output.
  Both effects are exact in the raw result. Under-dispatch reduces all direct
  inputs and output; the denominator mismatch inflates auxiliary fuels,
  especially natural gas. The offsets make the signed aggregate look correct
  while the fuel composition is wrong.
- **Oil refining:** the approximately 10% result difference is exactly the
  template's Target `Maximum Availability = 90%`. For every checked projection
  year, total positive LEAP refinery output is precisely 90% of seeded
  Exogenous Capacity. This is separate from the prior USA gross/net bug.
  Refining also has a second, fuel-level presentation/boundary issue: the
  converted LEAP balance exposes only the refinery process row, while the Ninth
  comparator is `09.07 + 10.01.11`. Products such as refinery gas and naphtha
  are therefore shown from LEAP without a separate `10.01.11` subtraction.

The dashboard rollup is behaving as configured. It is not the source of the
numbers, but its inclusive label can hide these offsetting composition errors.

## Evidence and scope

Primary evidence:

- archived PRC dashboard mapping chain:
  `C:\Users\Work\Downloads\05_PRC_Target_dashboard_archive_260826_123917`;
- seed workbook:
  `outputs/leap_exports/supply_reconciliation/baseline_seed/leap_import_baseline_seed_05_PRC_20260826.xlsx`, read with `header=2`;
- PRC template:
  `data/leap_export_templates/PRC clean slate 24_08.xlsx`, read with `header=2`;
- current producer and regression evidence in
  `codebase/functions/transformation_record_builder.py`,
  `codebase/supply_reconciliation/leap_io.py`, and
  `tests/test_transformation_efficiency_feedstock_only.py`.

The dashboard table was filtered to one comparison scope,
`esto_extended_leap_ninth`. The same rows are duplicated in the archive's
other comparison scopes, so summing across scopes would double-count them.

Official LEAP guidance confirms the observed semantics: Exogenous Capacity is
user-entered capacity, while actual generation depends on requirements,
availability, first simulation year, and dispatch rules. In particular, LEAP's
FAQ says that with no requirements nothing is generated, even when capacity
exists. See [LEAP FAQs, questions 5 and 9](https://leap.sei.org/help24/TechSupport/Frequesntly_Asked_Questions.htm?agt=index).

## Year-by-year signed comparison

Values are PJ. The LEAP conversion emits only the inclusive flow for these
modules, so the LEAP direct and standalone-own-use cells are intentionally
absent rather than zero.

### Gas works

| Source / boundary | 2022 | 2023 | 2030 | 2040 | 2060 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ninth `09.06.01` direct | -1,097.908 | -1,281.124 | -1,655.682 | -1,636.637 | -1,018.522 |
| Ninth `10.01.02` own use | -196.892 | -78.649 | -88.776 | -85.606 | -42.298 |
| Ninth inclusive | -1,294.800 | -1,359.773 | -1,744.458 | -1,722.243 | -1,060.820 |
| LEAP inclusive | -1,712.428 | -1,361.516 | -1,743.584 | -1,718.604 | -1,061.136 |
| LEAP minus Ninth inclusive | -417.628 | -1.743 | +0.874 | +3.639 | -0.316 |

The near-zero post-2022 aggregate residual is real, but it is cancellation and
not fuel-level agreement.

### Oil refining

| Source / boundary | 2022 | 2023 | 2030 | 2040 | 2060 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ninth `09.07` direct | +4,627.181 | -1,200.438 | -1,258.417 | -977.990 | -638.478 |
| Ninth `10.01.11` own use | -3,898.653 | -2,229.205 | -2,273.819 | -1,911.818 | -1,474.403 |
| Ninth inclusive comparison | +1,658.401 | -3,429.643 | -3,532.236 | -2,889.808 | -2,112.881 |
| LEAP inclusive | +1,432.217 | -3,036.289 | -3,129.095 | -2,555.452 | -1,861.676 |
| LEAP minus Ninth inclusive | -226.184 | +393.355 | +403.141 | +334.356 | +251.205 |

For 2022, the published inclusive refining row is not the simple signed sum of
the two preceding rows because the comparison frontier omits the 929.873 PJ
heat-own-use component that has no equivalent LEAP refinery result. From 2023
onward PRC refinery heat own use is zero, so direct plus own use equals the
inclusive total.

## Gas works: source -> seed -> LEAP result

### 2023 lineage

| Quantity | Ninth source | Seed expression / setting | LEAP result | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Gross gas-works-gas output | 771.109586 | Exogenous Capacity 771.109586; Output Share 100% | 704.408210 | Capacity is not a target; activity is demand-dispatched. |
| Process efficiency | 771.109586 / 2,052.233996 = 37.574155% | Process Efficiency 37.574155% | Implied feedstock throughput 1,874.714700 | LEAP output divided by efficiency. |
| Coal direct input | -1,483.294190 | Other bituminous coal Feedstock Share 72.277050% | feedstock -1,354.988480 | Direct input scales with dispatched throughput. |
| Coal own use | -0.447186 | Auxiliary Fuel Use 0.000579925 PJ/PJ | auxiliary -1.087195 | LEAP multiplies the ratio by throughput, not output. |
| Natural-gas direct input | -391.733207 | Feedstock Share 19.088136% | feedstock -357.848083 | Direct input scales with dispatched throughput. |
| Natural-gas own use | -76.166185 | Auxiliary Fuel Use 0.098774787 PJ/PJ | auxiliary -185.174545 | Wrong denominator in the seed/LEAP interface. |
| Natural gas inclusive | -467.899392 | share plus auxiliary ratio | -543.022627 | Exact sum of the preceding two LEAP components. |
| Coke-oven-gas direct input | part of -151.038960 coal products | Feedstock Share 6.945682% | -130.211730 | No auxiliary component; ordinary dispatch scaling only. |
| Motor-gasoline own use | -0.955295 | Auxiliary Fuel Use 0.001238858 PJ/PJ | -2.322506 | Pure auxiliary example proving the same denominator. |
| Other-products own use | -0.003979 | Auxiliary Fuel Use 0.000005160 PJ/PJ | -0.009674 | Minor-fuel example; same exact identity. |

The exact LEAP reconstruction is:

```text
actual output A       = 704.408210
efficiency e          = 0.3757415516
feedstock throughput F = A / e = 1,874.714700

natural gas
  feedstock = F * 0.1908813554 = 357.848083
  auxiliary = F * 0.0987747867 = 185.174545
  reported  = -(357.848083 + 185.174545) = -543.022627

motor gasoline
  auxiliary = F * 0.0012388582 = 2.322506
  reported  = -2.322506
```

These equations reproduce the raw LEAP rows to floating-point precision. The
seed generator instead constructed each auxiliary ratio as source own use /
gross output. For natural gas, `76.166185 / 771.109586 = 0.098774787`.
That relationship is source-correct but LEAP-interface-wrong for this module.

### Why activity is 704.408210 PJ

The raw balance contains the following 2023 gas-works-gas requirements:

```text
final demand                              633.652671
electricity interim input                  44.077171
heat plant interim input                   26.678368
total requirement                         704.408210
gas works output                          704.408210
```

The template settings are `Dispatch Rule = PercentShare`, `Process Share =
100%`, `Maximum Availability = 100%`, `Minimum Utilization = 0%`, and `First
Simulation Year = FirstScenarioYear`. The output fuel has `Shortfall Rule =
RequirementsRemainUnmet` and `Surplus Rule = SurplusAvailable`. Nothing in
those settings tells LEAP to manufacture the remaining 66.701376 PJ merely
because capacity exists.

The same pattern persists:

| Year | Seed capacity | LEAP output | Utilisation |
| --- | ---: | ---: | ---: |
| 2023 | 771.109586 | 704.408210 | 91.3499% |
| 2030 | 1,187.122653 | 1,107.892642 | 93.3259% |
| 2040 | 1,205.301150 | 1,126.707562 | 93.4793% |
| 2060 | 912.670502 | 874.049645 | 95.7684% |

### Gas-works hypotheses

| Hypothesis | Finding |
| --- | --- |
| Capacity is under-utilised because there is no output requirement | **Proven.** Output equals total requirement, not capacity. |
| Capacity has a wrong gross/net or input/output basis | **Ruled out for the seeded value.** It equals the Ninth gross output and is an output-capacity value; it is simply not a production target. |
| Feedstock / auxiliary denominator differs from the generator assumption | **Proven for auxiliary use.** Feedstock shares are applied to throughput as expected; auxiliary ratios are also applied to throughput, though generated per gross output. |
| LEAP conversion maps gross to net incorrectly | **Not the numerical cause of the gas rows.** The conversion faithfully maps the already-combined LEAP process balance to the inclusive comparison row. |
| Dashboard hides offsetting composition errors | **Proven.** The signed aggregate is close while coal, natural gas, and gas-works-gas are materially different. |

## Refining: source -> seed -> LEAP result

### 2023 process boundary

| Quantity | Value (PJ unless stated) |
| --- | ---: |
| Ninth gross `09.07` positive output | 31,646.825381 |
| Ninth same-product `10.01.11` own use | 1,598.136475 |
| Ninth net deliverable positive output | 30,048.688907 |
| Seed Exogenous Capacity | 30,048.688907 |
| Template Target Maximum Availability | 90% |
| LEAP total positive refinery output | 27,043.820016 |
| `27,043.820016 / 30,048.688907` | **90.000000%** |
| Ninth crude-oil feedstock | 32,847.263643 |
| Seed Process Efficiency | 96.345393% |
| LEAP crude-oil input | 29,540.828643 |

The current code and workbook use a deliberate refinery exception:
`codebase/supply_reconciliation/leap_io.py` selects
`deliverable_output_values` for Oil Refining capacity because LEAP grosses
feedstock up when the process also consumes its own output. This is covered by
`test_refinery_capacity_uses_deliverable_output_and_preserves_runtime_additions`.
That implementation contradicts the still-active prose in work-queue item
[30] and SEED-C025, which say refinery capacity is gross. The executable code,
test, seed workbook, and LEAP result all show the net-capacity exception.

### Exact output and external-own-use scaling

The seed's Output Shares use gross `09.07` output shares, and its Auxiliary Fuel
Use ratios use `10.01.11 / gross output`. LEAP applies both to its actual
27,043.820016 PJ output activity:

| Fuel | Seed share / auxiliary ratio | Exact LEAP calculation | LEAP result | Ninth inclusive |
| --- | ---: | ---: | ---: | ---: |
| Gas and diesel oil | Output Share 26.240193% | 27,043.820016 x 0.26240193 | +7,096.350567 | +8,304.188124 |
| Refinery gas | Output Share 2.983194% | 27,043.820016 x 0.02983194 | +806.769616 | +188.793629 |
| Naphtha | Output Share 8.983685% | 27,043.820016 x 0.08983685 | +2,429.531602 | +2,307.875553 |
| Natural gas | Auxiliary 0.003687246 PJ/PJ | 27,043.820016 x 0.003687246 | -99.717231 | -116.689646 |
| Electricity | Auxiliary 0.016253725 PJ/PJ | 27,043.820016 x 0.016253725 | -439.562816 | -514.378800 |

The equations reproduce the raw rows to floating-point precision. Same-product
auxiliary use affects LEAP's internal feedstock requirement, but the raw
transformation balance does not expose a standalone `10.01.11` result to
subtract from the refinery product rows. In 2023 the raw crude input is
1,471.173148 PJ above `actual positive output / Process Efficiency`, consistent
with LEAP grossing feedstock up for internal auxiliary requirements. The exact
internal gross-up formula cannot be uniquely recovered from this one balance
export and should be isolated in the controlled test below.

### Refinery hypotheses

| Hypothesis | Finding |
| --- | --- |
| Already-known gross/net bug is the 10% difference | **Ruled out as the 10% cause.** The uniform factor is Maximum Availability. Gross/net semantics remain a separate fuel-composition issue. |
| Unutilised capacity analogous to gas works | **Partly, but for a different reason.** Refining is hard-capped at 90% availability every projection year; gas works is demand-dispatched below a 100% ceiling. |
| Ninth source imbalance | **Not supported.** The 2023 gross output/feedstock efficiency, own-use split, and inclusive balance reconcile internally. |
| Mapping/conversion issue | **Proven for same-product presentation.** The inclusive comparator contains `10.01.11`; LEAP supplies only the process balance and no separable own-use row. |
| Combination | **Proven.** Maximum Availability explains the uniform 10% activity loss; boundary presentation explains the material fuel reshuffling, especially refinery gas. |

## Smallest safe remedies

### Gas works

Use a PRC-only controlled copy first.

1. Force the intended baseline-seed output by writing Target `Minimum
   Utilization = 100%` on
   `Transformation\Gas works plants\Processes\Gas works plants`. Do not add
   own use to Exogenous Capacity; keep capacity equal to gross `09.06.01`
   output.
2. Rebase each Gas works `Auxiliary Fuel Use` ratio to the denominator LEAP
   actually uses in this module: source `10.01.02` own use divided by gross
   `09.06.01` feedstock throughput. For 2023 natural gas this is
   `76.166185 / 2,052.233996 = 0.037114...`, not 0.098774787.
3. Keep Process Efficiency as gross output / direct feedstock and keep the
   existing feedstock shares.
4. Validate fuel by fuel against `09.06.01 + 10.01.02`; an aggregate-only
   tolerance is insufficient.

If LEAP does not accept or safely apply a 100% minimum utilisation for this
module, the alternative is an explicit production/output requirement. Do not
inflate Exogenous Capacity to compensate for dispatch.

### Oil refining

1. The confirmed narrow fix for the uniform difference is to write Target
   `Maximum Availability = 100%` for Oil Refining during the baseline-seed
   import. Do not inflate Exogenous Capacity by `1 / 0.9`; that would misstate
   the capacity boundary.
2. In the same controlled copy, compare two fuel-boundary formulations at 100%
   availability:
   - current net-deliverable capacity with gross output shares / gross
     auxiliary denominators; and
   - net-deliverable capacity with net-inclusive output shares and auxiliary
     ratios rebased to net deliverable output, while retaining gross
     output/feedstock efficiency.
3. Accept a formulation only if the raw LEAP balance reproduces crude input,
   external auxiliary fuels, and each same-product `09.07 + 10.01.11` value.
   Do not repair the dashboard by inferred subtraction unless LEAP exposes a
   separately auditable own-use result.

## Focused regression tests

- Gas works: a fixture where gross output, direct feedstock, and own use are all
  non-zero; assert the written capacity, minimum utilisation, efficiency,
  feedstock shares, and throughput-denominator auxiliary ratios reconstruct
  every inclusive fuel.
- Gas works: retain the PRC 2023 exact identities above as a regression case;
  fail if aggregate agreement masks a material fuel residual.
- Refining: assert the baseline seed explicitly owns Maximum Availability for
  the tested scenario and does not silently inherit 90% from a template.
- Refining: assert total positive output equals intended net-deliverable output
  at 100% availability, and separately assert gross feedstock and each external
  auxiliary fuel.
- Refining: retain refinery gas and naphtha as same-product cases and natural
  gas/electricity as external cases.
- Conversion: assert LEAP's single process row and the Ninth `09 + 10.01`
  frontier are labelled as an inclusive comparison, while documenting whether
  the LEAP result is gross or net for each fuel.

## Unresolved / next evidence required

- A controlled LEAP import/export is required to prove that Gas works
  `Minimum Utilization = 100%` forces the intended output without an unwanted
  system-side consequence.
- The same test must confirm the module-specific denominator for auxiliary use
  after the proposed ratio rebasing. The archived balance proves what LEAP did,
  but not whether another LEAP setting can change that denominator.
- For refining, Maximum Availability at 100% is expected to remove the uniform
  10% activity loss, but a fresh export is required. The same run must decide
  which output-share/auxiliary denominator formulation reproduces the
  fuel-level inclusive boundary.
- The exact internal LEAP feedstock gross-up formula for same-product refinery
  auxiliary use is not exposed by the archived balance. Record process output,
  feedstock input, auxiliary consumption, and capacity from a minimal two-fuel
  refinery test to identify it directly.
- Active documentation must be reconciled after the controlled test:
  work-queue item [30] and SEED-C025 currently describe a gross refinery
  capacity basis, while executable code and tests intentionally use net
  deliverable refinery capacity.

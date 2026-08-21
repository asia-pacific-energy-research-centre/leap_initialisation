# Own-use of a process's own output is inflating transformation feedstock

**Date:** 2026-08-20
**Status:** diagnosis complete, no code changed. Distinct from WEBQ-002 — see
[the WEBQ-002 note](webq_002_synthetic_own_use_rollup_findings.md).

> **READ §10 FIRST.** Two earlier conclusions in this note were wrong and are
> retained only as a record. Running the current producer code shows **coke
> ovens AND blast furnaces are both calculated correctly today** — the export
> analysed in §2 is stale. The real defect is in §10: **the 9th Outlook carries
> no coal transformation at all after the base year for 10 of 11 economies.**

---

## 1. The defect in one line

When a transformation process consumes some of the fuel it produces, that
self-consumption is registered as LEAP **Auxiliary Fuel Use** instead of being
netted off the process output. LEAP treats auxiliary use as demand *on top of*
output, grosses production up to cover it, and therefore burns more feedstock.

```
inflated_feedstock = (gross_output + own_use_of_own_output) / efficiency
```

## 2. Confirmed magnitudes (`01_AUS`, Target)

Source: `outputs/diagnostics/ah72_investigation_20260818/leap_balance_source_review.csv`
and `leap_review_tools/outputs/aus_detailed_road_app_test/.../01_AUS/balance_review/`,
against raw `data/00APEC_2024_low_with_subtotals.csv`.

| Process | Feedstock | LEAP | ESTO | Error |
|---|---|---:|---:|---|
| Coke ovens | 01.01 Coking coal | −140.107 | −116.622 | **+23.485 PJ (+20.1%)** |
| Blast furnaces | 02.01 Coke oven coke | −83.862 | −41.931 | **+41.931 PJ (+100.0%)** |

**Two variables are wrong per process, not one.** The self-consumed gas is
double-counted: once as an output the process must make, and once as an
auxiliary demand it must satisfy. So the process is required to produce it
twice — feedstock inflates, *and* the net gas output fails to cancel:

| Process | Row | LEAP | Should be | Error |
|---|---|---:|---:|---|
| Coke ovens | 01.01 Coking coal | −140.107 | −116.622 | **−23.485** |
| Coke ovens | 02.03 Coke oven gas | +16.980 | **0.000** | **+16.980** |
| Coke ovens | 02.01 Coke oven coke | +62.127 | +62.127 | ok |
| Coke ovens | 02.07 Coal tar | +5.214 | +5.214 | ok |
| Coke ovens | 17 Electricity | −0.438 | −0.438 | ok |
| Blast furnaces | 02.01 Coke oven coke | −83.862 | −41.931 | **−41.931** |
| Blast furnaces | 02.04 Blast furnace gas | +16.775 | **0.000** | **+16.775** |
| Blast furnaces | 08.01 Natural gas | −4.523 | −4.523 | ok |
| Blast furnaces | 17 Electricity | −0.438 | −0.438 | ok |

At the "(including own use)" boundary the gas must net to zero — ESTO produces
16.980 and consumes 16.980. LEAP shows the full production and none of the
consumption.

**The boundary therefore does not conserve:**

| Process | LEAP net | ESTO net | Discrepancy |
|---|---:|---:|---:|
| Coke ovens | −56.224 | −49.719 | **−6.505 PJ** |
| Blast furnaces | −72.048 | −46.892 | **−25.156 PJ** |

AUS coal transformation as a whole destroys ~31.7 PJ more energy than ESTO says
it does.

**Reconstruction, exact to six decimals on both processes:**

| | gross output | own use of own output | efficiency | predicted feedstock | LEAP feedstock | residual |
|---|---:|---:|---:|---:|---:|---:|
| Coke ovens | 84.321545 | 16.980300 (coke oven gas) | 0.723033 | 140.106822 | 140.106822 | **0.000000** |
| Blast furnaces | 16.775000 | 16.775000 (blast furnace gas) | 0.400062 | 83.861998 | 83.861998 | **0.000000** |

Two processes, two different efficiencies, zero residual on both. The
blast-furnace figure is exactly 100% only because its own use happens to equal
its output; the rule is `own_use / efficiency`, not doubling.

## 3. It persists into projection years

| year | LEAP feedstock | gross output | auxiliary ratio | implied efficiency | feedstock if netted | error |
|---|---:|---:|---:|---:|---:|---|
| 2022 | 140.1068 | 84.3215 | 0.20138 | 0.723033 | 116.6220 | +23.485 PJ (+20.1%) |
| 2023 | 139.7806 | 84.2026 | **0.20138** | 0.723698 | 116.3505 | +23.430 PJ (+20.1%) |

The auxiliary ratio is byte-identical across the two years. Efficiency moves
with the 9th projection; the ratio does not. This follows from the producers
being `*_by_year` functions that compute the ratio for every year column, so the
base-year mistake propagates across the whole horizon at a constant percentage.

## 4. Root cause — exact locations

Four functions, two live pairs. Each excludes only the **feedstock** fuel from
being turned into auxiliary use. None checks whether the loss fuel is one of the
process's **own outputs**.

| File | Function | Line | Predicate |
|---|---|---|---|
| `codebase/functions/transformation_series_utils.py` | `merge_loss_into_auxiliary_by_year` | ~133 | `if label == feedstock_label: continue` |
| `codebase/functions/transformation_series_utils.py` | `build_auxiliary_from_losses_by_year` | ~108 | `if str(label) in exclude: continue` (`exclude` = feedstock labels only) |
| `codebase/functions/transformation_record_builder.py` | `merge_loss_into_auxiliary` | ~372 | same feedstock-only test |
| `codebase/functions/transformation_record_builder.py` | `build_auxiliary_from_losses` | ~351 | **no exclusion at all** |

The module header of `transformation_analysis_utils.py` states the intended
behaviour plainly at lines 8–9: *"Computes efficiency as output / (feedstock +
losses)… Treats own-use/loss fuels as auxiliary fuels unless they match
feedstock."* Coke oven gas is neither feedstock nor a genuine auxiliary import —
it is the process's own product — so it falls through the wrong branch.

Verification: auxiliary ratio applied by LEAP = 16.9803 / 84.3215 = 0.20138, and
84.3215 × 1.20138 / 0.723033 = 140.106822.

**Note on the fix:** the exclusion needs the process's *output fuel labels*,
which none of these four functions currently receives — they take an output
*total*, not a label set. So this is a small signature change plus call-site
threading, not a one-line edit.

### 4a. One thing still unresolved — which component carries the error

The relationship `feedstock = (output + aux) / efficiency` is proven exactly.
But two algebraically identical readings fit the same data, and the observed
numbers cannot separate them:

- **(i)** the seed writes the *correct* efficiency 0.723033 and a coke-oven-gas
  auxiliary ratio of 0.20138, and LEAP grosses production up to cover the
  auxiliary demand; or
- **(ii)** the seed writes a *wrong* efficiency of 0.601840
  (= 0.723033 × 84.3215 / 101.3018) and LEAP faithfully computes
  `feedstock = output / efficiency`.

`0.723033 × 84.3215 / 101.3018 = 0.601840` and `84.3215 / 0.601840 = 140.1068`,
so both reproduce the export.

**Structural confirmation from the seed workbook.** In
`leap_import_baseline_seed_01_AUS_*.xlsx` the coke-oven process carries both:

```
Transformation\Coke ovens\Output Fuels\Coke oven gas
Transformation\Coke ovens\Processes\Coke ovens\Auxiliary Fuels\Coke oven gas
```

The same fuel is simultaneously an output of the process and an auxiliary fuel
of that same process. That is the defect in structural form.

**But the written values do not match either reading.** From
`INIT_01_AUS_UPDATE_20260802_231118`, coke ovens, 2023:

| Variable | Value |
|---|---:|
| Process Efficiency | **121.415 %** |
| Auxiliary Fuel Use (Coke oven gas) | 0.125488 |
| Historical Production / Exogenous Capacity | 134.383 |

121.4% is neither the physical 72.3% of reading (i) nor the 60.2% of reading
(ii), and a coke oven cannot exceed 100%. The producer's own intent is
unambiguous — `compute_efficiency_by_year` is `output / feedstock` and its
docstring states *"LEAP treats auxiliary fuels separately from feedstock fuels.
Their energy must therefore not be added to the process-efficiency
denominator."* So the emitted 121.4% is itself unexplained.

**Why this could not be closed here:** the seed workbook available (2026-08-02)
and the balance export analysed (`aus_detailed_road_app_test`, vintage unknown)
come from different runs, so their numbers are not expected to reconcile.
Settling it needs a seed and the export generated **from that same seed**.

### 4b. The open question is about LEAP, not about this repo

Everything hinges on what LEAP does with Auxiliary Fuel Use when the auxiliary
fuel is produced by the same process:

- **If LEAP draws auxiliary fuel from the system fuel pool**, then efficiency
  `output / feedstock` = 0.723 is already correct, the coke oven's own gas
  output supplies its own auxiliary draw, and the feedstock inflation must
  originate elsewhere.
- **If LEAP requires the process to produce enough to cover its own auxiliary
  draw**, then efficiency must be restated as `(output + auxiliary) / feedstock`
  = 0.869 for feedstock to land on 116.622.

This is a LEAP behavioural question, not a code question, and it must be
answered before the fix is written.

### 4d. REVISION — the code already implements the agreed semantics

The §4 "four helper functions" diagnosis is **too shallow**. Those functions do
the auxiliary routing, but a downstream component is supposed to reconcile it,
and it already exists.

`transformation_record_builder.py:927` `_normalize_process_boundary_for_leap`,
added in **`c003856`, 2026-07-28** ("normalize shared transformation process
boundary"), is written for exactly this case. Its docstring:

> ESTO transformation output is gross. When a module also consumes one of its
> output fuels as auxiliary energy, LEAP must retain one gross basis for
> capacity, output shares, auxiliary ratios, and efficiency; LEAP then records
> the auxiliary consumption separately in the module balance. This applies to
> every transformation module, not only Oil Refining: coke ovens, blast
> furnaces, and LNG regasification can have the same overlap.

It detects `overlapping_auxiliary_labels` — auxiliary fuels that are also output
fuels of the same process — which is precisely the defect signature. It is
called at line 1168 with `preserve_gross_output_basis=True`. **This is the
agreed semantics of §4c, already built.**

#### The live defect is its documented bail-out

Same docstring, next paragraph:

> A fully self-consuming process has no valid auxiliary-per-net-output
> denominator. Preserve its gross representation until that edge case has a
> dedicated LEAP loss representation.

Implemented at line ~1080: if net total deliverable output falls to zero in any
year with positive gross output, it returns `zero_net_deliverable_preserved_gross`
and leaves the gross representation in place.

| Process | Gross outputs | Same-module auxiliary | Net total | Bails out? |
|---|---:|---:|---:|---|
| Coke ovens | coke 62.127 + gas 16.980 + tar 5.214 = **84.322** | gas 16.980 | **67.341** | no |
| Blast furnaces | blast furnace gas **16.775** (only output) | bfg 16.775 | **0.000** | **YES** |

**AUS blast furnaces are a fully self-consuming process.** Their only output is
blast furnace gas, and own use consumes all of it. They hit the deferred edge
case exactly, keep the gross representation, and that is what produces the
+41.931 PJ (+100%) feedstock error. This is a known, documented, deliberately
deferred gap — not an oversight.

**Coke ovens should not hit it** (net 67.341 > 0), so the +23.485 PJ coke-oven
error is unexplained by this path. Either the analysed LEAP area was seeded
before 2026-07-28, or something else is wrong on the coke-oven path. The review
CSV is dated 2026-08-18, but that is when the *review* ran, not when the area
was seeded — so this does not settle it.

#### Rule violation to raise

Per the standing rule that **process efficiency is always output ÷ feedstock**,
the value found in `INIT_01_AUS_UPDATE_20260802_231118` (dated 2026-08-02, i.e.
*after* `c003856`) should be raised:

| Variable | Value | Expected |
|---|---:|---|
| Process Efficiency, coke ovens, 2023 | **121.415 %** | ≤ 100 %, physically ~72 % |
| Output share, coke oven coke | 98.397 % | ~92.3 % of net output |
| Output share, coal tar | 1.603 % | ~7.7 % of net output |
| Output share, coke oven gas | 0 % | 0 % — correctly netted |

The gas share being zero shows the normalizer *did* run and net the overlap. But
the remaining shares and the >100% efficiency do not reconcile with any
AUS coke-oven figures I can construct. Unexplained; needs its own look.

The code's stated intent matches the rule everywhere it is written down —
`compute_efficiency_by_year`, `calculate_efficiency`, and the
`build_*_record` docstring all say output ÷ feedstock with auxiliaries excluded.
So the violation is in the values produced, not in the intent.

## 4c. Agreed target (decision, 2026-08-20)

**Keep the auxiliary representation.** Gross values are the priority, because
own use is extracted from LEAP results separately from the balance tables and
must be precise in its own right. Concretely, after the fix:

| Quantity | Required value (AUS coke ovens, 2022) |
|---|---:|
| `Output Fuels\Coke oven gas` (gross) | **16.980** — unchanged |
| `Auxiliary Fuels\Coke oven gas` (gross, when multiplied out) | **16.980** |
| Derived feedstock, coking coal | **116.622** |
| Balance-table net for coke oven gas | **0.000** (16.980 produced − 16.980 consumed) |
| Separately extracted own use | **16.980** |

Rejected alternative: netting own use off the output. It would zero the gross
gas output row and make own use unrecoverable from the LEAP results.

## 5. Exposure across economies

Detection is a set intersection — own-use fuels that are also outputs of the
same process — so it carries no arithmetic assumption. Base year 2022,
`00APEC_2024_low_with_subtotals.csv`, the four processes that have
`loss_flow_codes` configured:

| Process | Economies affected | Notes |
|---|---:|---|
| Oil refineries | 14 | refinery gas, and in several economies also motor gasoline, fuel oil, LPG, petroleum coke |
| Coke ovens | 9 | coke oven gas (coke oven coke in PRC and MEX) |
| Blast furnaces | 6 | blast furnace gas |
| Gas works plants | 1 | gas works gas, `05PRC`, negligible |
| **Total** | **30 economy × process combinations, 14 distinct economies** | |

Worst percentage errors after AUS blast furnaces (100%): `11MEX` blast furnaces
~74%, `18CT` blast furnaces ~30%, `04CHL` blast furnaces ~28%, `09ROK` blast
furnaces ~18%, `20USA` blast furnaces ~21%, `20USA` coke ovens ~5%.

**Caveat on magnitude, oil refineries.** The scan estimates efficiency as
total positive ÷ total negative. That proxy reproduced the AUS coke-oven and
blast-furnace LEAP values exactly, because those processes have a single
feedstock. It is **not** reliable for refineries: the real producer uses a
*primary* feedstock via `compute_primary_io`, and the proxy returns efficiencies
above 1.0 for `05PRC`, `08JPN`, `18CT`, `04CHL`. Treat refineries as
**mechanism-confirmed, magnitude-unverified** until checked against an actual
refinery export.

## 6. Relationship to WEBQ-002

WEBQ-002 does not cause this — it writes labels, never values. But it is why the
error stayed invisible. The affected rows are exactly the ones WEBQ-002
mislabels: the diagnostic showed `reference_unavailable` (no comparator to
check against) and the instruction *"leave the process efficiency and auxiliary
values unchanged."* That is precisely where the defect lives.

Fixing WEBQ-002 does not change a single number, but it stops the diagnostic
pointing away from this.

## 7. Suggested next steps

1. Verify one refinery economy against a real export before trusting the §5
   refinery magnitudes.
2. Decide the correct semantics with the modeller: net own-use-of-own-output off
   the output (making the "(including own use)" boundary net to zero, as ESTO
   does), versus keeping it as auxiliary and correcting the efficiency instead.
   These give different LEAP structures, not just different numbers.
3. Thread the output fuel labels into the four functions in §4 and exclude them,
   with a regression test pinning AUS coke ovens at 116.622 and AUS blast
   furnaces at 41.931.
4. Re-seed and re-export the affected economies. 14 economies are in scope.

---

## 8. RESOLVED — what the current code actually produces

Rather than dating artifacts, the producer was run directly against current code
with real AUS ESTO data (`summarize_transformation_flows`, base year 2022).

### Coke ovens — correct today

| Emitted value | Result | Verdict |
|---|---:|---|
| Process efficiency | 0.723033 | ✅ = output ÷ feedstock, obeys the rule |
| Feedstock, coking coal | 116.622 | ✅ matches ESTO |
| Gross outputs | coke 62.127, gas 16.980, tar 5.214 | ✅ gross preserved |
| Auxiliary ratio, coke oven gas | 0.2014 | ✅ × 84.322 = 16.980, the true own use |

Under the standing rule that auxiliary fuel is drawn from the system pool, LEAP
computes `feedstock = output ÷ efficiency` = 84.322 ÷ 0.723033 = **116.622**,
which is right. **The 140.107 in §2 cannot be produced by today's code.** That
export is stale.

### Blast furnaces — broken today

| Emitted value | Result | Verdict |
|---|---:|---|
| Process efficiency | 0.400062 | = output ÷ feedstock, obeys the rule |
| Feedstock, coke oven coke | 41.931 | matches ESTO |
| Gross output | blast furnace gas 16.775 (only output) | gross preserved |
| **Auxiliary ratio, blast furnace gas** | **1.0** | ❌ the process must consume **100%** of what it makes |
| Net deliverable output | **0.000** | ❌ degenerate process |

`output_values == gross_output_values`, confirming
`_normalize_process_boundary_for_leap` took its documented bail-out
(`zero_net_deliverable_preserved_gross`). AUS blast furnaces deliver nothing:
every unit of gas produced is consumed by the plant itself.

An auxiliary ratio of exactly 1.0 is the signature. **This is the live defect,
and it is the case the docstring says is deferred**: *"A fully self-consuming
process has no valid auxiliary-per-net-output denominator. Preserve its gross
representation until that edge case has a dedicated LEAP loss representation."*

Six economies have blast furnaces (§5): `01AUS`, `09ROK`, `18CT`, `20USA`,
`11MEX`, `04CHL`.

### Not verified — projection years

In this minimal run only ESTO data was supplied, so 2023+ carried no values and
efficiency came out 0.0 for every projection year in both processes. That is an
artifact of the cut-down input, **not** evidence of a projection bug. A real run
merges the 9th projection first. Whether projection-year efficiencies are
populated correctly is untested here and remains open.

## 9. Revised recommendation

1. **Fix the fully-self-consuming case** — a process whose auxiliary ratio
   reaches 1.0 has no valid LEAP representation as a transformation process.
   This is the documented deferred gap and the only confirmed live defect.
   Six economies affected.
2. **Do not change the coke-oven path.** It obeys the rule and produces correct
   values. §2's numbers come from a stale export.
3. **Re-export AUS** and re-run the balance review before trusting any remaining
   coal-transformation discrepancy — the current review evidence predates the
   2026-07-28 boundary normalizer.
4. **Still to explain:** the 121.415% process efficiency found in the
   2026-08-02 seed (§4d). Today's code emits 72.3%, so that artifact came from
   somewhere else. Worth one look, since it violates the rule outright.

---

## 10. THE ACTUAL DEFECT — coal transformation has no 9th projection

### 10a. Correction: §8's blast-furnace conclusion was wrong

An auxiliary ratio of 1.0 is not a defect. It is `own use ÷ output`, computed
the same way for every fuel; the fact that the own-use fuel happens to be the
process's own output does not change the arithmetic. Verified against ESTO:

| Emitted variable | Reconstructs to | ESTO | Verdict |
|---|---:|---:|---|
| feedstock = output ÷ efficiency = 16.775 ÷ 0.400062 | 41.931 | 41.931 | ✅ |
| aux draw, blast furnace gas = 1.0 × 16.775 | 16.775 | 16.775 | ✅ |
| aux draw, natural gas = 0.2696 × 16.775 | 4.523 | 4.523 | ✅ |
| aux draw, electricity = 0.026125 × 16.775 | 0.438 | 0.438 | ✅ |
| balance-table net for blast furnace gas | 0.000 | 0.000 | ✅ |
| own use, separately extractable | 16.775 | 16.775 | ✅ |

**Both coke ovens and blast furnaces are correct in current code.** There is no
own-use gross-up defect. Sections 1–9 describe a stale export.

### 10b. What is actually wrong

`data/merged_file_energy_ALL_20251106.csv`, scenario Target, sub1sector
`09_08_coal_transformation`, subtotals excluded. Absolute PJ by year:

| Economy | Level | 2022 | 2025 | 2030 | 2040 | 2050 |
|---|---|---:|---:|---:|---:|---:|
| 05_PRC | child | 39,612.3 | **0.0** | 0.0 | 0.0 | 0.0 |
| 08_JPN | child | 2,873.1 | **0.0** | 0.0 | 0.0 | 0.0 |
| 09_ROK | child | 1,497.1 | **0.0** | 0.0 | 0.0 | 0.0 |
| 20_USA | child | 936.6 | **0.0** | 0.0 | 0.0 | 0.0 |
| 18_CT | child | 546.4 | **0.0** | 0.0 | 0.0 | 0.0 |
| 03_CDA | child | 173.1 | **0.0** | 0.0 | 0.0 | 0.0 |
| 11_MEX | child | 91.6 | **0.0** | 0.0 | 0.0 | 0.0 |
| 12_NZ | child | 37.7 | **0.0** | 0.0 | 0.0 | 0.0 |
| 04_CHL | child | 34.8 | **0.0** | 0.0 | 0.0 | 0.0 |
| 01_AUS | child | 226.1 | **0.0** | 0.0 | 0.0 | 0.0 |
| **16_RUS** | **PARENT (`sub2sectors = x`)** | 2,195.8 | **1,882.7** | 576.3 | 34.4 | 0.0 |

**Ten of eleven economies lose coal transformation entirely after the base
year.** China's 39,612 PJ of coke ovens and blast furnaces does not decline —
it ceases. That is not a projection.

The single exception, Russia, is also the single economy that publishes at the
**parent** level (`sub2sectors = x`) rather than at the coke-oven /
blast-furnace children. Its projection is intact and plausible
(−1,214.9 coking coal in 2022 → −1,041.6 → −318.8 → −19.1 → 0).

That correlation is the lead: the projection survives where the data sits on
the parent row and disappears where it sits on the child rows.

### 10c. Why the approved carry-forward does not rescue it

P3-06 approved carrying the ESTO base year forward where the 9th is absent. It
does not fire here, for two compounding reasons:

1. `_fill_general_missing_ninth_children`
   (`ninth_projection_mapping.py:761`) explicitly **excludes**
   `COAL_PARENT_ESTO_FLOW` and `GAS_PARENT_ESTO_FLOW` — coal is meant to use its
   own dedicated path.
2. That fill targets children **missing** beneath a parent that still has a
   value. Here the child rows are *present and explicitly zero*, and the parent
   is zero too, so there is nothing to detect and nothing to distribute.

**Present-but-zero is not treated as missing.** This is the same shape as
work queue item **[50]** for transfers, and the same trap recorded in the
zero-fill mechanisms review.

### 10d. What this means for the seed

With no 9th projection, LEAP's coke ovens and blast furnaces flatline from 2025
in ten economies. The base-year values are right; everything after is empty.
That is the projection problem, and it has nothing to do with own use.

### 10e. Next steps

1. Decide whether the 9th table is *expected* to carry child-level coal
   transformation projections. If yes, this is an input-data defect to raise
   upstream, not a code fix.
2. If the data is as intended, extend the approved base-year carry-forward to
   treat **present-but-zero** projection rows as absent, for coal transformation
   specifically — mirroring whatever is agreed for item [50].
3. Compare against the Russia parent-level path, which works, before choosing
   between the two.

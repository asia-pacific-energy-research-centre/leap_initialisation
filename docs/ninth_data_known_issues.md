# Known issues in the 9th Outlook projection data

**Purpose.** A standing record of defects and gaps in the maintained 9th table
so they are diagnosed once, not repeatedly rediscovered from downstream
symptoms. Every entry here is an **input-data** characteristic. Where our code
should compensate, that is stated separately.

**Source scanned:** `data/merged_file_energy_ALL_20251106.csv`, scenario Target,
subtotal rows excluded (`subtotal_layout` / `subtotal_results`).
**Scan date:** 2026-08-20.

**How to read this.** "Dead after base year" means the sector has a non-trivial
2022 value and is **exactly zero in every projection year** (2025, 2030, 2035,
2040, 2050, 2060). That is different from declining to zero, which several
sectors legitimately do.

---

## 1. Summary scan

| 9th sector | Economies with a base year | Of which dead after 2022 | Base-year PJ lost | Category |
|---|---:|---:|---:|---|
| `18_02_chp_plants` | 10 | **6** | 55,599.5 | **gap** |
| `09_08_coal_transformation` | 11 | **10** | 46,028.7 | **gap** |
| `11_statistical_discrepancy` | 19 | 16 | 14,493.4 | expected |
| `06_stock_changes` | 19 | **19** | 8,539.8 | expected |
| `08_03_products_transferred` | 5 | **5** | 5,203.9 | **gap** |
| `08_02_interproduct_transfers` | 5 | **5** | 781.1 | **gap** |
| `09_02_chp_plants` | 11 | 7 | 690.5 | **gap** |
| `08_transfers` | 7 | 3 | 448.0 | **gap** |
| `09_07_oil_refineries` | 20 | 1 | 97.1 | **gap** |
| `09_x_heat_plants` | 5 | 2 | 88.8 | **gap** |
| `19_02_heat_plants` | 5 | 1 | 34.7 | **gap** |
| `09_04_electric_boilers` | 1 | 1 | 9.5 | **gap** |
| `09_05_chemical_heat_for_electricity_production` | 2 | 2 | 2.6 | **gap** |
| `09_11_charcoal_processing` | 5 | 1 | 1.1 | **gap** |
| `19_01_chp_plants` | 5 | 1 | 1.0 | **gap** |

### Expected, not defects

- **`06_stock_changes`** — dead in all 19 economies. Stock change is a
  historical balancing item; the Outlook does not project it. Treat as by
  design.
- **`11_statistical_discrepancy`** — dead in 16 of 19. Also a residual, not a
  modelled quantity. The three economies that *do* carry it forward
  (`03_CDA`, `04_CHL`, `09_ROK`) are the anomaly, not the sixteen that don't.

Everything else in the table is a genuine coverage gap.

---

## 2. `09_08_coal_transformation` — dead in 10 of 11 economies

**The largest transformation-side gap, and fully characterised.**

| Economy | Level published | 2022 | 2025 | 2030 | 2040 | 2050 |
|---|---|---:|---:|---:|---:|---:|
| 05_PRC | child | 39,612.3 | **0** | 0 | 0 | 0 |
| 08_JPN | child | 2,873.1 | **0** | 0 | 0 | 0 |
| 09_ROK | child | 1,497.1 | **0** | 0 | 0 | 0 |
| 20_USA | child | 936.6 | **0** | 0 | 0 | 0 |
| 18_CT | child | 546.4 | **0** | 0 | 0 | 0 |
| 01_AUS | child | 226.1 | **0** | 0 | 0 | 0 |
| 03_CDA | child | 173.1 | **0** | 0 | 0 | 0 |
| 11_MEX | child | 91.6 | **0** | 0 | 0 | 0 |
| 12_NZ | child | 37.7 | **0** | 0 | 0 | 0 |
| 04_CHL | child | 34.8 | **0** | 0 | 0 | 0 |
| **16_RUS** | **parent** | 2,195.8 | **1,882.7** | 576.3 | 34.4 | 0 |

China's 39,612 PJ of coke ovens and blast furnaces does not decline — it ceases
in 2025.

### 2a. Parent and children are mutually exclusive

This is the key structural fact and it constrains any fix:

| Economy | Parent (`sub2sectors = x`) net 2022 | Children net 2022 |
|---|---:|---:|
| 01_AUS | 0.00 | −57.46 |
| 05_PRC | 0.00 | −7,768.14 |
| 20_USA | 0.00 | −240.35 |
| …8 more | 0.00 | non-zero |
| **16_RUS** | **−233.90** | **0.00** |

**No economy populates both levels.** Ten publish only at the coke-oven /
blast-furnace children with an empty parent row; Russia publishes only at the
parent with empty children.

Consequences:

- There is **no double-counting risk** between the two levels — they never
  coexist.
- Where children are populated, **the children *are* the total**. There is no
  parent value for them to over- or under-shoot.
- Where only the parent is populated (Russia), children must be derived from
  it. That path already exists —
  `ninth_projection_mapping.py` `build_economy_specific_child_flow_profiles`
  splits `COAL_PARENT_ESTO_FLOW` by base-year child shares.

### 2b. Russia is the only evidence of intent

Russia glides down: −233.9 → −200.6 (2025) → −61.4 (2030) → −3.7 (2040) → 0
(2050). The other ten cliff to exactly zero in 2025.

A managed decline to zero is plausible modelling. **An instantaneous drop to
zero in the first projection year is not.** That asymmetry is the strongest
argument that the ten zeros are missing data rather than a modelled phase-out —
but it is an inference, not a statement from the data owner. **Confirm with the
9th team before building on it.**

### 2c. Why our carry-forward does not rescue it

P3-06 approved carrying the ESTO base year forward where the 9th is absent. It
does not fire here, for two compounding reasons:

1. `_fill_general_missing_ninth_children`
   (`codebase/functions/ninth_projection_mapping.py:761`) explicitly
   **excludes** `COAL_PARENT_ESTO_FLOW` and `GAS_PARENT_ESTO_FLOW` — coal is
   meant to use its own dedicated path.
2. That fill targets children **missing** beneath a parent that still has a
   value. Here the child rows are *present and explicitly zero*, and the parent
   is zero too. Nothing looks missing, so nothing triggers.

**Present-but-zero is not treated as absent.** This is the same shape as the
transfers gap in §3 and the same trap recorded in the zero-fill mechanisms
review.

### 2d. Downstream symptom

LEAP's coke ovens and blast furnaces flatline from 2025 in ten economies. The
base-year values are correct; everything after is empty. This was originally
misdiagnosed as an own-use accounting defect — see
[the coal transformation note](coal_transformation_own_use_grossup_findings.md),
§10.

---

## 3. Transfers — `08_02`, `08_03`, `08_transfers`

Dead in every economy that has them for `08_02_interproduct_transfers`
(`05_PRC`, `13_PNG`, `14_PE`, `18_CT`, `21_VN`) and
`08_03_products_transferred` (`02_BD`, `04_CHL`, `05_PRC`, `14_PE`, `18_CT`);
3 of 7 for `08_transfers`.

Owned by **work queue item [50]**, which records the same behaviour from the
seed side: transfer rows are sourced from historical values and extended as
zero because no projection scenario is supplied. The decision pending there —
carry the ESTO base year forward, or retain zero-fill — should be made jointly
with §2, since the mechanism is identical.

---

## 4. CHP and heat plants — `18_02`, `09_02`, `09_x`, `19_01`, `19_02`

`18_02_chp_plants` is the **largest single gap by energy**: 55,599 PJ across
`01_AUS`, `02_BD`, `03_CDA`, `04_CHL`, `11_MEX`, `12_NZ`, while `09_ROK`,
`16_RUS`, `18_CT` and `20_USA` retain projections.

`09_02_chp_plants` is dead in 7 of 11. Heat plants (`09_x`, `19_01`, `19_02`)
are dead in a handful each.

**Not yet characterised.** The parent/child analysis of §2a has *not* been
repeated for CHP, and it should be before any fix — CHP has its own interim
allocation workflow and a different structure. Do not assume §2's conclusions
transfer.

---

## 5. Smaller gaps

| Sector | Dead in | Note |
|---|---|---|
| `09_07_oil_refineries` | 1 of 20 | isolated; identify the economy before acting |
| `09_04_electric_boilers` | 1 of 1 | the only economy with the sector |
| `09_05_chemical_heat_for_electricity_production` | 2 of 2 | every economy with the sector |
| `09_11_charcoal_processing` | 1 of 5 | isolated |

---

## 6. Standing guidance

1. **Do not treat an explicit zero in a projection year as a modelled zero**
   without checking this document. For the sectors listed above it means
   "not projected", not "ceases".
2. **Check the publication level before splitting or aggregating.** §2a shows
   an economy may publish only at the parent or only at the children. Code that
   assumes both, or assumes a fixed level, will silently lose data.
3. **Raise new instances here** rather than in a downstream note. Symptoms in
   seeds, exports and dashboards trace back to a small number of input gaps.
4. **Confirm intent with the 9th team** before compensating for any gap. A
   modelled phase-out and a missing projection look identical in the data.

## 7. Reproducing the scan

Scan logic: filter scenario Target, drop subtotal rows, group by `sub1sectors`
(falling back to `sectors` where `sub1sectors` is `x`), and compare the
absolute base-year sum against the absolute sum across all projection years.
Flag groups whose base year exceeds 1 PJ and whose projection total is below
1e-6 PJ.

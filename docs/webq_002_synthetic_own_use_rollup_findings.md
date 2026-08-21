# WEBQ-002 — Synthetic `(including own use)` rollups and the baseline-seed path

**Date:** 2026-08-20
**Scope:** diagnosis only. No production code, mapping data, or test file was
changed, and no workflow was run. The untracked `.tmp_webq002_*.py` scripts,
`codebase/mapping_tools/build_apec_2026_preliminary.py` and its test were not
touched — ownership was not established, so they were left alone.
**Verdict:** `REVIEW_REQUIRED` — see [§6](#6-recommendation).

---

## 1. Headline answer

**Yes, synthetic `(including own use)` rows enter the seed/carry-forward
*classification* set. No, they do not become numeric seed or carry-forward
*sources*.**

`build_balance_review_table()` admits the synthetic parent label into the
`seed_or_carry_forward_process` / `no_direct_projection_comparator` candidate set
through a prefix match that cannot tell a parent from a child. In a real
`01_AUS` diagnostic run, **17 of 17** flagged rows are synthetic parents and
**zero** are real child rows — see [§3.1](#31-real-run-evidence-01_aus).

But the flag it sets is a *review* classification. It forces
`update_signal_eligible = False` and `requires_issue_review = True`, and its only
consumers are the review workbook and the update-preview blocker. No producer
converts it into a written value. Verified by exhausting every reader of the
flag ([§2](#2-call-chain-and-exact-predicates), step 8).

So the queue's control-path concern is **confirmed**; the queue's implied risk of
a *silent bad seed number* is **not**. The harm is misclassification, a wrong row
identity, a wrong `next_action` that reads as a carry-forward instruction, and 24
contaminated supply rows.

Two corrections to the queue's framing, both from the live mapping:

- `09.08.03`, `09.08.04` and `09.08.05` are **not** synthetic today. The live
  mapping names them by their plain child labels. They are unaffected.
- `09.06.01 Gas works plants (including own use)` **is** synthetic, is in the
  same prefix tuple, and is the **largest** contributor (8 of 17 flagged rows).
  The queue does not mention it. Any rule must cover it.

---

## 2. Call chain and exact predicates

| Step | Location | Behaviour |
|---|---|---|
| 1 | `leap_mappings/config/outlook_mappings_master.xlsx`, sheet `leap_combined_esto` | Names the LEAP branch's ESTO target as the **synthetic** label. The plain child label is absent for the three affected processes. |
| 2 | `codebase/utilities/leap_results_dashboard_utils.py:1535` `pull_base_year_value()` | The synthetic label has no raw ESTO row. The single-code fallback searches `09.08.01.*` descendants, finds none → returns `NaN`. Base side is correctly *unavailable*. |
| 3 | [`baseline_seed_balance_diagnostics.py:1457`](codebase/functions/baseline_seed_balance_diagnostics.py:1457) rollup-alias block | `_expand_esto_flow_code_selector()` reduces the synthetic label to `["09.08.01"]` and the **exact** mask matches the plain child's projection row. The synthetic label acquires a projection comparator equal to the **transformation-only** value and is stamped `projection_allocation_complete = True`. There is no `len(component_codes) > 1` guard here, unlike the base-side path in step 2. |
| 4 | [`:2029`](codebase/functions/baseline_seed_balance_diagnostics.py:2029) `_add_auxiliary_values_for_active_process()` | Adds `10.01.*` own use back **only if exactly one** configured transformation flow is active for the key. This repairs step 3 in the happy path. If the child projection is zero or absent, nothing is added. |
| 5 | [`:872-889`](codebase/functions/baseline_seed_balance_diagnostics.py:872) `missing_rollup` | Correctly classifies the row `mapping_grain_or_allocation_required`, owner `mapping_or_diagnostic`, note "synthetic own-use boundary rollup". |
| 6 | [`:905-935`](codebase/functions/baseline_seed_balance_diagnostics.py:905) | **The defect.** `confirmed_seed_process = esto_flow.str.startswith(SEED_OR_CARRY_FORWARD_TRANSFORMATION_FLOW_PREFIXES)`. `"09.08.01 Coke ovens (including own use)".startswith("09.08.01 Coke ovens")` is `True`, so the synthetic parent is admitted and **unconditionally overwrites step 5**. |
| 7 | [`:955-980`](codebase/functions/baseline_seed_balance_diagnostics.py:955) | Every flagged row propagates `affected_by_no_projection_transformation = True` onto `01 Production` / `02 Imports` / `03 Exports` rows sharing economy·scenario·year·product. |
| 8 | `balance_review_workbook_builder.py:666`, `:461-500`, `:778-800`; `results_update_preview.py:746`; `portable_release/validation.py:50` | The **complete** set of readers. They highlight supply cells, count comparison states, and block allocator proposals. **No seed or carry-forward writer reads this flag.** |

Row identifiers that can classify a rollup as eligible, all from step 6:

```
esto_flow.startswith(<seed prefix>)          # matches parent AND child alike
& |leap_value_pj| > tolerance
& reference_source != "ESTO"
& (status == "reference_unavailable"
   OR |source_value_pj| <= tolerance
   OR transformation_auxiliary_comparison_status
        == "auxiliary_present_without_process_comparator")
```

The prefix tuple ([`:192-202`](codebase/functions/baseline_seed_balance_diagnostics.py:192))
holds nine plain child labels. Membership is by `startswith`, so each entry also
silently admits its `(including own use)` parent.

---

## 3. Evidence

Probes are read-only, import live repo code, and read the live mapping workbook
(`outlook_mappings_master.xlsx`, sha256 `4d867bcf…`, source commit `74a505a4`)
plus one existing diagnostic output. Nothing was executed that writes to the
repo.

### 3.1 Real-run evidence (`01_AUS`)

Source: `outputs/diagnostics/ah72_investigation_20260818/leap_balance_source_review.csv`
— 547 rows, `01_AUS`, scenarios Reference/Target, years 2022–2023.

**Every flagged row is a synthetic parent:**

| `esto_flow` | rows flagged `no_direct_projection_comparator` |
|---|---:|
| `09.06.01 Gas works plants (including own use)` | 8 |
| `09.08.01 Coke ovens (including own use)` | 5 |
| `09.08.02 Blast furnaces (including own use)` | 4 |
| **Total** | **17** |
| *of which real child rows* | **0** |

**The plain child label never appears in the review at all:**

| child flow | exact rows in the real review output |
|---|---:|
| `09.08.01 Coke ovens` | 0 |
| `09.08.02 Blast furnaces` | 0 |
| `09.06.01 Gas works plants` | 0 |

This is the single most important fact for the fix. There is no sibling child row
to compare against, so a child-comparator resolver must read the
projection/base tables, not other review rows.

**Downstream contamination:** 24 supply rows carry
`affected_by_no_projection_transformation = True`. Every distinct
`impact_source_transformation_flows` token is a synthetic parent:
`09.06.01 Gas works plants (including own use)`,
`09.08.01 Coke ovens (including own use)`,
`09.08.02 Blast furnaces (including own use)`.

**`10.01.*` ownership is not being mistaken for missing `09.08` split
evidence.** 56 `10.01.*` rows are present in the run; **0** are flagged. They are
not in the prefix tuple and cannot be. Queue investigation point 3 is clean.

### 3.2 Natural experiment — the prefix tuple is the whole cause

Four synthetic labels appear in the same real run with the same shape. The only
thing that differs is whether the label's child is in the prefix tuple:

| `esto_flow` | in prefix tuple | `status` | `primary_classification` | rows |
|---|---|---|---|---:|
| `09.07 Oil refineries (including own use)` | **False** | `reference_unavailable` | `mapping_grain_or_allocation_required` ✅ | 14 |
| `09.07 Oil refineries (including own use)` | **False** | `value_mismatch` | `protected_flow_difference` ✅ | 13 |
| `09.06.01 Gas works plants (including own use)` | **True** | `reference_unavailable` | `seed_or_carry_forward_process` ❌ | 7 |
| `09.06.01 Gas works plants (including own use)` | **True** | `value_mismatch` | `seed_or_carry_forward_process` ❌ | 1 |
| `09.08.01 Coke ovens (including own use)` | **True** | `reference_unavailable` | `seed_or_carry_forward_process` ❌ | 5 |
| `09.08.01 Coke ovens (including own use)` | **True** | `value_mismatch` | `protected_flow_difference` ✅ | 2 |
| `09.08.02 Blast furnaces (including own use)` | **True** | `reference_unavailable` | `seed_or_carry_forward_process` ❌ | 4 |
| `09.08.02 Blast furnaces (including own use)` | **True** | `missing_in_leap` | `unresolved` | 2 |

`09.07 Oil refineries (including own use)` is a synthetic own-use rollup of
identical construction, and with the identical `reference_unavailable` status it
receives the **correct** `mapping_grain_or_allocation_required` classification —
purely because `09.07 Oil refineries` is not in the prefix tuple. Nothing about
the data distinguishes the two cases. The classification difference is caused
entirely by tuple membership.

The two `09.08.01` `value_mismatch → protected_flow_difference` rows are the
happy path (regime J1 in §3.5). **The rule must preserve them.**

### 3.3 Live mapping scope — `leap_combined_esto`, seed-prefix flows

| ESTO flow named by the mapping | synthetic | ESTO products | LEAP branches | affected |
|---|---|---:|---:|---|
| `09.06.01 Gas works plants (including own use)` | **yes** | 26 | 1 | **yes** — not in the queue |
| `09.06.02 Liquefaction/regasification plants` | no | 7 | 1 | no |
| `09.06.03 Natural gas blending plants` | no | 10 | 1 | no |
| `09.06.04 Gas-to-liquids plants` | no | 5 | 1 | no |
| `09.08.01 Coke ovens (including own use)` | **yes** | 26 | 1 | **yes** |
| `09.08.02 Blast furnaces (including own use)` | **yes** | 12 | 1 | **yes** |
| `09.08.03 Patent fuel plants` | no | 22 | 1 | no |
| `09.08.04 BKB/PB plants` | no | 23 | 1 | no |
| `09.08.05 Liquefaction (coal to oil)` | no | 23 | 1 | no |

Maintained component evidence, sheet `esto_rollup_rules`, `include = True`,
`ROLLUP_MODE = NON_EXPANDING`:

| synthetic parent | components |
|---|---|
| `09.08.01 Coke ovens (including own use)` | `09.08.01` + `10.01.05` |
| `09.08.02 Blast furnaces (including own use)` | `09.08.02` + `10.01.07` |
| `09.06.01 Gas works plants (including own use)` | `09.06.01` + `10.01.02` |

### 3.4 Prefix admission — the mechanism, and the latent risk

| ESTO flow label | kind | matches a seed prefix | selector codes |
|---|---|---|---|
| `09.08.01 Coke ovens` | plain child | True | `[09.08.01]` |
| `09.08.01 Coke ovens (including own use)` | synthetic | **True** | `[09.08.01]` |
| `09.08.02 Blast furnaces (including own use)` | synthetic | **True** | `[09.08.02]` |
| `09.08.03 Patent fuel plants (including own use)` | synthetic | **True** | `[09.08.03]` |
| `09.08.04 BKB/PB plants (including own use)` | synthetic | **True** | `[09.08.04]` |
| `09.08.05 Liquefaction (coal to oil) (including own use)` | synthetic | **True** | `[09.08.05]` |

The mechanism admits all nine prefixes' parents. Only three occur today (§3.3);
the rest are latent and would activate the moment the mapping adds a rollup
label for them.

### 3.5 Child-comparator resolution — the three live regimes

Synthetic label only (the live mapping shape), product `01.01 Coking coal`,
LEAP = 62.127 PJ, driven through the real auxiliary combiner and classifier:

| Case | 9th `09.08.01` | 9th `10.01.05` | combined comparator | auxiliary status | `primary_classification` | flagged |
|---|---:|---:|---:|---|---|---|
| **J1** valid child comparator | 70.0 | −4.0 | **66.0** | `combined_with_active_process_comparator` | `protected_flow_difference` ✅ | False |
| **J2** child projection is zero | 0.0 | −4.0 | 0.0 | `auxiliary_present_without_process_comparator` | `seed_or_carry_forward_process` ❌ | True |
| **J3** child projection absent | — | −4.0 | `nan` → `reference_unavailable` | *(blank)* | `seed_or_carry_forward_process` ❌ | True |

The 17 real flagged rows are all J3 (`transformation_auxiliary_comparison_status`
is blank, `source_value_pj` is `NaN`), except one J2 row
(`09.06.01` / `17 Electricity` / Target 2023, `source_value_pj = 0.0`).

In J2 and J3 the `10.01.*` own-use evidence exists and is correctly **not**
substituted for the missing `09.08` split.

### 3.6 Base-vs-projection asymmetry (secondary finding)

| Call | Result |
|---|---|
| `pull_base_year_value("09.08.01 Coke ovens", 2022)` | `62.127` |
| `pull_base_year_value("09.08.01 Coke ovens (including own use)", 2022)` | `nan` — correct, guarded by `len(component_codes) > 1` |
| `apply_canonical_projection_comparators()` on the synthetic label, 9th `09.08.01` = 70.0, `10.01.05` = −4.0 | comparator **70.0**, `projection_allocation_complete = True` — own use silently omitted; the true inclusive value is 66.0 |

The projection-side alias path has no equivalent guard. Step 4 repairs it in J1
only. This is a **separate defect** — see §4 "out of scope".

### 3.7 Latent regime — if the mapping ever adds the plain child

With **both** labels mapped for one key, `_active_process_count == 2`, the
auxiliary combiner refuses to act, and both rows are stamped
`auxiliary_present_without_process_comparator`:

| `esto_flow` | base | projection | auxiliary status |
|---|---:|---:|---|
| `09.08.01 Coke ovens` | 62.127 | 70.0 | `auxiliary_present_without_process_comparator` |
| `09.08.01 Coke ovens (including own use)` | `nan` | 70.0 | `auxiliary_present_without_process_comparator` |

Both then flag, double-counting one finding across two identities. Not live
today; worth a guard test.

### 3.8 Before / after candidate-row set

**On real `01_AUS` data**, applying the §4 rule as a post-filter:

| measure | BEFORE | AFTER |
|---|---:|---:|
| seed/carry-forward candidates | **17** | **0** |
| — of which synthetic parents | 17 (100%) | 0 |
| — of which real child rows | 0 | 0 |
| contaminated supply rows | **24** | **0** |
| `10.01.*` rows flagged | 0 | 0 |
| `09.07 …(including own use)` classification | correct | unchanged |
| `09.08.01` J1 happy-path rows | `protected_flow_difference` | unchanged |

**On a synthetic fixture** where the plain child *is* mapped and *does* have a
comparator (the §3.7 regime), so the parent/child interaction is visible:

BEFORE

| `esto_flow` | `primary_classification` | flagged | supply contaminated |
|---|---|---|---|
| `09.08.01 Coke ovens (including own use)` | `seed_or_carry_forward_process` | **True** | — |
| `09.08.01 Coke ovens` | `protected_flow_difference` | False | — |
| `10.01.05 Coke ovens` | `protected_flow_difference` | False | — |
| `01 Production` | `protected_flow_difference` | False | **True** |
| `02 Imports` | `expected_error_signal` | False | **True** |

AFTER

| `esto_flow` | `primary_classification` | `balance_contract_issue` | flagged | supply contaminated |
|---|---|---|---|---|
| `09.08.01 Coke ovens (including own use)` | `mapping_grain_or_allocation_required` | `synthetic_rollup_requires_child_resolution` | **False** | — |
| `09.08.01 Coke ovens` | `protected_flow_difference` | `protected_flow_difference` | False | — |
| `10.01.05 Coke ovens` | `protected_flow_difference` | `protected_flow_difference` | False | — |
| `01 Production` | `protected_flow_difference` | `protected_flow_difference` | False | False |
| `02 Imports` | `expected_error_signal` | `expected_error_signal_difference` | False | False |

### 3.9 No coverage is lost

With the rollup **and** its child both genuinely lacking a comparator, the child
is flagged on its own identity today and would continue to be:

| `esto_flow` | `status` | flagged today | after the rule |
|---|---|---|---|
| `09.08.02 Blast furnaces (including own use)` | `reference_unavailable` | True | blocked, re-classified, still `requires_issue_review` |
| `09.08.02 Blast furnaces` | `reference_unavailable` | **True** | **True — survives unchanged** |
| `10.01.07 Blast furnaces` | `value_mismatch` | False | False |

Blocking the parent moves the finding to the correct identity rather than hiding
it. In the live mapping shape the child row does not exist at all, so for the
three affected processes the rule must **re-classify** rather than rely on a
sibling.

---

## 4. Proposed narrow rule

A **rollup source blocker** confined to the `confirmed_seed_process` predicate at
[`baseline_seed_balance_diagnostics.py:905`](codebase/functions/baseline_seed_balance_diagnostics.py:905).

1. Exclude any `esto_flow` containing `(including own use)` from
   `confirmed_seed_process`. The prefix match becomes parent-aware.
2. Stop step 6 overwriting step 5. The synthetic row keeps
   `mapping_grain_or_allocation_required` and its correct evidence note.
3. **The child resolver already exists — reuse its verdict, do not build a new
   one.** `_add_auxiliary_values_for_active_process()` (step 4) *is* the child
   resolution, and it records its verdict in
   `transformation_auxiliary_comparison_status`:
   - `combined_with_active_process_comparator` → child resolved; the row is
     regime J1 and never enters the blocked set in the first place;
   - `auxiliary_present_without_process_comparator` → the `10.01.*` component
     resolved but the `09.0x` child process did not;
   - blank with `reference_unavailable` → nothing resolved.

   So the blocked set contains only unresolved cases, and no projection/base
   table lookup is needed inside `build_balance_review_table()`. Emit
   `balance_contract_issue = "synthetic_rollup_child_comparator_unresolved"`,
   with the evidence note distinguishing the last two sub-cases.
4. Both outcomes keep `requires_issue_review = True` and
   `update_signal_eligible = False`. Neither becomes a silent assumption.
5. A `10.01.*` row must never satisfy the child test — it is own-use/loss
   ownership, not `09.08` split evidence. Already true; assert it.
6. Any exception must be an explicit reviewed allow-list entry keyed on the full
   synthetic label, never a name-derived inference.

**Deliberately out of scope**, recorded so they are not folded in:

- The §3.6 projection-alias gap. Fixing it alone would turn J1 from a correct
  66.0 into `reference_unavailable`, because it is coupled to the auxiliary
  combiner. **Do not touch it in the same commit.**
- The J2 conflation of "9th projection is zero" with "no comparator" is a
  pre-existing semantic question, unchanged by this rule.

Impacted locations, in order of blast radius:

| File | Change |
|---|---|
| `codebase/functions/baseline_seed_balance_diagnostics.py:872-935` | the rule itself |
| `codebase/functions/balance_review_workbook_builder.py:481-570` | **no change needed** — the state loop is an `if`/`continue` chain in which every review row increments exactly one counter and appends exactly one record (or increments `mapped` and appends none). A de-flagged row falls through to the `reference_unavailable` branch, so `accounted` and `expected_missing` stay balanced by construction |
| `codebase/portable_release/validation.py:50` | **no change needed** — it lists `no_direct_projection_comparator` as a *column*, not a value set; `balance_contract_issue` has no enumerated vocabulary anywhere |
| `tests/test_portable_release_golden_balance_review.py:64` | golden `no_direct_projection_comparator: 12` will move |
| `tests/test_baseline_seed_balance_diagnostics_workflow.py:1393-1435` | **no change needed** — `test_review_marks_seed_process_and_affected_supply_fuels` uses the plain child `09.08.01 Coke ovens`, not the synthetic parent, so it stays green and becomes a second anti-regression anchor |
| `docs/check_registry.md` | new check → `tests/test_check_registry.py` fails otherwise |
| `docs/baseline_seed_rule_inventory.md` | SEED-C rule detail |

---

## 5. Proposed regression test

New module `tests/test_synthetic_own_use_rollup_seed_blocker.py`. Pure fixture
frames through `build_balance_review_table()` — no workflow, no I/O.

```python
"""WEBQ-002: synthetic (including own use) rollups must not be seed sources."""
from __future__ import annotations

import pandas as pd
import pytest

from codebase.functions.baseline_seed_balance_diagnostics import (
    DIFFERENCE_OUTPUT_COLUMNS,
    SEED_OR_CARRY_FORWARD_TRANSFORMATION_FLOW_PREFIXES,
    build_balance_review_table,
)

# The three synthetic labels the live mapping actually emits (see WEBQ-002 §3.3).
SYNTHETIC = [
    ("09.08.01 Coke ovens", "02.01 Coke oven coke", "10.01.05 Coke ovens"),
    ("09.08.02 Blast furnaces", "02.04 Blast furnace gas", "10.01.07 Blast furnaces"),
    ("09.06.01 Gas works plants", "08.03 Gas works gas", "10.01.02 Gas works plants"),
]


def _diff_row(**kwargs) -> dict:
    row = {column: pd.NA for column in DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        economy="01_AUS", scenario="target", year=2022,
        reference_source="9th Outlook", leap_component_count=1,
        ninth_pair_count=1, ninth_pair_max_esto_claimants=1,
        projection_allocation_complete=True, update_allocation_required=False,
        transformation_auxiliary_comparison_status="",
    )
    row.update(kwargs)
    return row


@pytest.mark.parametrize("child, product, own_use", SYNTHETIC)
def test_synthetic_rollup_is_not_a_seed_or_carry_forward_source(child, product, own_use):
    """The synthetic parent must never enter the seed/carry-forward set."""
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow=f"{child} (including own use)", esto_product=product,
                  leap_value_pj=62.127, source_value_pj=pd.NA,
                  absolute_difference_pj=62.127, difference_pj=62.127,
                  status="reference_unavailable"),
    ]))
    row = review.iloc[0]
    assert bool(row["no_direct_projection_comparator"]) is False
    assert row["primary_classification"] == "mapping_grain_or_allocation_required"
    assert row["balance_contract_issue"].startswith("synthetic_rollup_")
    # It stays visible for review; it does not become a silent assumption.
    assert bool(row["requires_issue_review"]) is True
    assert bool(row["update_signal_eligible"]) is False


def test_plain_child_without_a_comparator_is_still_flagged():
    """Blocking the parent must not hide a genuine child-level finding."""
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow="09.08.02 Blast furnaces",
                  esto_product="02.04 Blast furnace gas",
                  leap_value_pj=40.0, source_value_pj=pd.NA,
                  absolute_difference_pj=40.0, difference_pj=40.0,
                  status="reference_unavailable"),
    ]))
    row = review.iloc[0]
    assert bool(row["no_direct_projection_comparator"]) is True
    assert row["primary_classification"] == "seed_or_carry_forward_process"


def test_happy_path_combined_comparator_is_untouched():
    """Regime J1: a resolved inclusive comparator stays an ordinary difference."""
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow="09.08.01 Coke ovens (including own use)",
                  esto_product="02.01 Coke oven coke",
                  leap_value_pj=62.127, source_value_pj=66.0,
                  absolute_difference_pj=3.873, difference_pj=-3.873,
                  status="value_mismatch",
                  transformation_auxiliary_comparison_status=
                      "combined_with_active_process_comparator"),
    ]))
    row = review.iloc[0]
    assert bool(row["no_direct_projection_comparator"]) is False
    assert row["primary_classification"] == "protected_flow_difference"


@pytest.mark.parametrize("child, product, own_use", SYNTHETIC)
def test_own_use_row_is_never_a_seed_candidate(child, product, own_use):
    """10.01.* ownership must not be read as 09.08 split evidence."""
    assert not own_use.startswith(SEED_OR_CARRY_FORWARD_TRANSFORMATION_FLOW_PREFIXES)
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow=own_use, esto_product=product, leap_value_pj=3.5,
                  source_value_pj=pd.NA, absolute_difference_pj=3.5,
                  difference_pj=3.5, status="reference_unavailable"),
    ]))
    assert bool(review.iloc[0]["no_direct_projection_comparator"]) is False


def test_synthetic_rollup_does_not_contaminate_supply_rows():
    """The parent must not propagate affected_by_no_projection_transformation."""
    product = "02.01 Coke oven coke"
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow="09.08.01 Coke ovens (including own use)",
                  esto_product=product, leap_value_pj=62.127,
                  source_value_pj=pd.NA, absolute_difference_pj=62.127,
                  difference_pj=62.127, status="reference_unavailable"),
        _diff_row(esto_flow="01 Production", esto_product=product,
                  leap_value_pj=100.0, source_value_pj=101.0,
                  absolute_difference_pj=1.0, difference_pj=-1.0,
                  status="value_mismatch"),
    ]))
    assert not review["affected_by_no_projection_transformation"].astype(bool).any()


def test_both_labels_mapped_does_not_double_flag_one_finding():
    """Latent regime guard (WEBQ-002 §3.7): parent and child must not both flag."""
    product = "02.01 Coke oven coke"
    aux = "auxiliary_present_without_process_comparator"
    review = build_balance_review_table(pd.DataFrame([
        _diff_row(esto_flow="09.08.01 Coke ovens (including own use)",
                  esto_product=product, leap_value_pj=62.127,
                  source_value_pj=pd.NA, absolute_difference_pj=62.127,
                  difference_pj=62.127, status="reference_unavailable",
                  transformation_auxiliary_comparison_status=aux),
        _diff_row(esto_flow="09.08.01 Coke ovens", esto_product=product,
                  leap_value_pj=62.127, source_value_pj=70.0,
                  absolute_difference_pj=7.873, difference_pj=-7.873,
                  status="value_mismatch",
                  transformation_auxiliary_comparison_status=aux),
    ]))
    flagged = review["no_direct_projection_comparator"].astype(bool)
    assert int(flagged.sum()) <= 1
    assert not flagged[review["esto_flow"].str.contains(r"\(including own use\)")].any()
```

Status against current code: `test_plain_child_without_a_comparator_is_still_flagged`
and `test_happy_path_combined_comparator_is_untouched` **pass today** and are the
anti-regression anchors. The other four **fail today** and are the defect
reproducers.

---

## 6. Recommendation

**`REVIEW_REQUIRED`.** The mechanism is unambiguous and reproducible on real run
output, but three things need the owner's decision before a change lands.

1. **The queue's premise is only partly confirmed.** Synthetic rollups reach the
   seed/carry-forward *classification*, not the seed *values*; every reader of
   the flag was enumerated and none writes a seed. If the intent was to stop bad
   numbers entering a seed, no such path exists and the priority should drop. If
   the intent was to fix the control path and the review identity — which the
   real-run evidence shows is genuinely wrong on 17 rows plus 24 supply rows —
   the §4 rule does exactly that.
2. **The scope differs from the queue.** `09.08.03`–`09.08.05` are unaffected;
   `09.06.01 Gas works plants` is affected and is the largest contributor, yet is
   unlisted. Item [51] should be corrected before a commit references it.
3. **The change is narrower than first assessed.** On re-reading the consumers,
   the `balance_review_workbook_builder` audit invariants self-balance and no
   vocabulary is enumerated anywhere, so the blast radius is one predicate plus
   one classification block in `build_balance_review_table()`. The only
   hard-coded value that moves is `GOLDEN_COMPARISON_STATE_COUNTS` in
   `tests/test_portable_release_golden_balance_review.py`, where 12 rows
   redistribute from `no_direct_projection_comparator` into
   `reference_unavailable` / `mapped`. That is a mechanical golden refresh, but
   it must be *observed* from a rerun, not hand-edited.

Recommended sequencing once approved:

- **(a)** rule + `docs/check_registry.md` entry + the §5 test module — one commit;
- **(b)** golden-count refresh from an observed rerun — separate commit;
- **(c)** the §3.6 projection-alias guard — separate queue item, since it is
  coupled to the auxiliary combiner and must not ride along.

---

## 7. Reproducing this note

Probe scripts are read-only, import live repo code, and run in seconds. They live
in the session scratchpad and can be promoted verbatim if a durable fixture is
wanted:

| script | covers |
|---|---|
| `webq002_probe.py` | §3.4 prefix admission, auxiliary rule set, §3.6 base asymmetry |
| `webq002_probe_d.py` | §3.6 projection-alias comparator |
| `webq002_probe_e.py` | §3.5 auxiliary regimes, §3.7 latent regime |
| `webq002_probe_f.py` | §3.8 fixture before/after and supply contamination |
| `webq002_probe_g.py` | §3.9 coverage retention |
| `webq002_probe_h.py` | §3.3 live mapping scan |
| `webq002_probe_i.py` | §3.3 scope table and `esto_rollup_rules` components |
| `webq002_probe_j.py` | §3.5 the three live regimes |
| `webq002_probe_k.py` | §3.1 real-run evidence |
| `webq002_probe_l.py` | §3.1–§3.2 natural experiment, real-data before/after |

Run with `C:/Users/Work/miniconda3/python.exe`, per `AGENTS.md`.

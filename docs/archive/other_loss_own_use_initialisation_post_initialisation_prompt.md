# Other Loss / Own-Use Initialisation and Post-Initialisation Prompt

## Short Version

You are working in:

`C:\Users\Work\github\leap_initialisation`

Update the other-loss / own-use proxy workflow so its stage semantics match the approved description:

* **Initialisation stage** includes both baseline seed and results-update passes.
* **Post-initialisation stage** begins only once the workflow is no longer trying to match external projection-year target energy values.
* In post-initialisation, intensity should be held constant from a calibrated anchor year, and projected own-use/loss energy should follow the proxy activity trend.

Use this wording consistently:

> intensity should be held constant from the base-year-calibrated value. If the base year is zero but later projection years become nonzero, use the first valid nonzero projection year as the anchored intensity year.

Avoid the shorter wording:

> intensity should be held constant from the base year or last valid nonzero year

because that can imply the anchor year keeps moving through time.

Keep terminology consistent across code comments, docs, prompts, and any user-facing explanations.

---

## Objective

Clarify the workflow’s stage model so it no longer treats `second` or results-update mode as a generic post-initialisation concept.

The implementation should distinguish between:

1. **Initialisation** — target energy is still being matched.
2. **Post-initialisation** — target energy is no longer being matched; intensity is anchored and own-use/loss energy is driven by activity.

The intent is to make the workflow easier to reason about and avoid conflating:

* activity source mode;
* stage semantics;
* intensity behaviour;
* and calibration/anchor-year logic.

---

## Key Approved Semantics

Use this description as the source of truth.

### Initialisation stage

During initialisation, the workflow is still trying to reproduce an existing dataset in LEAP. This includes both the first baseline seed import and later results-update passes.

In this stage, target energy values are still available and should still be matched. Projection years can still be target-driven during initialisation because their target values usually come from the 9th Outlook or another completed Outlook dataset.

For each year:

`intensity_y = abs(target_energy_y) / proxy_activity_y`

This means that if the target own-use/loss energy and proxy activity do not move at exactly the same rate, intensity may vary over time. That is expected during initialisation because intensity is being used to reproduce target energy values.

### Results-update passes are still initialisation

After the first LEAP run, the proxy activity can be updated using LEAP balance results where available. This changes the proxy activity source, but it remains part of initialisation if target energy values are still being matched.

In other words:

`intensity_y = abs(target_energy_y) / updated_proxy_activity_y`

The results-update pass should not be treated as post-initialisation just because proxy activity is now coming from LEAP results.

### Post-initialisation stage

Post-initialisation begins only once the model is no longer trying to match external projection-year target energy values.

At that point, stop recalculating intensity to fit the 9th Outlook or another completed Outlook projection. Instead, hold intensity constant from a calibrated anchor year and let projected own-use/loss energy move with the proxy activity trend.

Projected energy then becomes:

`projected_energy_y = proxy_activity_y × anchored_intensity`

The usual anchor is the base-year-calibrated intensity.

If the base year is zero but later projection years become nonzero, use the first valid nonzero projection year as the anchored intensity year. In that case, the anchored intensity can be derived from the 9th Outlook target energy if that value is available and nonzero, or otherwise estimated using the best available method.

Do not keep updating the anchor year through the projection unless there is an explicit, reviewed reason to do so.

### Zero versus missing target energy

Preserve the distinction between:

* **true zero target energy** — the source data explicitly indicate zero, so the workflow should keep energy and intensity at zero;
* **missing target energy** — there is no external target to copy, so the workflow should not collapse to zero and should instead use the best available proxy activity with an anchored intensity.

---

## Scope

### In scope

1. Review the current stage naming and logic in:

   * `codebase/other_loss_own_use_proxy_workflow.py`
   * `codebase/functions/other_loss_own_use_proxy_utils.py`
   * any caller or documentation that describes `OTHER_LOSS_OWN_USE_PROXY_STAGE`

2. Make the stage model explicit:

   * initialisation;
   * post-initialisation;
   * activity source mode as a separate concern;
   * intensity behaviour as a separate concern.

3. Update wording consistently so the approved phrasing is used:

   > intensity should normally be held constant from the base-year-calibrated value. If the base year is zero but later projection years become nonzero, use the first valid nonzero projection year as the anchored intensity year.

4. Update comments and docs so the distinction between matching target energy and holding intensity constant is obvious.

5. Add or improve debug/provenance outputs where useful, especially:

   * `intensity_mode`
   * `anchor_year`
   * `target_energy_source`
   * `proxy_activity_source`

### Out of scope

* Broad methodology redesign.
* Dashboard changes unless a small debug output is already part of the workflow.
* Rewriting the whole proxy workflow.
* Weakening validation to hide missing activity or zero-intensity issues.

---

## Implementation Guidance

### A. Separate concepts clearly

Make it obvious that these are different ideas:

* **Stage**: whether target energy is still being matched.
* **Activity source**: where proxy activity comes from, such as ESTO/9th data, LEAP balance results, trade fallback, production fallback, etc.
* **Intensity behaviour**: whether intensity is recalculated to match target energy or held constant from an anchor year.
* **Anchor year**: the year from which post-initialisation intensity is held constant.

### B. Stage naming

Avoid using `second` as though it means post-initialisation.

If needed, introduce or document a distinct post-initialisation mode/flag that controls anchored intensity behaviour.

Suggested conceptual modes:

* `baseline_seed_initialisation`
* `results_update_initialisation`
* `post_initialisation_anchored_intensity`

The exact names can differ, but the semantics should be clear.

### C. Calibration and anchor rule

During initialisation:

`intensity_y = abs(target_energy_y) / proxy_activity_y`

During post-initialisation:

`projected_energy_y = proxy_activity_y × anchored_intensity`

The anchor rule should be:

1. If the base year has valid nonzero target energy and valid nonzero proxy activity, use the base-year-calibrated intensity.
2. If the base year is zero but later projection years become nonzero, use the first valid nonzero projection year as the anchored intensity year.
3. The first valid nonzero projection-year anchor can be derived from 9th Outlook target energy if available and nonzero, or otherwise estimated using the best available method.
4. Once the anchor is chosen, hold it constant. Do not keep moving the anchor through later projection years.

### D. Missing activity or zero-FIE cases

Do not allow these cases to pass silently:

* target energy is nonzero but proxy activity is zero or missing;
* proxy activity is nonzero but FIE is zero when target energy should be nonzero;
* target energy exists but is being treated as missing;
* missing target energy is being interpreted as true zero.

For these cases, use the configured fallback rules or produce a clear warning/check output.

This is especially important for cases like:

* `Liquefaction/regasification plants`
* `Oil refining`
* `Pump storage plants`

where zero activity or zero FIE can cause the proxy branch to produce zero own-use/loss energy.

### E. Wording update

Replace vague references to:

> base year or last valid nonzero year

with:

> base-year-calibrated value, or the first valid nonzero projection year if the base year is zero but later projection years become nonzero.

Use “last valid nonzero year” only if the code truly means a backward-looking fallback from the current year, and explain that clearly. Otherwise prefer “first valid nonzero projection year” for the post-initialisation anchor case.

---

## Validation Expectations

After the wording and logic review/update:

* baseline seed and results-update should still behave as initialisation modes;
* both should continue matching target energy values where target energy exists;
* results-update may change proxy activity source, but should not automatically imply post-initialisation;
* post-initialisation should keep intensity anchored;
* projected own-use/loss energy should vary with activity, not be re-fit to target energy;
* true zero target energy should remain zero;
* missing target energy should not automatically collapse to zero;
* comments/docs should reflect the same semantic split.

---

## Acceptance Criteria

1. The codebase clearly distinguishes initialisation from post-initialisation.
2. Baseline seed and results-update are documented as part of initialisation.
3. Post-initialisation uses anchored intensity, not target matching.
4. The anchor rule is explicit:

   * use the base-year-calibrated intensity where valid;
   * if the base year is zero but later projection years become nonzero, use the first valid nonzero projection year as the anchor.
5. Activity source mode is not conflated with stage semantics.
6. Any docs/prompts/comments updated by this task preserve the approved wording.
7. Nonzero target energy with zero/missing activity is flagged or handled through a documented fallback.
8. Debug/provenance outputs make it possible to see the target source, activity source, intensity mode, and anchor year.

---

## Notes

This prompt is mainly about concept alignment and wording consistency. If a code change is needed, keep it minimal and only after the stage model is fully understood.

Do not weaken validation or add exceptions just to make the current output pass. The goal is to make the proxy workflow easier to understand and more reliable.

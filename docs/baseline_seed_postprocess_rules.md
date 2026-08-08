# Baseline-seed post-processing rules

The final baseline-seed writer has an optional, template-backed policy layer for
LEAP variables that normal workflow producers do not own. It is intended for
narrow corrections such as enforcing a selected process's `Maximum
Availability` without adding that variable to every transformation producer.

## Activation

The baseline-seed preset in `codebase/supply_reconciliation_workflow.py`
contains:

```python
"APPLY_BASELINE_SEED_POSTPROCESS_RULES": False,
"BASELINE_SEED_POSTPROCESS_RULES_PATH": (
    REPO_ROOT / "config" / "baseline_seed_postprocess_rules.json"
),
```

Set the boolean to `True` for a run that should apply the configured rules.
Results-update and patch presets explicitly keep the feature disabled so a
prior notebook run cannot leak the setting into another preset.

## Rule structure

The JSON file has `version: 1` and a `rules` list. Each rule supports:

- `rule_id`: required stable identifier used in the audit;
- `enabled`: independent per-rule switch;
- `economies`: optional economy allowlist such as `["20_USA"]`;
- `branch_path_equals`: optional exact path or list of exact paths;
- `branch_path_contains`: optional string or list of strings that must all
  appear in the path;
- `variable_equals`: optional variable or list of variables;
- `scenarios`: optional scenario allowlist;
- `template_value_not_equal_to`: optional numeric trigger. The rule applies
  only when at least one populated year in the canonical template differs;
- `include_blank_template_values`: whether blank template years also trigger;
- `replacement_expression`: required expression written to the seed; and
- `require_match`: raise when the rule does not find a triggering row.

At least one branch-path or variable constraint is mandatory. This prevents an
accidental unconstrained rewrite.

The optional `excluded_branch_path_workbooks` list names maintained Excel
catalogues whose `Branch Path` values are protected from every automatic rule.
Paths are resolved relative to the JSON file. Each entry can specify `sheets`,
`branch_path_column`, and whether the workbook is `required`. Exclusion is by
exact normalized branch path and applies to every variable, scenario and
economy on that path.

Example:

```json
{
  "rule_id": "real_template_oil_refining_maximum_availability_100",
  "enabled": true,
  "economies": [
    "01_AUS", "02_BD", "05_PRC", "10_MAS", "11_MEX", "12_NZ",
    "13_PNG", "15_PHL", "19_THA", "20_USA", "21_VN"
  ],
  "branch_path_equals": "Transformation\\Oil Refining\\Processes\\Oil Refining",
  "variable_equals": "Maximum Availability",
  "scenarios": ["Target"],
  "template_value_not_equal_to": 100,
  "replacement_expression": "100"
}
```

## Application boundary

Rules run after all normal producer workbooks are combined and documented
exclusions are removed, but before final seed validation and expression
conversion. A matching row is copied from that economy's canonical, non-shared
LEAP template so its branch, variable, scenario, region, metadata and IDs use
the correct area. The configured expression then replaces the template value.

The logical key is `(Branch Path, Variable, Scenario, Region)`. An existing seed
row with the same key is replaced; otherwise the row is inserted. Final
baseline-seed validation still runs normally.

Each enabled run writes:

```text
supporting_files/baseline_seed_validation/
  baseline_seed_<economy>_<date>_postprocess_overrides.csv
```

The audit records the rule, action, prior expression, replacement expression,
and the template years/values that triggered the change.

## 2026-07-29 non-provisional template audit

A read-only scan used the repository template resolver's `COMP_GEN` semantics
and checked all populated year cells on Transformation `Maximum Availability`
rows in the 11 real templates.

- All 11 real-template economies had
  `Transformation\Oil Refining\Processes\Oil Refining`, Target, at `90` for
  every year from 2023 through 2060.
- USA also had Coal CHP at `50` and Gas CHP at `80`. These are separate,
  technology-specific settings. Their process paths are present in
  `leap_mappings/data/temp/new leap rows.xlsx`, so the exclusion catalogue
  prevents any current or future automatic rule from changing them.
- Blank projection years on Current Accounts rows were recorded separately and
  are normal scenario-window blanks, not explicit non-100 settings.

The shipped JSON rule therefore names the 11 real-template economies and only
the exact Oil Refining process path, Target scenario, and Maximum Availability
variable. The workflow switch remains off until deliberately activated.

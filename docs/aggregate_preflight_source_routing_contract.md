# Aggregate compressed-preflight source-routing contract

## Current behaviour (characterized 2026-07-22)

`run_preflight_compressed_projection()` runs the workflow with
`economies=["00_APEC"]`, but calls
`_create_preflight_compressed_source_files()` without `economy_filter`.
The helper selects the aggregate ESTO and ninth source files only when that
filter contains `"00_APEC"`. Consequently, the current projection preflight
can run an aggregate workflow using the ordinary configured source tables.

`tests/test_preflight_compressed_results_update.py` records both facts:

- a passing characterization test proves the filter is currently omitted;
- a strict expected-failure contract specifies the intended filter.

## Minimal production fix

At the single projection-preflight call site in
`codebase/functions/supply_preflight.py`, add:

```python
economy_filter=["00_APEC"],
```

to `_create_preflight_compressed_source_files(...)`. Then remove the
`pytest.mark.xfail` marker from the contract test; no helper rewrite or new
configuration is required.

## Output-risk boundary and verification

This is source-selection-only for the compressed `00_APEC` projection
preflight. It does not change real-economy source selection, output labels,
the main selected-economy workflow, or any full-horizon seed. It *does* change
the aggregate preflight's compressed ESTO/ninth inputs, so it must be treated
as behavior-affecting within that isolated preflight.

Required verification after the fix:

1. Run the focused tests and convert the contract test to an ordinary passing
   assertion.
2. Run one normal two-year `01_AUS` workflow with compressed projection
   preflight enabled.
3. Confirm the preflight log/source paths name the aggregate ninth source and
   that the selected `01_AUS` run still completes. No full-horizon run is
   required solely for this routing correction.

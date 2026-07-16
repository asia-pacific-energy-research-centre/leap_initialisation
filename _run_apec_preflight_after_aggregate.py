#%%
"""Run the isolated synthetic-APEC compressed-projection preflight from Jupyter."""

import codebase.supply_reconciliation_workflow as workflow


def run_apec_preflight_after_aggregate() -> None:
    """Configure and run the focused APEC preflight after aggregate sources exist."""
    workflow.ECONOMIES = ["00_APEC"]
    workflow.SCENARIOS = ["Target"]
    workflow.RUN_OUTPUT_LABEL = "APEC_PREFLIGHT_AGGREGATE_RETRY_20260715"
    workflow.RUN_MODE = "full"
    workflow.__dict__.update(workflow._PRESET_BASELINE_SEED)
    workflow.PREFLIGHT_COMPRESSED_PROJECTION_ONLY = True
    workflow.PREFLIGHT_COMPRESSED_FAIL_FAST = True
    workflow.RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = False
    workflow.run_with_config()


#%% Frequently changed run toggle
RUN_APEC_PREFLIGHT = False

if RUN_APEC_PREFLIGHT:
    run_apec_preflight_after_aggregate()

#%%

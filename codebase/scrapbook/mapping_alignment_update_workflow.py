#%%
"""Retired compatibility entry point for canonical mapping maintenance.

The former workflow updated both ``leap_mappings.xlsx`` and
``master_config.xlsx``. All mapping maintenance now belongs to the canonical
``outlook_mappings_master.xlsx`` workflow.
"""
from codebase.outlook_mapping_maintenance_workflow import run_workflow


def run_mapping_alignment_update() -> dict[str, object]:
    """Run canonical Outlook mapping maintenance without legacy workbook writes."""
    return run_workflow()


#%%
RUN_MAPPING_ALIGNMENT_UPDATE = False

if RUN_MAPPING_ALIGNMENT_UPDATE:
    RESULT = run_mapping_alignment_update()
#%%

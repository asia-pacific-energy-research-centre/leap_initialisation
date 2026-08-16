#%%
"""Select temporary LEAP export destinations from each economy's template."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from codebase.utilities import leap_export_template_resolver


NONENERGY_FUELS: tuple[str, ...] = (
    "Additives and oxygenates",
    "Anthracite",
    "BKB and PB",
    "Biogas",
    "Bitumen",
    "Coal tar",
    "Coke oven coke",
    "Coke oven gas",
    "Crude oil",
    "Ethane",
    "Fuel oil",
    "Gas and diesel oil",
    "Kerosene",
    "LPG",
    "Lubricants",
    "Motor gasoline",
    "Naphtha",
    "Natural gas",
    "Natural gas liquids",
    "Other bituminous coal",
    "Other products",
    "Paraffin waxes",
    "Petroleum coke",
    "Refinery gas not liquefied",
    "Sub bituminous coal",
    "White spirit SBP",
)

PREFERRED_NONENERGY_SECTOR = "Non Energy Use"
LEGACY_NONENERGY_SECTOR = "Other sector"
PREFERRED_GREEN_ELECTRICITY_LABEL = "Electricity for hydrogen"
LEGACY_GREEN_ELECTRICITY_LABEL = "Electricity"

_DEMAND_ROOT = r"Demand\All demand aggregated"
_ELECTROLYSER_FEEDSTOCK_ROOT = (
    r"Transformation\Hydrogen transformation\Processes\Electrolysers\Feedstock Fuels"
)


def _required_nonenergy_paths(sector_label: str) -> set[str]:
    """Return the complete canonical non-energy branch set for one destination."""
    return {f"{_DEMAND_ROOT}\\{sector_label}\\{fuel}" for fuel in NONENERGY_FUELS}


def _missing_paths(required_paths: set[str], template_paths: frozenset[str]) -> list[str]:
    """Return deterministic missing-path diagnostics."""
    return sorted(required_paths.difference(template_paths))


def resolve_template_compatibility(
    economy: str,
    template_path: Path | str | None = None,
) -> dict[str, object]:
    """Choose preferred or legacy destinations after checking exact template rows."""
    is_aggregate = leap_export_template_resolver.is_aggregate_economy(economy)
    if template_path is None and is_aggregate:
        # Compressed preflight uses 00_APEC as a synthetic aggregate and never
        # imports its workbook into one LEAP area. Match the established
        # aggregate structural rule: use the union of available area templates
        # for label compatibility, but never borrow any area's IDs.
        template = None
        resolved_template_path = Path("APEC_TEMPLATE_BRANCH_PATH_UNION")
        template_paths = (
            leap_export_template_resolver.resolve_template_branch_paths_or_apec_union(
                economy
            )
        )
    else:
        template = (
            leap_export_template_resolver.find_leap_export_template(economy)
            if template_path is None
            else None
        )
        resolved_template_path = Path(
            template.path if template is not None else template_path
        )
        template_paths = (
            leap_export_template_resolver.read_leap_export_template_branch_paths(
                resolved_template_path
            )
        )

    preferred_nonenergy_missing = _missing_paths(
        _required_nonenergy_paths(PREFERRED_NONENERGY_SECTOR), template_paths
    )
    legacy_nonenergy_missing = _missing_paths(
        _required_nonenergy_paths(LEGACY_NONENERGY_SECTOR), template_paths
    )
    if not preferred_nonenergy_missing:
        nonenergy_sector = PREFERRED_NONENERGY_SECTOR
    elif not legacy_nonenergy_missing:
        nonenergy_sector = LEGACY_NONENERGY_SECTOR
    else:
        raise ValueError(
            f"Template {resolved_template_path.name} supports neither the complete preferred "
            f"nor legacy non-energy branch set for {economy}. "
            f"Preferred missing={len(preferred_nonenergy_missing)}; "
            f"legacy missing={len(legacy_nonenergy_missing)}."
        )

    preferred_green_path = (
        f"{_ELECTROLYSER_FEEDSTOCK_ROOT}\\{PREFERRED_GREEN_ELECTRICITY_LABEL}"
    )
    legacy_green_path = (
        f"{_ELECTROLYSER_FEEDSTOCK_ROOT}\\{LEGACY_GREEN_ELECTRICITY_LABEL}"
    )
    if preferred_green_path in template_paths:
        green_electricity_label = PREFERRED_GREEN_ELECTRICITY_LABEL
    elif legacy_green_path in template_paths:
        green_electricity_label = LEGACY_GREEN_ELECTRICITY_LABEL
    else:
        raise ValueError(
            f"Template {resolved_template_path.name} supports neither the preferred "
            f"nor legacy electrolyser electricity branch for {economy}."
        )

    return {
        "economy": str(economy),
        "template_path": str(resolved_template_path),
        "template_filename": resolved_template_path.name,
        "template_is_provisional": bool(
            template.is_provisional
            if template is not None
            else (
                False
                if is_aggregate and template_path is None
                else leap_export_template_resolver.is_provisional_template(
                    resolved_template_path
                )
            )
        ),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "preferred_nonenergy_supported": not preferred_nonenergy_missing,
        "legacy_nonenergy_supported": not legacy_nonenergy_missing,
        "selected_nonenergy_sector": nonenergy_sector,
        "preferred_nonenergy_missing_count": len(preferred_nonenergy_missing),
        "preferred_nonenergy_missing_paths": " | ".join(preferred_nonenergy_missing),
        "legacy_nonenergy_missing_count": len(legacy_nonenergy_missing),
        "legacy_nonenergy_missing_paths": " | ".join(legacy_nonenergy_missing),
        "preferred_green_electricity_supported": preferred_green_path in template_paths,
        "legacy_green_electricity_supported": legacy_green_path in template_paths,
        "selected_green_electricity_label": green_electricity_label,
    }


def write_template_compatibility_audit(
    economies: Iterable[str],
    audit_path: Path | str,
) -> tuple[dict[str, dict[str, object]], Path]:
    """Resolve all run economies before export and write the decisions to CSV."""
    decisions = {
        str(economy): resolve_template_compatibility(str(economy))
        for economy in economies
    }
    resolved_audit_path = Path(audit_path)
    resolved_audit_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(decisions.values()).sort_values("economy").to_csv(
        resolved_audit_path,
        index=False,
    )
    print(f"[INFO] Wrote template compatibility audit: {resolved_audit_path}")
    for economy, decision in decisions.items():
        print(
            f"[INFO] [{economy}] template compatibility: non-energy -> "
            f"{decision['selected_nonenergy_sector']}; 17_x_green_electricity -> "
            f"{decision['selected_green_electricity_label']}."
        )
    return decisions, resolved_audit_path


def warn_if_all_templates_support_preferred(audit_path: Path | str) -> bool:
    """Warn only when the audit covers every real template and all are migrated."""
    resolved_audit_path = Path(audit_path)
    audit = pd.read_csv(resolved_audit_path)
    available = set(
        leap_export_template_resolver.available_template_economies(
            include_provisional=False
        )
    )
    audited = set(audit["economy"].astype(str))
    supports_preferred = bool(
        not audit.empty
        and audit["preferred_nonenergy_supported"].astype(str).str.lower().eq("true").all()
        and audit["preferred_green_electricity_supported"].astype(str).str.lower().eq("true").all()
    )
    if available and audited == available and supports_preferred:
        print(
            "[WARN] Every non-provisional economy template now supports the preferred "
            "Non Energy Use and Electricity for hydrogen branches. Confirm the template "
            "migration and downstream mappings are fully implemented, then remove the "
            f"legacy compatibility behavior. Audit: {resolved_audit_path}"
        )
        return True
    return False


#%%

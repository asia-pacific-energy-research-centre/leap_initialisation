"""Supply branch classification helpers for LEAP Resources exports."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg
from codebase.configuration.all_products_and_flows import ESTO_PRODUCT_LIST
from codebase.functions.leap_core import sanitize_leap_name
from codebase.utilities.master_config import read_config_table

REPO_ROOT = Path(__file__).resolve().parents[2]

SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH = Path(
    getattr(
        workflow_cfg,
        "SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH",
        REPO_ROOT / "data" / "full model export.xlsx",
    )
)
SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET = str(
    getattr(
        workflow_cfg,
        "SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET",
        "Export",
    )
)
SUPPLY_ROOT_CLASSIFICATION_STRICT = bool(
    getattr(
        workflow_cfg,
        "SUPPLY_ROOT_CLASSIFICATION_STRICT",
        False,
    )
)

_SUPPLY_ROOT_LOOKUP_CACHE: dict[str, str] | None = None
_SUPPLY_ROOT_LOOKUP_SOURCE_INFO: dict[str, object] | None = None
_SUPPLY_ROOT_LOOKUP_MISS_WARNED: set[str] = set()
_SUPPLY_BRANCH_PATH_LOOKUP_CACHE: set[str] | None = None
_SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO: dict[str, object] | None = None
_SUPPLY_BRANCH_PATH_MISS_WARNED: set[str] = set()
_SUPPLY_BRANCH_LABEL_LOOKUP_CACHE: dict[tuple[str, str], str] | None = None

SECONDARY_ESTO_PRODUCT_MAJOR_CODES = {"02", "04", "07"}
SECONDARY_ESTO_PRODUCT_EXACT = {
    "06.03 Refinery feedstocks",
    "06.04 Additives/ oxygenates",
    "06.05 Other hydrocarbons",
    "08.02 LNG",
    "08.03 Gas works gas",
    "15.03 Charcoal",
    "15.04 Black liqour",
    "16.05 Biogasoline",
    "16.06 Biodiesel",
    "16.07 Bio jet kerosene",
    "16.08 Other liquid biofuels",
    "17 Electricity",
    "18 Heat",
}


def _esto_product_major_code(product):
    """Return the two-digit ESTO major product code when present."""
    text = str(product or "").strip()
    match = re.match(r"^(\d{2})(?:[.\s]|$)", text)
    if match:
        return match.group(1)
    return ""


def _is_secondary_esto_product(product):
    """Return True for ESTO products that originate from transformation/refinement."""
    major_code = _esto_product_major_code(product)
    if major_code in {"19", "20", "21"}:
        return False
    if product in SECONDARY_ESTO_PRODUCT_EXACT:
        return True
    return major_code in SECONDARY_ESTO_PRODUCT_MAJOR_CODES


ESTO_PRODUCT_CLASSIFICATION = {
    product: ("secondary" if _is_secondary_esto_product(product) else "primary")
    for product in ESTO_PRODUCT_LIST
    if _esto_product_major_code(product) not in {"19", "20", "21"}
}


def _normalize_supply_lookup_fuel_name(value):
    """Normalize a fuel label into a stable lookup key for branch-root resolution."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Strip leading ESTO product code prefix (e.g. "02.08 " or "07.04.01 ") so that
    # "02.08 BKB and PB" and "BKB and PB" both normalize to the same key.
    text = re.sub(r"^\d+(\.\d+)*\s+", "", text).strip()
    sanitized = sanitize_leap_name(text)
    normalized = " ".join(str(sanitized or "").strip().lower().split())
    return normalized


def _read_branch_variable_rows_from_workbook(
    source_path,
    sheet_name="Export",
):
    """Read workbook rows by auto-detecting the header row containing Branch Path + Variable."""
    path = Path(str(source_path).replace("\\", "/"))
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        return pd.DataFrame()
    raw = read_config_table(path, sheet_name=sheet_name, header=None)
    header_row = None
    for idx in range(len(raw.index)):
        values = {
            str(item).strip().lower()
            for item in raw.iloc[idx].tolist()
            if str(item).strip() and str(item).lower() != "nan"
        }
        if "branch path" in values and "variable" in values:
            header_row = int(idx)
            break
    if header_row is None:
        return pd.DataFrame()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = raw.iloc[header_row].tolist()
    if "Branch Path" not in data.columns:
        return pd.DataFrame()
    data = data[data["Branch Path"].notna()].copy()
    return data


def _load_supply_root_lookup_from_export():
    """Load and cache supply root (Primary/Secondary) lookup from the canonical LEAP export."""
    global _SUPPLY_ROOT_LOOKUP_CACHE
    global _SUPPLY_ROOT_LOOKUP_SOURCE_INFO
    if _SUPPLY_ROOT_LOOKUP_CACHE is not None:
        return _SUPPLY_ROOT_LOOKUP_CACHE

    path = Path(str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH).replace("\\", "/"))
    if not path.is_absolute():
        path = REPO_ROOT / path
    sheet = str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET).strip() or "Export"

    if not path.exists():
        print(
            "[WARN] Supply root classification source workbook not found: "
            f"{path}. Falling back to legacy ESTO-based classification."
        )
        _SUPPLY_ROOT_LOOKUP_SOURCE_INFO = {
            "path": str(path),
            "sheet": sheet,
            "status": "missing",
            "lookup_size": 0,
        }
        _SUPPLY_ROOT_LOOKUP_CACHE = {}
        return _SUPPLY_ROOT_LOOKUP_CACHE

    try:
        rows = _read_branch_variable_rows_from_workbook(path, sheet_name=sheet)
    except Exception as exc:
        print(
            "[WARN] Failed reading supply root classification source workbook "
            f"{path} (sheet={sheet}): {exc}. Falling back to legacy ESTO-based classification."
        )
        _SUPPLY_ROOT_LOOKUP_SOURCE_INFO = {
            "path": str(path),
            "sheet": sheet,
            "status": "read_failed",
            "lookup_size": 0,
        }
        _SUPPLY_ROOT_LOOKUP_CACHE = {}
        return _SUPPLY_ROOT_LOOKUP_CACHE

    root_counts_by_fuel: dict[str, dict[str, int]] = {}
    for branch_path in rows.get("Branch Path", pd.Series(dtype=str)).astype(str):
        parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
        if len(parts) < 3:
            continue
        if parts[0].lower() != "resources":
            continue
        root = parts[1].strip().title()
        if root not in {"Primary", "Secondary"}:
            continue
        fuel_key = _normalize_supply_lookup_fuel_name(parts[2])
        if not fuel_key:
            continue
        bucket = root_counts_by_fuel.setdefault(fuel_key, {"Primary": 0, "Secondary": 0})
        bucket[root] = int(bucket.get(root, 0)) + 1

    lookup: dict[str, str] = {}
    conflicts: list[tuple[str, dict[str, int]]] = []
    for fuel_key, counts in root_counts_by_fuel.items():
        primary_count = int(counts.get("Primary", 0))
        secondary_count = int(counts.get("Secondary", 0))
        if primary_count and secondary_count:
            conflicts.append((fuel_key, counts))
            chosen = "Primary" if primary_count >= secondary_count else "Secondary"
            lookup[fuel_key] = chosen
            continue
        lookup[fuel_key] = "Secondary" if secondary_count > 0 else "Primary"

    if conflicts:
        preview = ", ".join(
            [
                f"{fuel} (Primary={counts.get('Primary', 0)}, Secondary={counts.get('Secondary', 0)})"
                for fuel, counts in conflicts[:20]
            ]
        )
        print(
            "[WARN] Supply root source has fuel(s) mapped to both Primary and Secondary; "
            f"using majority root for {len(conflicts)} fuel(s). Sample: {preview}"
        )

    print(
        "[INFO] Loaded supply root classification lookup from LEAP export source: "
        f"{path} (sheet={sheet}, fuels={len(lookup)})."
    )
    _SUPPLY_ROOT_LOOKUP_SOURCE_INFO = {
        "path": str(path),
        "sheet": sheet,
        "status": "loaded",
        "lookup_size": int(len(lookup)),
        "conflicts": int(len(conflicts)),
    }
    _SUPPLY_ROOT_LOOKUP_CACHE = lookup
    return _SUPPLY_ROOT_LOOKUP_CACHE


def _resolve_supply_root_from_export_lookup(*candidates):
    """Resolve Primary/Secondary from workbook lookup using candidate labels."""
    lookup = _load_supply_root_lookup_from_export()
    if not lookup:
        return None
    for candidate in candidates:
        key = _normalize_supply_lookup_fuel_name(candidate)
        if not key:
            continue
        root = lookup.get(key)
        if root in {"Primary", "Secondary"}:
            return root
    return None


def _normalize_supply_branch_path_for_lookup(branch_path):
    """Normalize Resources branch paths for existence checks against export source."""
    parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
    if len(parts) < 3:
        return ""
    if parts[0].lower() != "resources":
        return ""
    root = parts[1].strip().lower()
    if root not in {"primary", "secondary"}:
        return ""
    fuel = _normalize_supply_lookup_fuel_name(parts[2])
    if not fuel:
        return ""
    return f"resources\\{root}\\{fuel}"


def _load_supply_branch_path_lookup_from_export():
    """Load existing Resources branch paths from canonical LEAP export source."""
    global _SUPPLY_BRANCH_PATH_LOOKUP_CACHE
    global _SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO
    if _SUPPLY_BRANCH_PATH_LOOKUP_CACHE is not None:
        return _SUPPLY_BRANCH_PATH_LOOKUP_CACHE

    path = Path(str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH).replace("\\", "/"))
    if not path.is_absolute():
        path = REPO_ROOT / path
    sheet = str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET).strip() or "Export"
    if not path.exists():
        _SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO = {
            "path": str(path),
            "sheet": sheet,
            "status": "missing",
            "lookup_size": 0,
        }
        _SUPPLY_BRANCH_PATH_LOOKUP_CACHE = set()
        return _SUPPLY_BRANCH_PATH_LOOKUP_CACHE
    try:
        rows = _read_branch_variable_rows_from_workbook(path, sheet_name=sheet)
    except Exception as exc:
        print(
            "[WARN] Failed reading supply branch-path lookup from LEAP export source "
            f"{path} (sheet={sheet}): {exc}. Branch existence checks disabled."
        )
        _SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO = {
            "path": str(path),
            "sheet": sheet,
            "status": "read_failed",
            "lookup_size": 0,
        }
        _SUPPLY_BRANCH_PATH_LOOKUP_CACHE = set()
        return _SUPPLY_BRANCH_PATH_LOOKUP_CACHE
    lookup: set[str] = set()
    for branch_path in rows.get("Branch Path", pd.Series(dtype=str)).astype(str):
        token = _normalize_supply_branch_path_for_lookup(branch_path)
        if token:
            lookup.add(token)
    _SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO = {
        "path": str(path),
        "sheet": sheet,
        "status": "loaded",
        "lookup_size": int(len(lookup)),
    }
    _SUPPLY_BRANCH_PATH_LOOKUP_CACHE = lookup
    return _SUPPLY_BRANCH_PATH_LOOKUP_CACHE


def _load_supply_branch_label_lookup_from_export():
    """Load normalized resource fuel labels and their exact template spelling."""
    global _SUPPLY_BRANCH_LABEL_LOOKUP_CACHE
    if _SUPPLY_BRANCH_LABEL_LOOKUP_CACHE is not None:
        return _SUPPLY_BRANCH_LABEL_LOOKUP_CACHE

    path = Path(str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH).replace("\\", "/"))
    if not path.is_absolute():
        path = REPO_ROOT / path
    sheet = str(SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET).strip() or "Export"
    lookup: dict[tuple[str, str], str] = {}
    if not path.exists():
        _SUPPLY_BRANCH_LABEL_LOOKUP_CACHE = lookup
        return lookup

    try:
        rows = _read_branch_variable_rows_from_workbook(path, sheet_name=sheet)
        for branch_path in rows.get("Branch Path", pd.Series(dtype=str)).astype(str):
            parts = [part.strip() for part in str(branch_path or "").split("\\") if part.strip()]
            if len(parts) < 3 or parts[0].lower() != "resources":
                continue
            root = parts[1].strip().title()
            if root not in {"Primary", "Secondary"}:
                continue
            fuel_label = parts[2].strip()
            normalized = _normalize_supply_lookup_fuel_name(fuel_label)
            if normalized:
                lookup.setdefault((root.lower(), normalized), fuel_label)
    except Exception as exc:
        print(
            "[WARN] Failed reading exact supply branch labels from export source "
            f"{path} (sheet={sheet}): {exc}"
        )
    _SUPPLY_BRANCH_LABEL_LOOKUP_CACHE = lookup
    return lookup


def _resolve_supply_branch_label_from_export(root, *candidates):
    """Return the exact template fuel label for a resolved resource root."""
    lookup = _load_supply_branch_label_lookup_from_export()
    root_key = str(root or "").strip().lower()
    if root_key not in {"primary", "secondary"}:
        return None
    for candidate in candidates:
        normalized = _normalize_supply_lookup_fuel_name(candidate)
        if not normalized:
            continue
        label = lookup.get((root_key, normalized))
        if label:
            return label
    return None


def _supply_branch_exists_in_export_source(branch_path):
    """Return True when branch path exists in canonical export source (or source unavailable)."""
    lookup = _load_supply_branch_path_lookup_from_export()
    info = _SUPPLY_BRANCH_PATH_LOOKUP_SOURCE_INFO or {}
    if str(info.get("status") or "").lower() != "loaded":
        # Do not block exports when source is unavailable.
        return True
    token = _normalize_supply_branch_path_for_lookup(branch_path)
    if not token:
        return False
    return token in lookup


def _classify_supply_root_for_product(product_label):
    """Return the supply root classification ('primary' or 'secondary') for an ESTO product."""
    label = str(product_label or "").strip()
    if not label:
        return "primary"
    mapped = ESTO_PRODUCT_CLASSIFICATION.get(label)
    if mapped in {"primary", "secondary"}:
        return mapped
    # Fallback to prefix-based rule for products not present in ESTO_PRODUCT_LIST.
    return "secondary" if _is_secondary_esto_product(label) else "primary"


def _get_supply_branch_roots_for_entry(fuel_key, fuel_entry):
    """Resolve the LEAP supply branch root(s) for one export fuel entry."""
    entry = fuel_entry or {}
    fuel_name = str(entry.get("fuel_name") or "").strip()
    esto_label = str(entry.get("fuel_label_esto") or "").strip()
    key_label = str(fuel_key or "").strip()

    root_from_export = _resolve_supply_root_from_export_lookup(
        fuel_name,
        esto_label,
        key_label,
    )
    if root_from_export in {"Primary", "Secondary"}:
        return [["Resources", root_from_export]]

    missing_key = _normalize_supply_lookup_fuel_name(fuel_name or esto_label or key_label)
    if missing_key and missing_key not in _SUPPLY_ROOT_LOOKUP_MISS_WARNED:
        _SUPPLY_ROOT_LOOKUP_MISS_WARNED.add(missing_key)
        if SUPPLY_ROOT_CLASSIFICATION_STRICT:
            raise ValueError(
                "Supply root classification missing from LEAP export source for fuel "
                f"'{fuel_name or esto_label or key_label}'. "
                f"Source={SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH} "
                f"(sheet={SUPPLY_ROOT_CLASSIFICATION_SOURCE_SHEET})."
            )
        print(
            "[WARN] Supply root classification not found in LEAP export source for fuel "
            f"'{fuel_name or esto_label or key_label}'. "
            "Falling back to legacy ESTO-based classification."
        )

    classification = _classify_supply_root_for_product(esto_label or fuel_name or key_label)
    if classification == "secondary":
        return [["Resources", "Secondary"]]
    return [["Resources", "Primary"]]

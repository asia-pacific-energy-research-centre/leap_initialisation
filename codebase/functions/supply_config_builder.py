"""Workbook-backed supply fuel config and display-name helpers."""
from __future__ import annotations

import pandas as pd

from codebase.functions.esto_data_utils import try_debug_breakpoint
from codebase.utilities.master_config import config_table_exists, read_config_table


def find_first_existing_file(path_candidates):
    """Return the first path that exists from the provided candidates."""
    try:
        for path in path_candidates:
            if config_table_exists(path):
                return path
        print(f"No code-to-name workbook found in {path_candidates}")
        return None
    except Exception as exc:
        print(f"Failed to locate workbook from {path_candidates}: {exc}")
        try_debug_breakpoint()
        raise


def load_code_to_name_mapping(path_candidates):
    """Load a code-to-name mapping from the first available workbook."""
    try:
        for path in path_candidates:
            if not config_table_exists(path, sheet_name="code_to_name"):
                continue
            mapping_df = read_config_table(path, sheet_name="code_to_name", dtype=str).fillna("")
            mapping = {}

            if "code" in mapping_df.columns and "name" in mapping_df.columns:
                working = mapping_df.copy()
                if "source_sheet" in working.columns:
                    working["source_sheet"] = working["source_sheet"].fillna("").astype(str)
                    working["source_priority"] = working["source_sheet"].ne("9th").astype(int)
                    working = (
                        working.sort_values("source_priority")
                        .drop_duplicates(subset=["code"], keep="first")
                        .drop(columns=["source_priority"])
                    )
                else:
                    working = working.drop_duplicates(subset=["code"], keep="first")

                mapping.update(
                    dict(
                        zip(
                            working["code"].astype(str).str.strip(),
                            working["name"].astype(str).str.strip(),
                        )
                    )
                )

            if "9th_label" in mapping_df.columns and "name" in mapping_df.columns:
                ninth_labels = mapping_df["9th_label"].astype(str).str.strip()
                names = mapping_df["name"].astype(str).str.strip()
                mapping.update({label: name for label, name in zip(ninth_labels, names) if label})

            if "esto_label" in mapping_df.columns and "name" in mapping_df.columns:
                esto_labels = mapping_df["esto_label"].astype(str).str.strip()
                names = mapping_df["name"].astype(str).str.strip()
                mapping.update({label: name for label, name in zip(esto_labels, names) if label})

            if mapping:
                print(f"Loaded code-to-name mapping from {path}: {len(mapping)} entries")
                return mapping

        print("Code-to-name mapping not found; using labels as-is.")
        return {}
    except Exception as exc:
        print(f"Failed to load code-to-name mapping: {exc}")
        try_debug_breakpoint()
        raise


def map_code_label(label, code_to_name_mapping):
    """Return a label mapped to a human-readable name when available."""
    try:
        if not code_to_name_mapping:
            return label
        if label is None:
            return label
        if isinstance(label, float) and pd.isna(label):
            return label
        return code_to_name_mapping.get(str(label), label)
    except Exception as exc:
        print(f"Failed to map label {label}: {exc}")
        try_debug_breakpoint()
        raise


def apply_code_to_name_mapping(major_sector_config, code_to_name_mapping):
    """Apply code-to-name mapping to build display names in sector config."""
    try:
        updated = {}
        for fuel_key, fuel_config in major_sector_config.items():
            updated_config = fuel_config.copy()
            mapped_name = map_code_label(fuel_key, code_to_name_mapping)
            if mapped_name == fuel_key:
                mapped_name = updated_config.get("fuel_label_esto", fuel_key)
            updated_config["fuel_name"] = mapped_name
            updated[fuel_key] = updated_config
        return updated
    except Exception as exc:
        print(f"Failed to apply code-to-name mapping: {exc}")
        try_debug_breakpoint()
        raise


def build_supply_sector_config(
    code_to_name_paths,
    exclude_prefixes=None,
    dataset_key="esto",
):
    """Build sector config entries for every ESTO fuel product."""
    workbook_path = None
    for path in code_to_name_paths:
        if config_table_exists(path, sheet_name="ESTO"):
            workbook_path = path
            break
    if not workbook_path:
        print(
            "Warning: code-to-name workbook is missing; supply export will run with an empty sector config."
        )
        return {}
    try:
        df = read_config_table(workbook_path, sheet_name="ESTO", dtype=str)
        df = df[df["products"].notna()].copy()
        df["products"] = df["products"].astype(str).str.strip()
        if exclude_prefixes:
            mask = ~df["products"].str.startswith(tuple(exclude_prefixes), na=False)
            df = df[mask]
        mapping_df = read_config_table(workbook_path, sheet_name="code_to_name", dtype=str).fillna("")
        lookup = {
            str(row.get("esto_label") or "").strip(): row.to_dict()
            for _, row in mapping_df.iterrows()
            if str(row.get("esto_label") or "").strip()
        }

        config = {}
        for product in sorted(df["products"].unique()):
            entry = lookup.get(product, {})
            config[product] = {
                "dataset_key": dataset_key,
                "fuel_label_esto": product,
                "fuel_code_ninth": entry.get("9th_label") or None,
                "fuel_name": entry.get("name") or product,
            }
        print(
            f"Built supply config for {len(config)} ESTO products "
            f"(excluding prefixes {exclude_prefixes})."
        )
        return config
    except Exception as exc:
        print(f"Failed to build supply sector config: {exc}")
        try_debug_breakpoint()
        raise

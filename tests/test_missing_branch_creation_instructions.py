import pandas as pd

from codebase.analysis import missing_branch_esto_vintage_impact as report


def test_creation_instructions_keep_only_source_energy(monkeypatch, tmp_path):
    findings = pd.DataFrame(
        {
            "rule_id": ["SEED-011", "SEED-011", "SEED-011"],
            "status": ["fail", "fail", "fail"],
            "economy": ["05_PRC"] * 3,
            "Branch Path": [
                r"Transformation\Coal mines\BKB and PB",
                r"Transformation\Coal mines\Patent fuel",
                r"Transformation\Coal mines\Lubricants",
            ],
        }
    )

    def fake_esto(path, keys, vintage, base_year):
        values = {"2024": 0.0, "2025": 0.0, "2026": 0.0}
        if vintage == "2024":
            values["2024"] = 12.0
        return pd.DataFrame(
            {
                "economy": keys["economy"],
                "branch_path": keys["branch_path"],
                f"esto_{vintage}_base_{base_year}": keys["branch_path"].map(
                    lambda path: values["2024"] if path.endswith("BKB and PB") else 0.0
                ),
            }
        )

    def fake_ninth(keys, data_path=None):
        return pd.DataFrame(
            {
                "economy": keys["economy"],
                "branch_path": keys["branch_path"],
                "ninth_2024_projected_sum": [5.0, 7.0, 9.0],
                "ninth_2025_projected_sum": [5.0, 7.0, 9.0],
                "ninth_2026_projected_sum": [5.0, 7.0, 9.0],
                "ninth_match_mode": ["fuel_aggregate_fallback", "fuel_aggregate_fallback", "exact_subfuel"],
            }
        )

    monkeypatch.setattr(report, "load_esto_values", fake_esto)
    monkeypatch.setattr(report, "load_ninth_projection_values", fake_ninth)
    seed_rows = {
        "05_PRC": pd.DataFrame(
            {
                "Branch Path": [r"Transformation\Coal mines\Lubricants"],
                "Variable": ["Activity Level"],
                "2022": [0.0],
            }
        )
    }
    output = tmp_path / "missing_branch_creation_instructions.csv"
    result = report.build_creation_instructions_for_run(
        findings,
        seed_rows_by_economy=seed_rows,
        output_path=output,
        esto_vintages={name: (None, year) for name, year in (("2024", 2022), ("2025", 2023), ("2026", 2024))},
    )

    assert set(result["branch_label"]) == {"BKB and PB", "Patent fuel"}
    assert "Lubricants" not in set(result["branch_label"])
    assert result.loc[result["branch_label"].eq("Patent fuel"), "ninth_match_mode"].item() == "exact_subfuel"
    assert output.exists()

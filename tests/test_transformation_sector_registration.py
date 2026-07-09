#%%
# Summary: Verify that composite transformation analyses register every LEAP module they own.

from codebase.functions import transformation_analysis_utils as core


def test_gas_works_and_blending_are_independently_registered(monkeypatch):
    callback_calls = []

    monkeypatch.setattr(core, "DATASET_MAP", {"esto": (object(), [2022])})
    monkeypatch.setattr(core, "resolve_dataset", lambda dataset_map, key: dataset_map[key])
    monkeypatch.setattr(core, "get_economy_list", lambda data, configured: ["01_AUS"])
    monkeypatch.setattr(core, "map_code_label", lambda label, mapping: label)

    def callback(data, year_cols, economy, loss_data, loss_year_cols, sector_config, records):
        callback_calls.append((economy, sector_config["sector_key"]))

    core.reset_analyzed_sector_titles()
    core.run_analysis_for_sector(True, "gas_works", callback, [])
    assert core.get_analyzed_sector_titles() == {"Gas works plants"}

    core.reset_analyzed_sector_titles()
    core.run_analysis_for_sector(True, "gas_blending", callback, [])
    assert core.get_analyzed_sector_titles() == {"Natural gas blending plants"}

    assert callback_calls == [("01_AUS", "gas_works"), ("01_AUS", "gas_blending")]


def test_lng_registers_liquefaction_and_regasification(monkeypatch):
    monkeypatch.setattr(core, "DATASET_MAP", {"ninth": (object(), [2022])})
    monkeypatch.setattr(core, "resolve_dataset", lambda dataset_map, key: dataset_map[key])
    monkeypatch.setattr(core, "get_economy_list", lambda data, configured: ["01_AUS"])
    monkeypatch.setattr(core, "map_code_label", lambda label, mapping: label)

    core.reset_analyzed_sector_titles()
    core.run_analysis_for_sector(True, "lng", lambda *parameters: None, [])

    assert core.get_analyzed_sector_titles() == {
        "NG Liquefaction",
        "LNG regasification",
    }


def test_nonspecified_transformation_registers_canonical_title(monkeypatch):
    monkeypatch.setattr(core, "DATASET_MAP", {"esto": (object(), [2022])})
    monkeypatch.setattr(core, "resolve_dataset", lambda dataset_map, key: dataset_map[key])
    monkeypatch.setattr(core, "get_economy_list", lambda data, configured: ["01_AUS"])
    monkeypatch.setattr(core, "map_code_label", lambda label, mapping: label)

    core.reset_analyzed_sector_titles()
    core.run_analysis_for_sector(True, "nonspecified_transformation", lambda *parameters: None, [])

    assert core.get_analyzed_sector_titles() == {"Non specified transformation"}


#%%

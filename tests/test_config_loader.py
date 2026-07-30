from tvrenamer.config import load_config


def test_load_config_from_path(tmp_path):
    cfg = tmp_path / ".tvrenamer.toml"
    cfg.write_text('[providers]\norder = ["wikidata","wikipedia"]\n')
    data = load_config(str(cfg), root=None)
    assert "providers" in data
    assert data["providers"]["order"][0] == "wikidata"


def test_load_config_from_root(tmp_path):
    cfg = tmp_path / ".tvrenamer.toml"
    cfg.write_text('[defaults]\ntemplate = "{show}"\n')
    data = load_config(path=None, root=str(tmp_path))
    assert data.get("defaults", {}).get("template") == "{show}"

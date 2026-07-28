from app.config import Settings


def test_settings_load_yaml_from_env(tmp_path, monkeypatch):
    keywords = tmp_path / "keywords.yaml"
    rules = tmp_path / "rules.yaml"
    keywords.write_text("pow_terms: [pow]\ngpu_terms: [cuda]\nlaunch_terms: [mainnet]\nrisk_terms: [premine]\n", encoding="utf-8")
    rules.write_text("thresholds:\n  qualified: 75\n", encoding="utf-8")

    monkeypatch.setenv("KEYWORDS_FILE", str(keywords))
    monkeypatch.setenv("RULES_FILE", str(rules))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp.db")

    settings = Settings.from_env()
    assert settings.keywords()["pow_terms"] == ["pow"]
    assert settings.rules()["thresholds"]["qualified"] == 75

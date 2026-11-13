import json

import pytest

from limitful import config


def test_settings_round_trip_and_environment_override(monkeypatch):
    assert config.load() == {} and config.provider() is None and config.api_key() is None
    config.update(provider="claude", api_key="  key-1  ")
    assert (config.provider(), config.api_key()) == ("claude", "key-1")
    config.update(provider=None)
    assert (config.provider(), config.api_key()) == (None, "key-1")
    monkeypatch.setenv("LIMITFUL_LLM", "ollama")
    assert config.provider() == "ollama"
    with pytest.raises(ValueError):
        config.update(provider="gpt")


def test_a_damaged_settings_file_is_treated_as_empty():
    config.config_path().parent.mkdir(parents=True)
    config.config_path().write_text("{not json")
    assert config.load() == {}
    config.config_path().write_text(json.dumps(["a list"]))
    assert config.load() == {}

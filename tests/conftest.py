import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Tests never read or write the real settings file or model choice."""
    monkeypatch.setenv("LIMITFUL_CONFIG", str(tmp_path / "settings" / "config.json"))
    for name in ("LIMITFUL_LLM", "LIMITFUL_TRANSCRIBER", "LIMITFUL_DATA", "LIMITFUL_CACHE", "PORT", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

import pytest

@pytest.fixture(autouse=True)
def isolated_model_mode(monkeypatch):
    # Unit/API fixtures never download weights. Production defaults to local inference.
    monkeypatch.setenv('SEMANTIC_MODE', 'fixture')

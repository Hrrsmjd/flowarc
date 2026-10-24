import pytest

from flowarc import gemini, store


@pytest.fixture(autouse=True)
def no_atlas(monkeypatch):
    """Tests never touch a real Atlas cluster, even with MONGODB_URI in .env."""
    monkeypatch.setattr(store, "db", lambda: None)


def _offline():
    raise RuntimeError("tests never call the real Gemini API")


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    """Tests never call Gemini, even with GEMINI_API_KEY set. Mock what a test needs."""
    monkeypatch.setattr(gemini, "client", _offline)

import pytest

from flowarc import store


@pytest.fixture(autouse=True)
def no_atlas(monkeypatch):
    """Tests never touch a real Atlas cluster, even with MONGODB_URI in .env."""
    monkeypatch.setattr(store, "db", lambda: None)

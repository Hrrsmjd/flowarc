from flowarc import config, dashboard, mock
from flowarc.sample import STAGES, Sample


def test_mock_state_shape():
    st = mock.state(now=1792800000.0)
    assert st["mode"] == "mock"
    featured = next(s for s in st["samples"] if s["id"] == st["run"]["featured"])
    assert any(e.get("failed") for e in featured["log"])  # the demo's failed check
    assert any(e.get("fix") for e in featured["log"])  # and Argon's fix
    for s in st["samples"]:
        assert s["stage"] in STAGES + ["done"]
    sources = {p["source"] for p in st["diversity"]["points"]}
    assert sources == {"flowarc", "car_baseline"}


def test_live_state_from_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    assert dashboard.live_state() is None
    s = Sample(id="s0001", concept={"name": "cow", "bucket": "animals"})
    s.record_check("novelty", True, nearest=0.3)
    s.save()
    st = dashboard.live_state()
    assert st["mode"] == "live"
    assert st["samples"][0]["title"] == "cow"
    assert st["samples"][0]["log"][0]["msg"] == "check novelty: pass"

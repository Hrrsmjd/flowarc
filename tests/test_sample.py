from flowarc import config
from flowarc.pipeline import advance
from flowarc.sample import Sample, all_samples


def test_sample_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    s = Sample(id="s0001", concept={"name": "cow"})
    s.record_check("watertight", True, holes=0)
    advance(s)
    loaded = Sample.load("s0001")
    assert loaded.stage == "images"
    assert loaded.checks["concept"][0]["passed"]
    assert [x.id for x in all_samples()] == ["s0001"]

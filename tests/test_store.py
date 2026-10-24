import mongomock
import pytest

from flowarc import concepts, config, gemini, store
from flowarc.pipeline import advance
from flowarc.sample import Sample, all_samples, coverage, nearest


@pytest.fixture
def atlas(monkeypatch):
    d = mongomock.MongoClient()["flowarc"]
    monkeypatch.setattr(store, "db", lambda: d)
    return d


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)


def test_registry_roundtrip_in_atlas(atlas, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    s = Sample(id="s0001", concept={"name": "cow", "bucket": "animals and organic forms"})
    s.record_check("watertight", True, holes=0)
    advance(s)
    loaded = Sample.load("s0001")
    assert loaded.stage == "images" and loaded.checks["concept"][0]["passed"]
    assert [x.id for x in all_samples()] == ["s0001"]
    assert atlas.logs.count_documents({"sample": "s0001"}) == 1
    assert not (tmp_path / "samples").exists()  # nothing written locally
    assert coverage() == {"animals and organic forms": 1}
    with pytest.raises(KeyError):
        Sample.load("missing")


def test_nearest_uses_vector_search(atlas, monkeypatch):
    seen = {}

    def aggregate(pipeline):
        seen["pipeline"] = pipeline
        return [
            {"_id": "s0002", "name": "cow", "score": 0.99},
            {"_id": "s0001", "name": "self", "score": 1.0},
        ]

    monkeypatch.setattr(atlas.samples, "aggregate", aggregate)
    rows = nearest([1.0, 0.0], k=1, exclude="s0001")
    search = seen["pipeline"][0]["$vectorSearch"]
    assert search["index"] == store.VECTOR_INDEX and search["filter"]["status"] == {"$ne": "failed"}
    assert rows == [{"id": "s0002", "name": "cow", "similarity": pytest.approx(0.98)}]


def test_novelty_check_local(local, monkeypatch):
    vectors = {
        "cow: a cow": [1.0, 0.0],
        "heifer: a young cow": [0.99, 0.1],
        "chair: a chair": [0.0, 1.0],
    }
    monkeypatch.setattr(gemini, "embed", lambda texts: [vectors[t] for t in texts])
    for i, (name, desc) in enumerate(
        [("cow", "a cow"), ("heifer", "a young cow"), ("chair", "a chair")]
    ):
        s = Sample(id=f"s{i}", concept={"name": name, "description": desc})
        passed = concepts.check_novelty(s)
        s.status = "pending" if passed else "failed"
        s.save()
        assert passed == (name != "heifer")
    check = Sample.load("s1").checks["concept"][0]
    assert check["nearest"][0]["name"] == "cow" and check["similarity"] > 0.92

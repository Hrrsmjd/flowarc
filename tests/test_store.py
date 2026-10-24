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
    assert atlas.logs.count_documents({"sample": "s0001"}) == 2  # the check + "advanced"
    assert not (tmp_path / "samples").exists()  # nothing written locally
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


def _capture(monkeypatch, coll, rows):
    seen = {}

    def aggregate(pipeline):
        seen["pipeline"] = pipeline
        return [dict(r) for r in rows]

    monkeypatch.setattr(coll, "aggregate", aggregate)
    return seen


def test_facets_from_search_meta(atlas, monkeypatch):
    meta = {
        "count": {"lowerBound": 3},
        "facet": {
            "bucket": {"buckets": [{"_id": "plants", "count": 2}, {"_id": "animals", "count": 1}]},
            "status": {"buckets": [{"_id": "done", "count": 3}]},
            "stage": {"buckets": []},
            "reynolds": {"buckets": [{"_id": 1000.0, "count": 3}]},
        },
    }
    seen = _capture(monkeypatch, atlas.samples, [meta])
    f = store.facets()
    stage = seen["pipeline"][0]["$searchMeta"]
    assert stage["index"] == store.TEXT_INDEX
    assert stage["facet"]["operator"] == store.NOT_FAILED
    assert f["total"] == 3 and f["bucket"] == {"plants": 2, "animals": 1}
    assert f["reynolds"] == {"1000.0": 3}
    assert coverage() == {"plants": 2, "animals": 1}


def test_facets_empty_registry(atlas, monkeypatch):
    _capture(monkeypatch, atlas.samples, [])
    assert store.facets() == {"total": 0} and store.coverage() == {}


def test_text_search_and_autocomplete(atlas, monkeypatch):
    seen = _capture(monkeypatch, atlas.samples, [{"_id": "s1", "name": "heron", "score": 2.5}])
    assert store.search("long legged bird") == [{"id": "s1", "name": "heron", "score": 2.5}]
    q = seen["pipeline"][0]["$search"]
    assert q["index"] == store.TEXT_INDEX and q["text"]["query"] == "long legged bird"
    _capture(monkeypatch, atlas.samples, [{"_id": "s1", "name": "heron"}])
    assert store.autocomplete("her") == ["heron"]


def test_check_results_are_searchable_log_fields(atlas, monkeypatch):
    s = Sample(id="s9", stage="mesh")
    s.record_check("watertight", False, holes=3)
    entry = atlas.logs.find_one({"sample": "s9"})
    assert entry["check"] == "watertight" and entry["passed"] is False and entry["holes"] == 3
    seen = _capture(monkeypatch, atlas.logs, [])
    store.search_log("holes", failed_only=True)
    q = seen["pipeline"][0]["$search"]
    assert q["index"] == store.LOG_INDEX
    assert q["compound"]["filter"] == [{"equals": {"path": "passed", "value": False}}]


def test_hybrid_fuses_semantic_and_keyword(atlas, monkeypatch):
    seen = _capture(monkeypatch, atlas.samples, [{"_id": "s1", "name": "heron", "score": 0.03}])
    rows = store.hybrid("long legged wading bird", k=3, bucket="animals and organic forms")
    assert rows == [{"id": "s1", "name": "heron", "score": 0.03}]
    fusion = seen["pipeline"][0]["$rankFusion"]["input"]["pipelines"]
    vs = fusion["semantic"][0]["$vectorSearch"]
    assert vs["index"] == store.SEMANTIC_INDEX and vs["query"] == "long legged wading bird"
    assert vs["filter"]["concept.bucket"] == "animals and organic forms"
    kw = fusion["keyword"][0]["$search"]
    assert kw["index"] == store.TEXT_INDEX and kw["compound"]["filter"]
    assert seen["pipeline"][1] == {"$limit": 3}


def test_find_similar_uses_hybrid_in_atlas(atlas, monkeypatch):
    from flowarc.sample import find_similar

    monkeypatch.setattr(store, "hybrid", lambda text, k, bucket: [{"id": "s1", "q": text}])
    assert find_similar("heron") == [{"id": "s1", "q": "heron"}]


def test_failure_memory_offline(local):
    from flowarc.sample import past_fixes, repair_context

    a = Sample(id="s1", stage="mesh")
    r1 = a.record_repair("mesh has 3 holes in the tail fin", "voxel remesh at 256")
    a.repair_outcome(r1, True)
    r2 = a.record_repair("floating fragments near the base", "drop small components")
    a.repair_outcome(r2, False)
    Sample(id="s2", stage="sim").record_repair("holes in the mesh", "smaller time step")
    fixes = past_fixes("two holes in the wing", "mesh")
    assert fixes == [
        {
            "sample": "s1",
            "diagnosis": "mesh has 3 holes in the tail fin",
            "action": "voxel remesh at 256",
        }
    ]
    assert "voxel remesh at 256" in repair_context("holes in wing", "mesh")
    assert repair_context("blow-up", "render") == ""


def test_failure_memory_in_atlas(atlas, monkeypatch):
    s = Sample(id="s1", stage="mesh")
    rid = s.record_repair("hole in fin", "voxel remesh")
    s.repair_outcome(rid, True)
    doc = atlas.repairs.find_one()
    assert doc["fixed"] is True and doc["stage"] == "mesh" and doc["sample"] == "s1"
    assert atlas.logs.find_one({"sample": "s1"})["diagnosis"] == "hole in fin"
    seen = _capture(monkeypatch, atlas.repairs, [{"sample": "s1", "action": "voxel remesh"}])
    assert store.past_fixes("holes", "mesh") == [{"sample": "s1", "action": "voxel remesh"}]
    pipes = seen["pipeline"][0]["$rankFusion"]["input"]["pipelines"]
    assert pipes["semantic"][0]["$vectorSearch"]["filter"] == {"stage": "mesh", "fixed": True}
    assert pipes["keyword"][0]["$search"]["index"] == store.REPAIR_TEXT_INDEX


def test_stage_stats_fallback_counts_the_log(atlas):
    s = Sample(id="s1", stage="mesh")
    s.record_check("watertight", False)
    s.record_check("watertight", True)
    advance(s)
    Sample(id="s2", stage="mesh").record_check("watertight", True)
    rows = {r["stage"]: r for r in store.metrics(minutes=5)}
    mesh = rows["mesh"]
    assert (mesh["checks"], mesh["passed"], mesh["failed"]) == (3, 2, 1)
    assert mesh["advanced"] == 1 and mesh["samples"] == 2


def test_metrics_prefers_stream_processor_output(atlas):
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    atlas.metrics.insert_one({"_id": "mesh@now", "stage": "mesh", "window": now, "passed": 4})
    assert store.metrics()[0]["passed"] == 4

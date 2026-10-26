import pytest

from flowarc import reviews, store
from flowarc.sample import Sample

mongomock = pytest.importorskip("mongomock")


@pytest.fixture
def db(monkeypatch, tmp_path):
    from flowarc import config

    monkeypatch.setattr(config, "DATA", tmp_path)
    d = mongomock.MongoClient()["flowarc"]
    monkeypatch.setattr(store, "db", lambda: d)
    return d


def sample(sid, **kw):
    s = Sample(sid, **kw)
    s.save()
    return s


def review(db, sid, decision, note=""):
    db.reviews.insert_one(
        {"sample": sid, "decision": decision, "note": note, "t": 1, "status": "new"}
    )


def test_retry_requeues_a_failed_sample_at_its_stage(db):
    sample("s00001", stage="sim", status="failed", attempts={"sim": 3})
    review(db, "s00001", "retry", "smaller time step")
    assert reviews.take() == ["s00001"]
    s = Sample.load("s00001")
    assert (s.stage, s.status, s.attempts["sim"]) == ("sim", "pending", 0)
    assert "smaller time step" in s.meta["repairs"][-1]
    assert db.reviews.find_one()["status"] == "done"
    assert reviews.take() == []


def test_retry_of_a_flagged_sample_starts_at_its_soft_failure(db):
    checks = {
        "mesh": [{"name": "symmetry", "passed": False, "hard": False}],
        "sim": [{"name": "stable", "passed": True}],
    }
    sample("s00002", stage="done", status="flagged", checks=checks, attempts={"mesh": 1})
    review(db, "s00002", "retry")
    assert reviews.take() == ["s00002"]
    assert Sample.load("s00002").stage == "mesh"


def test_accept_drop_and_skip(db):
    sample("s00003", stage="done", status="flagged")
    sample("s00004", stage="mesh", status="failed")
    sample("s00005", stage="mesh", status="failed")
    sample("s00006", stage="sim", status="running")
    review(db, "s00003", "accept")
    review(db, "s00004", "drop")
    review(db, "s00005", "retry")
    review(db, "s00006", "retry")
    assert reviews.take(skip={"s00005"}) == []
    assert Sample.load("s00003").status == "done"
    assert Sample.load("s00004").status == "failed"
    assert Sample.load("s00006").status == "running"
    assert db.reviews.find_one({"sample": "s00005"})["status"] == "new"


def test_no_atlas_no_reviews():
    assert reviews.take() == []

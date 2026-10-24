import importlib.util
from pathlib import Path

import pytest

from flowarc import mock

mongomock = pytest.importorskip("mongomock")

spec = importlib.util.spec_from_file_location(
    "demo_feed", Path(__file__).parent.parent / "scripts" / "demo_feed.py"
)
demo_feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_feed)


def test_mock_batch_tells_the_demo_story():
    b = mock.batch()
    live = [e for e in b["logs"] if e["sample"] == b["run"]["live"]]
    assert live[0]["t"] > 0  # starts during the demo
    assert any(e.get("passed") is False for e in live)  # a check fails
    assert any(e["msg"].startswith("repair:") for e in live)  # Argon repairs it
    assert live[-1]["msg"] == "advanced" and live[-1]["stage"] == "package"  # and it finishes
    assert {a["kind"] for a in b["approvals"]} == {"publish", "over_budget", "flagged"}


def test_feed_plays_into_mongo_and_waits_for_approval(monkeypatch):
    db = mongomock.MongoClient()["flowarc_demo"]
    monkeypatch.setattr(demo_feed.time, "sleep", lambda s: None)
    real_find = db.approvals.find_one

    def approve_on_poll(q):  # a viewer presses Approve while the feed waits
        db.approvals.update_one({"_id": q["_id"]}, {"$set": {"status": "approved"}})
        return real_find(q)

    monkeypatch.setattr(db.approvals, "find_one", approve_on_poll)
    uploaded = []  # mongomock has no GridFS

    def publish(db, sample, kind, name, attempt, data, ctype, src):
        assert data and ctype in ("image/jpeg", "model/gltf-binary")
        uploaded.append((sample, kind, name, attempt))

    monkeypatch.setattr(demo_feed.media, "publish", publish)
    b = mock.batch()
    demo_feed.play(db, b, speed=1000)
    live = db.samples.find_one({"_id": b["run"]["live"]})
    assert live["status"] == "done" and live["attempts"] == {"mesh": 2}
    assert db.logs.count_documents({}) == len(b["logs"]) + 1
    assert db.logs.find_one({"msg": {"$regex": "^published"}})
    assert db.baseline.count_documents({}) == len(b["baseline"])
    assert len(uploaded) == len(b["media"])
    assert (b["run"]["live"], "mesh", "mesh", 2) in uploaded

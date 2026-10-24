import importlib.util
import json
from pathlib import Path

import pytest
import trimesh
from PIL import Image

from flowarc import mock

mongomock = pytest.importorskip("mongomock")

spec = importlib.util.spec_from_file_location(
    "demo_media", Path(__file__).parent.parent / "scripts" / "demo_media.py"
)
demo_media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_media)


def _registry(tmp_path, n):
    db = mongomock.MongoClient()["flowarc"]
    files = [{"path": f"views/{v}.jpg"} for v in mock.VIEWS] + [{"path": "mesh/mesh.stl"}]
    for i in range(n):
        sid = f"s{i:05d}"
        d = tmp_path / "data" / "samples" / sid
        (d / "views").mkdir(parents=True)
        (d / "mesh").mkdir()
        for v in mock.VIEWS:
            Image.new("RGB", (600, 600), (40 * i, 90, 160)).save(d / "views" / f"{v}.jpg")
        body = trimesh.creation.icosphere(subdivisions=3)
        body.apply_scale([2, 1, 1])
        body.export(d / "mesh" / "mesh.stl")
        db.samples.insert_one(
            {
                "_id": sid,
                "status": "done" if i else "running",
                "concept": {"name": f"Real thing {i}", "bucket": mock.TAXONOMY[0], "reynolds": 1e4},
                "meta": {"files": files},
            }
        )
    db.samples.insert_one({"_id": "s99999", "concept": {}, "meta": {"files": files[:2]}})
    return db


def test_real_samples_replace_the_stand_ins(tmp_path, monkeypatch):
    db = _registry(tmp_path, 3)
    found = demo_media.candidates(db, 12)
    assert [s["_id"] for s in demo_media.candidates(db, 12, str(tmp_path / "data"))] == [
        "s00001",
        "s00002",
        "s00000",
    ]
    assert [s["_id"] for s in found] == ["s00001", "s00002", "s00000"]  # finished first, no partial

    web = tmp_path / "web"
    real = demo_media.build(found, demo_media.fetcher(str(tmp_path / "data")), web)
    live = real["samples"][0]
    assert live["slot"] == mock.LIVE and live["source"] == "s00001"
    for url in [*live["views"].values(), live["mesh"], live["broken_mesh"]]:
        assert (web / url).exists()
    whole = trimesh.load(web / live["mesh"], force="mesh").bounds
    cut = trimesh.load(web / live["broken_mesh"], force="mesh").bounds
    assert cut[1][0] < whole[1][0]  # the back is gone

    path = tmp_path / "demo_real.json"
    path.write_text(json.dumps(real))
    monkeypatch.setattr(mock, "REAL", path)
    b = mock.batch()
    s = {x["_id"]: x for x in b["samples"]}
    assert s[mock.LIVE]["concept"]["name"] == "Real thing 1"
    files = {
        (m["kind"], m["name"], m["attempt"]): m["url"]
        for m in b["media"]
        if m["sample"] == mock.LIVE
    }
    assert files[("mesh", "mesh", 1)] == live["broken_mesh"]
    assert files[("mesh", "mesh", 2)] == live["mesh"]
    assert files[("view", "side", 1)] == live["views"]["side-1"]
    assert files[("view", "side", 2)] == live["views"]["side"]
    assert any(e.get("reason") == mock.REAL_STORY["reason"] for e in b["logs"])
    other = [m for m in b["media"] if m["sample"] == "s0017" and m["kind"] == "mesh"]
    assert [m["attempt"] for m in other] == [2] and other[0]["url"] == real["samples"][1]["mesh"]

import io
import shutil
import subprocess

import pytest
import trimesh
from PIL import Image

from flowarc import config, media

mongomock = pytest.importorskip("mongomock")


def _sample(root, sid):
    d = root / "samples" / sid
    (d / "views").mkdir(parents=True)
    (d / "mesh").mkdir()
    for v in ("front", "side"):
        Image.new("RGB", (1024, 1024), "white").save(d / "views" / f"{v}.jpg")
    trimesh.creation.icosphere(subdivisions=5).export(d / "mesh" / "mesh.stl")  # 20,480 faces
    return d


def test_sync_uploads_new_files_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    db = mongomock.MongoClient()["flowarc"]
    db.samples.insert_one({"_id": "s00001", "attempts": {"mesh": 2}})
    _sample(tmp_path, "s00001")
    blobs = {}

    def publish(db, sample, kind, name, attempt, data, ctype, src):  # mongomock has no GridFS
        meta = {"sample": sample, "kind": kind, "name": name, "attempt": attempt, "src": src}
        blobs[name] = data
        db["media.files"].insert_one({"metadata": {**meta, "content_type": ctype}})

    monkeypatch.setattr(media, "publish", publish)

    assert media.sync(db) == 3
    assert media.sync(db) == 0  # unchanged files are skipped

    files = {f["metadata"]["name"]: f for f in db["media.files"].find()}
    assert files["mesh"]["metadata"]["attempt"] == 2
    assert files["front"]["metadata"]["content_type"] == "image/jpeg"
    assert Image.open(io.BytesIO(blobs["front"])).size == (media.VIEW_PX, media.VIEW_PX)


def test_mesh_glb_decimates_large_meshes(tmp_path):
    path = tmp_path / "m.stl"
    trimesh.creation.icosphere(subdivisions=6).export(path)  # 81,920 faces
    glb = trimesh.load(io.BytesIO(media.mesh_glb(path, faces=5000)), file_type="glb", force="mesh")
    assert len(glb.faces) <= 5000


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_flow_video_is_reencoded_small(tmp_path):
    src = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=30",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    data = media.video_mp4(src)
    assert data and len(data) <= media.VIDEO_MAX
    assert b"ftyp" in data[:16]

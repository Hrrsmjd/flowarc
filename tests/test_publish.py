import hashlib
from pathlib import Path
from types import SimpleNamespace

from flowarc import config, publish
from flowarc.sample import Sample


class FakeHub:
    def __init__(self):
        self.files = {}

    def create_commit(self, repo, ops, commit_message, repo_type):
        for o in ops:
            self.files[o.path_in_repo] = Path(o.path_or_fileobj).read_bytes()

    def upload_file(self, path_or_fileobj, path_in_repo, **kw):
        self.files[path_in_repo] = Path(path_or_fileobj).read_bytes()

    def get_paths_info(self, repo, paths, expand, repo_type):
        found = [self.files[p] for p in paths if p in self.files]
        return [
            SimpleNamespace(lfs=SimpleNamespace(sha256=hashlib.sha256(b).hexdigest()))
            for b in found
        ]


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "MONGODB_URI", "")
    monkeypatch.setattr(config, "HF_REPO", "me/flowarc")
    hub = FakeHub()
    monkeypatch.setattr(publish, "api", lambda: hub)
    s = Sample(id="s00001", concept={"name": "cube"})
    (s.dir / "views").mkdir(parents=True)
    (s.dir / "views" / "front.jpg").write_bytes(b"jpg")
    (s.dir / "sample.zarr" / "a").mkdir(parents=True)
    (s.dir / "sample.zarr" / "a" / "c0").write_bytes(b"chunk")
    return s, hub


def test_upload_stage_lists_links(tmp_path, monkeypatch):
    s, hub = setup(tmp_path, monkeypatch)
    assert publish.upload_stage(s, "images") == ["views/front.jpg"]
    assert hub.files["samples/s00001/views/front.jpg"] == b"jpg"
    (f,) = s.meta["files"]
    assert f["url"].endswith("me/flowarc/resolve/main/samples/s00001/views/front.jpg")
    publish.upload_stage(s, "images")
    assert len(s.meta["files"]) == 1


def test_publish_verifies_then_deletes(tmp_path, monkeypatch):
    s, _ = setup(tmp_path, monkeypatch)
    s.status = "done"
    r = publish.publish(s, delete=True)
    assert r["verified"] and r["deleted_from_rds"]
    assert not (s.dir / "sample.zarr").exists() and not (s.dir / "sample.zarr.zip").exists()


def test_publish_keeps_rds_copy_on_mismatch(tmp_path, monkeypatch):
    s, hub = setup(tmp_path, monkeypatch)
    s.status = "done"
    hub.upload_file = lambda path_or_fileobj, path_in_repo, **kw: hub.files.update(
        {path_in_repo: b"bad"}
    )
    r = publish.publish(s, delete=True)
    assert not r["verified"] and (s.dir / "sample.zarr").exists()

"""Private Hugging Face dataset for sample files (`FLOWARC_HF_REPO`, token in `HF_TOKEN`).

The dashboard reads sample state from Atlas and files from here. Small files go up after each
stage, so a running sample can be shown. The Zarr goes up only when a person publishes a
finished sample (scripts/publish.py); once its checksum on HF matches, the RDS copy can go.
"""

import hashlib
import shutil
import time
import zipfile
from pathlib import Path

from flowarc import config
from flowarc.sample import Sample

STAGE_FILES = {
    "images": ["views/*.jpg"],
    "mesh": ["mesh/mesh.stl", "mesh/renders/*.jpg"],
    "render": ["sim/video.mp4"],
}


def api():
    from huggingface_hub import HfApi

    return HfApi()


def url(sample_id: str, path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{config.HF_REPO}/resolve/main/samples/{sample_id}/{path}"
    )


def upload_stage(s: Sample, stage: str) -> list[str]:
    """Upload the files a stage made; list them in s.meta["files"] with their links."""
    if not config.HF_REPO:
        return []
    from huggingface_hub import CommitOperationAdd

    paths = sorted(p for pat in STAGE_FILES.get(stage, []) for p in s.dir.glob(pat))
    rel = [p.relative_to(s.dir).as_posix() for p in paths]
    if not rel:
        return []
    ops = [CommitOperationAdd(f"samples/{s.id}/{r}", str(p)) for r, p in zip(rel, paths)]
    api().create_commit(config.HF_REPO, ops, commit_message=f"{s.id} {stage}", repo_type="dataset")
    files = [f for f in s.meta.get("files", []) if f["path"] not in rel]
    s.meta["files"] = files + [{"path": r, "stage": stage, "url": url(s.id, r)} for r in rel]
    return rel


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def zip_zarr(z: Path) -> Path:
    """One uncompressed zip (zarr reads it with ZipStore): one HF file instead of thousands."""
    zp = z.with_name(z.name + ".zip")
    if not zp.exists():
        part = zp.with_name(zp.name + ".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as f:
            for p in sorted(z.rglob("*")):
                if p.is_file():
                    f.write(p, p.relative_to(z).as_posix())
        part.rename(zp)
    return zp


def remote_sha256(path: str) -> str | None:
    info = api().get_paths_info(config.HF_REPO, [path], expand=True, repo_type="dataset")
    return info[0].lfs.sha256 if info and info[0].lfs else None


def publish(s: Sample, delete: bool = False) -> dict:
    """Upload a finished sample's Zarr, check the checksum on HF, then delete the RDS copy if asked."""
    if not config.HF_REPO:
        raise RuntimeError("set FLOWARC_HF_REPO")
    if s.status not in ("done", "flagged"):
        raise ValueError(f"{s.id} is {s.status}, not finished")
    zp = zip_zarr(s.dir / "sample.zarr")
    digest, path = sha256(zp), f"samples/{s.id}/{zp.name}"
    if remote_sha256(path) != digest:
        api().upload_file(
            path_or_fileobj=str(zp),
            path_in_repo=path,
            repo_id=config.HF_REPO,
            repo_type="dataset",
            commit_message=f"{s.id} zarr",
        )
    ok = remote_sha256(path) == digest
    if ok and delete:
        shutil.rmtree(s.dir / "sample.zarr", ignore_errors=True)
        zp.unlink()
    s.meta["published"] = {
        "url": url(s.id, zp.name),
        "sha256": digest,
        "verified": ok,
        "deleted_from_rds": ok and delete,
        "t": time.time(),
    }
    s.log(f"zarr upload {'verified' if ok else 'checksum mismatch'}", **s.meta["published"])
    s.save()
    return s.meta["published"]

"""Put real pipeline output into the dashboard's demo: real concepts, Nano Banana views and
Hunyuan3D meshes from the registry, in place of the drawn stand-ins.

Reads finished samples from Atlas (MONGODB_URI, MONGODB_DB) and their files from the private
HF dataset (FLOWARC_HF_REPO, HF_TOKEN), or from a local FLOWARC_DATA folder with --local. Writes
web/lib/demo_real.json, the files under web/public/mock-media/real/, and a new
web/lib/mock.json. Commit those and the dashboard's mock replay and demo_feed show them.

    python scripts/demo_media.py               # up to 12 samples from Atlas + HF
    python scripts/demo_media.py --local data  # files from a local copy instead of HF

The live sample's story needs a failed first attempt, which the dataset doesn't keep: its first
side view is cropped and its first mesh has its back cut off, to match the scripted Flash
review. Everything else is the pipeline's own output.
"""

import argparse
import io
import json
import shutil
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

from flowarc import config, media, mock, store

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "public"
# Slots the demo shows first: the live sample, the two that finish during the demo, then history.
SLOTS = [mock.LIVE, "s0017", "s0018", "s0015", "s0014", "s0001", "s0002", "s0007", "s0009"]
SLOTS += [f"s{i:04d}" for i in range(1, 19) if f"s{i:04d}" not in SLOTS + ["s0013"]]
CONCEPT_KEYS = ("name", "bucket", "description", "facing", "reynolds", "yaw_deg", "ground")


NEEDED = ["mesh/mesh.stl"] + [f"views/{v}.jpg" for v in mock.VIEWS]


def candidates(db, n: int, local: str | None = None) -> list[dict]:
    """Samples with all their views and a mesh (on HF, or in the local folder), finished first."""
    out, seen = [], {"samples": 0, "with views": 0, "with views and mesh": 0}
    for s in db.samples.find({"concept.name": {"$exists": True}}, {"embedding": 0}).sort("_id", 1):
        if local:
            d = Path(local) / "samples" / s["_id"]
            paths = {p for p in NEEDED if (d / p).exists()}
        else:
            paths = {f["path"] for f in (s.get("meta") or {}).get("files", [])}
        seen["samples"] += 1
        seen["with views"] += all(p in paths for p in NEEDED[1:])
        if all(p in paths for p in NEEDED):
            seen["with views and mesh"] += 1
            out.append(s)
    where = f"under {local}" if local else "on the HF dataset (meta.files)"
    print(f"Atlas {db.name}: " + ", ".join(f"{v} {k}" for k, v in seen.items()) + f" {where}")
    out.sort(key=lambda s: s.get("status") != "done")
    return out[:n]


def fetcher(local: str | None):
    if local:
        root = Path(local) / "samples"
        return lambda sid, path: (root / sid / path).read_bytes()
    if not config.HF_REPO:
        raise SystemExit("set FLOWARC_HF_REPO and HF_TOKEN, or pass --local")
    from huggingface_hub import hf_hub_download

    def fetch(sid: str, path: str) -> bytes:
        f = hf_hub_download(config.HF_REPO, f"samples/{sid}/{path}", repo_type="dataset")
        return Path(f).read_bytes()

    return fetch


def cropped(jpeg: bytes, keep: float = 0.72) -> bytes:
    """The view with its right side blanked: the 'bad' first view of the live sample."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    w, h = img.size
    img.paste((255, 255, 255), (int(w * keep), 0, w, h))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def broken(stl: bytes, keep: float = 0.8) -> bytes:
    """The mesh without its back (the far end along x, the flow direction)."""
    import trimesh

    m = trimesh.load(io.BytesIO(stl), file_type="stl", force="mesh")
    x = m.triangles_center[:, 0]
    lo, hi = x.min(), x.max()
    m.update_faces(x <= lo + keep * (hi - lo))
    m.remove_unreferenced_vertices()
    return _glb(m)


def _glb(m) -> bytes:
    if len(m.faces) > media.MESH_FACES:
        m = m.simplify_quadric_decimation(face_count=media.MESH_FACES)
    return m.export(file_type="glb")


def build(
    samples: list[dict], fetch, web: Path = WEB, n: int = 12, max_mb: float = 60, save=None
) -> dict:
    """Save up to n samples' views and meshes under web/mock-media/real/<id>/.

    Returns demo_real.json, and passes it to `save` after every sample, so a run that stops
    part way still leaves a working demo. A sample that fails, or whose mesh is over max_mb
    (decimating it can run a small machine out of memory), is skipped for the next one.
    """
    out = web / "mock-media" / "real"
    shutil.rmtree(out, ignore_errors=True)
    rows = []
    for s in samples:
        if len(rows) == n:
            break
        slot, sid = SLOTS[len(rows)], s["_id"]
        try:
            row = _sample(slot, s, fetch, web, out / sid, max_mb)
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(out / sid, ignore_errors=True)
            print(f"skipped {sid}: {e}")
            continue
        rows.append(row)
        print(f"{slot} <- {sid} {s['concept'].get('name', '')}")
        if save:
            save({"samples": rows})
    return {"samples": rows}


def _sample(slot: str, s: dict, fetch, web: Path, d: Path, max_mb: float) -> dict:
    sid = s["_id"]
    d.mkdir(parents=True)

    def rel(name: str) -> str:
        return (d / name).relative_to(web).as_posix()

    views = {}
    for v in mock.VIEWS:
        (d / f"{v}.jpg").write_bytes(media.view_jpeg(fetch(sid, f"views/{v}.jpg")))
        views[v] = rel(f"{v}.jpg")
    stl = fetch(sid, "mesh/mesh.stl")
    if len(stl) > max_mb * 1e6:
        raise ValueError(f"mesh is {len(stl) / 1e6:.0f} MB (over --max-mb {max_mb:g})")
    (d / "mesh.stl").write_bytes(stl)
    (d / "mesh.glb").write_bytes(media.mesh_glb(d / "mesh.stl"))
    (d / "mesh.stl").unlink()
    row = {
        "slot": slot,
        "source": sid,
        "concept": {k: s["concept"][k] for k in CONCEPT_KEYS if s["concept"].get(k) is not None},
        "views": views,
        "mesh": rel("mesh.glb"),
    }
    if slot == mock.LIVE:  # the failed first attempt the story needs
        side = mock.REAL_STORY["view"]
        (d / f"{side}-1.jpg").write_bytes(cropped((d / f"{side}.jpg").read_bytes()))
        (d / "mesh-broken.glb").write_bytes(broken(stl))
        row["views"][f"{side}-1"] = rel(f"{side}-1.jpg")
        row["broken_mesh"] = rel("mesh-broken.glb")
    return row


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--max", type=int, default=12, help="how many real samples to use")
    p.add_argument("--local", help="FLOWARC_DATA folder to read files from instead of HF")
    p.add_argument("--max-mb", type=float, default=60, help="skip meshes bigger than this")
    args = p.parse_args()
    db = store.db()
    if db is None:
        raise SystemExit("set MONGODB_URI (see .env.example)")
    found = candidates(db, 10_000, args.local)
    if not found:
        raise SystemExit(
            "no sample has all 4 views and a mesh there yet. Run it where the pipeline's data "
            "is, with --local <FLOWARC_DATA folder>, or wait for the runner to upload to HF."
        )

    def save(real: dict) -> None:
        mock.REAL.write_text(json.dumps(real, indent=1))
        mock.write(str(ROOT / "web" / "lib" / "mock.json"), str(WEB))

    n = min(args.max, len(SLOTS))
    real = build(found, fetcher(args.local), n=n, max_mb=args.max_mb, save=save)
    if not real["samples"]:
        raise SystemExit("every sample failed; see the messages above")
    print(
        "now: git add web/lib/demo_real.json web/lib/mock.json web/public/mock-media && git commit"
    )


if __name__ == "__main__":
    main()

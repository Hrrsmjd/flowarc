"""Copies each sample's reference views and mesh to Atlas (GridFS) so the dashboard can show them.

The images and meshes live on the GPU box; the dashboard on Vercel can't read that disk. This
uploads a 512 px JPEG of each view and a decimated GLB of each mesh attempt to the GridFS bucket
`media`, tagged with the sample, the attempt and the view name. Unchanged files are skipped.

Run it next to the runner on the GPU box.

    python -m flowarc.media              # upload anything new once
    python -m flowarc.media --watch 15   # keep uploading every 15 s while the runner works
"""

import argparse
import hashlib
import io
import time

from PIL import Image

from flowarc import config, store

BUCKET = "media"
VIEW_PX = 512
MESH_FACES = 20_000  # ~350 KB GLB; Vercel functions return at most 4.5 MB


def view_jpeg(raw: bytes, px: int = VIEW_PX) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((px, px))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def mesh_glb(path, faces: int = MESH_FACES) -> bytes:
    import trimesh

    m = trimesh.load(path, force="mesh")
    if len(m.faces) > faces:
        m = m.simplify_quadric_decimation(face_count=faces)
    return m.export(file_type="glb")


def _bucket(db):
    from gridfs import GridFSBucket

    return GridFSBucket(db, bucket_name=BUCKET)


def publish(
    db, sample: str, kind: str, name: str, attempt: int, data: bytes, ctype: str, src: str
) -> None:
    meta = {
        "sample": sample,
        "kind": kind,
        "name": name,
        "attempt": attempt,
        "src": src,
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": ctype,
        "t": time.time(),
    }
    _bucket(db).upload_from_stream(f"{sample}/{kind}/{attempt}/{name}", data, metadata=meta)


def sync(db) -> int:
    """Upload new or changed views and meshes for every sample folder under FLOWARC_DATA.

    A file is identified by its path, size and modification time, so unchanged files are not
    re-read (meshes take a second or more to decimate).
    """
    root = config.DATA / "samples"
    if not root.exists():
        return 0
    files = db[f"{BUCKET}.files"]
    n = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        tries = (db.samples.find_one({"_id": d.name}, {"attempts": 1}) or {}).get("attempts", {})
        todo = [(f, "view", f.stem) for f in sorted((d / "views").glob("*.jpg"))]
        todo += [(f, "mesh", "mesh") for f in [d / "mesh" / "mesh.stl"] if f.exists()]
        for path, kind, name in todo:
            st = path.stat()
            src = f"{path.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}"
            if files.find_one({"metadata.src": src}, {"_id": 1}):
                continue
            if kind == "view":
                data, ctype, attempt = (
                    view_jpeg(path.read_bytes()),
                    "image/jpeg",
                    tries.get("images", 1),
                )
            else:
                data, ctype, attempt = mesh_glb(path), "model/gltf-binary", tries.get("mesh", 1)
            publish(db, d.name, kind, name, attempt, data, ctype, src)
            n += 1
    return n


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--watch", type=float, default=0, help="repeat every N seconds")
    args = p.parse_args()
    db = store.db()
    if db is None:
        raise SystemExit("set MONGODB_URI (see .env.example)")
    while True:
        n = sync(db)
        if n:
            print(f"uploaded {n} files")
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()

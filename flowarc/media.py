"""Copies each sample's reference views and mesh to Atlas (GridFS) so the dashboard can show them.

The images and meshes live on the GPU box; the dashboard on Vercel can't read that disk. This
uploads a 512 px JPEG of each view, a decimated GLB of each mesh attempt and a small re-encode
of the flow video to the GridFS bucket `media`, tagged with the sample, the attempt and the view
name. Unchanged files are skipped.

Run it next to the runner on the GPU box.

    python -m flowarc.media              # upload anything new once
    python -m flowarc.media --watch 15   # keep uploading every 15 s while the runner works
"""

import argparse
import hashlib
import io
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from flowarc import config, store

BUCKET = "media"
VIEW_PX = 512
MESH_FACES = 20_000  # ~350 KB GLB; Vercel functions return at most 4.5 MB
VIDEO_MAX = 4_000_000  # bytes, under that same limit
_too_big: set[str] = set()  # videos that wouldn't shrink enough, so --watch doesn't retry them
VIDEO_VERSION = 2  # bump to re-encode every flow video already in GridFS


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


def video_mp4(path, width: int = 1280) -> bytes | None:
    """The flow video re-encoded to serve (H.264, no audio, faststart), or None if it won't fit.

    Two passes at the bitrate that fills VIDEO_MAX for the clip's length, so the picture is as
    sharp as the size limit allows (a fixed CRF made long clips blocky and short ones tiny).
    """
    probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    secs = float(
        subprocess.run([*probe, str(path)], check=True, capture_output=True, text=True).stdout
    )
    for share in (0.92, 0.8, 0.65):
        kbps = int(VIDEO_MAX * 8 * share / secs / 1000)
        with tempfile.TemporaryDirectory() as tmp:
            out, log = Path(tmp) / "out.mp4", Path(tmp) / "pass"
            base = ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-an", "-c:v", "libx264"]
            base += ["-vf", f"scale='min({width},iw)':-2", "-b:v", f"{kbps}k", "-preset", "slow"]
            base += ["-pix_fmt", "yuv420p", "-passlogfile", str(log)]
            subprocess.run([*base, "-pass", "1", "-f", "mp4", "/dev/null"], check=True)
            subprocess.run([*base, "-pass", "2", "-movflags", "+faststart", str(out)], check=True)
            data = out.read_bytes()
        if len(data) <= VIDEO_MAX:
            return data
    return None


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


def mesh_files(d: Path) -> list[Path]:
    """mesh_N.stl per try (the runner keeps one each), else mesh.stl from older runs."""
    tries = sorted((d / "mesh").glob("mesh_[0-9]*.stl"), key=lambda p: int(p.stem[5:]))
    return tries or [f for f in [d / "mesh" / "mesh.stl"] if f.exists()]


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
        todo += [(f, "mesh", "mesh") for f in mesh_files(d)]
        todo += [(f, "video", "flow") for f in [d / "sim" / "video.mp4"] if f.exists()]
        for path, kind, name in todo:
            st = path.stat()
            src = f"{path.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}"
            if kind == "video":
                src += f":v{VIDEO_VERSION}"
            if src in _too_big or files.find_one({"metadata.src": src}, {"_id": 1}):
                continue
            if kind == "view":
                data, ctype, attempt = (
                    view_jpeg(path.read_bytes()),
                    "image/jpeg",
                    tries.get("images", 1),
                )
            elif kind == "mesh":
                k = path.stem.removeprefix("mesh_")
                attempt = int(k) if k.isdigit() else tries.get("mesh", 1)
                data, ctype = mesh_glb(path), "model/gltf-binary"
            else:
                data, ctype, attempt = video_mp4(path), "video/mp4", tries.get("sim", 1)
                if data is None:
                    _too_big.add(src)
                    print(f"{d.name}: flow video too big to serve even re-encoded; skipped")
                    continue
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

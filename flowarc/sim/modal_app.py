"""FluidX3D on Modal H100s. Same solver and build as w7830; only the GPU is elsewhere.

Deploy: modal deploy flowarc/sim/modal_app.py   (needs MODAL_TOKEN_ID / MODAL_TOKEN_SECRET)
The client side is flowarc/sim/modal_solver.py.
"""

import io
import queue
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
FX3D_COMMIT = "dbf0bb5b19233668672f73a0865a41424651a09c"
APP = "flowarc-sim"
VOLUME = "flowarc-sim"
GPU = "H100"
MAX_GPUS = 10

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-base-ubuntu22.04", add_python="3.12")
    .apt_install("git", "make", "g++", "ffmpeg", "ocl-icd-libopencl1", "clinfo")
    .run_commands(
        "mkdir -p /etc/OpenCL/vendors && echo libnvidia-opencl.so.1 > /etc/OpenCL/vendors/nvidia.icd",
        f"git clone https://github.com/ProjectPhysX/FluidX3D /FluidX3D && cd /FluidX3D && git checkout {FX3D_COMMIT}",
    )
    .pip_install("numpy", "scipy", "trimesh", "rtree", "manifold3d", "pillow")
    .add_local_file(HERE / "fluidx3d/build.sh", "/build/build.sh", copy=True)
    .add_local_file(HERE / "fluidx3d/setup.cpp", "/build/setup.cpp", copy=True)
    .run_commands("bash /build/build.sh /FluidX3D /fx3d-bin")
    .env({"FLOWARC_FLUIDX3D_BIN": "/fx3d-bin", "NVIDIA_DRIVER_CAPABILITIES": "compute,utility"})
    .add_local_python_source("flowarc")
)

app = modal.App(APP, image=image)
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)


@app.function(gpu=GPU, timeout=60)
def clinfo() -> str:
    """Check that the NVIDIA OpenCL driver is visible in the container."""
    r = subprocess.run(["clinfo", "-l"], check=False, capture_output=True, text=True)
    return r.stdout + r.stderr


@app.function(gpu=GPU, volumes={"/vol": vol}, timeout=6 * 3600, max_containers=MAX_GPUS)
def simulate(run_id: str, mesh: bytes, cfg: dict):
    """Runs FluidX3D().run on one H100. Yields progress dicts, then {"result": ..., "tar": path}.
    The output folder is tarred into the volume for the client to download."""
    from PIL import Image

    from flowarc.sim.fluidx3d import FluidX3D
    from flowarc.sim.solver import SimConfig

    cfg["domain"] = tuple(cfg["domain"])
    work = Path("/tmp") / run_id
    shutil.rmtree(work, ignore_errors=True)
    (work / "sim").mkdir(parents=True)
    (work / "body_in.stl").write_bytes(mesh)
    events: queue.Queue = queue.Queue()

    def progress(p):
        jpg = None
        if p["latest"]:
            buf = io.BytesIO()
            Image.open(p["latest"]).convert("RGB").save(buf, "JPEG", quality=80)
            jpg = buf.getvalue()
        events.put({"frames": p["frames"], "of": p["of"], "jpg": jpg})

    def go():
        try:
            r = FluidX3D().run(work / "body_in.stl", SimConfig(**cfg), work / "sim", 0, progress)
            events.put({"done": r})
        except BaseException as e:  # noqa: BLE001
            events.put({"error": repr(e)})

    threading.Thread(target=go, daemon=True).start()
    while True:
        ev = events.get()
        if "error" in ev:
            log = work / "sim" / "fluidx3d.log"
            tail = log.read_text(errors="replace")[-3000:] if log.exists() else ""
            raise RuntimeError(ev["error"] + "\n" + tail)
        if "done" in ev:
            break
        yield ev
    r = ev["done"]
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tar = Path("/vol") / f"{run_id}.tar"
    with tarfile.open(tar, "w") as t:
        t.add(work / "sim", arcname="sim")
    vol.commit()
    shutil.rmtree(work, ignore_errors=True)
    yield {
        "result": {
            "ok": r.ok,
            "stats": r.stats,
            "cost": r.cost | {"gpu": f"modal {gpu}"},
            "has_frames": r.frames is not None,
        },
        "tar": tar.name,
    }


@app.local_entrypoint()
def check():
    print(clinfo.remote())

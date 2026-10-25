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
import time
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

HUNYUAN_COMMIT = "82920d6"
hunyuan_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.10")
    .apt_install("git", "libgl1", "libglib2.0-0", "wget")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        index_url="https://download.pytorch.org/whl/cu124",
    )
    .pip_install(
        "accelerate==1.1.1",
        "diffusers==0.30.0",
        "einops==0.8.0",
        "huggingface-hub==0.30.2",
        "numpy==1.24.4",
        "omegaconf==2.3.0",
        "onnxruntime==1.23.2",
        "opencv-python-headless==4.11.0.86",
        "pymeshlab==2025.7.post1",
        "pytorch-lightning==1.9.5",
        "rembg==2.0.65",
        "safetensors==0.4.4",
        "transformers==4.46.0",
        "trimesh==4.4.7",
        "tqdm==4.66.5",
        "pydantic==2.10.6",
        "timm",
        "scikit-image",
        "pyyaml",
        "hf_transfer",
    )
    .run_commands(
        "git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 /hy && cd /hy && "
        f"git checkout {HUNYUAN_COMMIT}",
        "mkdir -p /u2net && wget -q -O /u2net/u2net.onnx "
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    )
    .env(
        {
            "HY3DGEN_MODELS": "/models",
            "U2NET_HOME": "/u2net",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
        }
    )
    .run_commands(
        'python -c "from huggingface_hub import snapshot_download; snapshot_download('
        "'tencent/Hunyuan3D-2.1', allow_patterns=['hunyuan3d-dit-v2-1/*', 'hunyuan3d-vae-v2-1/*'], "
        "local_dir='/models/tencent/Hunyuan3D-2.1')\""
    )
    .add_local_file(HERE.parent / "mesh/hunyuan_run.py", "/hy/hunyuan_run.py")
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


@app.function(image=hunyuan_image, gpu="L40S", timeout=1800, max_containers=MAX_GPUS)
def hunyuan(image: bytes, seed: int = 0) -> bytes:
    """Hunyuan3D-2.1 shape only: one view image -> raw.glb bytes (same script as on w7830)."""
    work = Path("/tmp") / f"hy-{seed}-{time.time_ns()}"
    work.mkdir(parents=True)
    (work / "view.jpg").write_bytes(image)
    r = subprocess.run(
        ["python", "/hy/hunyuan_run.py", "/hy", work / "view.jpg", work / "raw.glb", str(seed)],
        check=False,
        capture_output=True,
        text=True,
    )
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr)[-3000:])
    return (work / "raw.glb").read_bytes()


@app.local_entrypoint()
def check():
    print(clinfo.remote())

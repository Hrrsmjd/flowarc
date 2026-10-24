"""Pluggable image-to-3D generators. Shape only, no textures."""

import os
import subprocess
from pathlib import Path
from typing import Protocol


class MeshGenerator(Protocol):
    name: str

    def generate(self, views: dict[str, Path], out: Path, gpu: int, seed: int = 0) -> Path:
        """Write a mesh file to `out` from reference views and return its path."""
        ...


class Hunyuan21:
    """Hunyuan3D-2.1 shape model, single image. Runs in its own venv (FLOWARC_HUNYUAN = repo path)."""

    name = "hunyuan3d-2.1"

    def __init__(self, repo: str | None = None, view: str = "three-quarter"):
        self.repo = Path(repo or os.environ["FLOWARC_HUNYUAN"])
        self.view = view

    def generate(self, views: dict[str, Path], out: Path, gpu: int, seed: int = 0) -> Path:
        out.mkdir(parents=True, exist_ok=True)
        mesh = out / "raw.glb"
        script = Path(__file__).with_name("hunyuan_run.py")
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu)}
        with open(out / "hunyuan.log", "w") as log:
            subprocess.run(
                [
                    self.repo / ".venv/bin/python",
                    script,
                    self.repo,
                    views[self.view],
                    mesh,
                    str(seed),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=1800,
            )
        return mesh


class Hunyuan21Modal(Hunyuan21):
    """Same model and script on a Modal GPU (flowarc/sim/modal_app.py), for when local GPUs are full."""

    def __init__(self, view: str = "three-quarter"):
        self.view = view

    def generate(self, views: dict[str, Path], out: Path, gpu: int, seed: int = 0) -> Path:
        import modal

        from flowarc.sim import modal_app

        out.mkdir(parents=True, exist_ok=True)
        fn = modal.Function.from_name(modal_app.APP, "hunyuan")
        mesh = out / "raw.glb"
        mesh.write_bytes(fn.remote(views[self.view].read_bytes(), seed))
        return mesh


GENERATORS: dict[str, type] = {Hunyuan21.name: Hunyuan21}

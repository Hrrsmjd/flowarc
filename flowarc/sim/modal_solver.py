"""Client for the Modal FluidX3D runner (modal_app.py). Same interface as FluidX3D.run, so the
pipeline only swaps the solver (FLOWARC_SOLVER=modal). Outputs land in `out` as if run locally."""

import shutil
import tarfile
import time
from dataclasses import asdict
from pathlib import Path

from flowarc.sim.solver import SimConfig, SimResult


class ModalFluidX3D:
    def run(self, mesh: Path, cfg: SimConfig, out: Path, gpu: int, progress=None) -> SimResult:
        import modal

        from flowarc.sim import modal_app

        out = Path(out)
        simulate = modal.Function.from_name(modal_app.APP, "simulate")
        vol = modal.Volume.from_name(modal_app.VOLUME)
        run_id = f"{out.parent.name}-{int(time.time())}"
        final = None
        for ev in simulate.remote_gen(run_id, Path(mesh).read_bytes(), asdict(cfg)):
            if "result" in ev:
                final = ev
            elif progress:
                latest = None
                if ev.get("jpg"):
                    latest = out / "live_src.jpg"
                    out.mkdir(parents=True, exist_ok=True)
                    latest.write_bytes(ev["jpg"])
                progress({"frames": ev["frames"], "of": ev["of"], "latest": latest})
        if final is None:
            raise RuntimeError("Modal sim ended without a result")
        tar = out.parent / f"{run_id}.tar"
        with open(tar, "wb") as f:
            vol.read_file_into_fileobj(final["tar"], f)
        for d in ("probes", "render"):  # a retry must not mix in the last run's frames
            shutil.rmtree(out / d, ignore_errors=True)
        with tarfile.open(tar) as t:
            t.extractall(out.parent, filter="data")
        tar.unlink()
        vol.remove_file(final["tar"])
        r = final["result"]
        video = out / "video.mp4"
        return SimResult(
            ok=r["ok"],
            forces=out / "forces.csv",
            frames=out / "probes" if r["has_frames"] else None,
            stats=r["stats"],
            cost=r["cost"] | {"video": str(video) if video.exists() else None},
        )

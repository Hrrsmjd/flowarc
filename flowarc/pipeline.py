"""Runs samples through the stages. Each stage checks its output and says whether it passed.

State is saved after every stage, so a crashed run picks up from the last finished stage.
When a stage fails, Argon picks the fix (triage.py).
"""

import json
import math
import shutil
import time
import traceback
from dataclasses import asdict
from pathlib import Path

import trimesh

from flowarc import concepts, config, gemini, images, triage
from flowarc.sample import STAGES, Sample, all_samples
from flowarc.sim.solver import SimConfig, SimResult


class BudgetExceeded(RuntimeError):
    pass


def advance(sample: Sample) -> None:
    """Move the sample to the next stage after its current one passes."""
    sample.log("advanced")
    i = STAGES.index(sample.stage)
    sample.stage = STAGES[i + 1] if i + 1 < len(STAGES) else "done"
    sample.save()


def new_samples(n: int, seed: int | None = None) -> list[Sample]:
    """Stage 1: Argon proposes, the most novel n are kept."""
    existing = all_samples()
    start = 1 + max((int(s.id[1:]) for s in existing), default=0)
    out = []
    token = gemini.CALLS.set([])
    try:
        picked = concepts.select(n, seed)
        calls = gemini.CALLS.get()
    finally:
        gemini.CALLS.reset(token)
    for i, c in enumerate(picked):
        s = Sample(id=f"s{start + i:05d}", embedding=c.pop("embedding"), concept=c)
        s.meta["phase"] = config.PHASE.name  # the dashboard counts this run's samples by it
        # Argon proposes the whole batch in one call: every sample shows it under Prompts,
        # and only the first counts it towards the run's totals.
        for call in calls:
            s.log(f"gemini {call['model']}", actor="gemini", **call, shared=len(picked), copy=i > 0)
        s.record_check("novel", True)
        advance(s)
        out.append(s)
    return out


def views_of(s: Sample) -> dict[str, Path]:
    return {v: s.dir / "views" / f"{v}.jpg" for v in images.VIEWS}


def run_images(s: Sample, gpu: int) -> bool:
    views, review = images.make_views(s.concept)
    for v, img in views.items():
        views_of(s)[v].parent.mkdir(parents=True, exist_ok=True)
        views_of(s)[v].write_bytes(img)
    s.record_check(
        "views_consistent",
        review["consistent"],
        bad=review["bad_views"],
        reason=review.get("reason"),
        hard=False,
        actor="argon",
    )
    return True  # views are only a reference for the mesh review


def run_mesh(s: Sample, gpu: int) -> bool:
    from flowarc.mesh.stage import make_mesh

    tries = s.attempts["mesh"]
    cells = cells_per_length(s)
    raw = s.dir / "mesh" / "raw.glb"
    remesh = s.meta.pop("remesh", False) and raw.exists()  # Argon chose repair_mesh
    rep = make_mesh(
        views_of(s),
        s.dir / "mesh",
        gpu,
        s.concept,
        raw=raw if remesh else None,
        seed=tries,
        min_thickness=2 / cells,
        remesh=remesh,
    )
    if not rep["passed"] and rep["base_ok"]:
        argon_mesh_call(s, rep, cells)
    (s.dir / "mesh" / f"report_{tries}.json").write_text(json.dumps(rep, indent=1, default=float))
    if (s.dir / "mesh" / "mesh.stl").exists():  # each try's mesh, for the dashboard (flowarc.media)
        shutil.copyfile(s.dir / "mesh" / "mesh.stl", s.dir / "mesh" / f"mesh_{tries}.stl")
    rev = rep.get("review", {})
    s.record_check(
        "mesh",
        rep["passed"],
        geometry=rep["geometry"]["passed"],
        silhouette=rep["silhouette"]["min_iou"],
        holes=rev.get("holes"),
        flash_failed=rev.get("flash", {}).get("failed"),
        summary=rev.get("flash", {}).get("summary"),
        flash=rev.get("flash", {}).get("checks"),
        turns=rev.get("turns"),
        argon=rep.get("argon"),
        actor="argon",
    )
    return rep["passed"]


def argon_mesh_call(s: Sample, rep: dict, cells: int) -> None:
    """Argon judges the symmetry and thin-parts failures of an otherwise good mesh (triage.judge_mesh)."""
    from flowarc.mesh.stage import thicken

    d = triage.judge_mesh(s, rep, s.dir / "mesh" / "renders", 2)
    if not d:
        return
    rep["argon"] = d
    if not d["symmetric"]:
        s.concept["symmetric"] = False
    left = {"symmetry"} - (
        {"symmetry"} if d["decision"] == "accept" or not d["symmetric"] else set()
    )
    left &= set(rep["judgement"])
    if "thin" in rep["judgement"]:
        if d["decision"] == "thicken":
            rep["geometry"] = geo = thicken(
                s.dir / "mesh", 2 / cells, s.concept.get("ground", False)
            )
            rep["thickened"] = True
            if not (geo["thin_ok"] and geo["watertight"] and geo["bodies"] == 1):
                left.add("thin")
        elif d["decision"] != "accept":
            left.add("thin")
    if d["decision"] == "new_mesh":
        left.add("argon")
    rep["passed"] = not left


DNS_MAX_RE = 1e3  # resolved at 64 cells/L without a subgrid model
SMALL_BOX_RE = 1e4  # drag within ~1% of the 8x4x4 box on the manta; walls matter more at low Re


def failed_runs(s: Sample) -> list[dict]:
    return [c for c in s.checks.get("sim", []) if c["name"] == "stable" and not c["passed"]]


def lattice_velocity(s: Sample) -> float:
    """After an LES run that went too fast (Mach >= 0.5), slow the inflow so its peak lands near
    0.4. Without this a retry reruns the same sim and fails the same way. Costs more steps.
    A failed DNS run is retried with LES instead (see sim_config): slowing DNS also lowers its
    viscosity, which makes it less stable."""
    u = SimConfig.lattice_velocity
    for c in failed_runs(s):
        if c.get("mach_max") and c.get("les", True):
            u = c.get("u", u) * min(1.0, 0.4 / c["mach_max"])
    return u


LAMINAR_MAX_CELLS = 128  # the 8x4x4 box at 256 cells/L needs ~120 GB, more than one A100


def cells_per_length(s: Sample) -> int:
    """The phase's finest grid; laminar samples (big box) stop at LAMINAR_MAX_CELLS."""
    cells = config.PHASE.cells_per_length[-1]
    return cells if s.concept["reynolds"] >= SMALL_BOX_RE else min(cells, LAMINAR_MAX_CELLS)


def sim_config(s: Sample) -> SimConfig:
    return SimConfig(
        reynolds=s.concept["reynolds"],
        lattice_velocity=lattice_velocity(s),
        cells_per_length=cells_per_length(s),
        **(
            {"domain": (5.0, 2.5, 2.5), "body_offset": 1.25}
            if s.concept["reynolds"] >= SMALL_BOX_RE
            else {}
        ),
        ground=s.concept.get("ground", False),
        les=s.concept["reynolds"] > DNS_MAX_RE or bool(failed_runs(s)),
        justification=f"DNS up to Re {DNS_MAX_RE:g}, LES (Smagorinsky) above; Re above 1e5 nominal",
    )


LIVE_EVERY = 600  # seconds between live-frame uploads per sim (HF limits commits)


def sim_progress(s: Sample, p: dict) -> None:
    """Frames done so far in Atlas; the newest frame on HF every LIVE_EVERY s."""
    from PIL import Image

    from flowarc import publish

    last = s.meta.get("sim_progress", {}).get("live_t", 0)
    s.meta["sim_progress"] = {
        "frames": p["frames"],
        "of": p["of"],
        "t": time.time(),
        "live_t": last,
    }
    if p["latest"] and config.HF_REPO and time.time() - last >= LIVE_EVERY:
        try:
            jpg = s.dir / "sim" / "live.jpg"
            Image.open(p["latest"]).convert("RGB").save(jpg, quality=80)
            publish.upload_live(s, jpg)
            s.meta["sim_progress"]["live_t"] = time.time()
        except Exception as e:  # noqa: BLE001
            s.log(f"live frame upload error: {e!r}")
    s.save()


def solver():
    if config.SOLVER == "modal":
        from flowarc.sim.modal_solver import ModalFluidX3D

        return ModalFluidX3D()
    from flowarc.sim.fluidx3d import FluidX3D

    return FluidX3D()


def run_sim(s: Sample, gpu: int) -> bool:
    m = trimesh.load(s.dir / "mesh" / "mesh.stl")
    m.apply_transform(
        trimesh.transformations.rotation_matrix(
            math.radians(s.concept.get("yaw_deg", 0)), [0, 0, 1]
        )
    )
    m.export(s.dir / "mesh" / "sim_body.stl")
    cfg = sim_config(s)
    s.meta.pop("sim_progress", None)  # from an earlier try
    r = solver().run(
        s.dir / "mesh" / "sim_body.stl", cfg, s.dir / "sim", gpu, lambda p: sim_progress(s, p)
    )
    st = r.stats
    s.meta["sim"] = {
        **asdict(r),
        "forces": str(r.forces),
        "frames": str(r.frames) if r.frames else None,
        "cells_thinnest": float(cfg.cells_per_length * m.extents.min()),
    }
    s.meta.setdefault("gpu_seconds", 0)
    s.meta["gpu_seconds"] += r.cost.get("seconds", 0) or 0
    stable = r.ok and math.isfinite(st.get("cd_mean", math.nan)) and st.get("mach_max", 0) < 0.5
    s.record_check(
        "stable",
        stable,
        mach_max=st.get("mach_max"),
        max_u_wall=st.get("max_u_wall"),
        cd=st.get("cd_mean"),
        u=cfg.lattice_velocity,
        les=cfg.les,
    )
    s.record_check("mass", st.get("mass_drift", 1) < 1e-2, drift=st.get("mass_drift"), hard=False)
    s.record_check(
        "converged", st.get("cd_half_change", 1) < 0.05, change=st.get("cd_half_change"), hard=False
    )
    return stable


def run_render(s: Sample, gpu: int) -> bool:
    from flowarc import render

    video = s.dir / "sim" / "video.mp4"
    if not s.record_check("video", video.exists() and video.stat().st_size > 0):
        return False
    rev = render.review(video, s.concept, save_to=s.dir / "sim" / "frames")
    s.meta["video_review"] = rev
    s.record_check(
        "video_review",
        rev["passed"],
        failed=rev["failed"],
        summary=rev["summary"],
        hard=False,
        actor="argon",
    )
    return True


def run_package(s: Sample, gpu: int) -> bool:
    from flowarc.package import pack, size_bytes

    d = s.meta["sim"]
    r = SimResult(
        ok=d["ok"],
        forces=Path(d["forces"]),
        frames=d["frames"] and Path(d["frames"]),
        stats=d["stats"],
        cost=d["cost"],
    )
    meta = {"concept": s.concept, "checks": s.checks, "mesh": "mesh/mesh.stl"}
    z = pack(r, sim_config(s), s.dir / "sample.zarr", json.loads(json.dumps(meta, default=str)))
    s.meta["zarr_gb"] = size_bytes(z) / 1e9
    for scratch in ("probes", "render"):  # ~1.8 GB per sample, now in the Zarr and the video
        shutil.rmtree(s.dir / "sim" / scratch, ignore_errors=True)
    return s.record_check("packed", True, gb=s.meta["zarr_gb"])


STAGE_FNS = {
    "images": run_images,
    "mesh": run_mesh,
    "sim": run_sim,
    "render": run_render,
    "package": run_package,
}


def gpu_hours() -> float:
    return sum(s.meta.get("gpu_seconds", 0) for s in all_samples()) / 3600


def upload(s: Sample, stage: str, attempt: int | None = None) -> None:
    """Stage files to the private HF dataset for the dashboard. A failed upload doesn't fail the sample.
    `attempt` marks a failed try, kept under its own folder."""
    from flowarc import publish

    try:
        publish.upload_stage(s, stage, attempt)
    except Exception as e:  # noqa: BLE001
        s.log(f"{stage} upload error: {e!r}")
    s.save()


def run_sample(s: Sample, gpu: int, budget_hours: float = math.inf) -> Sample:
    """Run the remaining stages. Ends done, flagged (a soft check failed) or failed."""
    s.meta.setdefault("phase", config.PHASE.name)
    if s.meta.pop("in_try", None) == s.stage:  # a restart cut the last try short; don't count it
        s.attempts[s.stage] -= 1
    while s.stage != "done":
        if s.stage == "sim" and gpu_hours() >= budget_hours:
            s.status = "pending"
            s.save()
            raise BudgetExceeded(f"{gpu_hours():.1f} GPU h used; approve more with --budget")
        stage = s.stage
        s.attempts[stage] = s.attempts.get(stage, 0) + 1
        if s.attempts[stage] > config.MAX_ATTEMPTS.get(stage, 1):
            s.status = "failed"
            s.log(f"{stage}: out of attempts")
            s.save()
            return s
        s.status = "running"
        s.meta["gpu"] = gpu
        s.meta["in_try"] = stage
        s.save()
        n_checks, error = len(s.checks.get(stage, [])), None
        token = gemini.CALLS.set([])
        try:
            passed = STAGE_FNS[stage](s, gpu)
        except Exception as e:  # noqa: BLE001 - any stage crash counts as a failed try
            s.log(f"{stage} error: {e!r}", trace=traceback.format_exc())
            passed, error = False, repr(e)
        finally:
            for c in gemini.CALLS.get():
                s.log(f"gemini {c['model']}", actor="gemini", **c)
            gemini.CALLS.reset(token)
        s.meta.pop("in_try", None)
        triage.close_repair(s, stage, passed)
        if passed:
            advance(s)
            upload(s, stage)
            continue
        upload(s, stage, s.attempts[stage])
        token = gemini.CALLS.set([])
        try:
            go_on = triage.handle(s, stage, s.checks.get(stage, [])[n_checks:], error)
        finally:
            for c in gemini.CALLS.get():
                s.log(f"gemini {c['model']}", actor="gemini", **c)
            gemini.CALLS.reset(token)
        if not go_on:
            s.status = "failed"
            s.save()
            return s
    soft = [
        c
        for cs in s.checks.values()
        for c in cs
        if not c["passed"]
        and c.get("hard") is False
        # the mesh passed Flash's review, and the mesh is what gets simulated
        and c["name"] != "views_consistent"
    ]
    s.status = "flagged" if soft else "done"
    s.save()
    return s

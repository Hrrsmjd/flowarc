"""A mock batch in the registry's own shape, for the dashboard before the pipeline runs.

The documents match what the pipeline writes to Atlas (`samples`, `logs`, `approvals`) plus a
`baseline` collection of car-only embeddings for the diversity map. Log times are seconds
relative to the start of the live part of the demo: negative times are history, positive ones
play out live (the dashboard's mock replay and scripts/demo_feed.py both use them).

    python -m flowarc.mock web/mock.json

Seeded, so every run gives the same numbers. Nothing here is a real result.
"""

import json
import math
import random
import sys

from flowarc.sample import STAGES

TAXONOMY = [
    "animals and organic forms",
    "vehicles (land, air, sea, fictional, any era)",
    "buildings and structures",
    "furniture and everyday objects",
    "sports gear and tools",
    "plants",
    "abstract or parametric shapes",
    "combinations of the above",
]

# name, bucket index, Reynolds, yaw, ground plane, facing
CONCEPTS = [
    ("Hot-air balloon", 1, 1.1e4, 0, False, "any side"),
    ("1930s biplane", 1, 8.1e4, 0, False, "nose first"),
    ("Gothic chapel with spire", 2, 9.5e4, 0, True, "west front"),
    ("Windsor chair", 3, 3.1e4, 20, True, "seat front"),
    ("Recurve bow", 4, 1.2e4, 0, False, "broadside"),
    ("Saguaro cactus", 5, 6.0e4, 0, True, "any side"),
    ("Trefoil knot torus", 6, 850, 0, False, "lobe first"),
    ("Dolphin with snorkel", 7, 1.5e4, 10, False, "nose first"),
    ("Manta ray", 0, 9.0e4, 0, False, "head first"),
    ("Steam locomotive", 1, 3.3e4, 0, True, "smokebox first"),
    ("Lattice radio mast", 2, 2.4e4, 0, True, "face on"),
    ("Grand piano, lid open", 3, 7.7e4, 0, True, "keyboard first"),
    ("Kettlebell", 4, 4.0e3, 0, False, "handle up"),
    ("Bonsai pine", 5, 2.2e4, 0, True, "any side"),
    ("Gyroid sphere", 6, 120, 0, False, "any side"),
    ("Highland cow", 0, 4.2e4, 0, True, "head first"),
    ("Seahorse", 0, 2.6e3, 10, False, "snout first"),
    ("Pagoda, five tiers", 2, 5.4e4, 0, True, "front gate"),
]

LIVE = "s0016"  # the sample the demo follows: a mesh check fails, Argon fixes it, it finishes
DIM = 16  # mock embedding size; real ones come from gemini-embedding-2
PACE = 0.6  # the live sample takes about two minutes, so it fits in a 3-minute demo


def _script(fail_mesh: bool, flag_sim: bool = False, give_up: bool = False) -> list[tuple]:
    """(seconds after the previous event, stage, msg, extra fields) for one sample."""
    ev = [
        (
            2,
            "concept",
            "Argon proposed this concept for an under-covered bucket",
            {"actor": "argon"},
        ),
        (
            2,
            "concept",
            "check novelty: pass",
            {"check": "novelty", "passed": True, "similarity": 0.71},
        ),
        (1, "concept", "advanced", {}),
        (14, "images", "Nano Banana drew 4 views", {"actor": "nano-banana"}),
        (
            6,
            "images",
            "check view_consistency: pass",
            {"check": "view_consistency", "passed": True, "actor": "flash"},
        ),
        (1, "images", "advanced", {}),
        (18, "mesh", "Hunyuan3D-2.1 built the mesh", {"actor": "hunyuan3d"}),
        (
            4,
            "mesh",
            "check geometry: pass",
            {"check": "geometry", "passed": True, "watertight": True, "bodies": 1},
        ),
    ]
    if fail_mesh:
        ev += [
            (
                6,
                "mesh",
                "check flash_review: FAIL",
                {
                    "check": "flash_review",
                    "passed": False,
                    "actor": "flash",
                    "reason": "only three legs; the front-left leg is missing",
                    "iou": {"front": 0.71, "side": 0.88, "top": 0.90},
                },
            ),
            (
                9,
                "mesh",
                "repair: new mesh from a redrawn front view",
                {
                    "actor": "argon",
                    "diagnosis": "The front view shows the front-left leg hidden behind the right "
                    "one, so image-to-3D merged them. Redraw the front view with all four legs "
                    "clearly apart and rebuild the mesh.",
                },
            ),
            (10, "images", "Nano Banana redrew the front view", {"actor": "nano-banana"}),
            (16, "mesh", "Hunyuan3D-2.1 rebuilt the mesh (attempt 2)", {"actor": "hunyuan3d"}),
            (
                4,
                "mesh",
                "check geometry: pass",
                {"check": "geometry", "passed": True, "watertight": True, "bodies": 1},
            ),
        ]
    if give_up:
        ev += [
            (
                6,
                "mesh",
                "check flash_review: FAIL",
                {
                    "check": "flash_review",
                    "passed": False,
                    "actor": "flash",
                    "reason": "handle fused to the body",
                },
            ),
            (
                5,
                "mesh",
                "repair: dropped the concept after 4 attempts",
                {
                    "actor": "argon",
                    "diagnosis": "The handle hole closes at every seed; this shape is below the mesh resolution.",
                },
            ),
        ]
        return ev
    ev += [
        (
            6,
            "mesh",
            "check flash_review: pass",
            {
                "check": "flash_review",
                "passed": True,
                "actor": "flash",
                "iou": {"front": 0.91, "side": 0.89, "top": 0.92},
            },
        ),
        (
            2,
            "mesh",
            "check symmetry: pass",
            {"check": "symmetry", "passed": True, "chamfer": 0.004},
        ),
        (1, "mesh", "advanced", {}),
        (
            8,
            "sim",
            "Argon chose solver settings: 8x4x4 box, 48 then 64 cells/L, LES, u_lat 0.075, 10 L/U start-up",
            {"actor": "argon"},
        ),
        (20, "sim", "FluidX3D: 48 cells/L done", {"actor": "fluidx3d"}),
        (
            2,
            "sim",
            "check stability: pass",
            {"check": "stability", "passed": True, "mach_max": 0.19},
        ),
        (30, "sim", "FluidX3D: 64 cells/L done", {"actor": "fluidx3d"}),
    ]
    if flag_sim:
        ev += [
            (
                2,
                "sim",
                "check grid_convergence: FAIL",
                {"check": "grid_convergence", "passed": False, "d_cd": 0.061, "tol": 0.03},
            ),
            (1, "sim", "flagged: resolution cap reached, kept as 'not converged'", {}),
        ]
        return ev
    ev += [
        (
            2,
            "sim",
            "check grid_convergence: pass",
            {"check": "grid_convergence", "passed": True, "d_cd": 0.021, "tol": 0.03},
        ),
        (1, "sim", "advanced", {}),
        (14, "render", "rendered the 300-frame Q-criterion loop", {}),
        (
            8,
            "render",
            "check video_review: pass",
            {
                "check": "video_review",
                "passed": True,
                "actor": "flash",
                "notes": "wake detaches, no leaks",
            },
        ),
        (1, "render", "advanced", {}),
        (6, "package", "packed Zarr, 0.58 GB", {}),
        (1, "package", "advanced", {}),
    ]
    return ev


def _convergence(rng: random.Random, cd: float, coarse_bias: float) -> dict:
    """Running mean of drag over the recorded window at each grid level."""
    levels = []
    for cells, bias in ((48, coarse_bias), (64, 0.0)):
        t = [round(10 + 0.5 * i, 1) for i in range(61)]  # 10..40 L/U
        target = cd * (1 + bias)
        mean, s = [], 0.0
        for i, x in enumerate(t):
            s += target * (1 + 0.18 * math.sin(2 * math.pi * 0.19 * x) + rng.gauss(0, 0.06))
            mean.append(round(s / (i + 1), 4))
        levels.append(
            {
                "cells": cells,
                "t": t,
                "cd_mean": mean,
                "cd": round(target, 4),
                "cl_rms": round(0.12 * (1 + bias), 4),
                "st": round(0.196 * (1 - bias / 3), 4),
            }
        )
    return {"levels": levels, "tol": {"cd": 0.03, "cl_rms": 0.05, "st": 0.03}}


def _unit(rng: random.Random, centre: list[float] | None, spread: float) -> list[float]:
    v = [(c if centre else 0) + rng.gauss(0, spread) for c in (centre or [0] * DIM)]
    n = math.sqrt(sum(x * x for x in v))
    return [round(x / n, 4) for x in v]


def batch() -> dict:
    rng = random.Random(7)
    centres = [_unit(rng, None, 1.0) for _ in TAXONOMY]
    # start offsets (s): history, the live sample at 0, two more finishing during the demo
    plan = {
        "s0012": {"flag_sim": True},
        "s0013": {"give_up": True},
        "s0014": {"start": -150},
        "s0015": {"start": -90},
        LIVE: {"start": 0, "fail_mesh": True},
        "s0017": {"start": 35},
        "s0018": {"start": 75},
    }
    samples, logs = [], []
    for i, (name, b, re, yaw, ground, facing) in enumerate(CONCEPTS):
        sid = f"s{i + 1:04d}"
        p = plan.get(sid, {})
        start = p.get("start", -12600 + i * 900)
        script = _script(
            p.get("fail_mesh", False), p.get("flag_sim", False), p.get("give_up", False)
        )
        t = start
        for dt, stage, msg, extra in script:
            t += dt * PACE
            logs.append({"sample": sid, "t": round(t, 1), "stage": stage, "msg": msg, **extra})
        final = "failed" if p.get("give_up") else "flagged" if p.get("flag_sim") else "done"
        final_stage = "mesh" if p.get("give_up") else "sim" if p.get("flag_sim") else "done"
        cd = round(rng.uniform(0.3, 1.3), 3)
        bias = 0.061 if p.get("flag_sim") else 0.021
        samples.append(
            {
                "_id": sid,
                "stage": final_stage,
                "status": final,
                "concept": {
                    "name": name,
                    "bucket": TAXONOMY[b],
                    "description": f"{name}, {facing}",
                    "facing": facing,
                    "reynolds": re,
                    "yaw_deg": yaw,
                    "ground": ground,
                },
                "checks": {},
                "attempts": {"mesh": 2}
                if p.get("fail_mesh")
                else {"mesh": 4}
                if p.get("give_up")
                else {},
                "meta": {
                    "gpu": i % 7,
                    "gpu_seconds": 0 if p.get("give_up") else round(rng.uniform(260, 420), 1),
                    "convergence": None if p.get("give_up") else _convergence(rng, cd, bias),
                },
                "embedding": _unit(rng, centres[b], 0.25),
            }
        )
    # a pre-computed batch so the map isn't sparse
    for k in range(60):
        b = k % len(TAXONOMY)
        samples.append(
            {
                "_id": f"b{k + 1:04d}",
                "stage": "done",
                "status": "done",
                "concept": {"name": f"batch sample {k + 1}", "bucket": TAXONOMY[b]},
                "checks": {},
                "attempts": {},
                "meta": {"gpu_seconds": round(rng.uniform(260, 420), 1), "batch": True},
                "embedding": _unit(rng, centres[b], 0.32),
            }
        )
    car = centres[1]
    baseline = [
        {
            "_id": f"car{k + 1:04d}",
            "name": f"DrivAerNet++ car {k + 1}",
            "embedding": _unit(rng, car, 0.06),
        }
        for k in range(80)
    ]
    end_live = max(e["t"] for e in logs if e["sample"] == LIVE)
    approvals = [
        {
            "_id": "flagged-s0012",
            "kind": "flagged",
            "title": "Review flagged sample s0012 (Grand piano, lid open)",
            "detail": "Drag changed 6.1% between 48 and 64 cells/L; tolerance is 3%.",
            "sample": "s0012",
            "status": "pending",
            "t": -1800.0,
        },
        {
            "_id": "phase2",
            "kind": "over_budget",
            "title": "Run Phase 2 at 120 cells/L",
            "detail": "Argon estimates 100 samples in 4.1 h on 7 A100s (29 GPU-hours).",
            "status": "pending",
            "t": -600.0,
        },
        {
            "_id": "publish-pilot",
            "kind": "publish",
            "title": "Publish the pilot batch to Hugging Face (private)",
            "detail": "All finished samples with their checks; flagged ones keep their flag.",
            "status": "pending",
            "t": round(end_live + 5, 1),
        },
    ]
    return {
        "run": {
            "phase": "pilot",
            "cells_per_length": [48, 64],
            "target_samples": 20,
            "gpus": 7,
            "live": LIVE,
        },
        "samples": samples,
        "logs": sorted(logs, key=lambda e: e["t"]),
        "approvals": approvals,
        "baseline": baseline,
        "cycle": round(end_live + 60, 1),  # the mock replay restarts after this many seconds
    }


def stage_after(stage: str) -> str:
    i = STAGES.index(stage)
    return STAGES[i + 1] if i + 1 < len(STAGES) else "done"


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "web/mock.json"
    with open(out, "w") as f:
        json.dump(batch(), f, separators=(",", ":"))
    print(f"wrote {out}")

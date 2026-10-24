"""Mock dashboard state, shaped like the real one, for building the demo before the pipeline runs.

Seeded, so every run gives the same numbers. Nothing here is a real result.
"""

import math
import random
import time

from flowarc.sample import STAGES

BUCKETS = [
    "animals",
    "vehicles",
    "buildings",
    "furniture",
    "sports & tools",
    "plants",
    "abstract",
    "combinations",
]

# (title, bucket, Re, angle of attack in degrees, ground plane)
CONCEPTS = [
    ("Highland cow, standing", "animals", 4.2e5, 0, True),
    ("1930s biplane", "vehicles", 2.1e6, 4, False),
    ("Gothic chapel with spire", "buildings", 8.5e6, 0, True),
    ("Windsor chair", "furniture", 3.1e4, 0, True),
    ("Recurve bow", "sports & tools", 1.2e4, 90, False),
    ("Saguaro cactus", "plants", 6.0e5, 0, True),
    ("Trefoil knot torus", "abstract", 850, 0, False),
    ("Dolphin with snorkel", "combinations", 1.5e5, 2, False),
    ("Manta ray", "animals", 9.0e5, 6, False),
    ("Steam locomotive", "vehicles", 3.3e6, 0, True),
    ("Lattice radio mast", "buildings", 2.4e5, 0, True),
    ("Grand piano, lid open", "furniture", 7.7e5, 0, True),
    ("Kettlebell", "sports & tools", 4.0e3, 0, False),
    ("Bonsai pine", "plants", 2.2e4, 0, True),
    ("Gyroid sphere", "abstract", 120, 0, False),
    ("Hot-air balloon", "vehicles", 1.1e6, 0, False),
    ("Seahorse", "animals", 2.6e3, 10, False),
    ("Pagoda, five tiers", "buildings", 5.4e6, 0, True),
]

# The sample the demo follows: a mesh check fails, Argon diagnoses it and the retry passes.
FEATURED = "s0001"


def _events(sample_id: str, t0: float, fail_mesh: bool) -> list[dict]:
    """A plausible log for one sample, oldest first. `t` is seconds since the epoch."""
    t = t0
    out = []

    def ev(stage, msg, dt, **data):
        nonlocal t
        t += dt
        out.append({"t": round(t, 1), "stage": stage, "msg": msg, **data})

    ev("concept", "Argon proposed concept to fill the 'animals' gap", 4, actor="argon")
    ev("concept", "check novelty: pass", 2, actor="system", nearest=0.31, threshold=0.18)
    ev("images", "Nano Banana generated 4 views", 38, actor="nano-banana")
    ev("images", "check view_consistency: pass", 6, actor="flash")
    ev("mesh", "Hunyuan3D-2.1 generated mesh", 95, actor="hunyuan3d")
    ev("mesh", "check geometry: pass", 8, actor="system", watertight=True, bodies=1)
    if fail_mesh:
        ev(
            "mesh",
            "check silhouette_iou: FAIL",
            12,
            actor="system",
            iou={"front": 0.71, "side": 0.88, "top": 0.90},
            threshold=0.85,
            failed=True,
        )
        ev(
            "mesh",
            "Argon diagnosis: the front-left leg is missing in the mesh; front view shows three "
            "legs. Regenerate from a new front view with the prompt 'a highland cow standing on "
            "four legs, all four legs clearly separated'.",
            41,
            actor="argon",
            decision="regenerate",
            fix=True,
        )
        ev("images", "Nano Banana regenerated front view", 21, actor="nano-banana")
        ev("mesh", "Hunyuan3D-2.1 regenerated mesh (attempt 2)", 92, actor="hunyuan3d")
        ev("mesh", "check geometry: pass", 8, actor="system", watertight=True, bodies=1)
    ev(
        "mesh",
        "check silhouette_iou: pass",
        12,
        actor="system",
        iou={"front": 0.91, "side": 0.89, "top": 0.92},
        threshold=0.85,
    )
    ev("mesh", "check symmetry: pass", 5, actor="system", chamfer=0.004)
    ev(
        "sim",
        "Argon chose solver settings: 8x4x4 box, 48 -> 64 cells/L, LES (Smagorinsky), "
        "u_lat 0.075, 10 L/U start-up. Ground plane, so blockage is 3.1%.",
        33,
        actor="argon",
    )
    ev("sim", "FluidX3D level 48 cells/L on gpu 2", 64, actor="system")
    ev("sim", "check stability: pass", 2, actor="system", mach_max=0.19, nan=False)
    ev("sim", "FluidX3D level 64 cells/L on gpu 2", 148, actor="system")
    ev("sim", "check grid_convergence: pass", 3, actor="system", d_cd=0.021, tol=0.03)
    ev("render", "rendered 300-frame Q-criterion loop", 41, actor="system")
    ev("render", "check video_review: pass", 14, actor="flash", notes="wake detaches, no leaks")
    ev("package", "packed Zarr, 0.58 GB", 22, actor="system")
    return out


def _convergence(rng: random.Random, cd: float, coarse_bias: float) -> dict:
    """Running mean of drag over the recorded window at each grid level, plus the QoI table."""
    levels = []
    for cells, bias in ((48, coarse_bias), (64, 0.0)):
        t = [round(10 + 0.5 * i, 1) for i in range(61)]  # 10..40 L/U
        target = cd * (1 + bias)
        inst = [
            target * (1 + 0.18 * math.sin(2 * math.pi * 0.19 * x) + rng.gauss(0, 0.06)) for x in t
        ]
        mean, s = [], 0.0
        for i, v in enumerate(inst):
            s += v
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
    return {
        "levels": levels,
        "tol": {"cd": 0.03, "cl_rms": 0.05, "st": 0.03},
        "startup": 10.0,
    }


def state(now: float | None = None) -> dict:
    rng = random.Random(7)
    now = time.time() if now is None else now
    t_start = now - 3.6 * 3600
    samples = []
    for i, (title, bucket, re, angle, ground) in enumerate(CONCEPTS):
        sid = f"s{i + 1:04d}"
        if i < 11:
            stage, status = "done", "done"
        elif i == 11:
            stage, status = "sim", "flagged"
        elif i == 12:
            stage, status = "mesh", "failed"
        elif i < 16:
            stage, status = STAGES[[3, 2, 4][i - 13]], "running"
        else:
            stage, status = "concept", "pending"
        t0 = t_start + i * 600
        events = _events(sid, t0, fail_mesh=sid == FEATURED or i == 12)
        if status != "done":
            cut = {"concept": 1, "images": 3, "mesh": 6, "sim": 14, "render": 17}.get(stage, 0)
            if status == "pending":
                cut = 0
            events = events[: cut + (4 if i == 12 else 0)]
        if status == "failed":
            events.append(
                {
                    "t": events[-1]["t"] + 30,
                    "stage": "mesh",
                    "msg": "max attempts reached (4); Argon dropped the concept and logged why",
                    "actor": "argon",
                    "failed": True,
                }
            )
        if status == "flagged":
            events.append(
                {
                    "t": events[-1]["t"] + 9,
                    "stage": "sim",
                    "msg": "resolution cap reached: d_cd 0.061 > tol 0.03 between 48 and 64 "
                    "cells/L. Kept and flagged 'not converged'.",
                    "actor": "system",
                    "failed": True,
                }
            )
        cd = round(rng.uniform(0.3, 1.3), 3)
        attempts = {"mesh": 2} if sid == FEATURED else {}
        samples.append(
            {
                "id": sid,
                "title": title,
                "bucket": bucket,
                "stage": stage,
                "status": status,
                "concept": {"description": title, "re": re, "angle": angle, "ground": ground},
                "attempts": attempts,
                "gpu": (i % 7) if status == "running" else None,
                "log": events,
                "convergence": _convergence(rng, cd, 0.061 if status == "flagged" else 0.021)
                if stage in ("render", "package", "done") or status == "flagged"
                else None,
                "gpu_seconds": round(sum(1 for e in events if e["stage"] == "sim") * 105.0, 1),
            }
        )

    # 2D projection of shape embeddings: ours spread over buckets, the car baseline in one tight blob.
    centres = {
        b: (math.cos(k * 0.785) * 3.2, math.sin(k * 0.785) * 2.6) for k, b in enumerate(BUCKETS)
    }
    points = []
    for s in samples:
        cx, cy = centres[s["bucket"]]
        points.append(
            {
                "id": s["id"],
                "label": s["title"],
                "bucket": s["bucket"],
                "x": round(cx + rng.gauss(0, 0.55), 3),
                "y": round(cy + rng.gauss(0, 0.55), 3),
                "source": "flowarc",
            }
        )
    for k in range(60):  # extra pre-computed batch so the map isn't sparse
        b = BUCKETS[k % len(BUCKETS)]
        cx, cy = centres[b]
        points.append(
            {
                "id": f"b{k:04d}",
                "label": f"batch sample {k + 1}",
                "bucket": b,
                "x": round(cx + rng.gauss(0, 0.7), 3),
                "y": round(cy + rng.gauss(0, 0.7), 3),
                "source": "flowarc",
            }
        )
    cx, cy = centres["vehicles"]
    for k in range(80):
        points.append(
            {
                "id": f"car{k:04d}",
                "label": f"DrivAerNet++ car {k + 1}",
                "bucket": "vehicles",
                "x": round(cx + 0.4 + rng.gauss(0, 0.25), 3),
                "y": round(cy + 0.2 + rng.gauss(0, 0.18), 3),
                "source": "car_baseline",
            }
        )

    done = sum(s["status"] == "done" for s in samples)
    return {
        "mode": "mock",
        "generated_at": now,
        "run": {
            "phase": "pilot",
            "cells_per_length": [48, 64],
            "target_samples": 20,
            "started_at": t_start,
            "gpus": 7,
            "samples_per_hour": round(done / 3.6, 2),
            "gpu_hours": round(sum(s["gpu_seconds"] for s in samples) / 3600, 2),
            "featured": FEATURED,
        },
        "samples": samples,
        "diversity": {"points": points, "baseline": "DrivAerNet++ (cars only)"},
        "approvals": [
            {
                "id": "a1",
                "kind": "publish",
                "title": "Publish pilot batch to Hugging Face (private)",
                "detail": "11 samples, 6.4 GB. 1 flagged 'not converged' is included with its flag.",
                "status": "pending",
            },
            {
                "id": "a2",
                "kind": "over_budget",
                "title": "Run Phase 2 at 120 cells/L",
                "detail": "Argon estimates 100 samples in 4.1 h on 7 A100s (29 GPU-hours).",
                "status": "pending",
            },
            {
                "id": "a3",
                "kind": "flagged",
                "title": "Review flagged sample s0012 (Grand piano, lid open)",
                "detail": "Drag changed 6.1% between 48 and 64 cells/L; tolerance is 3%.",
                "status": "pending",
                "sample": "s0012",
            },
        ],
    }

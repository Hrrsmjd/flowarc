"""Stage 6: pack one simulation into a Zarr store.

Units: lengths in L (nose at x=0, centred in y, and in z unless on the ground), velocity in U, time in L/U.
  surface/points (Ns,3), surface/cp (T,Ns), surface/u (T,Ns,3) + cp_mean, cp_rms
  volume/points (Nv,3), volume/cp (T,Nv), volume/u (T,Nv,3) + cp_mean, cp_rms, u_mean, u_rms
  time (T,), forces (Nt,4): t, cd, cs, cl
Attributes hold the config, stats, cost and any extra metadata.
"""

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import trimesh
import zarr

from flowarc.sim.solver import SimConfig, SimResult


def _put(g, name: str, a: np.ndarray, dtype) -> None:
    a = np.ascontiguousarray(a, dtype=dtype)
    chunks = (
        (min(len(a), 25), *[min(n, 50_000) for n in a.shape[1:]])
        if a.ndim > 1
        else (min(len(a), 50_000),)
    )
    g.create_array(name, data=a, chunks=chunks)


def pack(result: SimResult, cfg: SimConfig, out: Path, meta: dict | None = None) -> Path:
    sim = Path(result.forces).parent
    L, U = cfg.cells_per_length, cfg.lattice_velocity
    lo, hi = trimesh.load(sim / "body.stl", force="mesh").bounds
    origin = np.array([lo[0], (lo[1] + hi[1]) / 2, 1.0 if cfg.ground else (lo[2] + hi[2]) / 2])
    surf = np.load(sim / "surface_points.npy")
    vol = np.load(sim / "volume_points.npy")
    data = np.stack(
        [np.fromfile(f, np.float32).reshape(-1, 4) for f in sorted((sim / "probes").glob("*.bin"))]
    )
    frames = np.loadtxt(sim / "frames.csv", delimiter=",", skiprows=1, ndmin=2)
    forces = np.loadtxt(sim / "forces.csv", delimiter=",", skiprows=1, ndmin=2)
    cp = (data[..., 0] - 1) / 3 / (0.5 * U**2)
    u = data[..., 1:] / U
    q = 0.5 * U**2 * result.stats["area_cells"]

    g = zarr.open_group(Path(out), mode="w")
    g.attrs.update(
        json.loads(
            json.dumps(
                {
                    "config": asdict(cfg),
                    "stats": result.stats,
                    "cost": result.cost,
                    "meta": meta or {},
                },
                default=str,
            )
        )
    )
    _put(g, "time", frames[: len(data), 1] * U / L, np.float32)
    _put(g, "forces", np.column_stack([forces[:, 0] * U / L, forces[:, 1:] / q]), np.float32)
    for name, pts, sl in [
        ("surface", surf, slice(0, len(surf))),
        ("volume", vol, slice(len(surf), None)),
    ]:
        s = g.create_group(name)
        _put(s, "points", (pts - origin) / L, np.float32)
        _put(s, "cp", cp[:, sl], np.float16)
        _put(s, "u", u[:, sl], np.float16)
        _put(s, "cp_mean", cp[:, sl].mean(0), np.float32)
        _put(s, "cp_rms", cp[:, sl].std(0), np.float32)
        if name == "volume":
            _put(s, "u_mean", u[:, sl].mean(0), np.float32)
            _put(s, "u_rms", u[:, sl].std(0), np.float32)
    return Path(out)


def size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())

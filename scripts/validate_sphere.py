"""Sphere check: drag vs Schiller-Naumann and shedding Strouhal number.

Usage: python scripts/validate_sphere.py OUT_DIR [--cells 64] [--re 20 100 300] [--gpu 0] [--quick]
"""

import argparse
import json
from pathlib import Path

import trimesh

from flowarc.sim.fluidx3d import FluidX3D
from flowarc.sim.solver import SimConfig


def cd_reference(re: float) -> float:
    """Schiller-Naumann sphere drag, good to about 5% for Re < 800."""
    return 24 / re * (1 + 0.15 * re**0.687)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("--cells", type=int, default=64)
    p.add_argument("--re", type=float, nargs="+", default=[20, 100, 300])
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument(
        "--domain", type=float, nargs=3, default=[6.0, 3.0, 3.0], help="box size in diameters"
    )
    p.add_argument("--record", type=float, default=30.0, help="recorded time in D/U")
    p.add_argument("--quick", action="store_true", help="short run for smoke tests")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    mesh = a.out / "sphere.stl"
    trimesh.creation.icosphere(subdivisions=4, radius=0.5).export(mesh)
    rows = []
    for re in a.re:
        cfg = SimConfig(
            reynolds=re, cells_per_length=a.cells, les=False, render=False, frame_interval=1.0
        )
        if a.quick:
            cfg.startup_time, cfg.record_time = 2.0, 2.0
        r = FluidX3D(n_surface=1000, n_volume=1000).run(mesh, cfg, a.out / f"re{re:g}", a.gpu)
        row = {"re": re, "ok": r.ok, "cd_ref": cd_reference(re), **r.stats, **r.cost}
        rows.append(row)
        print(json.dumps(row))
    (a.out / "summary.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()

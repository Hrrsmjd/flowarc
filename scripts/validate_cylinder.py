"""Cylinder check: shedding Strouhal number and drag, spanwise periodic.

Usage: python scripts/validate_cylinder.py OUT_DIR [--cells 32] [--re 100 150] [--gpu 0] [--quick]
"""

import argparse
import json
from pathlib import Path

import trimesh

from flowarc.sim.fluidx3d import FluidX3D, lattice
from flowarc.sim.solver import SimConfig


def st_reference(re: float) -> float:
    """Williamson (1988) parallel shedding, 50 < Re < 180."""
    return 0.2120 - 4.5 / re


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("--cells", type=int, default=32)
    p.add_argument("--re", type=float, nargs="+", default=[100, 150])
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument(
        "--domain",
        type=float,
        nargs=3,
        default=[20.0, 2.0, 24.0],
        help="box in diameters, y is the span",
    )
    p.add_argument("--startup", type=float, default=60.0, help="discarded spin-up time in D/U")
    p.add_argument("--record", type=float, default=160.0, help="recorded time in D/U")
    p.add_argument("--quick", action="store_true", help="short smoke test")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for re in a.re:
        cfg = SimConfig(
            reynolds=re,
            cells_per_length=a.cells,
            domain=tuple(a.domain),
            body_offset=a.domain[0] / 4,
            periodic_span=True,
            startup_time=2.0 if a.quick else a.startup,
            record_time=2.0 if a.quick else a.record,
            les=False,
            render=False,
            frame_interval=1.0,
        )
        ny = lattice(cfg)["Ny"]
        span = ny / a.cells  # exactly the box width
        mesh = a.out / f"cylinder-re{re:g}.stl"
        c = trimesh.creation.cylinder(radius=0.5, height=span, sections=128)
        c.apply_transform(trimesh.transformations.rotation_matrix(1.5707963, [1, 0, 0]))
        c.export(mesh)
        r = FluidX3D(n_surface=1000, n_volume=1000).run(mesh, cfg, a.out / f"re{re:g}", a.gpu)
        row = {"re": re, "ok": r.ok, "st_ref": st_reference(re), **r.stats, **r.cost}
        if r.ok:  # voxel frontal area runs ~1 cell wide on each edge; use the exact D x span
            row["cd_exact_area"] = r.stats["cd_mean"] * r.stats["area_cells"] / (a.cells * ny)
        rows.append(row)
        print(json.dumps(row))
    (a.out / "summary.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()

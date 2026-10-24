"""Ahmed body check: drag vs Ahmed et al. (1984), on a moving ground.

Usage: python scripts/validate_ahmed.py OUT_DIR [--slant 25] [--cells 64] [--gpu 0] [--quick]
"""

import argparse
import json
from pathlib import Path

from flowarc.mesh.primitives import ahmed
from flowarc.sim.fluidx3d import FluidX3D
from flowarc.sim.solver import SimConfig

CD_REF = {25.0: 0.285, 35.0: 0.257}  # Ahmed et al. 1984, Re 4.29e6 on length
AREA = 389 * 288 / 1044**2  # frontal area without stilts, in L^2


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("--slant", type=float, default=25.0, help="rear slant angle in degrees")
    p.add_argument("--cells", type=int, default=64, help="cells per body length")
    p.add_argument("--re", type=float, default=4.29e6)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument(
        "--domain", type=float, nargs=3, default=[8.0, 4.0, 2.0], help="box in body lengths"
    )
    p.add_argument("--quick", action="store_true", help="short smoke test")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    mesh = a.out / "ahmed.stl"
    ahmed(a.slant).export(mesh)
    cfg = SimConfig(
        reynolds=a.re, cells_per_length=a.cells, domain=tuple(a.domain), ground=True, render=False
    )
    if a.quick:
        cfg.startup_time, cfg.record_time = 1.0, 1.0
    r = FluidX3D(n_surface=1000, n_volume=1000).run(mesh, cfg, a.out / "run", a.gpu)
    row = {"slant": a.slant, "ok": r.ok, "cd_ref": CD_REF.get(a.slant), **r.stats, **r.cost}
    if r.ok:  # voxel area includes the stilts and runs about a cell wide; use the body's exact area
        row["cd_exact_area"] = r.stats["cd_mean"] * r.stats["area_cells"] / (AREA * a.cells**2)
    print(json.dumps(row))
    (a.out / "summary.json").write_text(json.dumps(row, indent=1))


if __name__ == "__main__":
    main()

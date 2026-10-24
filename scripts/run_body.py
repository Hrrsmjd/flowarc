"""Run one body through FluidX3D and make the video.

Usage: python scripts/run_body.py MESH OUT_DIR [--re 1e6] [--cells 64] [--gpu 0] [--dns] [--quick] [--q Q]
Use MESH=aircraft for the built-in test aircraft.
"""

import argparse
import json
from pathlib import Path

from flowarc.mesh.primitives import aircraft
from flowarc.package import pack, size_bytes
from flowarc.sim.fluidx3d import FluidX3D
from flowarc.sim.solver import SimConfig


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mesh")
    p.add_argument("out", type=Path)
    p.add_argument("--re", type=float, default=1e6)
    p.add_argument("--cells", type=int, default=64)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--dns", action="store_true")
    p.add_argument("--ground", action="store_true", help="body rests on a moving ground at z=0")
    p.add_argument("--domain", type=float, nargs=3, help="box size in L (default from SimConfig)")
    p.add_argument("--offset", type=float, help="nose distance from the inlet in L")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--q", type=float, help="Q isosurface level in (U/L)^2 (default from Re)")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    mesh = Path(a.mesh)
    if a.mesh == "aircraft":
        mesh = a.out / "aircraft.stl"
        aircraft().export(mesh)
    cfg = SimConfig(reynolds=a.re, cells_per_length=a.cells, les=not a.dns, render=not a.no_render)
    cfg.ground = a.ground
    if a.domain:
        cfg.domain = tuple(a.domain)
    if a.offset is not None:
        cfg.body_offset = a.offset
    if a.quick:
        cfg.startup_time, cfg.record_time = 1.0, 1.0
    r = FluidX3D(q_star=a.q).run(mesh, cfg, a.out / "sim", a.gpu)
    gb = size_bytes(pack(r, cfg, a.out / "sample.zarr", {"mesh": a.mesh})) / 1e9 if r.ok else None
    print(json.dumps({"ok": r.ok, **r.stats, **r.cost, "zarr_gb": gb}))


if __name__ == "__main__":
    main()

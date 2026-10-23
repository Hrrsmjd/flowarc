import numpy as np
import trimesh
import zarr

from flowarc.package import pack
from flowarc.sim.fluidx3d import lattice, place
from flowarc.sim.solver import SimConfig, SimResult


def test_pack_shapes_and_units(tmp_path):
    cfg = SimConfig(reynolds=100, cells_per_length=20)
    m = place(trimesh.creation.icosphere(radius=0.5), cfg, lattice(cfg))
    m.export(tmp_path / "body.stl")
    np.save(
        tmp_path / "surface_points.npy",
        m.vertices[np.argsort(m.vertices[:, 0])[:10]].astype(np.float32),
    )
    np.save(tmp_path / "volume_points.npy", np.full((20, 3), 60, np.float32))
    (tmp_path / "probes").mkdir()
    U = cfg.lattice_velocity
    for k in range(3):  # rho giving cp = 1, u = U along x
        np.tile(np.float32([1 + 1.5 * U**2, U, 0, 0]), 30).tofile(tmp_path / f"probes/{k:05d}.bin")
    (tmp_path / "frames.csv").write_text(
        "frame,t,mass,umax,nans\n0,100,1,0.1,0\n1,200,1,0.1,0\n2,300,1,0.1,0\n"
    )
    (tmp_path / "forces.csv").write_text("t,fx,fy,fz\n100,1,0,0\n200,1,0,0\n")
    res = SimResult(
        ok=True, forces=tmp_path / "forces.csv", frames=None, stats={"area_cells": 2 / U**2}
    )
    g = zarr.open_group(pack(res, cfg, tmp_path / "s.zarr"), mode="r")
    assert g["surface/cp"].shape == (3, 10) and g["volume/u"].shape == (3, 20, 3)
    assert np.allclose(g["volume/cp_mean"][:], 1, atol=1e-3) and np.allclose(
        g["volume/u_mean"][:, 0], 1
    )
    assert np.isclose(g["surface/points"][:, 0].min(), 0, atol=1e-3)
    assert np.allclose(g["forces"][:, 1], 1) and np.isclose(g["time"][1], 200 * U / 20)

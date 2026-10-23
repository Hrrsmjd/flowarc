import numpy as np
import trimesh

from flowarc.sim.fluidx3d import frontal_area, lattice, place, stats, strouhal
from flowarc.sim.solver import SimConfig


def test_lattice_and_placement():
    cfg = SimConfig(reynolds=100, cells_per_length=20)
    lat = lattice(cfg)
    assert (lat["Nx"], lat["Ny"], lat["Nz"]) == (120, 60, 60)
    assert np.isclose(lat["nu"], 0.075 * 20 / 100)
    assert lat["frame_every"] == round(0.1 * 20 / 0.075)
    m = place(trimesh.creation.icosphere(radius=0.5), cfg, lat)
    lo, hi = m.bounds
    assert np.isclose(lo[0], 30) and np.allclose((lo[1:] + hi[1:]) / 2, 30)
    assert abs(frontal_area(m) - np.pi * 10**2) / (np.pi * 10**2) < 0.15


def test_stats_recovers_strouhal():
    cfg = SimConfig(reynolds=100, cells_per_length=20)
    lat = lattice(cfg)
    t = np.arange(0, lat["startup_steps"] + lat["record_steps"], lat["force_every"], dtype=float)
    f = 0.2 * lat["u"] / 20  # St = 0.2
    q = 0.5 * lat["u"] ** 2 * 100
    forces = np.column_stack([t, q * np.ones_like(t), q * 0.1 * np.sin(2 * np.pi * f * t), 0 * t])
    s = stats(forces, cfg, lat, 100)
    assert np.isclose(s["cd_mean"], 1) and abs(s["st_side"] - 0.2) < 0.02
    assert strouhal(np.zeros(100), 1, 1, 1) == 0

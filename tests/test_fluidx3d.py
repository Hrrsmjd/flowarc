import numpy as np
import trimesh

from flowarc.sim.fluidx3d import _table, frontal_area, lattice, place, stats, strouhal
from flowarc.sim.solver import SimConfig


def test_lattice_and_placement():
    cfg = SimConfig(reynolds=100, cells_per_length=20)
    lat = lattice(cfg)
    assert (lat["Nx"], lat["Ny"], lat["Nz"]) == (160, 80, 80)
    assert np.isclose(lat["nu"], 0.075 * 20 / 100)
    assert lat["frame_every"] == round(0.1 * 20 / 0.075)
    m = place(trimesh.creation.icosphere(radius=0.5), cfg, lat)
    lo, hi = m.bounds
    assert np.isclose(lo[0], 40) and np.allclose((lo[1:] + hi[1:]) / 2, 40)
    assert abs(frontal_area(m) - np.pi * 10**2) / (np.pi * 10**2) < 0.15


def test_stats_recovers_strouhal():
    cfg = SimConfig(reynolds=100, cells_per_length=20)
    lat = lattice(cfg)
    t = np.arange(0, lat["startup_steps"] + lat["record_steps"], lat["force_every"], dtype=float)
    f = 0.2 * lat["u"] / 20  # St = 0.2
    q = 0.5 * lat["u"] ** 2 * 100
    forces = np.column_stack([t, q * np.ones_like(t), q * 0.1 * np.sin(2 * np.pi * f * t), 0 * t])
    s = stats(forces, cfg, lat, 100)
    assert np.isclose(s["cd_mean"], 1) and abs(s["st"] - 0.2) < 0.02
    assert strouhal(np.zeros((100, 2)), 1, 1, 1) == 0


def test_forces_sampled_without_frames():
    lat = lattice(SimConfig(reynolds=100, cells_per_length=64, frame_interval=0))
    assert lat["force_every"] == round(0.005 * 64 / 0.075)


def test_strouhal_band_edge_is_nan():
    t = np.arange(1000) * 0.1
    assert np.isnan(strouhal(np.sin(2 * np.pi * 0.02 * t), 0.1, 1.0, 1.0))


def test_missing_table_is_empty(tmp_path):
    assert _table(tmp_path / "forces.csv", 4).shape == (0, 4)


def test_truncated_table_keeps_good_rows(tmp_path):
    p = tmp_path / "forces.csv"
    p.write_text("t,fx,fy,fz\n1,2,3,4\n2,3,4,5\n3,4,")
    assert _table(p, 4).tolist() == [[1, 2, 3, 4], [2, 3, 4, 5]]

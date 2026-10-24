"""FluidX3D backend: voxelized body in a D3Q19 LBM box, inflow along +x.

The mesh must already be normalized: length 1 along x, flow along +x.
With `ground`, z=0 is the ground plane. Everything is converted to lattice units here.
"""

import math
import os
import subprocess
from pathlib import Path

import numpy as np
import trimesh

from flowarc.sim.solver import SimConfig, SimResult

BIN = Path(os.environ.get("FLOWARC_FLUIDX3D_BIN", Path(__file__).resolve().parents[3] / "bin"))


def lattice(cfg: SimConfig) -> dict:
    """Grid size, viscosity and step counts for a config."""
    L, u = cfg.cells_per_length, cfg.lattice_velocity
    n = [round(d * L) for d in cfg.domain]
    steps = L / u  # steps per convective time L/U
    frame_every = max(1, round(cfg.frame_interval * steps)) if cfg.frame_interval else 10**12
    return {
        "Nx": n[0],
        "Ny": n[1],
        "Nz": n[2],
        "u": u,
        "nu": u * L / cfg.reynolds,
        "startup_steps": round(cfg.startup_time * steps),
        "record_steps": round(cfg.record_time * steps),
        "frame_every": frame_every,
        "force_every": max(1, round(cfg.force_interval * steps)),
    }


def place(mesh: trimesh.Trimesh, cfg: SimConfig, lat: dict) -> trimesh.Trimesh:
    """Scale to lattice units and move the nose to body_offset; centred in y (and z without ground)."""
    L = cfg.cells_per_length
    m = mesh.copy()
    m.apply_scale(L)
    lo, hi = m.bounds
    shift = [cfg.body_offset * L - lo[0], lat["Ny"] / 2 - (lo[1] + hi[1]) / 2, 0.0]
    shift[2] = 1.0 if cfg.ground else lat["Nz"] / 2 - (lo[2] + hi[2]) / 2
    m.apply_translation(shift)
    return m


def camera(m: trimesh.Trimesh, lat: dict, L: float) -> dict:
    """Three-quarter view of the body and its near wake (target is relative to the box centre)."""
    lo, hi = m.bounds
    c = (lo + hi) / 2
    t = [lo[0] + 1.3 * L - lat["Nx"] / 2, c[1] - lat["Ny"] / 2, c[2] - lat["Nz"] / 2]
    return {
        "cam_rx": -50.0,
        "cam_ry": 25.0,
        "cam_fov": 50.0,
        "cam_tx": round(t[0], 2),
        "cam_ty": round(t[1], 2),
        "cam_tz": round(t[2], 2),
        "cam_rad": round(1.4 * L, 2),
    }


def frontal_area(m: trimesh.Trimesh) -> float:
    """Projected area on the y-z plane in cells^2, from a 1-cell voxelization."""
    vox = m.voxelized(pitch=1.0).fill()
    return float(vox.matrix.any(axis=0).sum())


def probes(m: trimesh.Trimesh, lat: dict, n_surface: int, n_volume: int, seed: int = 0):
    """Surface points (pushed 1.5 cells out along the normal) and random wake-box points."""
    rng = np.random.default_rng(seed)
    pts, faces = trimesh.sample.sample_surface(m, n_surface, seed=seed)
    surf = pts + 1.5 * m.face_normals[faces]
    lo, hi = m.bounds
    size = hi - lo
    box_lo = np.maximum(lo - 0.5 * size.max(), 1)
    box_hi = np.minimum(hi + 0.5 * size.max(), [lat["Nx"] - 2, lat["Ny"] - 2, lat["Nz"] - 2])
    box_hi[0] = lat["Nx"] - 2  # keep the whole wake
    vol = rng.uniform(box_lo, box_hi, size=(n_volume, 3))
    inside = m.contains(vol) if m.is_watertight else np.zeros(len(vol), bool)
    vol = vol[~inside]
    return pts, surf.astype(np.float32), vol.astype(np.float32)


def strouhal(
    signals: np.ndarray, dt: float, L: float, u: float, st_min: float = 0.05, st_max: float = 5.0
) -> float:
    """Dominant shedding frequency of one or more force signals (columns), as St = f L / U.

    Signals are detrended; the summed power spectrum is searched between st_min (slow drift) and st_max (lattice ringing).
    """
    s = np.atleast_2d(np.asarray(signals, float).T).T
    if len(s) < 16:
        return 0.0
    t = np.arange(len(s))
    s = s - np.polyval(np.polyfit(t, s, 1), t[:, None])
    power = (np.abs(np.fft.rfft(s * np.hanning(len(s))[:, None], axis=0)) ** 2).sum(axis=1)
    st = np.fft.rfftfreq(len(s), dt) * L / u
    band = (st >= st_min) & (st <= st_max)
    if not band.any() or not power[band].any():
        return 0.0
    i = power[band].argmax()
    if i == 0:
        return float("nan")  # peak on the band edge: drift or unfinished transient, not shedding
    return float(st[band][i])


def _table(path: Path, cols: int) -> np.ndarray:
    """CSV with a header row. Keeps only whole rows, so a crash mid-write loses just the last line."""
    try:
        lines = path.read_text().splitlines()[1:]
    except OSError:
        return np.empty((0, cols))
    rows = []
    for line in lines:
        try:
            r = [float(v) for v in line.split(",")]
        except ValueError:
            continue
        if len(r) == cols:
            rows.append(r)
    return np.array(rows, float).reshape(-1, cols)


ST_MAX = 5.0  # fastest physical force content, as St = f L / U


def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    """Moving average over w samples along time (axis 0)."""
    if w <= 1 or len(x) < w:
        return x
    k = np.ones(w) / w
    return np.stack([np.convolve(c, k, mode="valid") for c in x.T], axis=1)


def stats(forces: np.ndarray, cfg: SimConfig, lat: dict, area: float) -> dict:
    """Force coefficients over the recorded window, plus a half-vs-half convergence check."""
    t, F = forces[:, 0], forces[:, 1:]
    rec = t > lat["startup_steps"]
    q = 0.5 * lat["u"] ** 2 * area
    C = F[rec] / q
    # Force ringing faster than St_max is a lattice artefact (fixed in steps, not in L/U), so RMS is low-passed.
    w = max(1, round(cfg.cells_per_length / (lat["u"] * ST_MAX) / lat["force_every"]))
    Cs = _smooth(C, w)
    out = {"area_cells": area, "samples": int(rec.sum())}
    for i, name in enumerate(["cd", "cs", "cl"]):
        c = C[:, i]
        out[f"{name}_mean"] = float(c.mean()) if len(c) else float("nan")
        out[f"{name}_rms"] = float(Cs[:, i].std()) if len(Cs) else float("nan")
        out[f"{name}_rms_raw"] = float(c.std()) if len(c) else float("nan")
    if len(C) >= 4:
        h = len(C) // 2
        a, b = C[:h, 0].mean(), C[h:, 0].mean()
        out["cd_half_change"] = float(abs(a - b) / max(abs(b), 1e-9))
        dt = lat["force_every"]
        L = cfg.cells_per_length
        unsteady = C[:, 1:].std(axis=0).max() > 1e-3  # steady wakes have no shedding frequency
        out["st"] = strouhal(C[:, 1:], dt, L, lat["u"]) if unsteady else 0.0
    return out


class FluidX3D:
    """Runs the FlowArc FluidX3D build (see build.sh) on one GPU."""

    def __init__(
        self,
        bin_dir: Path = BIN,
        n_surface: int = 50_000,
        n_volume: int = 200_000,
        q_star: float = 50.0,
    ):
        self.bin_dir = Path(bin_dir)
        self.q_star = q_star  # Q-criterion isosurface level in units of (U/L)^2
        self.n_surface = n_surface
        self.n_volume = n_volume

    def run(self, mesh: Path, cfg: SimConfig, out: Path, gpu: int) -> SimResult:
        out = Path(out)
        (out / "probes").mkdir(parents=True, exist_ok=True)
        (out / "render").mkdir(exist_ok=True)
        lat = lattice(cfg)
        m = place(trimesh.load(mesh, force="mesh"), cfg, lat)
        m.export(out / "body.stl")
        area = frontal_area(m)
        pts, surf, vol = (
            probes(m, lat, self.n_surface, self.n_volume)
            if cfg.frame_interval
            else (None, None, None)
        )
        if pts is not None:
            np.save(out / "surface_points.npy", surf)
            np.save(out / "volume_points.npy", vol)
            np.concatenate([surf, vol]).tofile(out / "probes.f32")
        keys = {
            **lat,
            "ground": int(cfg.ground),
            "periodic_y": int(cfg.periodic_span),
            "render": int(cfg.render),
            "stl": out / "body.stl",
            "probes": out / "probes.f32",
            "out": out,
            **camera(m, lat, cfg.cells_per_length),
        }
        (out / "fluidx3d.cfg").write_text("".join(f"{k} {v}\n" for k, v in keys.items()))
        exe = self.bin_dir / ("fluidx3d-les" if cfg.les else "fluidx3d-dns")
        if not exe.exists():
            raise FileNotFoundError(
                f"{exe} missing: run flowarc/sim/fluidx3d/build.sh or set FLOWARC_FLUIDX3D_BIN"
            )
        q = self.q_star * (cfg.lattice_velocity / cfg.cells_per_length) ** 2
        env = {**os.environ, "FLOWARC_CFG": str(out / "fluidx3d.cfg"), "FLOWARC_Q": f"{q:.6g}"}
        with open(out / "fluidx3d.log", "w") as log:
            proc = subprocess.run(
                [str(exe), str(gpu)], check=False, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        status = (
            dict(line.split() for line in (out / "status.txt").read_text().splitlines())
            if (out / "status.txt").exists()
            else {}
        )
        forces = _table(out / "forces.csv", 4)
        frames = _table(out / "frames.csv", 5)
        st = stats(forces, cfg, lat, area) if len(forces) else {}
        if len(frames):
            mass = frames[:, 2]
            st["mass_drift"] = float(abs(mass[-1] - mass[0]) / mass[0])
            st["max_u"] = float(frames[:, 3].max())
            st["mach_max"] = st["max_u"] * 3**0.5
        seconds = float(status.get("seconds", "nan"))
        cells = lat["Nx"] * lat["Ny"] * lat["Nz"]
        steps = int(status.get("steps", 0))
        cost = {
            "seconds": seconds,
            "cells": cells,
            "steps": steps,
            "mlups": cells * steps / seconds / 1e6 if math.isfinite(seconds) and seconds > 0 else 0,
            "gpu": gpu,
        }
        ok = proc.returncode == 0 and status.get("ok") == "1"
        video = None
        if ok and cfg.render and any((out / "render").glob("*.png")):
            video = out / "video.mp4"
            try:
                enc = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-framerate",
                        "30",
                        "-pattern_type",
                        "glob",
                        "-i",
                        str(out / "render/*.png"),
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-crf",
                        "20",
                        str(video),
                    ],
                    check=False,
                )
                if enc.returncode:
                    video = None
            except OSError:
                video = None
        return SimResult(
            ok=ok,
            forces=out / "forces.csv",
            frames=out / "probes" if pts is not None else None,
            stats=st,
            cost=cost | {"video": str(video) if video else None},
        )

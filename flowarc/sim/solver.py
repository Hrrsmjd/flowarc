"""Solver interface. The LBM backend sits behind it so it can be swapped."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class SimConfig:
    reynolds: float
    cells_per_length: int
    domain: tuple[float, float, float] = (6.0, 3.0, 3.0)  # in body lengths
    body_offset: float = 1.5  # body nose distance from inlet, in body lengths
    ground: bool = False
    lattice_velocity: float = 0.075
    les: bool = True  # Smagorinsky subgrid model
    startup_time: float = 10.0  # L/U
    record_time: float = 30.0  # L/U
    frame_interval: float = 0.1  # L/U; 0 = no frames
    render: bool = True  # write Q-criterion video frames
    justification: str = ""


@dataclass
class SimResult:
    ok: bool
    forces: Path  # force history file (drag, lift, side per step)
    frames: Path | None
    stats: dict = field(default_factory=dict)  # mean/RMS forces, Strouhal, stability checks
    cost: dict = field(default_factory=dict)  # seconds, cell updates, GPU


class Solver(Protocol):
    def run(self, mesh: Path, cfg: SimConfig, out: Path, gpu: int) -> SimResult: ...

"""Pluggable image-to-3D generators. Shape only, no textures."""

from pathlib import Path
from typing import Protocol


class MeshGenerator(Protocol):
    name: str

    def generate(self, views: dict[str, Path], out: Path, gpu: int) -> Path:
        """Write a mesh file to `out` from reference views and return its path."""
        ...


GENERATORS: dict[str, MeshGenerator] = {}

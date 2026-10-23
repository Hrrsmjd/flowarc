"""Pass/fail mesh checks: geometry, match to reference images, symmetry."""

import trimesh


def geometry(mesh: trimesh.Trimesh, min_thickness: float, bodies: int = 1) -> dict:
    """Watertight, manifold, expected body count, no self-intersections, no thin parts."""
    raise NotImplementedError


def silhouette_iou(mesh: trimesh.Trimesh, views: dict, threshold: float = 0.85) -> dict:
    raise NotImplementedError


def symmetry(mesh: trimesh.Trimesh, axis: int = 1) -> dict:
    """Chamfer distance between the mesh and its mirror image, relative to body length."""
    raise NotImplementedError

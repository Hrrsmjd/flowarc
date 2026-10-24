"""Small repairs Argon can call: fill holes, drop fragments, remesh watertight, normalize."""

import numpy as np
import trimesh
from scipy import ndimage


def drop_fragments(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Keep the largest connected piece."""
    parts = mesh.split(only_watertight=False)
    return max(parts, key=lambda p: len(p.faces)) if len(parts) > 1 else mesh


def fill_holes(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    m = mesh.copy()
    trimesh.repair.fill_holes(m)
    trimesh.repair.fix_normals(m)
    return m


def voxel_remesh(mesh: trimesh.Trimesh, cells: int = 256) -> trimesh.Trimesh:
    """Watertight remesh: voxelize, fill the inside, marching cubes. Closes holes and cracks finer than a cell."""
    pitch = mesh.extents.max() / cells
    vox = mesh.voxelized(pitch)
    shell = np.pad(vox.matrix, 2)
    # thicken the shell by a cell first so diagonal leaks and small holes don't stop the fill
    solid = ndimage.binary_erosion(ndimage.binary_fill_holes(ndimage.binary_dilation(shell)))
    out = trimesh.voxel.VoxelGrid(solid).marching_cubes
    out.apply_translation([-2.0, -2.0, -2.0])
    out.apply_transform(vox.transform)
    trimesh.smoothing.filter_taubin(out, iterations=10)
    return drop_fragments(out)


def thicken(mesh: trimesh.Trimesh, by: float, cells: int = 384) -> trimesh.Trimesh:
    """Grow the surface outward by about `by` (same units as the mesh), so parts thinner than
    2 * by get at least that thick. Voxel based, like voxel_remesh."""
    pitch = mesh.extents.max() / cells
    r = max(1, int(np.ceil(by / pitch)))
    vox = mesh.voxelized(pitch)
    shell = np.pad(vox.matrix, r + 2)
    solid = ndimage.binary_fill_holes(ndimage.binary_dilation(shell))
    solid = ndimage.binary_dilation(solid, iterations=r - 1) if r > 1 else solid
    out = trimesh.voxel.VoxelGrid(solid).marching_cubes
    out.apply_translation([-(r + 2.0)] * 3)
    out.apply_transform(vox.transform)
    trimesh.smoothing.filter_taubin(out, iterations=10)
    return drop_fragments(out)


def normalize(
    mesh: trimesh.Trimesh, rotation: np.ndarray | None = None, ground: bool = False
) -> trimesh.Trimesh:
    """Rotate into flow axes, scale the longest side to 1, nose at x = 0, centred in y, and z centred or on z = 0."""
    m = mesh.copy()
    if rotation is not None:
        m.vertices = m.vertices @ np.asarray(rotation).T
    m.vertices /= m.extents.max()
    lo, hi = m.bounds
    m.vertices -= [lo[0], (lo[1] + hi[1]) / 2, lo[2] if ground else (lo[2] + hi[2]) / 2]
    return m

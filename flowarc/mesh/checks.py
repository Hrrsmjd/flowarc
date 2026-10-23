"""Pass/fail mesh checks: geometry, match to reference images, symmetry.

Meshes are in flow axes: x along the flow (nose at min x), y across, z up.
"""

import io
import itertools

import numpy as np
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

GRID = 128  # silhouettes are compared on a GRID x GRID square

# view -> (axis looked along, image horizontal axis, image vertical axis)
VIEW_AXES = {"front": (0, 1, 2), "side": (1, 0, 2), "top": (2, 0, 1)}


def geometry(
    mesh: trimesh.Trimesh, min_thickness: float, bodies: int = 1, n_rays: int = 2000
) -> dict:
    """Watertight, consistent winding, expected body count, and the share of the surface thinner than min_thickness."""
    n_bodies = len(mesh.split(only_watertight=False))
    pts, faces = trimesh.sample.sample_surface(mesh, n_rays, seed=0)
    normals = mesh.face_normals[faces]
    origins = pts - normals * 1e-4 * mesh.scale
    hits, rays, _ = mesh.ray.intersects_location(origins, -normals, multiple_hits=False)
    depth = np.full(n_rays, np.inf)
    depth[rays] = np.linalg.norm(hits - origins[rays], axis=1)
    thin = float((depth < min_thickness).mean())
    out = {
        "watertight": bool(mesh.is_watertight),
        "winding": bool(mesh.is_winding_consistent),
        "bodies": n_bodies,
        "thin_fraction": thin,
    }
    out["passed"] = out["watertight"] and out["winding"] and n_bodies == bodies and thin < 0.01
    return out


def _square(mask: np.ndarray) -> np.ndarray:
    """Crop a mask to its bounding box, pad to a square and resize to GRID x GRID."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return np.zeros((GRID, GRID), bool)
    m = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    s = max(m.shape)
    pad = np.zeros((s, s), bool)
    oy, ox = (s - m.shape[0]) // 2, (s - m.shape[1]) // 2
    pad[oy : oy + m.shape[0], ox : ox + m.shape[1]] = m
    return np.asarray(Image.fromarray(pad).resize((GRID, GRID), Image.NEAREST))


def image_mask(img: bytes, white: int = 235) -> np.ndarray:
    a = np.asarray(Image.open(io.BytesIO(img)).convert("L"))
    return _square(a < white)


def projection(mesh: trimesh.Trimesh, view: str) -> np.ndarray:
    look, _, v = VIEW_AXES[view]
    occ = mesh.voxelized(mesh.extents.max() / GRID).matrix
    sil = occ.any(axis=look)
    # sil axes are the two remaining mesh axes in order; put v on rows (top row = max), h on columns
    rest = [a for a in range(3) if a != look]
    if rest.index(v) == 1:
        sil = sil.T
    return _square(sil[::-1])


def iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU, allowing a left-right flip (which side a view is taken from)."""
    return max(float((a & m).sum() / max((a | m).sum(), 1)) for m in (b, b[:, ::-1]))


def silhouette_iou(mesh: trimesh.Trimesh, views: dict[str, bytes], threshold: float = 0.85) -> dict:
    per = {v: iou(projection(mesh, v), image_mask(views[v])) for v in VIEW_AXES if v in views}
    return {"iou": per, "min_iou": min(per.values()), "passed": min(per.values()) >= threshold}


def rotations() -> list[np.ndarray]:
    """The 24 proper rotations that map axes onto axes."""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            r = np.zeros((3, 3))
            r[range(3), perm] = signs
            if np.linalg.det(r) > 0:
                out.append(r)
    return out


def best_orientation(mesh: trimesh.Trimesh, views: dict[str, bytes]) -> tuple[np.ndarray, float]:
    """Axis-aligned rotation that best matches the reference silhouettes (front/back stays ambiguous)."""
    masks = {v: image_mask(views[v]) for v in VIEW_AXES if v in views}
    best = (np.eye(3), -1.0)
    for r in rotations():
        m = mesh.copy()
        m.vertices = m.vertices @ r.T
        score = np.mean([iou(projection(m, v), masks[v]) for v in masks])
        if score > best[1]:
            best = (r, float(score))
    return best


def symmetry(mesh: trimesh.Trimesh, axis: int = 1, n: int = 5000) -> dict:
    """Chamfer distance between the mesh and its mirror image, relative to body length."""
    pts = trimesh.sample.sample_surface(mesh, n, seed=0)[0]
    mirror = pts.copy()
    c = (pts[:, axis].max() + pts[:, axis].min()) / 2
    mirror[:, axis] = 2 * c - mirror[:, axis]
    d1 = cKDTree(mirror).query(pts)[0].mean()
    d2 = cKDTree(pts).query(mirror)[0].mean()
    chamfer = float((d1 + d2) / 2 / mesh.extents.max())
    return {"chamfer": chamfer, "passed": chamfer < 0.01}

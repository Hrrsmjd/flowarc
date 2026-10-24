"""Pass/fail mesh checks: geometry, match to reference images, symmetry.

Meshes are in flow axes: x along the flow (nose at min x), y across, z up.
"""

import io

import numpy as np
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

GRID = 128  # silhouettes are compared on a GRID x GRID square

# view -> (axis looked along, image horizontal axis, image vertical axis)
# (look axis, image columns, image rows); top views are drawn nose up
VIEW_AXES = {"front": (0, 1, 2), "side": (1, 0, 2), "top": (2, 1, 0)}


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
        "thin_ok": thin < 0.01,
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


def iou(a: np.ndarray, b: np.ndarray, flips: bool = True) -> float:
    """IoU, allowing left-right and up-down flips (which side a view is taken from)."""
    cands = (b, b[:, ::-1], b[::-1], b[::-1, ::-1]) if flips else (b,)
    return max(float((a & m).sum() / max((a | m).sum(), 1)) for m in cands)


def silhouette_iou(mesh: trimesh.Trimesh, views: dict[str, bytes], threshold: float = 0.2) -> dict:
    """Low bar that only catches a wrong object or orientation. The views don't match each other
    exactly, and thin views (a flat body seen from the front) score low, so Flash is the main check."""
    per = {v: iou(projection(mesh, v), image_mask(views[v])) for v in VIEW_AXES if v in views}
    return {"iou": per, "min_iou": min(per.values()), "passed": min(per.values()) >= threshold}


Y_UP = np.array(
    [[0, 0, 1], [1, 0, 0], [0, 1, 0]], float
)  # Hunyuan output (y up, z long) to flow axes


def yaw(quarter_turns: int) -> np.ndarray:
    c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][quarter_turns % 4]
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def best_orientation(
    mesh: trimesh.Trimesh, views: dict[str, bytes], up: np.ndarray = Y_UP
) -> tuple[np.ndarray, float]:
    """Keep the generator's up axis and try the 4 headings. Silhouettes can't tell nose from tail,
    so the unflipped side view (nose on the left) breaks ties; the mesh review checks the result."""
    masks = {v: image_mask(views[v]) for v in VIEW_AXES if v in views}
    cands = []
    for k in range(4):
        r = yaw(k) @ up
        m = mesh.copy()
        m.vertices = m.vertices @ r.T
        score = float(np.mean([iou(projection(m, v), masks[v]) for v in masks]))
        side = iou(projection(m, "side"), masks["side"], flips=False) if "side" in masks else 0
        cands.append((round(score, 2), side, k, r, score))
    *_, r, score = max(cands, key=lambda c: c[:2])
    return r, score


def _chamfer(a: np.ndarray, b: np.ndarray) -> float:
    return (cKDTree(b).query(a)[0].mean() + cKDTree(a).query(b)[0].mean()) / 2


def symmetry(mesh: trimesh.Trimesh, axis: int = 1, n: int = 5000) -> dict:
    """Chamfer distance between the mesh and its mirror image, relative to body length.
    The distance between two random samples of the same surface is taken off, so large
    flat bodies (sparser samples) aren't marked asymmetric."""
    pts = trimesh.sample.sample_surface(mesh, n, seed=0)[0]
    other = trimesh.sample.sample_surface(mesh, n, seed=1)[0]
    mirror = other.copy()
    c = (pts[:, axis].max() + pts[:, axis].min()) / 2
    mirror[:, axis] = 2 * c - mirror[:, axis]
    floor = _chamfer(pts, other)
    chamfer = float(max(_chamfer(pts, mirror) - floor, 0) / mesh.extents.max())
    return {"chamfer": chamfer, "passed": chamfer < 0.01}

"""Stand-in views and meshes for the mock batch: simple procedural bodies, flat-shaded renders.

Only for the dashboard's mock replay; real samples get Nano Banana views and Hunyuan3D meshes.
The cow's first mesh is missing its front-left leg, so the demo's failed mesh check shows.
"""

import io
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from trimesh.creation import box, capsule, cylinder

from flowarc.mesh import primitives

PX = 512


def _at(m: trimesh.Trimesh, xyz) -> trimesh.Trimesh:
    m.apply_translation(xyz)
    return m


def cow(legs: int = 4) -> trimesh.Trimesh:
    """Flow axes: x along the flow (head at min x), y across, z up."""
    parts = [
        _at(box(extents=[1.0, 0.42, 0.42]), [0.55, 0, 0.62]),
        _at(box(extents=[0.26, 0.24, 0.26]), [0.0, 0, 0.78]),
        _at(cylinder(radius=0.035, height=0.5, sections=12), [0.86, 0, 0.62 + 0.0]),
    ]
    parts[2].apply_transform(
        trimesh.transformations.rotation_matrix(1.2, [0, 1, 0], [0.86, 0, 0.62])
    )
    for side in (-1, 1):  # horns
        h = capsule(height=0.16, radius=0.03, count=[8, 8])
        h.apply_transform(trimesh.transformations.rotation_matrix(side * 1.2, [1, 0, 0]))
        parts.append(_at(h, [-0.02, side * 0.17, 0.92]))
    spots = [(0.2, -0.13), (0.2, 0.13), (0.9, -0.13), (0.9, 0.13)][4 - legs :]
    for x, y in spots:
        parts.append(_at(cylinder(radius=0.06, height=0.44, sections=12), [x, y, 0.22]))
    return trimesh.util.concatenate(parts)


def biplane() -> trimesh.Trimesh:
    return primitives.aircraft()


def knot() -> trimesh.Trimesh:
    t = np.linspace(0, 2 * math.pi, 240, endpoint=False)
    path = np.stack(
        [np.sin(t) + 2 * np.sin(2 * t), np.cos(t) - 2 * np.cos(2 * t), -np.sin(3 * t)], axis=1
    )
    ring = []
    for i in range(len(t)):  # a tube: one circle of vertices per path point
        p, q = path[i], path[(i + 1) % len(t)]
        d = (q - p) / np.linalg.norm(q - p)
        a = np.cross(d, [0, 0, 1.0])
        a /= np.linalg.norm(a)
        b = np.cross(d, a)
        ring.append(
            [
                p + 0.45 * (math.cos(k) * a + math.sin(k) * b)
                for k in np.linspace(0, 2 * math.pi, 16, endpoint=False)
            ]
        )
    v = np.array(ring).reshape(-1, 3)
    n, s = len(t), 16
    f = []
    for i in range(n):
        for k in range(s):
            a, b = i * s + k, ((i + 1) % n) * s + k
            c, e = ((i + 1) % n) * s + (k + 1) % s, i * s + (k + 1) % s
            f += [[a, b, c], [a, c, e]]
    return trimesh.Trimesh(v, f)


def balloon() -> trimesh.Trimesh:
    env = trimesh.creation.icosphere(subdivisions=3, radius=0.5)
    env.vertices[:, 2] *= 1.15
    parts = [_at(env, [0, 0, 0.9]), _at(box(extents=[0.18, 0.18, 0.14]), [0, 0, 0.07])]
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        c = cylinder(radius=0.01, height=0.38, sections=6)
        parts.append(_at(c, [dx * 0.08, dy * 0.08, 0.32]))
    return trimesh.util.concatenate(parts)


# view -> (camera direction it looks along, image right, image up), flow axes
VIEWS = {
    "three-quarter": ((0.6, -0.65, -0.45), None, (0, 0, 1)),
    "front": ((1, 0, 0), None, (0, 0, 1)),
    "side": ((0, -1, 0), None, (0, 0, 1)),
    "top": ((0, 0, -1), None, (0, 1, 0)),
}


def render(mesh: trimesh.Trimesh, view: str, px: int = PX) -> bytes:
    """Flat-shaded orthographic render, grey body on white, painter's algorithm."""
    look, _, up = VIEWS[view]
    look = np.asarray(look, float) / np.linalg.norm(look)
    right = np.cross(look, up)
    right /= np.linalg.norm(right)
    upv = np.cross(right, look)
    v = mesh.vertices - mesh.bounds.mean(axis=0)
    x, y, depth = v @ right, v @ upv, v @ look
    scale = 0.8 * px / max(np.ptp(x), np.ptp(y))
    sx, sy = px / 2 + x * scale, px / 2 - y * scale
    light = -look + 0.5 * upv + 0.3 * right
    light /= np.linalg.norm(light)
    img = Image.new("RGB", (px, px), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for fi in np.argsort(-depth[mesh.faces].mean(axis=1)):  # far to near
        n = mesh.face_normals[fi]
        if n @ look > 0:
            continue  # facing away
        g = int(70 + 150 * max(0.0, float(n @ light)))
        draw.polygon([(sx[i], sy[i]) for i in mesh.faces[fi]], fill=(g, g, g + 4))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


SHAPES = {
    "Highland cow": cow,
    "1930s biplane": biplane,
    "Trefoil knot torus": knot,
    "Hot-air balloon": balloon,
}


def write(media: list[dict], names: dict[str, str], out: Path) -> None:
    """Write the files listed in the mock batch's `media` (sample id -> concept name in `names`)."""
    for m in media:
        make = SHAPES[names[m["sample"]]]
        broken = make is cow and m["kind"] == "mesh" and m["attempt"] == 1
        mesh = cow(legs=3) if broken else make()
        path = out / m["url"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if m["kind"] == "view":
            path.write_bytes(render(mesh, m["name"]))
        else:
            path.write_bytes(mesh.export(file_type="glb"))

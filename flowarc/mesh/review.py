"""Mesh review: grey renders of the mesh, a few computed checks, and Flash judging the renders.

The reference views don't match each other exactly, so they only tell Flash what the object should be.
"""

import io

import numpy as np
import trimesh
from PIL import Image

from flowarc import gemini
from flowarc.mesh import checks

CAMERAS = {  # direction the camera looks along, screen up
    "three-quarter": ([1, -1, -0.8], [0, 0, 1]),
    "front": ([1, 0, 0], [0, 0, 1]),
    "side": ([0, -1, 0], [0, 0, 1]),
    "top": ([0, 0, -1], [-1, 0, 0]),
    "back": ([-1, 0, 0], [0, 0, 1]),
    "bottom": ([0, 0, 1], [-1, 0, 0]),
}


def render(mesh: trimesh.Trimesh, view: str, px: int = 320, points: int = 700_000) -> Image.Image:
    """Orthographic grey render by splatting dense surface samples into a depth buffer."""
    d, up = (np.asarray(v, float) for v in CAMERAS[view])
    d /= np.linalg.norm(d)
    right = np.cross(d, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    pts, faces = trimesh.sample.sample_surface(mesh, points, seed=0)
    u, v, depth = pts @ right, pts @ up, pts @ d
    scale = 0.9 * px / max(np.ptp(u), np.ptp(v))
    rows = np.clip(((v.max() + v.min()) / 2 - v) * scale + px / 2, 0, px - 1).astype(int)
    cols = np.clip((u - (u.max() + u.min()) / 2) * scale + px / 2, 0, px - 1).astype(int)
    light = -d + 0.4 * up - 0.3 * right
    shade = 0.25 + 0.75 * np.clip(mesh.face_normals[faces] @ (light / np.linalg.norm(light)), 0, 1)
    img = np.full((px, px), 255.0)
    order = np.argsort(-depth)  # nearest written last
    img[rows[order], cols[order]] = 40 + 190 * shade[order]
    return Image.fromarray(img.astype(np.uint8)).convert("RGB")


def holes(mesh: trimesh.Trimesh) -> int:
    """Through-holes (genus). Image-to-3D meshes often have small extra tunnels, so this is a hint."""
    bodies = len(mesh.split(only_watertight=False))
    return round((2 * bodies - mesh.euler_number) / 2)


def holes_match(found: int, expected: int) -> bool:
    """Exact for a few holes; a quarter off is fine for many (struts, lattices)."""
    return abs(found - expected) <= round(0.25 * expected)


def proportions(mesh: trimesh.Trimesh, views: dict[str, bytes]) -> dict[str, float]:
    """Mesh aspect ratio over the reference silhouette's, per view (1 = same)."""
    out = {}
    for v, (look, h, w) in checks.VIEW_AXES.items():
        if v in views:
            r, c = np.nonzero(checks.image_mask(views[v]))
            image = (np.ptp(c) + 1) / (np.ptp(r) + 1)
            out[v] = float(mesh.extents[h] / mesh.extents[w] / image)
    return out


ITEMS = [
    "same_object",
    "part_counts",
    "no_extra_structures",
    "no_fused_or_missing_parts",
    "no_wrong_holes",
    "clean_surface",
    "upright_facing_flow",
]
SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check": {"type": "string", "enum": ITEMS},
                    "passed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["check", "passed", "reason"],
            },
        },
        "passed": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["checks", "passed", "summary"],
}
PROMPT = """You are checking a 3D mesh made by an image-to-3D model, before it goes into a fluid simulation.
Object: {description}
Its front: {facing}.
First come reference images of the object. They were generated separately and may not match each other exactly, so use them only to know what the object should be.
Then come grey renders of the mesh from fixed cameras (flow comes from the front, along the length).
Judge the mesh itself. For each check, say if it passes and why:
- same_object: it is clearly the object described and shown.
- part_counts: main parts are present with the right number of each (e.g. 2 wings, 1 tail).
- no_extra_structures: no blobs, spikes, loose bits, base plate or ground slab, leftover background.
- no_fused_or_missing_parts: parts that should be separate are not fused or webbed together; nothing major missing.
- no_wrong_holes: no holes or dents that should not exist; real holes are open.
- clean_surface: no lumpy noise, stair steps, or collapsed thin parts.
- upright_facing_flow: upright, with its front ({facing}) toward the front camera, i.e. pointing into the flow.
Pass overall only if every check passes. Be strict but do not fail for small style differences from the references."""


def flash_review(concept: dict, views: dict[str, bytes], renders: dict[str, Image.Image]) -> dict:
    parts = [
        {
            "type": "text",
            "text": PROMPT.format(
                description=concept["description"],
                facing=concept.get("facing") or "the end that would lead in a flow",
            ),
        }
    ]
    for v, img in views.items():
        parts += [{"type": "text", "text": f"reference {v}:"}, gemini.image_part(img, "image/jpeg")]
    for v, im in renders.items():
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        parts += [
            {"type": "text", "text": f"mesh render {v}:"},
            gemini.image_part(buf.getvalue(), "image/jpeg"),
        ]
    out = gemini.argon(parts, schema=SCHEMA)
    out["failed"] = [c["check"] for c in out["checks"] if not c["passed"]]
    return out


def review(mesh: trimesh.Trimesh, concept: dict, views: dict[str, bytes]) -> dict:
    """Computed checks plus the Flash review. `concept["holes"]`, if set, is the expected hole count.
    The hole count is recorded but Flash decides (no_wrong_holes): small spurious tunnels are common
    and tell us little."""
    out = {"holes": holes(mesh), "proportions": proportions(mesh, views)}
    if "holes" in concept:
        out["holes_ok"] = holes_match(out["holes"], concept["holes"])
    out["flash"] = flash_review(concept, views, {v: render(mesh, v) for v in CAMERAS})
    out["passed"] = out["flash"]["passed"]
    return out

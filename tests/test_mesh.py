import io

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from flowarc.mesh import checks, repair


def _img(draw) -> bytes:
    im = Image.new("RGB", (256, 256), "white")
    draw(ImageDraw.Draw(im))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def test_box_matches_its_silhouettes_and_orientation():
    box = trimesh.creation.box(extents=[2.0, 1.0, 0.5])
    views = {
        "front": _img(lambda d: d.rectangle([28, 78, 228, 178], fill="grey")),  # y by z = 2:1
        "side": _img(lambda d: d.rectangle([28, 103, 228, 153], fill="grey")),  # x by z = 4:1
        "top": _img(lambda d: d.rectangle([28, 78, 228, 178], fill="grey")),  # x by y = 2:1
    }
    assert checks.silhouette_iou(box, views)["passed"]
    turned = box.copy()
    turned.vertices = turned.vertices[:, [2, 0, 1]]  # lengths now along z, x, y
    r, score = checks.best_orientation(turned, views)
    assert score > 0.9
    assert np.allclose(repair.normalize(turned, r).extents, [1.0, 0.5, 0.25])


def test_geometry_and_symmetry():
    box = trimesh.creation.box(extents=[1.0, 0.4, 0.3])
    g = checks.geometry(box, min_thickness=0.05)
    assert g["passed"] and g["thin_fraction"] == 0
    assert not checks.geometry(box, min_thickness=0.35)["passed"]
    assert checks.symmetry(box)["passed"]
    lump = trimesh.util.concatenate(
        [box, trimesh.creation.box(extents=[0.2, 0.2, 0.2]).apply_translation([0, 0.3, 0])]
    )
    assert not checks.symmetry(lump)["passed"]


def test_voxel_remesh_closes_a_hole():
    m = trimesh.creation.icosphere(subdivisions=3)
    m.update_faces(np.arange(len(m.faces)) != 0)
    assert not m.is_watertight
    fixed = repair.voxel_remesh(m, cells=64)
    assert fixed.is_watertight and abs(fixed.volume - 4 / 3 * np.pi) < 0.3

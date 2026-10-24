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
        "top": _img(
            lambda d: d.rectangle([78, 28, 178, 228], fill="grey")
        ),  # nose up: y by x = 1:2
    }
    assert checks.silhouette_iou(box, views)["passed"]
    turned = box.copy()
    turned.vertices = turned.vertices[:, [1, 2, 0]]  # generator frame: y up, length along z
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


def test_review_computed_checks():
    from flowarc.mesh import review

    torus = trimesh.creation.torus(major_radius=1.0, minor_radius=0.3)
    assert review.holes(torus) == 1
    assert review.holes(trimesh.creation.icosphere()) == 0
    assert (
        review.holes_match(9, 10) and not review.holes_match(1, 0) and not review.holes_match(22, 2)
    )
    box = trimesh.creation.box(extents=[2.0, 1.0, 0.5])
    front = _img(lambda d: d.rectangle([28, 78, 228, 178], fill="grey"))  # y by z = 2:1
    assert abs(review.proportions(box, {"front": front})["front"] - 1) < 0.05
    img = np.asarray(review.render(box, "three-quarter", px=64, points=20_000))
    assert (img < 250).any() and (img == 255).any()


def test_thicken_fixes_a_thin_plate():
    plate = trimesh.creation.box(extents=[1.0, 0.5, 0.006])
    assert not checks.geometry(plate, min_thickness=0.01)["thin_ok"]
    thick = repair.normalize(repair.thicken(plate, 0.005))
    g = checks.geometry(thick, min_thickness=0.01)
    assert g["thin_ok"] and g["watertight"] and g["bodies"] == 1


def test_heading_lines_up_a_turned_body():
    box = trimesh.creation.box(extents=[1.0, 0.3, 0.2])
    box.apply_transform(trimesh.transformations.rotation_matrix(np.radians(40), [0, 0, 1]))
    pts = box.vertices @ checks.heading(box.vertices).T
    ext = pts.max(0) - pts.min(0)
    assert np.allclose(ext, [1.0, 0.3, 0.2], atol=1e-6)
    cube = trimesh.creation.box(extents=[1.0, 1.0, 0.2])
    assert np.allclose(checks.heading(cube.vertices), np.eye(3))


def test_off_axis_mesh_is_lined_up_when_flash_says_the_pose_is_wrong(tmp_path, monkeypatch):
    from flowarc.mesh import review, stage

    box = trimesh.creation.box(extents=[1.0, 0.3, 0.4])  # generator output is y-up
    box.apply_transform(trimesh.transformations.rotation_matrix(np.radians(35), [0, 1, 0]))
    raw = tmp_path / "raw.stl"
    box.export(raw)
    blank = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(blank, "JPEG")
    views = {}
    for v in ("front", "side", "top", "three-quarter"):
        views[v] = tmp_path / f"{v}.jpg"
        views[v].write_bytes(blank.getvalue())

    def fake_review(m, concept, imgs):
        xy = m.vertices[:, :2] - m.vertices[:, :2].mean(0)
        ang = np.degrees(np.arctan2(*np.linalg.eigh(xy.T @ xy)[1][::-1, 1])) % 180
        failed = [] if min(ang, 180 - ang) < 2 else ["upright_facing_flow"]
        return {"passed": not failed, "flash": {"failed": failed, "checks": [], "summary": ""}}

    monkeypatch.setattr(review, "review", fake_review)
    monkeypatch.setattr(checks, "best_orientation", lambda m, imgs: (checks.Y_UP, 0.0))
    rep = stage.make_mesh(views, tmp_path / "out", 0, {"name": "box"}, raw=raw, min_thickness=0.01)
    assert rep["review"]["passed"] and rep["review"]["turn"]["lined_up"]

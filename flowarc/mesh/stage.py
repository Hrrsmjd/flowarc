"""Stage 3: reference views -> checked, flow-aligned mesh."""

from pathlib import Path

import numpy as np
import trimesh

from flowarc.mesh import checks, repair, review
from flowarc.mesh.generators import Hunyuan21


def make_mesh(
    views: dict[str, Path],
    out: Path,
    gpu: int = 0,
    concept: dict | None = None,
    raw: Path | None = None,
    generator=None,
    seed: int = 0,
    min_thickness: float = 0.01,
) -> dict:
    """Writes out/mesh.stl and returns the report. `concept` turns on the Flash review."""
    out.mkdir(parents=True, exist_ok=True)
    raw = raw or (generator or Hunyuan21()).generate(views, out, gpu, seed=seed)
    mesh = trimesh.load(raw, force="mesh")
    report = {
        "raw": {
            "faces": len(mesh.faces),
            "watertight": mesh.is_watertight,
            "bodies": len(mesh.split(only_watertight=False)),
        }
    }
    mesh = repair.drop_fragments(mesh)
    report["remeshed"] = not mesh.is_watertight
    if report["remeshed"]:  # remeshing leaves stair steps, so only when needed
        mesh = repair.voxel_remesh(mesh, cells=384)
    imgs = {v: Path(f).read_bytes() for v, f in views.items()}
    ground = bool(concept and concept.get("ground"))
    rot, score = checks.best_orientation(mesh, imgs)
    oriented = repair.normalize(mesh, rot, ground=ground)
    if concept:
        rev = review.review(oriented, concept, imgs)
        if rev["flash"]["failed"] == ["upright_facing_flow"]:  # facing the wrong way: turn it
            rev["turns"] = []
            for k in (2, 1, 3):  # nose and tail swapped is the usual case
                r = checks.yaw(k) @ rot
                o = repair.normalize(mesh, r, ground=ground)
                rv = review.review(o, concept, imgs)
                rev["turns"].append({"deg": 90 * k, "failed": rv["flash"]["failed"]})
                if "upright_facing_flow" not in rv["flash"]["failed"]:
                    rot, oriented, rev = r, o, rv | {"turned_deg": 90 * k}
                    break
        report["review"] = rev
    mesh = oriented
    report |= {
        "orientation_score": score,
        "rotation": np.asarray(rot).tolist(),
        "geometry": checks.geometry(mesh, min_thickness),
        "silhouette": checks.silhouette_iou(mesh, imgs),
        "symmetry": checks.symmetry(mesh),
    }
    report["passed"] = (
        report["geometry"]["passed"]
        and report["silhouette"]["passed"]
        and report.get("review", {}).get("passed", True)
        and (report["symmetry"]["passed"] or not (concept or {}).get("symmetric"))
    )
    mesh.export(out / "mesh.stl")
    if concept:  # the grey views Flash saw, for the dashboard
        (out / "renders").mkdir(exist_ok=True)
        for v in review.CAMERAS:
            review.render(mesh, v).convert("RGB").save(out / "renders" / f"{v}.jpg", quality=90)
    return report

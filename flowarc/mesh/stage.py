"""Stage 3: reference views -> checked, flow-aligned mesh."""

from pathlib import Path

import numpy as np
import trimesh

from flowarc import config
from flowarc.mesh import checks, repair, review
from flowarc.mesh.generators import Hunyuan21, Hunyuan21Modal


def make_mesh(
    views: dict[str, Path],
    out: Path,
    gpu: int = 0,
    concept: dict | None = None,
    raw: Path | None = None,
    generator=None,
    seed: int = 0,
    min_thickness: float = 0.01,
    remesh: bool = False,
) -> dict:
    """Writes out/mesh.stl and returns the report. `concept` turns on the Flash review.

    `remesh` voxel-remeshes even a watertight mesh (Argon's repair_mesh, with `raw` the last one).
    """
    out.mkdir(parents=True, exist_ok=True)
    raw = raw or (
        generator or (Hunyuan21Modal() if config.MESH_HOST == "modal" else Hunyuan21())
    ).generate(views, out, gpu, seed=seed)
    mesh = trimesh.load(raw, force="mesh")
    report = {
        "raw": {
            "faces": len(mesh.faces),
            "watertight": mesh.is_watertight,
            "bodies": len(mesh.split(only_watertight=False)),
        }
    }
    mesh = repair.drop_fragments(mesh)
    report["remeshed"] = remesh or not mesh.is_watertight
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
            lined = checks.heading(mesh.vertices @ rot.T) @ rot  # long axis along the flow
            tries = [(False, k) for k in (2, 1, 3)]  # nose and tail swapped is the usual case
            if not np.allclose(lined, rot):  # turned off-axis, which quarter turns can't fix
                tries += [(True, k) for k in (0, 2, 1, 3)]
            for lined_up, k in tries:
                r = checks.yaw(k) @ (lined if lined_up else rot)
                o = repair.normalize(mesh, r, ground=ground)
                rv = review.review(o, concept, imgs)
                turn = {"deg": 90 * k, "lined_up": lined_up}
                rev["turns"].append(turn | {"failed": rv["flash"]["failed"]})
                if "upright_facing_flow" not in rv["flash"]["failed"]:
                    rot, oriented, rev = r, o, rv | {"turned_deg": 90 * k, "turn": turn}
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
    geo = report["geometry"]
    report["base_ok"] = (
        geo["watertight"]
        and geo["winding"]
        and geo["bodies"] == 1
        and report["silhouette"]["passed"]
        and report.get("review", {}).get("passed", True)
    )
    # failures Argon may judge (the shape may not be meant to be symmetric; thin parts may be fine)
    report["judgement"] = [
        n
        for n, bad in (
            ("symmetry", not report["symmetry"]["passed"] and (concept or {}).get("symmetric")),
            ("thin", not geo["thin_ok"]),
        )
        if bad
    ]
    report["passed"] = report["base_ok"] and not report["judgement"]
    mesh.export(out / "mesh.stl")
    if concept:  # the grey views Flash saw, for the dashboard
        save_renders(mesh, out)
    return report


def save_renders(mesh: trimesh.Trimesh, out: Path) -> None:
    (out / "renders").mkdir(exist_ok=True)
    for v in review.CAMERAS:
        review.render(mesh, v).convert("RGB").save(out / "renders" / f"{v}.jpg", quality=90)


def thicken(out: Path, min_thickness: float, ground: bool = False) -> dict:
    """Thicken out/mesh.stl in place so its thin parts reach min_thickness. Returns the new geometry check."""
    mesh = trimesh.load(out / "mesh.stl", force="mesh")
    mesh = repair.normalize(repair.thicken(mesh, min_thickness / 2), ground=ground)
    mesh.export(out / "mesh.stl")
    save_renders(mesh, out)
    return checks.geometry(mesh, min_thickness)

"""Reference views -> checked, flow-aligned mesh.
Usage: python scripts/mesh_one.py VIEWS_DIR OUT_DIR [--gpu 0] [--ground] [--raw MESH] [--concept concept.json]"""

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh

from flowarc.images import VIEWS
from flowarc.mesh import checks, repair, review
from flowarc.mesh.generators import Hunyuan21


def main():
    p = argparse.ArgumentParser()
    p.add_argument("views", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--ground", action="store_true")
    p.add_argument("--raw", type=Path, help="skip generation and use this mesh")
    p.add_argument("--concept", type=Path, help="concept JSON; runs the Flash mesh review")
    p.add_argument("--min-thickness", type=float, default=0.01, help="in body lengths")
    a = p.parse_args()
    paths = {v: a.views / f"{v}.jpg" for v in VIEWS}
    raw = a.raw or Hunyuan21().generate(paths, a.out, a.gpu)
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
    imgs = {v: f.read_bytes() for v, f in paths.items()}
    rot, score = checks.best_orientation(mesh, imgs)
    oriented = repair.normalize(mesh, rot, ground=a.ground)
    if a.concept:
        concept = json.loads(a.concept.read_text())
        rev = review.review(oriented, concept, imgs)
        if rev["flash"]["failed"] == ["upright_facing_flow"]:  # nose and tail swapped
            rot = checks.yaw(2) @ rot
            oriented = repair.normalize(mesh, rot, ground=a.ground)
            rev = review.review(oriented, concept, imgs) | {"turned": True}
        report["review"] = rev
    mesh = oriented
    report |= {
        "orientation_score": score,
        "rotation": np.asarray(rot).tolist(),
        "geometry": checks.geometry(mesh, a.min_thickness),
        "silhouette": checks.silhouette_iou(mesh, imgs),
        "symmetry": checks.symmetry(mesh),
    }
    mesh.export(a.out / "mesh.stl")
    (a.out / "mesh_report.json").write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, default=float))


if __name__ == "__main__":
    main()

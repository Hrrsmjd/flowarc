"""Reference views -> checked, flow-aligned mesh. Usage: python scripts/mesh_one.py VIEWS_DIR OUT_DIR [--gpu 0] [--ground] [--raw MESH]"""

import argparse
import json
from pathlib import Path

import trimesh

from flowarc.images import VIEWS
from flowarc.mesh import checks, repair
from flowarc.mesh.generators import Hunyuan21


def main():
    p = argparse.ArgumentParser()
    p.add_argument("views", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--ground", action="store_true")
    p.add_argument("--raw", type=Path, help="skip generation and use this mesh")
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
    mesh = repair.voxel_remesh(repair.drop_fragments(mesh))
    imgs = {v: f.read_bytes() for v, f in paths.items()}
    rot, score = checks.best_orientation(mesh, imgs)
    mesh = repair.normalize(mesh, rot, ground=a.ground)
    report |= {
        "orientation_score": score,
        "geometry": checks.geometry(mesh, a.min_thickness),
        "silhouette": checks.silhouette_iou(mesh, imgs),
        "symmetry": checks.symmetry(mesh),
    }
    mesh.export(a.out / "mesh.stl")
    (a.out / "mesh_report.json").write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, default=float))


if __name__ == "__main__":
    main()

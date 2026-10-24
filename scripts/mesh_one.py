"""Reference views -> checked, flow-aligned mesh.
Usage: python scripts/mesh_one.py VIEWS_DIR OUT_DIR [--gpu 0] [--raw MESH] [--concept concept.json]"""

import argparse
import json
from pathlib import Path

from flowarc.images import VIEWS
from flowarc.mesh.stage import make_mesh


def main():
    p = argparse.ArgumentParser()
    p.add_argument("views", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--raw", type=Path, help="skip generation and use this mesh")
    p.add_argument("--concept", type=Path, help="concept JSON; runs the Flash mesh review")
    p.add_argument("--min-thickness", type=float, default=0.01, help="in body lengths")
    a = p.parse_args()
    concept = json.loads(a.concept.read_text()) if a.concept else None
    views = {v: a.views / f"{v}.jpg" for v in VIEWS}
    report = make_mesh(
        views, a.out, a.gpu, concept, a.raw, seed=a.seed, min_thickness=a.min_thickness
    )
    (a.out / "mesh_report.json").write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, default=float))


if __name__ == "__main__":
    main()

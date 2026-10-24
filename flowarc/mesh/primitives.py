"""Simple procedural test bodies, used for solver checks before the image-to-3D stage exists."""

import trimesh
from trimesh.creation import box, capsule, cone
from trimesh.transformations import rotation_matrix


def aircraft() -> trimesh.Trimesh:
    """Fighter-like body: fuselage, nose cone, swept wings, twin fins. Length 1 along +x (nose at x=0)."""
    fuselage = capsule(height=0.62, radius=0.055, count=[24, 24])
    fuselage.apply_transform(rotation_matrix(1.5708, [0, 1, 0]))
    fuselage.apply_translation([0.55, 0, 0])
    nose = cone(radius=0.055, height=0.22, sections=24)
    nose.apply_transform(rotation_matrix(-1.5708, [0, 1, 0]))
    nose.apply_translation([0.2, 0, 0])
    parts = [fuselage, nose]
    for side in (-1, 1):
        wing = box(extents=[0.28, 0.32, 0.05])
        wing.apply_transform(rotation_matrix(side * 0.6, [0, 0, 1]))
        wing.apply_translation([0.62, side * 0.17, -0.01])
        fin = box(extents=[0.14, 0.05, 0.15])
        fin.apply_transform(rotation_matrix(side * 0.35, [1, 0, 0]))
        fin.apply_translation([0.9, side * 0.06, 0.08])
        tail = box(extents=[0.12, 0.14, 0.05])
        tail.apply_translation([0.93, side * 0.1, 0.0])
        parts += [wing, fin, tail]
    m = trimesh.boolean.union(parts, engine="manifold")
    lo, hi = m.bounds
    m.apply_translation(-lo)
    m.apply_scale(1.0 / (hi - lo)[0])
    m.apply_translation([0, -m.bounds[:, 1].mean(), -m.bounds[:, 2].mean()])
    return m


def ahmed(slant_deg: float = 25.0) -> trimesh.Trimesh:
    """Ahmed body (Ahmed et al. 1984) in body lengths, on four stilts that touch z = 0."""
    import numpy as np
    from manifold3d import CrossSection, Manifold

    W, H, r, slant, gap = 389 / 1044, 288 / 1044, 100 / 1044, 222 / 1044, 50 / 1044

    def rounded_front(
        h: float,
    ) -> CrossSection:  # [0,1] x [0,h], front corners rounded with radius r
        c = CrossSection.circle(r, 64)
        return (
            CrossSection.square((1 - r, h)).translate((r, 0))
            + CrossSection.square((1, h - 2 * r)).translate((0, r))
            + c.translate((r, r))
            + c.translate((r, h - r))
        )

    drop = slant * np.tan(np.radians(slant_deg))
    cut = CrossSection([[(1 - slant, H), (1, H - drop), (1.01, H - drop), (1.01, H + 0.01)]])
    side = (
        (rounded_front(H) - cut).extrude(W).rotate((90, 0, 0)).translate((0, W / 2, gap))
    )  # x-z profile
    plan = rounded_front(W).extrude(H).translate((0, -W / 2, gap))  # x-y profile
    m = side ^ plan
    for x in (0.2, 0.67):
        for y in (-0.16, 0.16):
            m += Manifold.cylinder(gap + 0.02, 0.02, -1, 24).translate((x, y, 0))
    mesh = m.to_mesh()
    return trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts)

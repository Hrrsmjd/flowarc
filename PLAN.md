# FlowArc — build plan

Deadline: **Sunday 25 Oct, 12:00 midday.** Owners: **O** = Ose (agent/platform + demo), **H** = Harris (physics/solver).

The one rule: **get ONE object through the whole chain tonight, then widen.** Keep `main` runnable; pull before you push.

**Pipeline (primary):** Argon generates mesh (code) → repair/validate → voxelise → LBM solve → store → target gaps → repeat.
**Stretch (Sat, for visual variety):** nano banana (image) → Hunyuan3D (mesh) as an alternative front end.

---

## 0. Lock scope (do this first, ~10 min)
- [ ] Objects: **Argon generates meshes via code** (procedural/parametric — cars, wings, ducts), CFD-ready by construction. Narrow class first — **O + H**
- [ ] Solver: **voxelise the mesh + lattice-Boltzmann / immersed boundary** (robust, fast; NOT body-fitted, NOT RANS/LES) — **H confirm**
- [ ] Repair/validate: trimesh — watertight / manifold / normals; keep one red→green case — **H**
- [ ] Gates: mesh valid + LBM residual < tol = "converged" — **H set numbers**
- [ ] Gap targeting: embed shape/params, vector-search Atlas, generate where coverage thin — **O**
- [ ] Interface contract: a `sample` = {params} → {mesh, voxel grid, flow field, residual, valid flag} — **O + H**

## 1. Tonight (Fri) — de-risk the chain. Nothing else matters.
- [ ] **O:** repo up, `pyproject.toml`, `.env` wired
- [ ] **O:** Argon generates one mesh via code
- [ ] **H:** voxelise + LBM solve on one object → flow field + residual
- [ ] **H:** define "valid mesh" and "converged solve"
- [ ] **O:** one full document written to MongoDB Atlas
- [ ] **GOAL:** `pipeline.smoke` runs generate → repair → voxelise → solve → store for ONE object ✅
- [ ] (stretch, only if above done) spike nano banana → Hunyuan3D hosting

## 2. Saturday AM — the loop
- [ ] **H:** solver robust across a range of generated objects; convergence reliable
- [ ] **O:** full loop as one autonomous run (generate → repair → voxelise → solve → store → repeat, `background=True`)

## 3. Saturday — split: Harris scales the science, Ose builds the demo
**H (science):**
- [ ] Flash subagents for parallel generation/eval
- [ ] repair step polished — detect + fix one malformed mesh (clean red→green)
- [ ] 2–3 validation checks → say "sanity-checked," not "accurate"
- [ ] (stretch) nano banana + Hunyuan3D path for visual variety

**O (demo + autonomy viz — the Agents That Ship story):**
- [ ] Control-room UI: live activity feed, parallel agent tiles, counter, coverage map
- [ ] Atlas vector-search targeting shown filling the coverage map live
- [ ] The "runs while I talk" device: loop keeps producing during the pitch
- [ ] Human-in-the-loop gate shown once (approval before anything external)

## 4. Saturday night — polish, then FREEZE
- [ ] End-to-end runs unattended and produces a growing library
- [ ] **Feature freeze** — no new scope after this point

## 5. Sunday AM → 11:00 — ship
- [ ] Rehearse the 3-min demo (loop running live, repair red→green, residual converging, library + coverage growing)
- [ ] Record the backup demo video
- [ ] Write the submission (name models/agents used + how: Argon, Flash, Atlas; nano banana/Hunyuan if used)
- [ ] Buffer 11:00–12:00 before deadline

---

## Critical path
Tonight's smoke test on the Argon-generates-mesh path. It has no external hosting dependency, so it's the safe core. Hunyuan is a stretch, never on the critical path.

## Kill-list (these sink the weekend)
- [ ] NOT body-fitted meshing — voxelise instead
- [ ] NOT a high-fidelity solver (no RANS/LES) — LBM / immersed boundary only
- [ ] NOT putting Hunyuan hosting on the critical path — it's a stretch
- [ ] NOT claiming "accurate" data — say "approximate, sanity-checked"

## Demo must-haves (what judges score)
- [ ] Autonomy is visible: agents working live + the "ran while I talked" moment
- [ ] One verification loop with a number (residual converging, or repair red→green)
- [ ] A named user (ML-for-science / CFD researcher)
- [ ] Argon clearly load-bearing (generates meshes + orchestrates + targets gaps)
- [ ] Human-in-the-loop line (nothing external acted on without approval)

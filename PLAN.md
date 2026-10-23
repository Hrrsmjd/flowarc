# FlowArc — build plan

Deadline: **Sunday 25 Oct, 12:00.** Owners: **O** = Ose (agent, platform, demo), **H** = Harris (physics, solver). Full brief: [docs/GOAL.md](docs/GOAL.md).

Rule: get one object through the whole chain first, then widen. Keep `main` runnable.

## Decisions
- Objects come from **images → image-to-3D** (Hunyuan3D-2.1 default), not from Argon writing mesh code.
- Solver: **our own D3Q19 lattice Boltzmann in NVIDIA Warp**, voxelized body, Smagorinsky LES at high Re. FluidX3D is the speed reference only (its licence bans commercial use and needs changed source published).
- Time in convective units L/U: drop ~10 L/U of start-up, record 30 L/U at 0.1 L/U (300 frames).
- Convergence is statistical: running means stable in time, QoIs within tolerance across grid levels. Hitting the resolution cap → keep, flag "not converged".
- Storage: Zarr, float16, one folder per sample under `FLOWARC_DATA`. MongoDB Atlas is an optional mirror of the registry.
- Human approval before publishing the dataset and before any run over the compute budget.

## Phases
| Phase | Cells along body | Samples | Goal |
|---|---|---|---|
| 1 pilot | ~64 (ladder 48 → 64) | 10–20, then 100 | every stage and check works |
| 2 first dataset | ~100–128 | 100 in a few hours on 7 A100s | real data |
| 3 reference | ~256 | as time allows | reference-video quality |

## Build order
1. [ ] **H** Solver slice: Warp LBM, sphere drag vs Re and cylinder/sphere Strouhal checks, one aircraft mesh → video + point cloud. Measure time and GB per sample.
2. [ ] **H** Mesh bake-off (~10 objects through Hunyuan3D-2.1 / 2mv / TRELLIS.2), mesh checks, Argon review and repair loop.
3. [ ] **H+O** One hand-picked object through all stages.
4. [ ] **O** Argon orchestration, Flash subagents, GPU pool. Phase 1: 10–20 samples, then 100.
5. [ ] **H** Report measured throughput, propose Phase 2 resolution. Run Phase 2 after approval.
6. [ ] **O** Dashboard: live agent activity, review requests, sample viewer, video gallery, diversity map.
7. [ ] **O+H** README for submission: problem, user, architecture, Gemini usage, how to run, limits.

## Demo (under 3 min)
- A live sample runs at Phase 1 resolution while the batch is pre-computed.
- Show one failed check going back to Argon and getting fixed.
- Show convergence numbers and the diversity map against a car-only baseline.
- Show the human approval gate.

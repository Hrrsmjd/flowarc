# FlowArc

**An agent that builds a shape-diverse dataset of turbulent 3D flow simulations.**

Datasets like DrivAerNet++ hold one kind of shape (cars). Neural physics models trained on them fail on anything else. FlowArc uses Gemini to invent objects of every kind (animals, aircraft, furniture, buildings, abstract shapes), turns each into a checked 3D mesh, and runs a time-resolved GPU flow simulation around it. Every sample ships with proof that it is sound: mesh checks, a stable solve and converged statistics.

Built at **Encode London 2026** (Google DeepMind Gemini 4 Argon bounty). All code was written during the hackathon. The full brief is in [docs/GOAL.md](docs/GOAL.md); the target look is [docs/fullflow_loop_1920x1080.mp4](docs/fullflow_loop_1920x1080.mp4); the build plan is in [PLAN.md](PLAN.md).

## Who it is for

People who train neural surrogates for fluid flow (mesh or point-cloud models) and need data that covers many shapes and flow regimes. We are the first users.

## Pipeline

```
concept → 4 reference images → mesh → checks/repair → LBM simulation → video + visual check → package
 (Argon)   (Nano Banana)      (image-to-3D)  (Argon)     (GPU, A100)     (Flash)               (Zarr)
```

Every stage has a pass/fail check. On failure the evidence goes back to Argon, which repairs or regenerates, up to a set number of tries.

1. **Concept.** Argon reads the dataset registry and proposes objects that fill gaps in a shape taxonomy. Each gets a Reynolds number, a flow angle and a ground plane or free stream. Near-duplicates are rejected by embedding distance.
2. **Reference images.** Four views (front, side, top, three-quarter) on white, each conditioned on the first. Flash checks the views agree.
3. **Mesh.** Image-to-3D (Hunyuan3D-2.1 by default, pluggable). Checks: watertight, one solid, no thin parts, silhouette IoU against the images, symmetry. Argon repairs small defects with code or regenerates.
4. **Simulation.** Lattice Boltzmann on a voxelized body, with an LES model at high Re. Settings come from Argon. Statistics (drag, lift, Strouhal number, wake profiles) must converge in time and across grid levels.
5. **Video and visual check.** A 10 s, 1080p loop of Q-criterion vortex surfaces. Flash watches it for leaks, blow-ups or a clipped wake.
6. **Package.** Surface pressure and wall shear, a 200k-point volume cloud with velocity and pressure for 300 frames, mean and RMS fields, force histories, video and metadata.

## Gemini models

| Model | Job |
|---|---|
| `gemini-4-argon` | Plans batches, picks solver settings, reviews meshes, diagnoses failures |
| `gemini-3.8-flash` | Per-sample checks: view consistency, mesh-vs-image comparison, video review |
| `gemini-nano-banana-2.1` | Reference images |
| `gemini-embedding-2` | Novelty check and diversity map |

All calls use the Interactions API (`client.interactions.create`, `google-genai>=2.30`).

## Compute

- 7× A100 40 GB (w7830): simulation, rendering, image-to-3D. One sample per GPU.
- Modal CPU ($100): optional cross-checks only.

## Layout

```
flowarc/         Python package
  config.py      paths and phase settings
  sample.py      sample record, state and log (the registry)
  gemini.py      thin Gemini wrapper
  concepts.py    stage 1
  images.py      stage 2
  mesh/          stage 3: generators, checks, repair
  sim/           stage 4: solver interface, FluidX3D backend, statistics
  render.py      stage 5
  package.py     stage 6
  pipeline.py    runs samples through the stages
scripts/         one-off runs and benchmarks
tests/
web/             dashboard (later)
docs/GOAL.md     the full brief
```

## Run

```bash
uv venv --python 3.12 && uv pip install -e '.[dev]'   # add '.[sim]' on a GPU box
cp .env.example .env                                   # add GEMINI_API_KEY
pytest
```

All data goes under `FLOWARC_DATA` (on w7830 this must be inside `~/RDS`).

## Limitations

- Phase 1–2 resolutions (64–128 cells along the body) do not resolve boundary layers at high Re; such samples are flagged "not converged" rather than dropped.
- The data is checked, not proven accurate. Each sample states its fidelity regime.

## Team

- **@Esoiya** — platform, agent and demo
- **@Hrrsmjd** — physics, solver, ML for science

## Known limits

- No wall model. At high Re the boundary layer is thinner than a few cells, so Re is nominal. Each sample records this under `resolution` in its Zarr attributes (`tau`, `bl_cells`, `re_nominal`).

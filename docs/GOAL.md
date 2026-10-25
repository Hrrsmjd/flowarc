# Agentic diverse-shape CFD dataset generator

## Goal
Build an autonomous agent that generates the most shape-diverse fluid-simulation dataset possible. It should go far beyond single-category datasets like DrivAerNet++ (cars only), so that neural physics models trained on it generalize to unseen geometry and flow regimes.

Each sample is a **time-resolved, turbulent 3D flow simulation** around one object: resolved vortex shedding and wake structures, not a steady-state solution. The reference video ([docs/fullflow_loop_1920x1080.mp4](fullflow_loop_1920x1080.mp4)) shows the target. It is a 12-second 1080p loop of a voxelized fighter jet in a statistically steady turbulent flow:
- the body is rendered grey on a plain navy background, with teal vortices and red where the flow is fast
- vortex structures are shown as isosurfaces (Q-criterion style), coloured by a flow quantity
- the wake is fully developed and detaches downstream

We want this for a large and very diverse set of objects.

Every sample ships with evidence that it is correct: a verified mesh and a statistically converged simulation.

This is a hackathon project for Encode London 2026 (Google DeepMind / Gemini 4 Argon bounty, Pathway 2). All project code must be written during the hackathon; open-source libraries and pretrained models are fine. We are the first users: we train neural physics models (mesh and point-cloud based) and need this data.

## Targets and phases
- **Phase 1 – pilot (low resolution).**
  - Run about 64 cells along the body's length.
  - Get 10–20 samples through the full pipeline, then 100.
  - Goal: every stage, check and output works end to end.
- **Phase 2 – first real dataset.**
  - 100 samples in a few hours on 7 A100s, at the highest resolution that fits that budget (expected around 100–128 cells along the body).
- **Phase 3 – reference quality, if time allows.**
  - Around 256 cells along the body (roughly the reference video's look); hours per sample.

Rough cost model, to be replaced by measured numbers in Phase 1:
- **Assumptions:**
  - LBM at about 10 billion cell updates per second per A100
  - domain 6L × 3L × 3L, where L is body length
  - lattice velocity 0.075
  - 40 convective times simulated

  Under these assumptions, cost scales with the fourth power of resolution.
- **Estimates per sample on one A100:**

  | Cells along body | Time per sample |
  |---|---|
  | 64 | ~1 min |
  | 96 | ~4 min |
  | 128 | ~13 min |
  | 256 | ~3.5 h |

## Compute
- **7× A100 GPUs:** simulations, rendering and image-to-3D generation. Run one sample per GPU at a time.
- **$100 on Modal (CPU):** light CPU work such as mesh checks and occasional cross-check runs. Budget it carefully.

## Gemini usage
- **Lead model:** `gemini-4-argon` via the official SDK (`google-genai>=2.3.0`), using the Interactions API (`client.interactions.create`).
- **Check the API before coding.** These APIs are new, so read the docs or the Gemini API skills (`npx skills add google-gemini/gemini-skills --skill gemini-api-dev`) before writing Gemini calls, rather than writing them from memory.
- **Argon API rules:**
  - Use `thinking_level` ("low", "medium" or "high"), not `thinking_budget`.
  - Do not pass `temperature`, `top_p`, `top_k` or `cached_content`.
  - Set `background=True` for outputs over 65,536 tokens.
- **Argon is slow.** Use it for planning, judgement and diagnosis, not routine per-sample checks. Use `thinking_level` "high" only for batch planning and hard failure diagnosis.
- **Other models:**
  - `gemini-nano-banana-2.1`, or the best image model in the current docs, for reference images.
  - `gemini-3.8-flash` for parallel per-sample subagents and routine visual checks.
  - `gemini-3.5-flash-lite` for cheap routing or classification, if useful.
- **Human approval** is required before publishing the dataset (e.g. to Hugging Face) and before any compute run above a set budget.
- **Results come from real runs.** Failures are logged and shown, never hidden.

## Pipeline
Argon orchestrates. It keeps a dataset registry in context (all samples, their descriptors and statistics) and decides what to generate next.

Each sample passes through the stages below, and each stage has a concrete pass/fail check. On failure, the evidence goes back to the agent, which decides whether to repair or regenerate. Each stage has a maximum number of attempts.

### 1. Concept generation
- **Propose concepts that fill gaps.** Argon proposes new object descriptions aimed at what the dataset lacks.
- **Use a taxonomy to force spread.** Buckets could include:
  - animals and organic forms
  - vehicles of all eras (land, air, sea, fictional)
  - buildings and structures
  - furniture and everyday objects
  - sports gear and tools
  - plants
  - abstract or parametric shapes
  - combinations of the above
- **Vary the geometry.** Vary topology (holes, thin parts, multiple bodies), aspect ratio, bluff versus streamlined, and symmetry.
- **Assign flow conditions.** Each concept also gets:
  - a Reynolds number, sampled log-uniformly across the widest range the solver can handle (see Simulation)
  - a flow direction or angle of attack
  - a ground plane or free stream
- **Check: novelty.** Embed the description (and later the images) and reject anything too close to existing samples. Track coverage per taxonomy bucket.

### 2. Reference images
- **Generate four views** on a plain white background: front, side, top and three-quarter. Prefer near-orthographic views.
- **Keep views consistent.** Generate one view first, then condition the others on it.
- **Check: consistency.** Review the set across views (same object, same part count, same proportions). Regenerate inconsistent views.

### 3. Mesh
- **Generator:** an image-to-3D model behind a pluggable interface. Generate shape only; textures aren't needed for CFD.
  - **Default:** Hunyuan3D-2.1, running locally on the A100s.
  - **Bake-off in Phase 1:** run about 10 objects through each candidate and pick by the match and geometry checks below. Candidates:
    - Hunyuan3D-2.1 (single image)
    - Hunyuan3D-2mv (open multi-view)
    - TRELLIS.2 (MIT licence)
    - Hunyuan3D 3.1 via API (up to 8 input views)

    Keep more than one generator if they win on different kinds of object.
- **Argon reviews and fixes.** Argon sees the reference images, renders of the mesh and the check results, then decides:
  - **Repair with code (small defects):**
    - fill holes, remove floating fragments
    - make watertight (voxel remesh, or a manifold-repair tool such as pymeshfix or manifold3d)
    - mirror a good half to enforce symmetry
    - thicken parts too thin to survive voxelization
  - **Regenerate (significant defects):** wrong part count, a missing or extra leg, wrong proportions. Fix the prompt or reference images (e.g. "a cow with four legs; the front-left leg was missing"), or switch generator.
- **Checks (all must pass):**
  - **Geometry:**
    - watertight and manifold
    - a single connected solid, unless multiple bodies are intended
    - no self-intersections
    - no features thinner than about 2 cells at the finest planned resolution
  - **Match:** render the mesh at the same camera poses as the reference images.
    - Compute silhouette IoU per view. Start with a threshold of 0.85 and tune it.
    - Add a visual comparison of renders against references: number of legs, wheels and wings, and proportions.
  - **Symmetry where expected:** reflect the mesh and measure the Chamfer distance to the original.
- **Normalize.** Scale to a characteristic length, orient so the flow runs along +x, and place on the ground plane if one is specified.

### 4. Simulation
- **Target:** transient, turbulence-resolving 3D flow around a voxelized body, as in the reference video.
- **Reynolds range.** Cover as wide a range as possible, from laminar (Re ~10) up to vehicle and aircraft scale (Re ~10^6–10^7). Establish the reliable upper limit through validation rather than assuming it.
- **Solver:** GPU lattice Boltzmann on a voxelized mesh, with a subgrid turbulence model (Smagorinsky or WALE) and wall modelling at high Re.
  - Candidates:
    - FluidX3D: closest match to the reference. It is fast, voxelizes STL meshes and has built-in rendering. Check its licence terms before use.
    - XLB (JAX, multi-GPU)
    - NVIDIA Warp
  - Pick based on measured speed on our A100s and ease of automation.
  - Keep the solver behind a swappable interface.
- **Fidelity regime chosen by Argon:**
  - low Re: direct simulation with no turbulence model
  - higher Re: LES with a subgrid model and wall model

  Record the regime, the near-wall resolution and the model in each sample's metadata.
- **Time in convective units.** One convective time is L/U (body length divided by free-stream speed); this makes samples comparable across objects.
  - Discard about 10 L/U of start-up transient. Argon can lengthen this if the wake hasn't developed.
  - Record 30 L/U at intervals of 0.1 L/U, giving 300 frames. That is about 6 shedding cycles for a typical bluff body, at about 50 frames per cycle.
  - At 30 fps playback this is a 10-second video.
- **Argon chooses initial settings** from the geometry and flow conditions:
  - domain size and blockage ratio (wake must not be clipped by the outlet)
  - base resolution (finer for thin parts, sharp edges, small gaps and higher Re)
  - lattice velocity (Mach number)
  - transient length
  - QoIs and their tolerances

  It writes a one-paragraph justification of these choices, stored in metadata.
- **Convergence loop (statistical).** Instantaneous turbulent fields never match between grids, so convergence is judged on statistics:
  - **Time convergence:** running means of the QoIs must be stable over the recorded window.
  - **Grid convergence:**
    - Refine (e.g. ×1.5 per axis) up to the phase's resolution cap.
    - Pass when the statistical QoIs change by less than their tolerance between successive levels.
    - QoIs include:
      - mean drag, lift and side force
      - RMS lift
      - dominant shedding frequency (Strouhal number from the force spectrum)
      - mean wake velocity profiles
    - Only the final level records the 300 output frames.
  - **Resolution cap:** if it is reached without passing, keep the sample but flag it "not converged". This is expected for many high-Re samples at Phase 1–2 resolutions.
  - **In Phase 1:** use a short ladder (e.g. 48 → 64) to exercise the loop.
- **Stability checks:**
  - no NaNs
  - LBM stability limits respected (low lattice Mach number, valid relaxation time)
  - mass conserved
- **Validate the solver first:**
  - sphere drag versus Reynolds against published data
  - cylinder or sphere shedding frequency (Strouhal number)
  - at least one high-Re benchmark with experimental data, such as the Ahmed body
  - optionally, a few RANS cross-checks on Modal CPU (e.g. OpenFOAM), within budget

### 5. Rendering and visual check
- **Render each sample as a 10-second, 30 fps, 1080p looping video** of the 300 recorded frames, in the reference style:
  - dark grey body on a light background
  - vortex isosurfaces (Q-criterion) coloured by a flow quantity
  - three-quarter camera view
- **A Flash subagent watches the video** and flags physical problems:
  - flow leaking through the body (gaps from voxelization)
  - wrong flow direction
  - blow-ups or checkerboard noise
  - wake clipped by the domain boundary
  - wake not yet developed
  - geometry missing parts after voxelization

  Argon diagnoses flagged samples and sends them back to the mesh or simulation stage.

### 6. Outputs and packaging
The body is static, so the surface mesh and point positions are fixed per sample. Only the field values change over time.

- **Fields per frame (all 300 frames):**
  - **Surface:** pressure and wall shear stress (3 components) on the vertices of the surface mesh. Decimate the mesh to about 50k vertices if needed.
  - **Volume:**
    - a fixed point cloud of about 200k points, sampled once per sample from the fluid region
    - denser near the body and in the wake (e.g. importance sampling by distance to the body and time-averaged vorticity)
    - velocity (3 components) and pressure interpolated from the lattice at each frame
- **Also store:**
  - time-averaged and RMS fields on the same points
  - QoI time histories (drag, lift and side force) at every solver step or at high frequency
  - the rendered video
- **Per-sample metadata:**
  - description and flow conditions
  - reference images
  - mesh, plus the generator used and any repairs
  - all check results
  - solver config, fidelity regime and Argon's justification
  - convergence history across levels
  - compute cost
- **Formats and size:**
  - Zarr or HDF5 (chunked, compressed), stored as float16, with a dataset card stating each sample's fidelity regime and limitations.
  - Expected size: about 0.5–1 GB per sample, so 50–100 GB for 100 samples. Report the measured size from Phase 1.
- **Publishing requires human approval.**

## Orchestration
- **Argon plans and diagnoses.** Flash subagents do the per-sample work in parallel, with capped concurrency.
- **Overlap stages across the GPU pool.** Mesh generation for upcoming samples runs while simulations of earlier ones are in progress.
- **The pipeline is resumable and idempotent.** Every sample has a state and a full log.
- **Track cost and time** per stage. Report samples per hour against the phase target.

## Dashboard (secondary; build after the pipeline produces data)
A Three.js/WebGPU dashboard showing:
- live agent activity per sample: stages, failed checks, fixes
- human-review requests: approve publishing, approve over-budget runs, review flagged samples
- a sample viewer:
  - reference images beside mesh renders, with IoU scores
  - convergence plots
  - the flow video
- a gallery of flow videos across the dataset
- a diversity map: a 2D projection of shape embeddings, with a car-only baseline overlaid

The live hackathon demo is under 3 minutes, so a live sample must run at Phase 1 resolution while the batch is pre-computed.

## Build order
1. **Solver vertical slice at Phase 1 resolution.**
   - Run one known aircraft mesh and produce a video in the reference style plus the point-cloud outputs.
   - Validate against the sphere and Strouhal benchmarks.
   - Measure time and storage per sample.
2. **Mesh generator bake-off** and the Argon review and repair loop.
3. One hand-picked object end to end through all stages.
4. Argon orchestration, parallel subagents, multi-GPU scheduling. Phase 1: 10–20 samples, then 100.
5. Report measured throughput and propose Phase 2 resolution. After approval, run Phase 2.
6. Dashboard.
7. README covering:
   - the problem and the user
   - architecture
   - which Gemini models and agents are used, and how (required for submission)
   - how to run it
   - limitations

At each milestone, report what works, what's broken and what's needed. Ask before adding major dependencies or spending significant compute.
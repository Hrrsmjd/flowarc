# FlowArc

**An autonomous agent that never stops making physics training data.**

FlowForge runs on its own, continuously generating 3D shapes, repairing any that come out malformed, then simulating airflow around each one until the solve converges. The result is a growing, validated library of CFD data for training ML models that predict how air and water flow.

Built at **Encode London 2026**. All code in this repository was written during the hackathon.

---

## How it works

```
 generate → validate/repair → simulate → converged? → store → target gaps → repeat
   (Argon)      (Argon)         (solver)    (gate)      (Atlas)   (Argon)
```

1. **Generate** — Gemini 4 Argon produces a new shape (parametric geometry).
2. **Validate & repair** — malformed geometry is detected and fixed before it wastes a solve.
3. **Simulate** — a fast solver runs airflow around the shape until residuals converge.
4. **Store** — the shape, flow field and metadata land in MongoDB Atlas.
5. **Target gaps** — Argon vector-searches the library and steers generation toward under-covered regions.
6. **Repeat** — the loop runs unattended via a long background run.

Argon is the generator, repairer and orchestrator. The solver and surrogate are ordinary code; Argon is load-bearing where diversity, repair reasoning and campaign orchestration are needed.

## Stack

- **Gemini 4 Argon** (`gemini-4-argon`) — generation, repair, orchestration
- **Antigravity managed agent** (`antigravity-preview-09-2026`) — autonomous sandbox execution
- **Gemini 3.8 Flash** — parallel subagents for batch generation/evaluation
- **MongoDB Atlas** — dataset store + vector search over shapes
- **WebGPU / Three.js** — live visualisation of the growing library and flow fields

## Repo layout

```
generator/   shape generation (Argon)
solver/      the CFD / airflow solver
pipeline/    the autonomous loop + orchestration
store/       MongoDB Atlas client, schema, vector search
web/         WebGPU viz — live gallery + flow fields
scripts/     one-off helpers, smoke tests
```

## Quickstart

```bash
# 1. clone
git clone https://github.com/Esoiya/flowforge-ai.git
cd flowforge-ai

# 2. secrets
cp .env.example .env    # fill in your keys
```

## Bounties

Entering: **Google DeepMind (Gemini 4 Argon)**, **MongoDB Atlas**, **Agents That Ship**.

## Team

- **@Esoiya** - Platform engineer
- **@Hrrsmjd** — Physics / fluid dynamics, ML for science

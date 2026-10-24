# Dashboard

Live dashboard for the demo, deployed on Vercel. It shows:

- run progress for each sample and stage
- agent activity for the sample running now, including failed checks and Argon's repairs
- a sample viewer: silhouette IoU per attempt, convergence of drag across grid levels
- the diversity map, our samples vs a car-only baseline
- the human approval gate (publish, over-budget runs, flagged samples)

The page polls `/api/state` every 2 s. The API reads MongoDB Atlas, the same collections the
pipeline writes (`samples`, `logs`, `approvals`, plus `baseline` for the map and `runs` for the
run summary). Without `MONGODB_URI` it plays a mock batch on a loop (`lib/mock.json`), so a
deployment is live from the first minute; **Restart** starts the story again.

| Route | |
|---|---|
| `GET /api/state` | run summary, samples with their logs, approvals |
| `GET /api/map` | 2D PCA of concept embeddings (ours + `baseline`) |
| `GET /api/search?q=` | sample search: Atlas Search index `samples_text`, regex if it's missing |
| `GET /api/media?id=` | a view (JPEG) or mesh (GLB) from the GridFS bucket `media`; `?hf=` a view from the HF dataset |
| `POST /api/approve` | `{id, decision: "approved" \| "rejected"}` sets the approval in Atlas |

## Run locally

```bash
cd web && npm install
npm run dev                      # http://localhost:3000, mock replay
MONGODB_URI=... MONGODB_DB=flowarc_demo npm run dev   # read Atlas
npm test
```

## Deploy on Vercel

1. New project from this repo, **Root Directory** `web`. No build step (`vercel.json` sets it).
2. Environment variables:
   - `MONGODB_URI`: Atlas connection string. Leave unset for the mock replay.
   - `MONGODB_DB`: `flowarc` for the real registry, `flowarc_demo` for the demo feed.
   - `FLOWARC_HF_REPO` and `HF_TOKEN` (read access): only for views from the private HF dataset
     when `flowarc.media` isn't running.
   - `APPROVAL_TOKEN` (recommended): approving then asks for this token, so a public URL
     can't approve publishing.
3. In Atlas, Network Access must allow Vercel (0.0.0.0/0 for the hackathon).

On a Hobby (free) Vercel team, Git deployments only build commits by team members unless the
repo is public. For a private repo, deploy from your own account with the CLI instead:
`cd web && npx vercel@latest link && npx vercel@latest --prod`.

## Demo feed

`scripts/demo_feed.py` plays the mock batch into Atlas in real time (database `flowarc_demo`),
so the deployed dashboard runs on Atlas end to end before the real pipeline does. At the end
it asks to publish and waits until someone presses Approve or Reject on the dashboard.

```bash
python scripts/demo_feed.py            # once; --loop to repeat, --speed 2 for faster
```

Regenerate the mock batch with `python -m flowarc.mock web/lib/mock.json`.

## Views and meshes

The Sample panel shows the four reference views (hover to enlarge) and the mesh in a 3D viewer
(three.js, vendored in `public/vendor`), with a tab per mesh attempt so a failed mesh and its
fix can be compared. They come from the GridFS bucket `media` in Atlas. On the GPU box, next to
the runner:

```bash
python -m flowarc.media --watch 15   # uploads new views (512 px JPEG) and meshes (GLB, ≤20k faces)
```

Without it, views the runner uploaded to the HF dataset (`meta.files`) still show, but no meshes:
the full STL is too large to pass through a Vercel function.

## What the pipeline needs to write

The dashboard already reads what `Sample.save`, `Sample.log`, `record_check` and
`record_repair` write. For the full picture the pipeline should also set:

- `concept.bucket`, `concept.reynolds`, `concept.facing`, `concept.ground`
- `status: "running"` while a sample is on a GPU, and `meta.gpu`
- `meta.gpu_seconds` and `meta.convergence`: `{levels: [{cells, t, cd_mean, cd, cl_rms, st}], tol: {cd, cl_rms, st}}`
- `actor` on log events (`argon`, `flash`, `nano-banana`, `hunyuan3d`, `fluidx3d`); without it
  the dashboard guesses from the message
- `iou: {front, side, top}` on the silhouette or Flash review check
- an `approvals` document `{_id, kind, title, detail, status: "pending", t}` before publishing or
  an over-budget run, then wait for `status` to change
- `baseline` documents `{_id, name, embedding}` for car-only concepts, embedded with the same
  model as the samples

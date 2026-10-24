# Dashboard

Static page (no build step) for the demo: run progress per sample and stage, live agent activity
with failed checks and Argon's fixes, a sample viewer (silhouette IoU per attempt, convergence of
running-mean drag across grid levels), the diversity map against a car-only baseline, and the
human approval gate.

```bash
python -m flowarc.dashboard           # reads the registry under FLOWARC_DATA; mock data if it is empty
python -m flowarc.dashboard --mock    # always mock data
```

Open http://localhost:8000. Click a row or a map point to open a sample; **Replay** steps
through the followed sample's log for the demo.

The page reads `GET /api/state` and posts decisions to `POST /api/approve`. Served as plain static
files (no Python), it falls back to `mock.json`. Regenerate that with
`python -m flowarc.dashboard --write-mock web/mock.json`. The state shape is built in
`flowarc/dashboard.py` (`live_state`) and `flowarc/mock.py`.

Live data the pipeline still needs to write: `bucket` in the concept, `meta.convergence`
(levels with `t`, `cd_mean`, `cd`, `cl_rms`, `st` and `tol`), `meta.gpu_seconds`, `actor` on log
events (`argon`, `flash`, ...), `DATA/diversity.json` (2D embedding points) and
`DATA/approvals.json`.

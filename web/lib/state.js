// Builds the dashboard state from registry documents (Atlas or the mock batch).
//
// Inputs follow the pipeline's Atlas collections: `samples` (_id, stage, status, concept,
// attempts, meta), `logs` ({sample, t, stage, msg, check?, passed?, actor?, ...}) and
// `approvals` ({_id, kind, title, detail, status, sample?, t}). A person's review of a flagged or
// failed sample is a log line with actor "human" and `review` (accept | retry | drop) plus `note`.

export const STAGES = ["concept", "images", "mesh", "sim", "render", "package"];

// "vehicles (land, air, ...)" -> "vehicles"; "animals and organic forms" -> "animals"
export const shortBucket = (b) => (b || "unknown").split(/ \(| and | or | of |,/)[0];

const ACTORS = [
  [/^repair:|^Argon/i, "argon"],
  [/Nano Banana|^images error/i, "nano-banana"],
  [/Hunyuan|TRELLIS/i, "hunyuan3d"],
  [/FluidX3D|^sim error/i, "fluidx3d"],
];
// Which model or tool runs each pipeline check (flowarc/pipeline.py).
const CHECK_ACTORS = {
  novel: "embedding",
  novelty: "embedding",
  views_consistent: "flash",
  view_consistency: "flash",
  mesh: "flash",
  flash_review: "flash",
  video_review: "flash",
  stable: "fluidx3d",
  mass: "fluidx3d",
  converged: "fluidx3d",
  stability: "fluidx3d",
};

function event(e) {
  // Older log lines carry the check only in the message: "check mesh: FAIL".
  const m = /^check (\w+): (pass|FAIL)/.exec(e.msg);
  const check = e.check || m?.[1];
  const passed = e.passed ?? (m ? m[2] === "pass" : undefined);
  const actor = e.actor || CHECK_ACTORS[check] || (ACTORS.find(([re]) => re.test(e.msg)) || [, "system"])[1];
  const error = / error: /.test(e.msg);
  return {
    t: e.t,
    stage: e.stage,
    msg: error ? e.msg.slice(0, 160) : e.msg,
    actor,
    failed: passed === false || error || /out of attempts/.test(e.msg),
    soft: e.hard === false,
    fix: /^repair:/.test(e.msg),
    check,
    diagnosis: e.diagnosis,
    reason: e.reason || e.summary || e.note,
    review: e.review,
    similarity: e.similarity,
    iou: e.iou || (typeof e.silhouette === "number" ? { "min view": e.silhouette } : undefined),
    d_cd: e.d_cd,
    tol: e.tol,
    mach_max: e.mach_max,
    cd: e.cd,
    change: e.change,
    gb: e.gb,
    notes: e.notes,
  };
}

// Gemini calls (pipeline.run_sample logs one line per call): counts and tokens per model.
function addCall(u, e) {
  const m = (u.by_model[e.model] ??= { calls: 0, tokens: 0 });
  m.calls += 1;
  m.tokens += e.tokens || 0;
  u.calls += 1;
  u.tokens += e.tokens || 0;
}

const STAT_KEYS = ["cd_mean", "cl_rms", "cs_rms", "st", "cd_half_change", "mach_max", "mass_drift"];
const pick = (o, keys) => (o ? Object.fromEntries(keys.filter((k) => o[k] != null).map((k) => [k, o[k]])) : null);

// Per sample: the latest attempt of each view, every mesh attempt (so a failed mesh and its
// fix can be compared), and the flow video.
function mediaBySample(media) {
  const out = new Map();
  for (const m of [...media].sort((a, b) => a.t - b.t)) {
    if (!out.has(m.sample)) out.set(m.sample, { views: {}, meshes: {} });
    const o = out.get(m.sample);
    const item = { url: m.url, attempt: m.attempt || 1, t: m.t };
    if (m.kind === "view") o.views[m.name] = item;
    else if (m.kind === "mesh") o.meshes[item.attempt] = item;
    else if (m.kind === "video") o.video = item; // the latest flow video
  }
  for (const o of out.values()) o.meshes = Object.values(o.meshes).sort((a, b) => a.attempt - b.attempt);
  return out;
}

export const VIEWS = ["three-quarter", "front", "side", "top"];

// Views the runner uploaded to the private HF dataset (meta.files, flowarc/publish.py), for
// samples flowarc/media.py hasn't copied to Atlas. api/media fetches them with HF_TOKEN.
function withHf(media, views) {
  if (!Object.keys(views).length) return media || null;
  const m = media || { views: {}, meshes: [] };
  return { ...m, views: { ...views, ...m.views } };
}

function hfViews(s) {
  const views = {};
  for (const f of s.meta?.files || []) {
    const m = /^views\/([\w-]+)\.jpg$/.exec(f.path || "");
    if (m) views[m[1]] = { url: `api/media?hf=${encodeURIComponent(`${s._id}/${f.path}`)}`, attempt: s.attempts?.images || 1, t: 0 };
  }
  return views;
}

// The latest human review, and whether anything has happened since (the runner acting on it).
function lastReview(log) {
  const i = log.findLastIndex((e) => e.review);
  if (i < 0) return null;
  return { decision: log[i].review, note: log[i].reason || "", t: log[i].t, acted: i < log.length - 1 };
}

const noCalls = () => ({ calls: 0, tokens: 0, by_model: {} });

export function buildState({ run = {}, samples, logs, approvals = [], media = [], mode, hfRepo = "", runFrom = "", now = Date.now() / 1000 }) {
  const files = mediaBySample(media);
  const bySample = new Map();
  const calls = new Map();
  const stageStart = new Map(); // when each sample's current stage began
  const total = noCalls();
  for (const e of logs) {
    if (!stageStart.has(e.sample) || e.msg === "advanced") stageStart.set(e.sample, e.t);
    if (e.msg === "advanced") continue; // stage moves show in the progress table
    if (e.actor === "gemini") {
      if (!calls.has(e.sample)) calls.set(e.sample, noCalls());
      const u = calls.get(e.sample);
      addCall(u, e);
      if (e.copy) { // a batch-wide call is logged on every sample, counted once in totals
        u.copies = { calls: (u.copies?.calls || 0) + 1, tokens: (u.copies?.tokens || 0) + (e.tokens || 0) };
      } else addCall(total, e);
      continue; // shown under Prompts, not in the activity feed
    }
    if (!bySample.has(e.sample)) bySample.set(e.sample, []);
    bySample.get(e.sample).push(event(e));
  }
  const rows = samples
    .filter((s) => !s.meta?.batch)
    .map((s) => {
      const c = s.concept || {};
      const log = (bySample.get(s._id) || []).sort((a, b) => a.t - b.t);
      const past = STAGES.indexOf(s.stage) > STAGES.indexOf("sim") || s.stage === "done" || s.status === "flagged";
      return {
        id: s._id,
        title: c.name || c.description || s._id,
        bucket: shortBucket(c.bucket),
        stage: s.stage,
        status: s.status,
        concept: c,
        attempts: s.attempts || {},
        gpu: s.meta?.gpu >= 0 ? s.meta.gpu : null, // the runner writes -1 for stages off the GPU
        gpu_seconds: s.status === "running" || s.status === "pending" ? 0 : s.meta?.gpu_seconds || 0,
        convergence: past ? s.meta?.convergence || null : null,
        sim: pick(s.meta?.sim?.stats, STAT_KEYS),
        zarr_gb: s.meta?.zarr_gb ?? null,
        stage_since: s.status === "running" ? stageStart.get(s._id) ?? null : null,
        progress: s.status === "running" && s.stage === "sim" ? pick(s.meta?.sim_progress, ["frames", "of"]) : null,
        gemini: calls.get(s._id) || noCalls(),
        hf: hfRepo && s.meta?.files?.length ? `https://huggingface.co/datasets/${hfRepo}/tree/main/samples/${s._id}` : null,
        published: Boolean(s.meta?.published),
        phase: s.meta?.phase || null,
        media: withHf(files.get(s._id), hfViews(s)),
        log,
        last_t: log.length ? log[log.length - 1].t : 0,
        review: lastReview(log),
      };
    });

  // The current run: samples from FLOWARC_RUN_FROM on (an id), else those tagged with the phase
  // of the sample that moved last (pipeline.run_sample sets meta.phase). Older test samples
  // stay in the registry but out of the run's counts; the page can still show everything.
  const tagged = rows.filter((r) => r.phase).sort((a, b) => b.last_t - a.last_t)[0];
  const current = runFrom ? null : tagged?.phase || null;
  for (const r of rows) r.in_run = runFrom ? r.id >= runFrom : current ? r.phase === current : true;

  // Follow the sample the demo is about while it runs, then any running sample, else whichever moved last.
  const running = rows.filter((r) => r.status === "running").sort((a, b) => b.last_t - a.last_t);
  const live = rows.find((r) => r.id === run.live && r.status === "running");
  const featured = (live || running[0] || [...rows].sort((a, b) => b.last_t - a.last_t)[0])?.id;

  const inRun = new Set(rows.filter((r) => r.in_run).map((r) => r.id));
  const times = logs.filter((e) => inRun.has(e.sample)).map((e) => e.t);
  const started = times.length ? Math.min(...times) : now;
  const hours = Math.max((now - started) / 3600, 1 / 60);
  const done = rows.filter((r) => r.in_run && r.status === "done").length;
  const seconds = (keep) => rows.filter((r) => keep(r) && (r.status === "done" || r.status === "flagged")).reduce((a, r) => a + r.gpu_seconds, 0);

  return {
    mode,
    generated_at: now,
    run: {
      phase: current || run.phase || "pilot",
      scope: runFrom ? `from ${runFrom}` : current ? `${current} phase` : null, // null: nothing to tell runs apart
      cells_per_length: run.cells_per_length || null, // from the `runs` document, when written
      target_samples: run.target_samples || 20,
      gpus: run.gpus || null,
      started_at: started,
      samples_per_hour: done / hours,
      gpu_hours: seconds((r) => r.in_run) / 3600,
      gpu_hours_all: seconds(() => true) / 3600,
      gemini: total,
      featured,
    },
    samples: rows,
    approvals: approvals
      .map((a) => ({ id: a._id, kind: a.kind, title: a.title, detail: a.detail, sample: a.sample, status: a.status, t: a.t }))
      .sort((a, b) => (b.status === "pending") - (a.status === "pending") || b.t - a.t),
  };
}

// 2D map of concept embeddings: PCA over our samples and the car baseline together.
export function diversityMap(samples, baseline) {
  const pts = [
    ...samples
      .filter((s) => s.embedding?.length && s.status !== "failed")
      .map((s) => ({ id: s._id, label: s.concept?.name || s._id, bucket: shortBucket(s.concept?.bucket), source: "flowarc", v: s.embedding })),
    ...baseline.filter((b) => b.embedding?.length).map((b) => ({ id: b._id, label: b.name || b._id, bucket: "vehicles", source: "car_baseline", v: b.embedding })),
  ];
  if (pts.length < 3) return { points: [] };
  const dim = Math.min(...pts.map((p) => p.v.length));
  const mean = new Float64Array(dim);
  for (const p of pts) for (let i = 0; i < dim; i++) mean[i] += p.v[i] / pts.length;
  const X = pts.map((p) => Float64Array.from({ length: dim }, (_, i) => p.v[i] - mean[i]));
  const comps = [];
  for (let k = 0; k < 2; k++) comps.push(topComponent(X, comps, dim));
  return {
    baseline: "DrivAerNet++ (cars only)",
    points: pts.map((p, n) => ({ id: p.id, label: p.label, bucket: p.bucket, source: p.source, x: dot(X[n], comps[0]), y: dot(X[n], comps[1]) })),
  };
}

const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);

// Power iteration on X^T X, deflated against earlier components.
function topComponent(X, prev, dim) {
  let v = Float64Array.from({ length: dim }, (_, i) => Math.sin(i + 1 + prev.length));
  for (let it = 0; it < 100; it++) {
    const w = new Float64Array(dim);
    for (const row of X) {
      const s = dot(row, v);
      for (let i = 0; i < dim; i++) w[i] += s * row[i];
    }
    for (const p of prev) {
      const s = dot(w, p);
      for (let i = 0; i < dim; i++) w[i] -= s * p[i];
    }
    const n = Math.hypot(...w) || 1;
    v = w.map((x) => x / n);
  }
  return v;
}

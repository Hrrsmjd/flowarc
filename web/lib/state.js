// Builds the dashboard state from registry documents (Atlas or the mock batch).
//
// Inputs follow the pipeline's Atlas collections: `samples` (_id, stage, status, concept,
// attempts, meta), `logs` ({sample, t, stage, msg, check?, passed?, actor?, ...}) and
// `approvals` ({_id, kind, title, detail, status, sample?, t}).

export const STAGES = ["concept", "images", "mesh", "sim", "render", "package"];

// "vehicles (land, air, ...)" -> "vehicles"; "animals and organic forms" -> "animals"
export const shortBucket = (b) => (b || "unknown").split(/ \(| and | or | of |,/)[0];

const ACTORS = [
  [/^repair:|^Argon/i, "argon"],
  [/Nano Banana/i, "nano-banana"],
  [/Hunyuan|TRELLIS/i, "hunyuan3d"],
  [/FluidX3D/i, "fluidx3d"],
];

function event(e) {
  const actor = e.actor || (ACTORS.find(([re]) => re.test(e.msg)) || [, "system"])[1];
  return {
    t: e.t,
    stage: e.stage,
    msg: e.msg,
    actor,
    failed: e.passed === false,
    fix: /^repair:/.test(e.msg),
    check: e.check,
    diagnosis: e.diagnosis,
    reason: e.reason,
    iou: e.iou,
    d_cd: e.d_cd,
    tol: e.tol,
    mach_max: e.mach_max,
    notes: e.notes,
  };
}

export function buildState({ run = {}, samples, logs, approvals = [], mode, now = Date.now() / 1000 }) {
  const bySample = new Map();
  for (const e of logs) {
    if (e.msg === "advanced") continue; // stage moves show in the progress table
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
        gpu: s.meta?.gpu ?? null,
        gpu_seconds: s.status === "running" || s.status === "pending" ? 0 : s.meta?.gpu_seconds || 0,
        convergence: past ? s.meta?.convergence || null : null,
        log,
        last_t: log.length ? log[log.length - 1].t : 0,
      };
    });

  // Follow the sample the demo is about while it runs, else whichever moved last.
  const running = rows.filter((r) => r.status === "running").sort((a, b) => b.last_t - a.last_t);
  const live = rows.find((r) => r.id === run.live && r.log.length);
  const featured = (live || running[0] || [...rows].sort((a, b) => b.last_t - a.last_t)[0])?.id;

  const times = logs.map((e) => e.t);
  const started = times.length ? Math.min(...times) : now;
  const hours = Math.max((now - started) / 3600, 1 / 60);
  const done = rows.filter((r) => r.status === "done").length;
  const allSeconds = samples
    .filter((s) => s.status === "done" || s.status === "flagged")
    .reduce((a, s) => a + (s.meta?.gpu_seconds || 0), 0);

  return {
    mode,
    generated_at: now,
    run: {
      phase: run.phase || "pilot",
      cells_per_length: run.cells_per_length || [48, 64],
      target_samples: run.target_samples || 20,
      gpus: run.gpus || 7,
      started_at: started,
      samples_per_hour: done / hours,
      gpu_hours: allSeconds / 3600,
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

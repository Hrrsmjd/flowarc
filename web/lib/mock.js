// Mock replay: plays the mock batch (lib/mock.json, from `python -m flowarc.mock`) on a loop,
// so the deployed dashboard is live even without Atlas. Log times in the file are seconds
// relative to the start of the live part; the loop restarts every `cycle` seconds.

import { readFileSync } from "node:fs";
import { STAGES } from "./state.js";

const batch = JSON.parse(readFileSync(new URL("./mock.json", import.meta.url), "utf8"));
// Approvals made in the mock, per replay (viewer start and loop), per server instance.
const decisions = new Map();
const MAX_REPLAYS = 200;

function replay(start, nowAbs) {
  const since = start > 0 && start <= nowAbs ? nowAbs - start : nowAbs;
  const loop = Math.floor(since / batch.cycle);
  return { rel: since - loop * batch.cycle, key: `${start}:${loop}` };
}

function decided(key) {
  if (!decisions.has(key)) {
    if (decisions.size >= MAX_REPLAYS) decisions.delete(decisions.keys().next().value);
    decisions.set(key, new Map());
  }
  return decisions.get(key);
}

const after = (stage) => STAGES[STAGES.indexOf(stage) + 1] || "done";

// `start` (epoch seconds) lets a viewer restart the story from the beginning.
export function mockRegistry(start = 0, nowAbs = Date.now() / 1000) {
  const { rel, key } = replay(start, nowAbs); // rel: seconds into this loop
  const mine = decisions.get(key);
  const toAbs = (t) => nowAbs - (rel - t);
  const logs = batch.logs.filter((e) => e.t <= rel);
  const samples = batch.samples.map((s) => {
    const all = batch.logs.filter((e) => e.sample === s._id);
    if (!all.length) return s; // pre-computed batch
    const seen = all.filter((e) => e.t <= rel);
    if (seen.length === all.length) return s;
    if (!seen.length) return { ...s, stage: "concept", status: "pending", embedding: [] };
    const moved = seen.filter((e) => e.msg === "advanced").pop();
    const tries = seen.filter((e) => e.stage === "mesh" && / built| rebuilt/.test(e.msg)).length;
    return {
      ...s,
      stage: moved ? after(moved.stage) : "concept",
      status: "running",
      attempts: tries > 1 ? { mesh: tries } : {},
    };
  });
  const approvals = batch.approvals
    .filter((a) => a.t <= rel)
    .map((a) => ({ ...a, t: toAbs(a.t), ...(mine?.get(a._id) || {}) }));
  const media = (batch.media || []).filter((m) => m.t <= rel).map((m) => ({ ...m, t: toAbs(m.t) }));
  return {
    run: batch.run,
    samples,
    media,
    logs: logs.map((e) => ({ ...e, t: toAbs(e.t) })),
    approvals,
    baseline: batch.baseline,
  };
}

export function mockDecide(id, status, start = 0, nowAbs = Date.now() / 1000) {
  decided(replay(start, nowAbs).key).set(id, { status, decided_at: nowAbs });
}

// Cosine similarity over the mock batch's concept embeddings, in place of Atlas Vector Search.
export function mockSimilar(id, start = 0, k = 6) {
  const all = mockRegistry(start).samples.filter((s) => !s.meta?.batch && s.embedding?.length);
  const me = all.find((s) => s._id === id);
  if (!me) return [];
  const norm = (v) => Math.hypot(...v);
  const cos = (a, b) => a.reduce((t, x, i) => t + x * b[i], 0) / (norm(a) * norm(b) || 1);
  return all
    .filter((s) => s._id !== id && s.status !== "failed")
    .map((s) => ({ id: s._id, name: s.concept.name, bucket: s.concept.bucket, status: s.status, similarity: cos(me.embedding, s.embedding) }))
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, k);
}

export function mockSearch(q, start = 0) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return mockRegistry(start).samples
    .filter((s) => !s.meta?.batch)
    .map((s) => {
      const text = `${s.concept.name} ${s.concept.description} ${s.concept.bucket}`.toLowerCase();
      return { s, score: words.filter((w) => text.includes(w)).length };
    })
    .filter((r) => r.score)
    .sort((a, b) => b.score - a.score)
    .slice(0, 8)
    .map(({ s }) => ({ id: s._id, name: s.concept.name, bucket: s.concept.bucket, status: s.status }));
}

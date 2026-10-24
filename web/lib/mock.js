// Mock replay: plays the mock batch (lib/mock.json, from `python -m flowarc.mock`) on a loop,
// so the deployed dashboard is live even without Atlas. Log times in the file are seconds
// relative to the start of the live part; the loop restarts every `cycle` seconds.

import { readFileSync } from "node:fs";
import { STAGES } from "./state.js";

const batch = JSON.parse(readFileSync(new URL("./mock.json", import.meta.url), "utf8"));
const decisions = new Map(); // approvals made during this loop, per server instance

const after = (stage) => STAGES[STAGES.indexOf(stage) + 1] || "done";

// `start` (epoch seconds) lets a viewer restart the story from the beginning.
export function mockRegistry(start = 0, nowAbs = Date.now() / 1000) {
  const since = start > 0 && start <= nowAbs ? nowAbs - start : nowAbs;
  const loop = Math.floor(since / batch.cycle);
  const rel = since - loop * batch.cycle; // seconds into this loop
  const key = `${start}:${loop}`;
  if (decisions.key !== key) {
    decisions.clear();
    decisions.key = key;
  }
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
    .map((a) => ({ ...a, t: toAbs(a.t), ...(decisions.get(a._id) || {}) }));
  return {
    run: batch.run,
    samples,
    logs: logs.map((e) => ({ ...e, t: toAbs(e.t) })),
    approvals,
    baseline: batch.baseline,
  };
}

export function mockDecide(id, status) {
  decisions.set(id, { status, decided_at: Date.now() / 1000 });
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

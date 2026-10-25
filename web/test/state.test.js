import assert from "node:assert/strict";
import { test } from "node:test";
import { mockRegistry, mockReview, mockSimilar } from "../lib/mock.js";
import { buildState, diversityMap, shortBucket } from "../lib/state.js";

const T0 = 1_800_000_000;
const at = (rel) => buildState({ ...mockRegistry(T0, T0 + rel), mode: "mock", now: T0 + rel });
const live = (st) => st.samples.find((s) => s.id === "s0016");

test("the mock replay plays the live sample from concept to done", () => {
  assert.equal(live(at(1)).status, "pending");
  const mid = at(20);
  assert.equal(live(mid).status, "running");
  assert.equal(mid.run.featured, "s0016");
  assert.ok(live(at(35)).log.some((e) => e.failed));
  assert.ok(live(at(40)).log.some((e) => e.fix && e.actor === "argon" && e.diagnosis));
  assert.equal(live(at(150)).status, "done");
  assert.ok(live(at(150)).convergence);
});

test("the publish approval appears once the live sample is done", () => {
  assert.ok(!at(20).approvals.some((a) => a.kind === "publish"));
  assert.ok(at(150).approvals.some((a) => a.kind === "publish" && a.status === "pending"));
});

test("diversity map puts the car baseline in a tight cluster", () => {
  const reg = mockRegistry(T0, T0 + 240);
  const pts = diversityMap(reg.samples, reg.baseline).points;
  const spread = (src) => {
    const q = pts.filter((p) => p.source === src);
    const mx = q.reduce((a, p) => a + p.x, 0) / q.length, my = q.reduce((a, p) => a + p.y, 0) / q.length;
    return Math.sqrt(q.reduce((a, p) => a + (p.x - mx) ** 2 + (p.y - my) ** 2, 0) / q.length);
  };
  assert.ok(spread("flowarc") > 4 * spread("car_baseline"));
  const full = diversityMap(reg.samples, reg.baseline).spread;
  assert.ok(full.flowarc > 2 * full.car_baseline);
});

test("bucket labels are short", () => {
  assert.equal(shortBucket("vehicles (land, air, sea, fictional, any era)"), "vehicles");
  assert.equal(shortBucket("abstract or parametric shapes"), "abstract");
});

test("views and mesh attempts appear as the live sample makes them", () => {
  assert.equal(live(at(5)).media, null);
  const drawn = live(at(20)).media;
  assert.deepEqual(Object.keys(drawn.views).sort(), ["front", "side", "three-quarter", "top"]);
  assert.equal(drawn.meshes.length, 0);
  const fixed = live(at(70)).media;
  const redrawn = live(at(70)).log.find((e) => /redrew the/.test(e.msg)).msg.split(" ")[4];
  assert.equal(fixed.views[redrawn].attempt, 2); // the redrawn view replaces the first
  assert.deepEqual(fixed.meshes.map((m) => m.attempt), [1, 2]);
  assert.notEqual(fixed.meshes[0].url, fixed.meshes[1].url); // the failed mesh and its fix
});

test("activity follows the next running sample once the live one is done", () => {
  const st = at(130);
  assert.equal(live(st).status, "done");
  const running = st.samples.filter((s) => s.status === "running").map((s) => s.id);
  assert.ok(running.length && running.includes(st.run.featured));
});

test("a mock approval stays with the viewer who made it", async () => {
  const { mockDecide } = await import("../lib/mock.js");
  const pub = (start, now) => mockRegistry(start, now).approvals.find((a) => a.kind === "publish");
  const alice = T0, bob = T0 + 60, now = T0 + 160;
  mockDecide(pub(alice, now)._id, "approved", alice, now);
  mockRegistry(bob, now + 2); // another viewer polls
  assert.equal(pub(alice, now + 4).status, "approved");
  assert.equal(pub(bob, now + 62)?.status ?? "pending", "pending");
});

test("only the current run counts: samples tagged with the latest phase, or from FLOWARC_RUN_FROM", () => {
  const sample = (id, phase, status, t) => ({ _id: id, stage: "done", status, concept: { name: id }, meta: phase ? { phase, gpu_seconds: 3600 } : { gpu_seconds: 3600 } });
  const samples = [sample("s00001", null, "failed"), sample("s00002", "pilot", "done"), sample("s00003", "real", "done"), sample("s00004", "real", "done")];
  const logs = samples.map((s, i) => ({ sample: s._id, t: T0 + i, msg: "x", stage: "concept" }));
  const st = buildState({ samples, logs, mode: "atlas", now: T0 + 10 });
  assert.deepEqual(st.samples.filter((s) => s.in_run).map((s) => s.id), ["s00003", "s00004"]);
  assert.equal(st.run.phase, "real");
  assert.equal(st.run.gpu_hours, 2);
  assert.equal(st.run.gpu_hours_all, 3);
  const from = buildState({ samples, logs, mode: "atlas", runFrom: "s00002", now: T0 + 10 });
  assert.deepEqual(from.samples.filter((s) => s.in_run).map((s) => s.id), ["s00002", "s00003", "s00004"]);
  const untagged = buildState({ samples: [sample("s00001", null, "done")], logs, mode: "atlas", now: T0 + 10 });
  assert.equal(untagged.run.scope, null);
  assert.ok(untagged.samples.every((s) => s.in_run));
});

test("similar shapes are the nearest embeddings, most alike first, never the sample itself", () => {
  const near = mockSimilar("s0001", T0 + 240);
  assert.ok(near.length > 0 && near.length <= 6);
  assert.ok(!near.some((s) => s.id === "s0001"));
  assert.ok(near.every((s, i) => i === 0 || near[i - 1].similarity >= s.similarity));
});

test("a batch-wide Argon call shows on every sample but counts once in the totals", () => {
  const sample = (id) => ({ _id: id, stage: "done", status: "done", concept: { name: id }, meta: {} });
  const call = (id, copy) => ({ sample: id, t: T0, msg: "gemini gemini-4-argon", stage: "concept", actor: "gemini", model: "gemini-4-argon", tokens: 100, shared: 2, copy });
  const st = buildState({ samples: [sample("s00001"), sample("s00002")], logs: [call("s00001", false), call("s00002", true)], mode: "atlas", now: T0 + 10 });
  assert.deepEqual(st.samples.map((s) => s.gemini.calls), [1, 1]);
  assert.deepEqual(st.samples.map((s) => s.gemini.copies?.tokens || 0), [0, 100]);
  assert.equal(st.run.gemini.calls, 1);
  assert.equal(st.run.gemini.tokens, 100);
});

test("a review shows in the agent log and stays open until the runner acts", () => {
  const T1 = T0 + 1000, now = T1 + 240;
  assert.ok(mockReview("s0012", "retry", "thicken the lid", T1, now));
  const s = buildState({ ...mockRegistry(T1, now), mode: "mock", now }).samples.find((x) => x.id === "s0012");
  const e = s.log.find((x) => x.review);
  assert.equal(e.actor, "human");
  assert.equal(e.reason, "thicken the lid");
  assert.deepEqual({ ...s.review, t: 0 }, { decision: "retry", note: "thicken the lid", t: 0, acted: false });
  assert.equal(mockReview("nope", "drop", "", T1, now), false);
});

test("the runner's GPU -1 (off the GPU) reads as no GPU", () => {
  const reg = mockRegistry(T0, T0 + 20);
  reg.samples = reg.samples.map((s) => (s._id === "s0016" ? { ...s, meta: { ...s.meta, gpu: -1 } } : s));
  assert.equal(live(buildState({ ...reg, mode: "mock", now: T0 + 20 })).gpu, null);
});

test("log lines never name Modal", () => {
  const samples = [{ _id: "s00001", stage: "sim", status: "running", concept: { name: "s00001" }, meta: {} }];
  const logs = [
    { sample: "s00001", t: T0, stage: "sim", msg: "sim: reset, Modal app restarted" },
    { sample: "s00001", t: T0 + 1, stage: "sim", msg: "sim: started on Modal", reason: "Modal timeout" },
  ];
  const log = buildState({ samples, logs, mode: "atlas", now: T0 + 10 }).samples[0].log;
  assert.deepEqual(log.map((e) => e.msg), ["sim: reset, app restarted", "sim: started"]);
  assert.equal(log[1].reason, "timeout");
});

test("a paused run is flagged from the runs document", () => {
  const reg = mockRegistry(T0, T0 + 20);
  assert.equal(buildState({ ...reg, mode: "mock", now: T0 + 20 }).run.paused, false);
  const st = buildState({ ...reg, run: { ...reg.run, paused: true, paused_note: "Gemini access lost" }, mode: "mock", now: T0 + 20 });
  assert.equal(st.run.paused, true);
  assert.equal(st.run.paused_note, "Gemini access lost");
});

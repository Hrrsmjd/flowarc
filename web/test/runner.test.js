import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildState } from "../lib/state.js";

// Shaped like what flowarc/pipeline.py (the runner) writes to Atlas, including older log lines.
const reg = JSON.parse(readFileSync(new URL("./fixtures/runner.json", import.meta.url)));
const st = buildState({ ...reg, mode: "atlas", now: 1792856143 });
const sample = (id) => st.samples.find((s) => s.id === id);

test("old log lines get their check and result from the message", () => {
  const mesh = sample("s00001").log.filter((e) => e.check === "mesh");
  assert.deepEqual(mesh.map((e) => e.failed), [true, false]);
  assert.equal(mesh[0].actor, "flash");
});

test("errors and running out of attempts count as failures", () => {
  assert.ok(sample("s00002").log.find((e) => e.msg.startsWith("images error")).failed);
  assert.ok(sample("s00001").log.find((e) => /out of attempts/.test(e.msg)).failed);
});

test("soft checks are marked soft; mesh silhouette becomes an IoU bar", () => {
  const log = sample("s00002").log;
  const conv = log.find((e) => e.check === "converged");
  assert.ok(conv.failed && conv.soft);
  assert.deepEqual(log.filter((e) => e.iou).map((e) => e.iou["min view"]), [0.62, 0.71]);
  assert.match(log.find((e) => e.check === "mesh").reason, /blob/);
});

test("solver statistics reach the sample viewer once past the sim stage", () => {
  assert.equal(sample("s00002").sim.cd_mean, 0.83);
  assert.equal(sample("s00001").zarr_gb, 0.41);
  assert.equal(st.run.featured, "s00002"); // the running one, not the newest pending one
});

test("media uploaded to GridFS keeps the latest view per name and every mesh attempt", () => {
  const media = [
    { sample: "s00001", kind: "view", name: "front", attempt: 1, t: 1, url: "api/media?id=a" },
    { sample: "s00001", kind: "view", name: "front", attempt: 2, t: 2, url: "api/media?id=b" },
    { sample: "s00001", kind: "mesh", name: "mesh", attempt: 2, t: 4, url: "api/media?id=d" },
    { sample: "s00001", kind: "mesh", name: "mesh", attempt: 1, t: 3, url: "api/media?id=c" },
  ];
  const m = buildState({ ...reg, media, mode: "atlas", now: 1792856143 }).samples.find((s) => s.id === "s00001").media;
  assert.equal(m.views.front.url, "api/media?id=b");
  assert.deepEqual(m.meshes.map((x) => x.url), ["api/media?id=c", "api/media?id=d"]);
});

test("views the runner put on the HF dataset show when GridFS has none", () => {
  const samples = reg.samples.map((s) =>
    s._id === "s00001" ? { ...s, meta: { ...s.meta, files: [{ path: "views/front.jpg", stage: "images" }, { path: "mesh/mesh.stl", stage: "mesh" }] } } : s,
  );
  const m = buildState({ ...reg, samples, mode: "atlas", now: 1792856143 }).samples.find((s) => s.id === "s00001").media;
  assert.deepEqual(Object.keys(m.views), ["front"]);
  assert.equal(m.views.front.url, "api/media?hf=s00001%2Fviews%2Ffront.jpg");
  assert.equal(m.meshes.length, 0);
});

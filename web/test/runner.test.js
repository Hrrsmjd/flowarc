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

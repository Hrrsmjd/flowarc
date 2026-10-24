import assert from "node:assert/strict";
import { test } from "node:test";
import { mockRegistry } from "../lib/mock.js";
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
  assert.equal(fixed.views.front.attempt, 2); // the redrawn front view replaces the first
  assert.deepEqual(fixed.meshes.map((m) => m.attempt), [1, 2]);
  assert.match(fixed.meshes[0].url, /^mock-media\/s0016\/mesh-1-mesh\.glb$/);
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

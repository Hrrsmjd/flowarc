import assert from "node:assert/strict";
import { test } from "node:test";
import { contentWords, hybridPipeline } from "../lib/atlas.js";

test("keyword search ignores filler words", () => {
  assert.equal(contentWords("something that eats"), "eats");
  assert.equal(contentWords("food"), "food");
  assert.equal(contentWords("what is it?"), "");
});

test("hybrid search weights the meaning of the name most, keywords on names only", () => {
  const [{ $rankFusion: f }, limit] = hybridPipeline("something that eats");
  assert.deepEqual(f.combination.weights, { semantic: 1, keyword: 1, name: 2 });
  assert.equal(f.input.pipelines.name[0].$vectorSearch.path, "concept.name");
  assert.equal(f.input.pipelines.semantic[0].$vectorSearch.path, "concept.description");
  assert.deepEqual(f.input.pipelines.keyword[0].$search.text, { query: "eats", path: "concept.name" });
  assert.deepEqual(limit, { $limit: 6 });
  const old = hybridPipeline("food", { withName: false })[0].$rankFusion;
  assert.ok(!old.input.pipelines.name && !old.combination.weights.name);
});

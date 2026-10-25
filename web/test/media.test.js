import assert from "node:assert/strict";
import { test } from "node:test";
import { CHUNK, byteRange } from "../api/media.js";

test("byte ranges for video seeking", () => {
  assert.equal(byteRange(undefined, 100), null);
  assert.deepEqual(byteRange("bytes=0-", 100), [0, 100]);
  assert.deepEqual(byteRange("bytes=10-19", 100), [10, 20]);
  assert.deepEqual(byteRange("bytes=90-500", 100), [90, 100]);
  assert.deepEqual(byteRange("bytes=-30", 100), [70, 100]);
  assert.equal(byteRange("bytes=100-", 100), false);
  assert.deepEqual(byteRange("bytes=0-", 2 * CHUNK), [0, CHUNK]); // an 8 MB video comes in two pieces
  assert.deepEqual(byteRange("bytes=0-", CHUNK), [0, CHUNK]);
});

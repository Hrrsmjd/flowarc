// MongoDB Atlas access for the API routes. The client is cached across invocations.

import { MongoClient } from "mongodb";

let client;

export const hasAtlas = () => Boolean(process.env.MONGODB_URI);

export async function db() {
  client ??= new MongoClient(process.env.MONGODB_URI, { appName: "flowarc-dashboard", maxPoolSize: 5 });
  await client.connect();
  return client.db(process.env.MONGODB_DB || "flowarc");
}

const NO_EMBEDDING = { projection: { embedding: 0 } };
const LOG_LIMIT = 4000;

export async function atlasRegistry({ withEmbeddings = false } = {}) {
  const d = await db();
  const [samples, logs, approvals, run, baseline, files] = await Promise.all([
    d.collection("samples").find({}, withEmbeddings ? { projection: { embedding: 1, status: 1, concept: 1 } } : NO_EMBEDDING).sort({ _id: 1 }).toArray(),
    withEmbeddings ? [] : d.collection("logs").find({}, { projection: { _id: 0, prompt: 0, reply: 0, trace: 0 } }).sort({ t: -1 }).limit(LOG_LIMIT).toArray(),
    withEmbeddings ? [] : d.collection("approvals").find({}).toArray(),
    d.collection("runs").findOne({ _id: "current" }),
    withEmbeddings ? d.collection("baseline").find({}).toArray() : [],
    withEmbeddings ? [] : d.collection("media.files").find({}, { projection: { metadata: 1 } }).toArray(),
  ]);
  // Views and meshes uploaded by flowarc/media.py, streamed back by api/media.
  const media = files
    .filter((f) => f.metadata?.sample)
    .map(({ _id, metadata: m }) => ({ sample: m.sample, kind: m.kind, name: m.name, attempt: m.attempt, t: m.t, url: `api/media?id=${_id}` }));
  return { run: run || {}, samples, logs: logs.reverse(), approvals, baseline, media };
}

// One sample's Gemini calls with their prompts and replies, oldest first.
export async function atlasCalls(sample) {
  const d = await db();
  return d.collection("logs").find({ sample, actor: "gemini" }, { projection: { _id: 0, trace: 0 } }).sort({ t: 1 }).limit(300).toArray();
}

export async function atlasDecide(id, status, by) {
  const d = await db();
  const r = await d.collection("approvals").updateOne(
    { _id: id, status: "pending" },
    { $set: { status, decided_at: Date.now() / 1000, decided_by: by } },
  );
  return r.modifiedCount === 1;
}

// Atlas Search over sample names and descriptions (index `samples_text`, made by
// scripts/setup_atlas.py), with a plain regex match if the index isn't there.
export async function atlasSearch(q) {
  const d = await db();
  const project = { $project: { name: "$concept.name", bucket: "$concept.bucket", status: 1 } };
  try {
    const rows = await d.collection("samples").aggregate([
      { $search: { index: "samples_text", text: { query: q, path: ["concept.name", "concept.description"], fuzzy: { maxEdits: 1 } } } },
      { $limit: 8 },
      project,
    ]).toArray();
    return { engine: "atlas-search", results: rows.map(({ _id, ...r }) => ({ id: _id, ...r })) };
  } catch {
    const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
    const rows = await d.collection("samples").aggregate([
      { $match: { $or: [{ "concept.name": re }, { "concept.description": re }] } },
      { $limit: 8 },
      project,
    ]).toArray();
    return { engine: "regex", results: rows.map(({ _id, ...r }) => ({ id: _id, ...r })) };
  }
}

// One GridFS file from the `media` bucket, or null; open([start, end)) streams it, or a byte range.
export async function atlasMedia(id) {
  const { GridFSBucket, ObjectId } = await import("mongodb");
  if (!ObjectId.isValid(id)) return null;
  const d = await db();
  const bucket = new GridFSBucket(d, { bucketName: "media" });
  const [file] = await bucket.find({ _id: new ObjectId(id) }).toArray();
  if (!file) return null;
  return { file, open: (range) => bucket.openDownloadStream(file._id, range ? { start: range[0], end: range[1] } : {}) };
}

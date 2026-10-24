// GET /api/media?id=: a view (JPEG) or mesh (GLB) from the Atlas GridFS bucket `media`.
// GET /api/media?hf=<sample>/views/<name>.jpg: a view from the private HF dataset, fetched
// with HF_TOKEN. In mock mode the files are static (public/mock-media), so this isn't used.
import { atlasMedia, hasAtlas } from "../lib/atlas.js";
import { send } from "../lib/http.js";

export default async function handler(req, res) {
  try {
    const q = new URL(req.url, "http://x").searchParams;
    if (q.has("hf")) return hf(q.get("hf"), res);
    const id = q.get("id") || "";
    const hit = hasAtlas() ? await atlasMedia(id) : null;
    if (!hit) return send(res, 404, { error: "not found" });
    res.writeHead(200, {
      "Content-Type": hit.file.metadata?.content_type || "application/octet-stream",
      "Content-Length": hit.file.length,
      "Cache-Control": "public, max-age=31536000, immutable", // files never change; a new upload gets a new id
    });
    hit.stream.pipe(res);
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

const HF_PATH = /^[\w-]+\/views\/[\w-]+\.jpg$/; // views only: meshes are too big for a function response

async function hf(path, res) {
  const repo = process.env.FLOWARC_HF_REPO;
  if (!repo || !HF_PATH.test(path)) return send(res, 404, { error: "not found" });
  const r = await fetch(`https://huggingface.co/datasets/${repo}/resolve/main/samples/${path}`, {
    headers: process.env.HF_TOKEN ? { Authorization: `Bearer ${process.env.HF_TOKEN}` } : {},
  });
  if (!r.ok) return send(res, r.status === 404 ? 404 : 502, { error: `HF ${r.status}` });
  res.writeHead(200, { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=300" });
  res.end(Buffer.from(await r.arrayBuffer()));
}

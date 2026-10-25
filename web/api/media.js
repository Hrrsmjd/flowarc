// GET /api/media?id=: a view (JPEG), mesh (GLB) or flow video (MP4) from the Atlas GridFS bucket
// `media`. Byte ranges are served too: Safari won't play a video without them.
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
    const size = hit.file.length;
    const range = byteRange(req.headers.range, size);
    if (range === false) {
      res.writeHead(416, { "Content-Range": `bytes */${size}` });
      return res.end();
    }
    const headers = {
      "Content-Type": hit.file.metadata?.content_type || "application/octet-stream",
      "Accept-Ranges": "bytes",
      "Cache-Control": "public, max-age=31536000, immutable", // files never change; a new upload gets a new id
    };
    if (range) {
      res.writeHead(206, { ...headers, "Content-Length": range[1] - range[0], "Content-Range": `bytes ${range[0]}-${range[1] - 1}/${size}` });
    } else {
      res.writeHead(200, { ...headers, "Content-Length": size });
    }
    hit.open(range).pipe(res);
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

export const CHUNK = 4_000_000; // a function response may be at most 4.5 MB; the player asks for the rest

// "bytes=a-b" -> [a, b + 1), at most CHUNK bytes; null = whole file; false = unsatisfiable.
export function byteRange(header, size) {
  const m = /^bytes=(\d*)-(\d*)$/.exec(header || "");
  if (!m || (!m[1] && !m[2])) return null;
  const start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
  const end = m[1] && m[2] ? Math.min(Number(m[2]) + 1, size) : size;
  return start < end ? [start, Math.min(end, start + CHUNK)] : false;
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

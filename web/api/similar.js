// GET /api/similar?id=: the shapes whose concept is closest to this one's (Atlas Vector Search).
import { atlasSimilar, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockSimilar } from "../lib/mock.js";

export default async function handler(req, res) {
  const id = new URL(req.url, "http://x").searchParams.get("id")?.slice(0, 40) || "";
  if (!id) return send(res, 200, { results: [] });
  try {
    const k = Math.min(12, Math.max(1, Number(new URL(req.url, "http://x").searchParams.get("k")) || 6));
    send(res, 200, hasAtlas() ? await atlasSimilar(id, k) : { engine: "mock", results: mockSimilar(id, startParam(req), k) });
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

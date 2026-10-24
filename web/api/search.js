// GET /api/search?q=...: find samples by name or description (Atlas Search when connected).
import { atlasSearch, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockSearch } from "../lib/mock.js";

export default async function handler(req, res) {
  const q = new URL(req.url, "http://x").searchParams.get("q")?.trim().slice(0, 100) || "";
  if (!q) return send(res, 200, { results: [] });
  try {
    send(res, 200, hasAtlas() ? await atlasSearch(q) : { engine: "mock", results: mockSearch(q, startParam(req)) });
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

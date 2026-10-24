// GET /api/media?id=: a view (JPEG) or mesh (GLB) from the Atlas GridFS bucket `media`.
// In mock mode the files are static (public/mock-media), so this route isn't used.
import { atlasMedia, hasAtlas } from "../lib/atlas.js";
import { send } from "../lib/http.js";

export default async function handler(req, res) {
  try {
    const id = new URL(req.url, "http://x").searchParams.get("id") || "";
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

// GET /api/map: 2D projection of concept embeddings, ours vs the car-only baseline.
import { atlasRegistry, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockRegistry } from "../lib/mock.js";
import { diversityMap } from "../lib/state.js";

export default async function handler(req, res) {
  try {
    const reg = hasAtlas() ? await atlasRegistry({ withEmbeddings: true }) : mockRegistry(startParam(req));
    send(res, 200, diversityMap(reg.samples, reg.baseline));
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

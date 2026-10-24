// GET /api/state: run summary, samples with their logs, and approvals. Polled by the page.
import { atlasRegistry, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockRegistry } from "../lib/mock.js";
import { buildState } from "../lib/state.js";

export default async function handler(req, res) {
  try {
    const atlas = hasAtlas();
    const reg = atlas ? await atlasRegistry() : mockRegistry(startParam(req));
    send(res, 200, buildState({ ...reg, mode: atlas ? "atlas" : "mock" }));
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

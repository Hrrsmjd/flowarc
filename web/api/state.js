// GET /api/state: run summary, samples with their logs, and approvals. Polled by the page.
import { atlasRegistry, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockRegistry } from "../lib/mock.js";
import { buildState } from "../lib/state.js";

export default async function handler(req, res) {
  try {
    const atlas = hasAtlas();
    const reg = atlas ? await atlasRegistry() : mockRegistry(startParam(req));
    const st = buildState({ ...reg, mode: atlas ? "atlas" : "mock", hfRepo: process.env.FLOWARC_HF_REPO || "", runFrom: process.env.FLOWARC_RUN_FROM || "" });
    if (atlas) st.db = process.env.MONGODB_DB || "flowarc";
    // The CDN shares the answer for a few seconds while a run is live, two minutes when idle.
    const live = !st.run.paused && st.samples.some((x) => x.status === "running");
    send(res, 200, st, live ? 4 : 120);
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

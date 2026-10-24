// GET /api/sample?id=: one sample's Gemini calls (model, prompt, reply, tokens), for the Prompts list.
import { atlasCalls, hasAtlas } from "../lib/atlas.js";
import { send, startParam } from "../lib/http.js";
import { mockRegistry } from "../lib/mock.js";

const keep = ({ t, stage, model, prompt, reply, seconds, tokens }) => ({ t, stage, model, prompt, reply, seconds, tokens });

export default async function handler(req, res) {
  try {
    const id = new URL(req.url, "http://x").searchParams.get("id") || "";
    const logs = hasAtlas()
      ? await atlasCalls(id)
      : mockRegistry(startParam(req)).logs.filter((e) => e.sample === id && e.actor === "gemini");
    send(res, 200, { calls: logs.map(keep) });
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

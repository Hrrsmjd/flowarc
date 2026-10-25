// POST /api/review {sample, decision: "accept" | "retry" | "drop", note?}: a person's call on a
// flagged or failed sample. Atlas keeps it in `reviews` for the runner and as a line in the
// agent log. Same token rule as /api/approve, so a public URL can't steer the run.
import { atlasReview, hasAtlas } from "../lib/atlas.js";
import { readJson, send, startParam } from "../lib/http.js";
import { mockReview } from "../lib/mock.js";

const DECISIONS = ["accept", "retry", "drop"];

export default async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "POST only" });
  const token = process.env.APPROVAL_TOKEN;
  if (!token && hasAtlas()) return send(res, 403, { error: "reviews are off: set APPROVAL_TOKEN on the server" });
  if (token && req.headers["x-approval-token"] !== token) return send(res, 401, { error: "approval token required" });
  try {
    const { sample, decision, note = "" } = await readJson(req);
    if (typeof sample !== "string" || !DECISIONS.includes(decision) || typeof note !== "string") {
      return send(res, 400, { error: "need sample and decision (accept, retry or drop)" });
    }
    const clean = note.trim().slice(0, 500);
    const ok = hasAtlas() ? await atlasReview(sample, decision, clean, "dashboard") : mockReview(sample, decision, clean, startParam(req));
    send(res, ok ? 200 : 404, ok ? { ok, decision } : { error: "no such sample" });
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

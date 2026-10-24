// POST /api/approve {id, decision: "approved" | "rejected"}: answer a human-approval request.
// The pipeline waits on the `approvals` document before publishing or going over budget.
// Set APPROVAL_TOKEN to require the same token in the x-approval-token header.
import { atlasDecide, hasAtlas } from "../lib/atlas.js";
import { readJson, send } from "../lib/http.js";
import { mockDecide } from "../lib/mock.js";

export default async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "POST only" });
  const token = process.env.APPROVAL_TOKEN;
  if (token && req.headers["x-approval-token"] !== token) return send(res, 401, { error: "approval token required" });
  try {
    const { id, decision } = await readJson(req);
    if (typeof id !== "string" || !["approved", "rejected"].includes(decision)) {
      return send(res, 400, { error: "need id and decision (approved or rejected)" });
    }
    if (!hasAtlas()) {
      mockDecide(id, decision);
      return send(res, 200, { ok: true, status: decision });
    }
    const ok = await atlasDecide(id, decision, "dashboard");
    send(res, ok ? 200 : 409, ok ? { ok, status: decision } : { error: "not pending" });
  } catch (e) {
    console.error(e);
    send(res, 500, { error: String(e.message || e) });
  }
}

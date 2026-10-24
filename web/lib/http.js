export function send(res, code, body) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

export async function readJson(req) {
  if (req.body && typeof req.body === "object") return req.body; // parsed by Vercel
  let raw = "";
  for await (const chunk of req) raw += chunk;
  return raw ? JSON.parse(raw) : {};
}

// ?start=<epoch seconds>: where the mock replay begins for this viewer.
export const startParam = (req) => Number(new URL(req.url, "http://x").searchParams.get("start")) || 0;

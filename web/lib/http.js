// cdnSeconds > 0 lets Vercel's CDN share a 200 among viewers for that long (the browser still
// doesn't cache it), so many open tabs cost about one function call per window, not one each.
export function send(res, code, body, cdnSeconds = 0) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  if (code === 200 && cdnSeconds > 0) res.setHeader("Vercel-CDN-Cache-Control", `max-age=${cdnSeconds}`);
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

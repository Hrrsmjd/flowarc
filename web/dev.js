// Local server with the same routes as Vercel: `npm run dev` (or `vercel dev`).
// Reads MONGODB_URI / MONGODB_DB / APPROVAL_TOKEN from the environment; mock replay without them.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const PORT = Number(process.env.PORT || 3000);
const PUBLIC = new URL("./public/", import.meta.url).pathname;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".glb": "model/gltf-binary" };

createServer(async (req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  if (path.startsWith("/api/")) {
    const name = path.slice(5).replace(/[^a-z]/g, "");
    try {
      const mod = await import(`./api/${name}.js`);
      return await mod.default(req, res);
    } catch {
      res.statusCode = 404;
      return res.end("not found");
    }
  }
  const file = normalize(join(PUBLIC, path === "/" ? "index.html" : path));
  if (!file.startsWith(PUBLIC)) return res.writeHead(403).end();
  try {
    const body = await readFile(file);
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" }).end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
}).listen(PORT, () => console.log(`dashboard on http://localhost:${PORT} (${process.env.MONGODB_URI ? "Atlas" : "mock replay"})`));

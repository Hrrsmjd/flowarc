// Theme drafts for the dashboard. Same content in every theme: overview first, then visuals,
// detail text folded away at the bottom or in the drawer. Data is a fixed snapshot.
import { createViewer } from "../mesh.js";
import { SAMPLES } from "./data.js";

const THEMES = [
  { id: "lab", name: "Lab Black", from: "General Intuition", fx: "ascii" },
  { id: "nebula", name: "Nebula", from: "Aleph" },
  { id: "tiles", name: "Tiles", from: "BeyondMath" },
  { id: "signal", name: "Signal", from: "PhysicsX" },
  { id: "notebook", name: "Notebook", from: "Physical Intelligence" },
  { id: "voxel", name: "Voxel", from: "Wild", fx: "pixel" },
  { id: "press", name: "Press", from: "Stripe Press" },
  { id: "horizon", name: "Horizon", from: "American Supercritical" },
  { id: "tunnel", name: "Wind Tunnel", from: "our own flow renders" },
  { id: "blueprint", name: "Blueprint", from: "engineering drawings" },
];
const STAGES = ["concept", "images", "mesh", "sim", "render", "package"];
const RUN = { total: 100, done: 8, running: 6, failed: 2, kinds: 7, fixed: 15, flagged: 2, gpuHours: 3.4 };
RUN.waiting = RUN.total - RUN.done - RUN.running - RUN.failed;
const GPUS = [
  { gpu: 1, name: "Dumpster Hauler Truck", stage: "sim", pct: 0.71 },
  { gpu: 2, name: "Bonsai Bookshelf", stage: "sim", pct: 0.44 },
  { gpu: 3, name: "Hourglass Sand Timer", stage: "render", pct: 0.82 },
  { gpu: 4, name: "Armored Bulldozer", stage: "sim", pct: 0.18 },
  { gpu: 5, name: "Three-Tier Cake Stand", stage: "mesh", pct: 0.5, tries: 2 },
  { gpu: 6, name: "Hurdle Barrier", stage: "mesh", pct: 0.3, tries: 3 },
];
const LOG = [
  ["2 m", "Argon", "fix", "Hurdle Barrier: views disagree on the base legs. Redrawing all four views."],
  ["5 m", "Flash", "fail", "Hurdle Barrier: views_consistent failed. Side and top show T-shaped legs, front shows them forward only."],
  ["9 m", "Runner", "pass", "Hourglass Sand Timer: drag settled after 18 L/U. Rendering video."],
  ["14 m", "Argon", "fix", "Three-Tier Cake Stand: top plate is 0.4% thick. Thickening thin parts to 2%."],
  ["21 m", "Flash", "pass", "Observatory Dome: mesh review passed. Telescope barrel faces the wind."],
  ["26 m", "Argon", "fix", "Aperture Skyscraper: mesh came out 37° off axis. Lined up the long axis, then tried 4 headings."],
  ["33 m", "Runner", "pass", "Five-Tier Pagoda: packaged 301 frames into Zarr (2.1 GB)."],
  ["41 m", "Argon", "pass", "Prickly Pear Armchair: concept is novel (nearest match 0.71)."],
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const reTxt = (re) => { const e = Math.floor(Math.log10(re)); const m = re / 10 ** e; return `${m.toFixed(1)}×10<sup>${e}</sup>`; };
const reRaw = (re) => { const e = Math.floor(Math.log10(re)); return `${(re / 10 ** e).toFixed(1)}e${e}`; };

// ---------- overview ----------
function overview() {
  const seg = [["done", RUN.done], ["running", RUN.running], ["failed", RUN.failed], ["waiting", RUN.waiting]];
  $("progress").innerHTML = seg.map(([k, n]) => `<span class="seg ${k}" style="flex:${n}"></span>`).join("");
  $("progress-key").innerHTML = seg.map(([k, n]) => `<span class="key ${k}"><i></i>${n} ${k}</span>`).join("");
  const stats = [
    ["Kinds of shape", RUN.kinds, "of 8 planned"],
    ["Fixed by Argon", RUN.fixed, "no human needed"],
    ["Flagged", RUN.flagged, "waiting for a look"],
    ["GPU-hours", RUN.gpuHours, "7 A100s"],
  ];
  $("stats").innerHTML = stats.map(([l, n, s]) => `<div class="stat"><dt class="label">${l}</dt><dd class="n">${n}</dd><dd class="s">${s}</dd></div>`).join("");
}

// ---------- hero ----------
let viewer;
const hero = SAMPLES[1];
function heroCard() {
  $("hero-name").textContent = hero.name;
  $("hero-meta").innerHTML = `${esc(hero.bucket)} · Re ${reTxt(hero.re)} · ${hero.yaw}° yaw`;
  $("stepper").innerHTML = STAGES.map((s) => `<li class="done" title="${s}"><span>${s}</span></li>`).join("");
}

function gpus() {
  $("gpus").innerHTML = GPUS.map((g) => {
    const i = STAGES.indexOf(g.stage);
    return `<div class="gpu"><div class="gpu-top"><span class="label">GPU ${g.gpu}</span><span class="stage">${g.stage}${g.tries ? ` · try ${g.tries}` : ""}</span></div>
      <strong>${esc(g.name)}</strong>
      <div class="pips">${STAGES.map((s, j) => `<i class="${j < i ? "done" : j === i ? "now" : ""}"></i>`).join("")}</div>
      <div class="gbar"><span style="width:${g.pct * 100}%"></span></div></div>`;
  }).join("");
}

function gallery() {
  const tiles = SAMPLES.map((s, i) => `<button class="tile" type="button" data-i="${i}">
      <span class="pic"><img src="${s.views["three-quarter"]}" alt="" loading="lazy"></span>
      <span class="t-id">${s.id}</span><span class="t-name">${esc(s.name)}</span>
      <span class="t-meta">${esc(s.bucket)} · Re ${reTxt(s.re)}</span></button>`);
  const pending = GPUS.slice(0, 4).map((g) => `<div class="tile ghost"><span class="pic"><span class="wait">${g.stage}…</span></span>
      <span class="t-id">GPU ${g.gpu}</span><span class="t-name">${esc(g.name)}</span><span class="t-meta">in progress</span></div>`);
  $("gallery").innerHTML = tiles.concat(pending).join("");
  $("gallery").querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => openDrawer(+b.dataset.i)));
}

// ---------- diversity map ----------
function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }
function divmap() {
  const r = rng(7);
  const buckets = ["vehicles", "animals", "plants", "furniture", "buildings", "sports gear", "combinations", "abstract"];
  const centres = buckets.map((_, i) => [0.5 + 0.33 * Math.cos(i * 0.785 + 0.3), 0.5 + 0.36 * Math.sin(i * 0.785 + 0.3)]);
  const counts = [22, 19, 17, 16, 13, 16, 12, 6];
  const gauss = () => (r() + r() + r() - 1.5) / 1.5;
  const W = 720, H = 420, P = 24;
  const X = (x) => P + x * (W - 2 * P), Y = (y) => P + y * (H - 2 * P);
  let g = "";
  for (let i = 0; i < 46; i++) g += `<circle class="base" cx="${X(0.18 + gauss() * 0.05)}" cy="${Y(0.82 + gauss() * 0.05)}" r="3.2"/>`;
  buckets.forEach((b, k) => {
    for (let i = 0; i < Math.round(counts[k] * 0.9); i++) g += `<circle class="ours b${k}" cx="${X(centres[k][0] + gauss() * 0.11)}" cy="${Y(centres[k][1] + gauss() * 0.12)}" r="4"/>`;
  });
  SAMPLES.forEach((s, i) => {
    const k = Math.max(0, buckets.indexOf(s.bucket.split(" ")[0] === "furniture" ? "furniture" : s.bucket));
    const x = X(centres[k][0] + gauss() * 0.06), y = Y(centres[k][1] + gauss() * 0.06);
    g += `<g class="pin" data-i="${i}" transform="translate(${x},${y})"><circle r="15"/><image href="${s.views["three-quarter"]}" x="-13" y="-13" width="26" height="26" clip-path="circle(13px)"/></g>`;
  });
  $("divmap").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shape map">${g}</svg>
    <div class="map-key"><span><i class="ours"></i>FlowArc</span><span><i class="base"></i>A car-only dataset</span></div>`;
  $("divmap").querySelectorAll(".pin").forEach((p) => p.addEventListener("click", () => openDrawer(+p.dataset.i)));
  const max = Math.max(...counts);
  $("coverage").innerHTML = `<p class="label">Planned shapes by kind</p>` + buckets.map((b, k) => `<div class="cov"><span>${b}</span><span class="track"><span class="fill b${k}" style="width:${(100 * counts[k]) / max}%"></span></span><span class="n">${counts[k]}</span></div>`).join("");
}

// ---------- details ----------
function details() {
  $("log").innerHTML = LOG.map(([t, who, kind, msg]) => `<li class="${kind}"><span class="t">${t} ago</span><span class="who">${who}</span><span class="msg">${esc(msg)}</span></li>`).join("");
  const rows = SAMPLES.map((s) => [s.id, s.name, STAGES.map(() => "✓")]).concat(GPUS.map((g, i) => [`s000${22 + i}`, g.name, STAGES.map((st, j) => (j < STAGES.indexOf(g.stage) ? "✓" : j === STAGES.indexOf(g.stage) ? "●" : ""))]));
  $("stages").innerHTML = `<thead><tr><th>Sample</th><th>Name</th>${STAGES.map((s) => `<th>${s}</th>`).join("")}</tr></thead><tbody>${rows.map(([id, n, c]) => `<tr><td class="mono">${id}</td><td>${esc(n)}</td>${c.map((x) => `<td class="c">${x}</td>`).join("")}</tr>`).join("")}</tbody>`;
  const use = [["gemini-4-argon", 41, "118.2k"], ["gemini-3.8-flash", 67, "64.0k"], ["gemini-nano-banana-2.1", 45, "38.7k"]];
  $("usage").innerHTML = `<thead><tr><th>Model</th><th>Calls</th><th>Tokens</th></tr></thead><tbody>${use.map((u) => `<tr><td class="mono">${u[0]}</td><td>${u[1]}</td><td>${u[2]}</td></tr>`).join("")}<tr class="sum"><td>Total</td><td>153</td><td>220.9k</td></tr></tbody>`;
}

// ---------- drawer ----------
function openDrawer(i) {
  const s = SAMPLES[i];
  const checks = [["Concept is new", "nearest match 0.7"], ["Views agree", "Flash"], ["Mesh is watertight", "one body, no thin parts"], ["Mesh looks right", "Flash review"], ["Drag settled", "within 2%"]];
  $("drawer-body").innerHTML = `
    <p class="label">${s.id} · ${esc(s.bucket)}</p>
    <h2 class="d-title">${esc(s.name)}</h2>
    <div class="d-hero"><img src="${s.views["three-quarter"]}" alt=""></div>
    <div class="d-views">${["front", "side", "top"].map((v) => `<figure><img src="${s.views[v]}" alt=""><figcaption>${v}</figcaption></figure>`).join("")}</div>
    <dl class="d-facts"><div><dt>Reynolds</dt><dd>${reTxt(s.re)}</dd></div><div><dt>Facing</dt><dd>${esc(s.facing)}</dd></div><div><dt>Ground</dt><dd>${s.ground ? "yes" : "no"}</dd></div><div><dt>Yaw</dt><dd>${s.yaw}°</dd></div></dl>
    <ul class="d-checks">${checks.map(([c, n]) => `<li><span class="ok">✓</span>${c}<span class="note">${n}</span></li>`).join("")}</ul>
    <details class="fold"><summary><span>Description</span></summary><p class="d-desc">${esc(s.desc)}</p></details>
    <details class="fold"><summary><span>Prompts</span><span class="count">3</span></summary>
      <ul class="prompts">
        <li><span class="mono">gemini-4-argon</span> · 3.2k tokens<pre>Pick one new object for a wind-tunnel dataset. Avoid anything close to: ${esc(SAMPLES.filter((x) => x !== s).slice(0, 3).map((x) => x.name).join(", "))}…</pre></li>
        <li><span class="mono">gemini-nano-banana-2.1</span> · 14.2k tokens<pre>Product photo of ${esc(s.desc.slice(0, 140))}…</pre></li>
        <li><span class="mono">gemini-3.8-flash</span> · 8.3k tokens<pre>These are front, side, top and three-quarter views. Do they show the same object?</pre></li>
      </ul></details>
    <div class="d-links"><a class="btn" href="${s.mesh}">Mesh (GLB)</a><a class="btn" href="#">Zarr on HF</a></div>`;
  $("drawer").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
  $("scrim").hidden = false;
}
function closeDrawer() {
  $("drawer").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
  $("scrim").hidden = true;
}

// ---------- flow effects (ASCII / pixel grid drawn from the flow video) ----------
let fxStop = null;
function startFx(kind) {
  if (fxStop) fxStop();
  fxStop = null;
  const frame = $("flow-frame");
  frame.classList.toggle("fx-on", !!kind);
  if (!kind) return;
  const v = $("flow-video");
  const c = document.createElement("canvas");
  c.className = "fx";
  frame.appendChild(c);
  const off = document.createElement("canvas");
  const ox = off.getContext("2d", { willReadFrequently: true });
  const css = getComputedStyle(document.documentElement);
  const pal = ["--fx-1", "--fx-2", "--fx-3", "--fx-4", "--fx-empty"].map((k) => css.getPropertyValue(k).trim());
  const ramp = ".:-=+*#%@";
  let raf, last = 0;
  const draw = (t) => {
    raf = requestAnimationFrame(draw);
    if (t - last < 70 || !v.videoWidth) return;
    last = t;
    const w = frame.clientWidth, h = frame.clientHeight, dpr = Math.min(devicePixelRatio, 2);
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const cw = kind === "ascii" ? 8 : 9, chh = kind === "ascii" ? 13 : 9;
    const cols = Math.floor(w / cw), rows = Math.floor(h / chh);
    off.width = cols; off.height = rows;
    const A = w / h, a = v.videoWidth / v.videoHeight;
    let sw = v.videoWidth, sh = v.videoHeight;
    if (a > A) sw = sh * A; else sh = sw / A;
    ox.drawImage(v, (v.videoWidth - sw) / 2, (v.videoHeight - sh) / 2, sw, sh, 0, 0, cols, rows);
    const px = ox.getImageData(0, 0, cols, rows).data;
    ctx.font = `600 12px "Geist Mono", ui-monospace, monospace`;
    ctx.textBaseline = "top";
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const o = (y * cols + x) * 4, r = px[o], g = px[o + 1], b = px[o + 2];
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b), sat = (mx - mn) / 255;
      const d = Math.min(1, Math.max(0, (0.93 - (0.299 * r + 0.587 * g + 0.114 * b) / 255) / 0.75));
      if (kind === "ascii") {
        if (d < 0.05 && sat < 0.08) continue;
        ctx.fillStyle = sat > 0.18 ? `rgb(${Math.min(255, r * 1.5)},${Math.min(255, g * 1.5)},${Math.min(255, b * 1.5)})` : `rgba(255,255,255,${0.3 + 0.7 * d})`;
        ctx.fillText(ramp[Math.min(ramp.length - 1, Math.floor(Math.max(d, sat) * ramp.length))], x * cw, y * chh);
      } else {
        let col = pal[4];
        if (sat > 0.16) col = r > g ? pal[2] : pal[1];
        else if (d > 0.45) col = pal[0];
        else if (d > 0.08) col = pal[3];
        if (col === pal[4] && !pal[4]) continue;
        ctx.fillStyle = col;
        ctx.fillRect(x * cw + 0.5, y * chh + 0.5, cw - 1, chh - 1);
      }
    }
  };
  raf = requestAnimationFrame(draw);
  fxStop = () => { cancelAnimationFrame(raf); c.remove(); };
}

// ---------- theme switching ----------
let themeToken = 0;
function setTheme(id) {
  const t = THEMES.find((x) => x.id === id) || THEMES[0];
  document.documentElement.dataset.theme = t.id;
  const link = $("theme-css");
  const mine = ++themeToken;
  const ready = () => {
    if (mine !== themeToken) return;
    themeToken++;
    viewer.clear();
    viewer.show(hero.mesh);
    startFx(t.fx);
  };
  if (!link.href.endsWith(`t/${t.id}.css`)) {
    link.onload = link.onerror = ready;
    link.href = `t/${t.id}.css`;
    setTimeout(ready, 1500);
  } else requestAnimationFrame(ready);
  const u = new URL(location.href);
  u.searchParams.set("t", t.id);
  history.replaceState(null, "", u);
  document.title = `FlowArc · ${t.name}`;
  $("switcher").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.id === t.id));
  $("sw-name").innerHTML = `<b>${THEMES.indexOf(t) + 1}. ${t.name}</b> <span>after ${t.from}</span>`;
}

function switcher() {
  $("switcher").innerHTML = `<span id="sw-name"></span><span class="sw-dots">${THEMES.map((t, i) => `<button type="button" data-id="${t.id}" title="${t.name}">${i + 1}</button>`).join("")}</span>`;
  $("switcher").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.id)));
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") return closeDrawer();
    const i = THEMES.findIndex((t) => t.id === document.documentElement.dataset.theme);
    if (e.key === "ArrowRight") setTheme(THEMES[(i + 1) % THEMES.length].id);
    if (e.key === "ArrowLeft") setTheme(THEMES[(i + THEMES.length - 1) % THEMES.length].id);
  });
}

overview();
heroCard();
gpus();
gallery();
divmap();
details();
switcher();
$("scrim").addEventListener("click", closeDrawer);
$("drawer-close").addEventListener("click", closeDrawer);
viewer = createViewer($("mesh-frame"));
if (new URLSearchParams(location.search).has("clean")) document.body.classList.add("clean");
setTheme(new URLSearchParams(location.search).get("t") || "lab");

// The stage: presenter mode as a dark full-screen view for a three-minute demo. The live shape
// is large, each agent has a mark and talks in the agent feed as the sample moves along, and
// the Atlas panel shows the shared memory and takes searches.
// Uses app.js's globals (state, selectedSample, viewUrl, esc, tick, select, STAGES, ...).

const CREW = {
  argon: { name: "Argon", role: "Supervisor", color: "#a594ff" },
  "nano-banana": { name: "Nano Banana", role: "Image gen", color: "#ffd84d" },
  hunyuan3d: { name: "Hunyuan3D", role: "Mesh gen", color: "#ff8f66" },
  flash: { name: "Flash", role: "Verifier", color: "#ffb02e" },
  fluidx3d: { name: "FluidX3D", role: "CFD solver", color: "#4cc9f0" },
  atlas: { name: "Atlas", role: "Memory", color: "#00ed64" },
};
// Who owns each stage, for lines that name no one and for the stage track.
const OWNER = { concept: "argon", images: "nano-banana", mesh: "hunyuan3d", sim: "fluidx3d", render: "fluidx3d", package: "atlas" };


// ---------- what the crew says ----------
const CHECKS = {
  view_consistency: ["All four views show the same shape", "The views don't match each other"],
  views_consistent: ["All four views show the same shape", "The views don't match each other"],
  flash_review: ["The mesh matches the drawings", "The mesh doesn't match the drawings"],
  mesh: ["The mesh matches the drawings", "The mesh doesn't match the drawings"],
  geometry: ["Watertight, in one piece", "The mesh has holes or loose bits"],
  symmetry: ["Symmetric where it should be", "It came out lopsided"],
  stability: ["The simulation is stable", "The simulation blew up"],
  stable: ["The simulation is stable", "The simulation blew up"],
  grid_convergence: ["Drag agrees on two grids", "Drag changes with the grid"],
  converged: ["Drag agrees on two grids", "Drag changes with the grid"],
  video_review: ["The flow looks physical", "Something's off in the flow"],
};
function line(e) {
  if (/^advanced$/.test(e.msg)) return null;
  if (e.actor === "gemini") return null; // calls show as "typing" instead
  if (e.fix) return { who: "argon", kind: "fix", text: `Fix: ${fixText(e.msg)}`, sub: e.diagnosis };
  if (e.check === "novel" || e.check === "novelty") {
    const sim = e.similarity != null ? ` The closest is ${Math.round(e.similarity * 100)}% alike.` : "";
    return e.failed
      ? { who: "atlas", kind: "fail", text: `Too close to a shape we already have.${sim} Back to Argon.` }
      : { who: "atlas", kind: "mem", text: `Searched every shape with Vector Search: this one is new.${sim}` };
  }
  const who = CREW[e.actor] ? e.actor : e.actor === "embedding" ? "atlas" : OWNER[e.stage] || "argon";
  if (e.check) {
    const [ok, bad] = CHECKS[e.check] || [`${e.check.replace(/_/g, " ")} check passed`, `${e.check.replace(/_/g, " ")} check failed`];
    const iou = e.iou && Object.values(e.iou).length ? ` (overlap ${Math.round(Math.min(...Object.values(e.iou)) * 100)}%)` : "";
    const cd = e.d_cd != null ? ` (Δ ${(e.d_cd * 100).toFixed(1)}%)` : "";
    return e.failed
      ? { who, kind: e.soft ? "warn" : "fail", text: `✕ ${bad}`, sub: e.reason }
      : { who, kind: "ok", text: `✓ ${ok}${iou}${cd}` };
  }
  // "FluidX3D: 64 cells/L done" -> "64 cells/L done": the name is already on the bubble.
  return { who, kind: e.failed ? "fail" : "", text: e.msg.replace(new RegExp(`^${CREW[who].name}:?\\s+`), "").replace(/^\w/, (c) => c.toUpperCase()) };
}
// The companion behind a Gemini call, from the model name in "gemini <model>".
const caller = (e) => (/banana|image/.test(e.msg) ? "nano-banana" : /flash/.test(e.msg) ? "flash" : "argon");

// ---------- render ----------
const stageEl = $("stage");
const stageOpen = () => !stageEl.hidden;
let chatFor = "", chatSeen = new Set(), stageViewer = null, novelSeen = 0;

function renderStage() {
  if (!state || !stageOpen()) return;
  const s = selectedSample();
  renderStageKpis();
  renderAtlas();
  if (!s) return;
  renderShape(s);
  renderChat(s);
}

function renderStageKpis() {
  const { samples } = state;
  const done = samples.filter((s) => s.status === "done").length;
  const kinds = new Set(samples.filter((s) => s.status !== "failed" && s.stage !== "concept").map((s) => s.bucket)).size;
  const fixes = samples.reduce((a, s) => a + s.log.filter((e) => e.fix).length, 0);
  const tiles = [["done", "Shapes done", done, 0], ["kinds", "Kinds of object", kinds, 0], ["fixes", "Fixed by Argon", fixes, 0]];
  const el = $("stage-kpis");
  if (!el.children.length) el.innerHTML = tiles.map(([k, l]) => `<div class="kpi" data-k="${k}"><dt>${l}</dt><dd class="num">0</dd></div>`).join("");
  for (const [k, , v, dp] of tiles) tick(el.querySelector(`[data-k="${k}"] .num`), v, dp);
}

// A drawing sheet: the main frame shows the flow, else the turning mesh, else the
// three-quarter view; the other views sit beside it as projections, with a title block.
function renderShape(s) {
  const live = s.status === "running";
  const kicker = $("sh-kicker");
  kicker.dataset.status = s.status;
  kicker.innerHTML = (live ? `<span class="pulse"></span>Live${s.gpu != null ? ` · GPU ${s.gpu}` : ""}` : s.status === "done" ? "Finished" : esc(s.status)) +
    (selected ? ` <button type="button" class="sh-back" id="sh-back">Back to live (L)</button>` : "");
  $("sh-back")?.addEventListener("click", () => { selected = null; render(); });
  $("sh-title").textContent = s.title;

  const views = VIEWS.map((v) => [v, s.media?.views?.[v]?.url]).filter(([, u]) => u);
  const video = s.media?.video?.url, meshes = s.media?.meshes || [], mesh = meshes[meshes.length - 1];
  const mode = video ? "flow" : mesh ? "mesh" : views.length ? "view" : "wait";
  const pane = $("sh-3d"), v = $("sh-video"), img = $("sh-img");
  pane.dataset.mode = mode;
  if (video) {
    if (v.getAttribute("src") !== video) { v.src = video; v.play().catch(() => {}); }
  } else if (v.getAttribute("src")) { v.removeAttribute("src"); v.load(); }
  if (mode === "mesh") {
    stageViewer ??= import("./mesh.js").then((m) => m.createViewer($("sh-mesh")));
    const failed = s.stage === "mesh" && live && s.log.slice(-3).some((e) => e.failed && e.stage === "mesh");
    stageViewer.then((vw) => vw.show(mesh.url, { failed })).catch(() => {});
  }
  const main = mode === "view" ? views[0] : null;
  if (main && img.getAttribute("src") !== main[1]) img.src = main[1];
  const cur = s.stage === "done" ? STAGES.length : STAGES.indexOf(s.stage);
  $("sh-3dlabel").textContent = mode === "flow" ? "Flow · FluidX3D · Q-criterion" : mode === "mesh" ? `Mesh · Hunyuan3D · try ${mesh.attempt || meshes.length}` : main ? `${main[0]} view · Nano Banana` : "";
  $("sh-wait").textContent = mode === "wait" ? (live ? "Nano Banana is drawing the views…" : "No pictures saved") : "";

  const side = views.filter((x) => x !== main).slice(0, 3);
  const sideHtml = side.map(([name, url]) => `<figure><img src="${esc(url)}" alt=""><figcaption>${esc(name)}</figcaption></figure>`).join("") ||
    `<figure class="empty"><figcaption>${live && cur <= 1 ? "views coming" : "no views"}</figcaption></figure>`;
  const sv = $("sh-views");
  if (sv.dataset.html !== sideHtml) sv.innerHTML = sv.dataset.html = sideHtml;

  const c = s.concept || {};
  const fixes = s.log.filter((e) => e.fix).length;
  const rows = [["Sample", s.id], ["Kind", s.bucket], ["Reynolds", c.reynolds ? fmtRe(c.reynolds) : "–"], ["Argon fixes", fixes || "0"], ["Gemini calls", s.gemini?.calls ?? "–"]];
  const block = rows.map(([k, val]) => `<tr><th>${k}</th><td>${esc(val)}</td></tr>`).join("");
  const tb = $("sh-block");
  if (tb.dataset.html !== block) tb.innerHTML = tb.dataset.html = block;

  $("sh-track").innerHTML = STAGES.map((st, i) => `<li class="${i < cur ? "done" : i === cur && live ? "now" : ""}"><span>${st}</span><small>${CREW[OWNER[st]].name}</small></li>`).join("");
}

// The sample's log as a drawing's revision table: time, agent, note.
function renderChat(s) {
  const ol = $("stage-chat");
  if (chatFor !== s.id) { chatFor = s.id; chatSeen = new Set(); ol.innerHTML = ""; }
  $("chat-sample").textContent = s.title;
  const t0 = s.log[0]?.t ?? 0;
  const lines = [];
  for (const e of s.log) {
    const l = line(e);
    if (!l) continue;
    const prev = lines[lines.length - 1];
    if (prev && prev.who === l.who && prev.text === l.text) continue;
    lines.push({ ...l, t: e.t - t0, key: `${e.t}|${e.msg}` });
  }
  const last = s.log[s.log.length - 1];
  const typing = s.status === "running" && last?.actor === "gemini" ? caller(last) : null;
  const shown = lines.slice(-8);
  const row = (l) => `<li class="msg ${l.kind} ${chatSeen.has(l.key) ? "" : "new"}"><span class="t">${fmtDur(Math.max(0, l.t))}</span><b>${CREW[l.who].name}</b><p>${esc(l.text)}${l.sub ? `<small>${esc(l.sub)}</small>` : ""}</p></li>`;
  const html = shown.map(row).join("") + (typing ? `<li class="msg typing"><span class="t">now</span><b>${CREW[typing].name}</b><p>working<i>.</i><i>.</i><i>.</i></p></li>` : "");
  if (ol.dataset.html === html) return;
  ol.dataset.html = html;
  ol.innerHTML = html;
  shown.forEach((l) => chatSeen.add(l.key));
  // The Atlas panel notes each novelty search as it lands.
  const novel = shown.filter((l) => l.who === "atlas").length;
  if (novel > novelSeen) $("atlas").classList.remove("ping"), void $("atlas").offsetWidth, $("atlas").classList.add("ping");
  novelSeen = novel;
}

function renderAtlas() {
  const { samples } = state;
  const views = samples.reduce((a, s) => a + Object.keys(s.media?.views || {}).length, 0);
  const meshes = samples.reduce((a, s) => a + (s.media?.meshes?.length || 0), 0);
  const videos = samples.filter((s) => s.media?.video).length;
  const html = [[samples.length, "shapes, each a 3072-d vector"], [views + meshes + videos, "views, meshes, flows in GridFS"], [samples.reduce((a, s) => a + s.log.length, 0), "agent events logged"]]
    .map(([n, l]) => `<div><b>${n.toLocaleString()}</b><span>${l}</span></div>`).join("");
  const el = $("atlas-stats");
  if (el.dataset.html !== html) el.innerHTML = el.dataset.html = html;
}

// ---------- ask Atlas ----------
let askTimer;
$("atlas-q").addEventListener("input", (e) => {
  clearTimeout(askTimer);
  const q = e.target.value.trim();
  if (!q) return void ($("atlas-results").hidden = true);
  askTimer = setTimeout(async () => {
    const r = await fetch(`api/search?q=${encodeURIComponent(q)}&start=${start}`).then((r) => (r.ok ? r.json() : { results: [] })).catch(() => ({ results: [] }));
    const engine = { hybrid: "Atlas hybrid search: Voyage AI meaning + keywords, fused with $rankFusion", "hybrid-descriptions": "Atlas hybrid search ($rankFusion)", "atlas-search": "Atlas Search", regex: "Atlas query", mock: "mock replay" }[r.engine] || "";
    const tiles = (r.results || []).slice(0, 6).map((x) => {
      const s = state.samples.find((y) => y.id === x.id), u = s && viewUrl(s);
      return `<button type="button" data-id="${esc(x.id)}">${u ? `<img src="${esc(u)}" alt="">` : `<span class="noimg"></span>`}<span>${esc(x.name)}</span></button>`;
    }).join("");
    $("atlas-results").innerHTML = `<div class="ar-grid">${tiles || "<p>No matches</p>"}</div><p class="ar-engine">${esc(engine)}</p>`;
    $("atlas-results").hidden = false;
    $("atlas-results").querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => {
      $("atlas-results").hidden = true;
      $("atlas-q").value = "";
      select(b.dataset.id);
    }));
  }, 250);
});
$("atlas-q").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; $("atlas-results").hidden = true; e.target.blur(); } });
stageEl.addEventListener("click", (e) => { if (!e.target.closest(".atlas")) $("atlas-results").hidden = true; });
addEventListener("keydown", (e) => {
  if (!stageOpen() || e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey) return;
  if (e.key === "/") { e.preventDefault(); $("atlas-q").focus(); }
  else if (e.key.toLowerCase() === "l") { selected = null; render(); }
});
$("stage-exit").addEventListener("click", () => present(false));

function stageShow(on) {
  stageEl.hidden = !on;
  if (!on) return;
  renderStage();
}
if (document.body.classList.contains("present")) stageShow(true);

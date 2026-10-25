// FlowArc dashboard. Polls /api/state (Atlas, or the mock replay when Atlas isn't set) every
// two seconds and /api/map every twenty.

const STAGES = ["concept", "images", "mesh", "sim", "render", "package"];
const POLL_MS = 2000;
const MAP_MS = 20000;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtRe = (re) => { const e = Math.floor(Math.log10(re)); const m = re / 10 ** e; return e < 4 ? Math.round(re).toLocaleString() : `${m.toFixed(1)}×10${sup(e)}`; };
const sup = (n) => String(n).split("").map((d) => "⁰¹²³⁴⁵⁶⁷⁸⁹"[d]).join("");
const fmtDur = (s) => (s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s` : `${(s / 3600).toFixed(1)}h`);
// Argon's fix as a line: "repair: retry: retry mesh generation" -> "retry mesh generation".
const fixText = (msg) => msg.replace(/^repair:\s*/, "").replace(/^(\w+):\s*(?=\1\b)/i, "");
// Wall-clock time in words, for "N shapes in 19 hours".
const fmtSpan = (s) => {
  const n = (x, unit) => `${x} ${unit}${x === 1 ? "" : "s"}`;
  if (s < 3600) return n(Math.max(1, Math.round(s / 60)), "minute");
  if (s < 48 * 3600) return n(Math.round(s / 3600), "hour");
  return n(+(s / 86400).toFixed(1), "day");
};

// The mock replay starts its story when the page opens; Restart begins it again.
let start = Math.floor(Date.now() / 1000);
let state = null;
let map = { points: [] };
let selected = null; // null: follow the live sample
let lastOk = 0;
let lastError = "";
let sampleSig = "";
const seen = new Set(); // timeline events already shown, so only new ones flash
const localApprovals = {};
const meshPick = {}; // sample id -> mesh attempt chosen in the tabs
let viewerP = null; // the 3D viewer loads three.js on first use

// ---------- data ----------
async function load() {
  try {
    const r = await fetch(`api/state?start=${start}`, { cache: "no-store" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    state = await r.json();
    lastOk = Date.now();
    lastError = "";
  } catch (e) {
    lastError = e.message;
    return liveTick();
  }
  for (const a of state.approvals) Object.assign(a, localApprovals[a.id] || {});
  scopeRun(state);
  if (selected && !state.samples.find((s) => s.id === selected)) {
    // A link to an older shape the run scope hides: show everything rather than lose it.
    if (olderIds.has(selected)) return void ((everything = true), load());
    selected = null;
  }
  render();
}

// Old test samples stay in the registry; by default the page counts only the current run.
let everything = false;
let olderIds = new Set(); // samples hidden by the run scope, so opening one can show them
function scopeRun(st) {
  if (!st.run.scope) return;
  olderIds = new Set(everything ? [] : st.samples.filter((s) => !s.in_run).map((s) => s.id));
  if (everything) return void (st.run.gpu_hours = st.run.gpu_hours_all);
  st.samples = st.samples.filter((s) => s.in_run);
  const g = { calls: 0, tokens: 0, by_model: {} };
  for (const s of st.samples) { // minus copies of a batch-wide call, so it counts once
    const c = s.gemini?.copies || {};
    g.calls += (s.gemini?.calls || 0) - (c.calls || 0);
    g.tokens += (s.gemini?.tokens || 0) - (c.tokens || 0);
  }
  st.run.gemini = g;
}

async function loadMap() {
  try {
    const r = await fetch(`api/map?start=${start}`, { cache: "no-store" });
    if (r.ok) map = await r.json();
    if (state) renderDiversity();
  } catch {}
}

function liveTick() {
  const age = (Date.now() - lastOk) / 1000;
  const el = $("live-status");
  el.classList.toggle("stale", Boolean(lastError) || !lastOk || age > 10);
  el.title = lastError || (state?.db ? `database ${state.db}` : "");
  if (lastError) return ($("live-text").textContent = `API error: ${lastError.slice(0, 60)}`);
  const src = state?.mode === "atlas" ? "MongoDB Atlas" : "mock replay";
  $("live-text").textContent = !lastOk ? "connecting…" : age > 10 ? `offline ${fmtDur(age)}` : `Live · ${src}`;
}

// ---------- tooltip ----------
const tip = $("tip");
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => (tip.hidden = true);

// ---------- render ----------
function render() {
  const { run, samples } = state;
  $("mode-badge").hidden = state.mode !== "mock";
  $("restart").hidden = state.mode !== "mock";
  liveTick();
  const elapsed = Date.now() / 1000 - run.started_at;
  $("run-sub").textContent = [
    `${run.phase} phase`,
    run.cells_per_length && `${run.cells_per_length.join(" → ")} cells/L`,
    run.gpus && `${run.gpus} GPUs`,
    `running ${fmtDur(elapsed)}`,
  ].filter(Boolean).join(" · ");
  renderOverview(run, samples);
  renderHero();
  renderGallery(samples);
  renderFinale();
  celebrate(samples);
  renderStages(samples);
  renderPicker(samples);
  renderApprovals();
  if (!samples.length) return renderEmpty();
  const s = selectedSample();
  const sig = `${s.id}|${s.status}|${s.stage}|${s.log.length}|${s.gemini?.calls}|${mediaSig(s)}`;
  if (sig !== sampleSig) {
    sampleSig = sig;
    renderSample();
    renderDiversity();
  }
  renderTimeline();
  window.renderStage?.();
  if (document.body.dataset.page === "home") renderHome();
}

// Connected, but nothing in the registry yet: say so instead of showing blank panels.
function renderEmpty() {
  const where = state.mode === "atlas" ? `Atlas database <b>${esc(state.db)}</b>` : "the registry";
  const msg = `<p class="muted">No samples in ${where} yet. Start the pipeline, or run <code>python scripts/demo_feed.py</code> with <code>MONGODB_DB=flowarc_demo</code>.</p>`;
  $("stages").innerHTML = "";
  $("progress-note").textContent = "0 samples";
  $("activity-sample").innerHTML = msg;
  $("activity-note").textContent = "";
  $("timeline").innerHTML = "";
  $("timeline").dataset.html = "";
  $("sample-body").innerHTML = "<p class='muted'>Nothing to show yet.</p>";
  $("sample-media").hidden = true;
  sampleSig = "";
  renderDiversity();
}

const featured = () => state.samples.find((s) => s.id === state.run.featured) || state.samples[0];
const selectedSample = () => (selected && state.samples.find((s) => s.id === selected)) || featured();
function select(id) {
  selected = id;
  if (!document.body.classList.contains("present")) go(id ? `shape/${encodeURIComponent(id)}` : "shape");
  // Search and similar shapes can point at an older sample the run scope hides: show all.
  if (olderIds.has(id)) {
    everything = true;
    sampleSig = "";
    return void load();
  }
  render();
}

// One sentence and one bar: how far the run is, before any detail.
function renderOverview(run, samples) {
  const n = (st) => samples.filter((s) => s.status === st).length;
  const done = n("done"), running = n("running"), bad = n("failed"), flagged = n("flagged");
  const total = Math.max(run.target_samples || 0, samples.length);
  const waiting = Math.max(0, total - done - running - bad - flagged);
  const fixes = samples.reduce((a, s) => a + s.log.filter((e) => e.fix).length, 0);
  const segs = [["done", done], ["running", running], ["flagged", flagged], ["failed", bad], ["waiting", waiting]];
  const bar = segs.filter(([, v]) => v).map(([k, v]) => `<span class="seg ${k}" style="flex:${v}" title="${v} ${k}"></span>`).join("");
  const key = segs.map(([k, v]) => `<span class="key ${k}"><i></i>${v} ${k}</span>`).join("");
  const html = `<p class="ov-label">${esc(run.phase || "")} run</p>
    <h1 class="headline"><span class="num">${done}</span> of ${total} shapes are done.</h1>
    <p class="lede">${running ? `${running} ${running === 1 ? "is" : "are"} running now. ` : ""}Argon has fixed ${fixes} problem${fixes === 1 ? "" : "s"} on its own${bad + flagged ? `; ${bad + flagged} need${bad + flagged === 1 ? "s" : ""} a look` : ""}.</p>
    <div class="progress" aria-label="Run progress">${bar}</div><div class="progress-key">${key}</div>`;
  const el = $("overview");
  if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; }
}

// How long the run has taken, wall clock: start to now while anything runs, else start to the last event.
function runTime() {
  const { run, samples } = state;
  const live = samples.some((s) => s.status === "running");
  const end = live || !samples.length ? Date.now() / 1000 : Math.max(...samples.map((s) => s.last_t || 0));
  return Math.max(0, end - run.started_at);
}
const runSpan = () => `${fmtSpan(runTime())}${state.run.gpus ? ` on ${state.run.gpus} GPUs` : ""}`;

// Counts up (or down) to a new value instead of jumping, so changes catch the eye.
function tick(el, to, dp = 0) {
  const from = Number(el.dataset.v ?? 0);
  if (from === to) return;
  el.dataset.v = to;
  el.closest(".kpi")?.classList.remove("bump");
  void el.offsetWidth;
  el.closest(".kpi")?.classList.add("bump");
  const t0 = performance.now(), dur = 700;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur), e = 1 - (1 - k) ** 3;
    el.textContent = (from + (to - from) * e).toFixed(dp);
    if (k < 1 && el.dataset.v == to) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------- now running ----------
const viewUrl = (s) => s.media && (s.media.views["three-quarter"] || Object.values(s.media.views)[0])?.url;

// The last thing worth pointing at: a failed check (Flash) or Argon's fix, if one of the last
// few events; otherwise the latest event as a caption.
function bubble(s) {
  // Only the stage it is on now: an old stage's failure reads as a current problem.
  const recent = s.log.filter((x) => s.status !== "running" || x.stage === s.stage).slice(-4).reverse();
  const e = recent.find((x) => x.fix || (x.failed && !x.soft)) || s.log[s.log.length - 1];
  if (!e) return "";
  if (e.review) {
    const said = { accept: "Accepted as is", retry: "Asked Argon to retry", drop: "Dropped it" }[e.review] || e.review;
    return `<div class="bubble human"><span class="who">You</span><b>${esc(said)}</b>${e.reason ? `<p>“${esc(e.reason)}”</p>` : ""}</div>`;
  }
  if (e.fix) {
    return `<div class="bubble argon"><span class="who">Argon</span><b>Fix: ${esc(fixText(e.msg))}</b>${e.diagnosis ? `<p>${esc(e.diagnosis)}</p>` : ""}</div>`;
  }
  if (e.failed) {
    const what = e.check ? `${e.check} check failed` : e.msg;
    return `<div class="bubble fail"><span class="who">${esc(e.actor === "system" ? e.stage : e.actor)}</span><b>✕ ${esc(what)}</b>${e.reason ? `<p>${esc(e.reason)}</p>` : ""}</div>`;
  }
  return `<div class="bubble"><span class="who">${esc(e.actor)}</span>${esc(e.msg)}</div>`;
}

const DOING = {
  concept: "Argon is writing the concept…",
  images: "Nano Banana is drawing four views…",
  mesh: "Hunyuan3D is building the mesh…",
  sim: "FluidX3D is running the airflow…",
  render: "FluidX3D is rendering the airflow…",
  package: "Packing the sample into Atlas…",
};
function renderHero() {
  const s = featured(), el = $("hero");
  el.hidden = !s;
  if (!s) return;
  const live = s.status === "running";
  const cur = s.stage === "done" ? STAGES.length : STAGES.indexOf(s.stage);
  const steps = STAGES.map((st, i) => `<li class="${i < cur ? "done" : i === cur && live ? "now" : ""}">${st}</li>`).join("");
  const v = s.status === "done" && s.media?.video;
  const pic = v
    ? `<video src="${esc(v.url)}" muted loop playsinline autoplay></video>`
    : viewUrl(s) ? `<img src="${esc(viewUrl(s))}" alt="" onerror="this.closest('.hero-pic').classList.add('broken')">` : "";
  const c = s.concept || {};
  // No picture yet (or it failed to load): show what Argon asked for and who is working on it.
  const empty = `<div class="hero-empty"><p class="he-who">${live ? esc(DOING[s.stage] || `${s.stage}…`) : "No pictures yet"}</p>${c.description ? `<blockquote>${esc(c.description)}</blockquote>` : ""}</div>`;
  const html = `<div class="hero-pic${pic ? "" : " broken"}">${pic}${empty}</div>
    <div class="hero-body">
      <div class="hero-kicker">${live ? `<span class="pulse"></span>Now running${s.gpu != null ? ` · GPU ${s.gpu}` : ""}` : "Latest sample"}</div>
      <h2 class="hero-title">${esc(s.title)}</h2>
      <p class="hero-sub">${esc(s.bucket)}${c.reynolds ? ` · Re ${fmtRe(c.reynolds)}` : ""}${pic && c.description && c.description !== s.title ? ` · ${esc(c.description)}` : ""}</p>
      <ol class="steps">${steps}</ol>
      ${bubble(s)}
      ${alsoRunning(s)}
    </div>`;
  if (el.dataset.html !== html) {
    el.dataset.html = html;
    el.innerHTML = html;
    el.querySelector("video")?.play().catch(() => {});
  }
}

// The other GPUs, one line each, so the hero stands in for the old GPU table.
function alsoRunning(s) {
  const others = state.samples.filter((x) => x.status === "running" && x.id !== s.id).sort((a, b) => (a.gpu ?? 99) - (b.gpu ?? 99));
  if (!others.length) return "";
  const row = (x) => `<li><a href="#shape/${encodeURIComponent(x.id)}">${x.gpu != null ? `<span class="gpu">GPU ${x.gpu}</span>` : ""}${esc(x.title)}<span class="st">${esc(x.stage)}</span></a></li>`;
  return `<div class="also"><p>Also running</p><ul>${others.slice(0, 4).map(row).join("")}</ul>${others.length > 4 ? `<p class="more">+${others.length - 4} more in the pipeline</p>` : ""}</div>`;
}

// ---------- gallery ----------
const GALLERY_MAX = 24; // newest first; the rest behind "Show all"
let galleryAll = false, galleryKind = ""; // "" = every kind
$("gallery-more").addEventListener("click", () => { galleryAll = !galleryAll; renderGallery(state.samples); });
function renderGallery(samples) {
  const all = samples.filter((s) => viewUrl(s));
  const kinds = [...new Set(all.map((s) => s.bucket))].sort();
  if (galleryKind && !kinds.includes(galleryKind)) galleryKind = "";
  const chips = [["", `All ${all.length}`], ...kinds.map((k) => [k, `${k} ${all.filter((s) => s.bucket === k).length}`])];
  const chipHtml = kinds.length > 1 ? chips.map(([k, l]) => `<button type="button" class="${k === galleryKind ? "on" : ""}" data-kind="${esc(k)}">${esc(l)}</button>`).join("") : "";
  if ($("gallery-kinds").dataset.html !== chipHtml) {
    $("gallery-kinds").dataset.html = chipHtml;
    $("gallery-kinds").innerHTML = chipHtml;
    $("gallery-kinds").querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => { galleryKind = b.dataset.kind; renderGallery(state.samples); }));
  }
  const shown = all.filter((s) => !galleryKind || s.bucket === galleryKind).sort((a, b) => (b.status === "running") - (a.status === "running") || b.last_t - a.last_t);
  $("gallery-note").textContent = shown.length ? `${shown.length} shapes · hover to turn, click to open` : "";
  const more = $("gallery-more");
  more.hidden = shown.length <= GALLERY_MAX;
  more.textContent = galleryAll ? "Show fewer" : `Show all ${shown.length}`;
  const html = shown.slice(0, galleryAll ? Infinity : GALLERY_MAX).map((s) => {
    const fixed = s.log.some((e) => e.fix);
    const badge = s.status === "running" ? `<span class="tag live">running</span>` : s.status === "flagged" ? `<span class="tag bad">⚑</span>` : s.status === "failed" ? `<span class="tag bad">✕</span>` : fixed ? `<span class="tag argon">fixed by Argon</span>` : "";
    const views = VIEWS.map((v) => s.media.views[v]?.url).filter(Boolean);
    return `<button class="tile" type="button" data-id="${esc(s.id)}" data-views="${esc(JSON.stringify(views))}"><img src="${esc(viewUrl(s))}" alt="" loading="lazy">${badge}<span class="cap">${esc(s.title)}<small>${esc(s.bucket)}</small></span></button>`;
  }).join("") || "<p class='muted small'>Finished shapes appear here.</p>";
  const el = $("gallery");
  if (el.dataset.html === html) return;
  el.dataset.html = html;
  el.innerHTML = html;
  el.querySelectorAll(".tile").forEach((t) => {
    const views = JSON.parse(t.dataset.views), img = t.querySelector("img");
    let timer;
    t.addEventListener("mouseenter", () => {
      let i = 0;
      timer = setInterval(() => (img.src = views[++i % views.length]), 550);
    });
    t.addEventListener("mouseleave", () => { clearInterval(timer); img.src = views[0]; });
    t.addEventListener("click", () => select(t.dataset.id));
  });
}

// ---------- finish moments ----------
const lastStatus = new Map();
function celebrate(samples) {
  for (const s of samples) {
    const was = lastStatus.get(s.id);
    lastStatus.set(s.id, s.status);
    if (was && was !== "done" && s.status === "done") toast(`✓ ${s.title} finished`, "good");
  }
}

const fmtTok = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

let toastTimer;
function toast(msg, kind = "") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 4000);
}

function stageState(s, stage) {
  const si = STAGES.indexOf(stage);
  const cur = s.stage === "done" ? STAGES.length : STAGES.indexOf(s.stage);
  const failedHere = s.log.some((e) => e.stage === stage && e.failed);
  if (si < cur) return { cls: "done", txt: "✓", retried: failedHere };
  if (si === cur) {
    if (s.status === "running") return { cls: "running", txt: "", retried: failedHere };
    if (s.status === "failed") return { cls: "failed", txt: "✕" };
    if (s.status === "flagged") return { cls: "flagged", txt: "⚑" };
  }
  return { cls: "pending", txt: "·" };
}

// A run can have 100+ samples: the funnel and the dots show all of them at a glance, the table
// only the ones that need a look unless you ask for all.
const FILTERS = {
  active: ["Needs a look", (s) => s.status === "flagged" || s.status === "failed"],
  running: ["Running", (s) => s.status === "running"],
  waiting: ["Waiting", (s) => s.status === "pending"],
  done: ["Done", (s) => s.status === "done"],
  all: ["All", () => true],
};
let stageFilter = null; // null: "active" once the run is big, else "all"

function renderFunnel(samples) {
  const at = (st) => samples.filter((s) => s.stage === st && s.status !== "done" && s.status !== "failed");
  const cells = STAGES.map((st) => {
    const here = at(st), run = here.filter((s) => s.status === "running").length;
    return `<div class="f-stage"><span class="f-n">${here.length}</span><span class="f-l">${st}</span>${run ? `<span class="f-run">${run} running</span>` : ""}</div>`;
  }).join("");
  const html = cells;
  if ($("funnel").dataset.html !== html) $("funnel").innerHTML = $("funnel").dataset.html = html;
  const sel = selectedSample()?.id;
  const dots = samples.map((s) => `<button type="button" class="sdot ${s.status}${s.id === sel ? " sel" : ""}" data-id="${esc(s.id)}" data-tip="${esc(`<b>${esc(s.id)} · ${esc(s.title)}</b><br>${esc(s.status)}${s.status === "running" || s.status === "pending" ? ` · ${esc(s.stage)}` : ""}`)}" aria-label="${esc(s.title)}"></button>`).join("");
  const el = $("dots");
  if (el.dataset.html === dots) return;
  el.innerHTML = el.dataset.html = dots;
  bindHover(el);
  el.querySelectorAll(".sdot").forEach((d) => d.addEventListener("click", () => select(d.dataset.id)));
}

function renderStages(samples) {
  renderFunnel(samples);
  const key = stageFilter || "all";
  const fhtml = Object.entries(FILTERS).map(([k, [label, f]]) => `<button type="button" role="tab" class="tab${k === key ? " on" : ""}" data-k="${k}">${label} <span class="muted">${samples.filter(f).length}</span></button>`).join("");
  if ($("stage-filter").dataset.html !== fhtml) {
    $("stage-filter").innerHTML = $("stage-filter").dataset.html = fhtml;
    $("stage-filter").querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => { stageFilter = b.dataset.k; renderStages(state.samples); }));
  }
  const shown = samples.filter(FILTERS[key][1]);
  const head = `<thead><tr><th>Sample</th>${STAGES.map((s) => `<th>${s}</th>`).join("")}</tr></thead>`;
  const rows = shown.map((s) => {
    const cells = STAGES.map((st) => {
      const c = stageState(s, st);
      const tries = s.attempts?.[st];
      const label = `${st}: ${c.cls}${c.retried ? ", failed a check then fixed" : ""}${tries ? `, ${tries} attempts` : ""}`;
      return `<td><div class="cell ${c.cls}${c.retried ? " retried" : ""}" title="${esc(label)}">${c.txt}${tries > 1 ? `<sup>${tries}</sup>` : ""}</div></td>`;
    }).join("");
    return `<tr data-id="${s.id}" class="${s.id === selectedSample()?.id ? "sel" : ""}"><td class="name"><span class="id">${s.id}</span>${esc(s.title)}</td>${cells}</tr>`;
  }).join("");
  $("stages").innerHTML = head + `<tbody>${rows || `<tr><td class="muted" colspan="${STAGES.length + 1}">Nothing here.</td></tr>`}</tbody>`;
  $("stages").querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.id)));
  const running = samples.filter((s) => s.status === "running").length;
  $("progress-note").textContent = `${samples.length} samples · ${running} on GPUs`;
  $("all-note").textContent = `${shown.length} of ${samples.length} · click a row to open it`;
  $("stage-legend").innerHTML = [
    ["done", "✓ passed"], ["running", "running"], ["flagged", "⚑ flagged"], ["failed", "✕ failed"], ["done retried", "✓ fixed after a failed check"],
  ].map(([c, t]) => `<span><span class="cell ${c}" style="display:inline-flex;width:22px;height:14px;font-size:10px;vertical-align:-2px"></span> ${t}</span>`).join("");
}

function renderPicker(samples) {
  const pick = $("sample-pick");
  if (document.activeElement === pick) return;
  const f = featured();
  pick.innerHTML = `<option value="">Follow live sample${f ? ` (${f.id})` : ""}</option>` +
    samples.map((s) => `<option value="${s.id}" ${s.id === selected ? "selected" : ""}>${s.id} · ${esc(s.title)}</option>`).join("");
}
$("sample-pick").addEventListener("change", (e) => select(e.target.value || null));

// ---------- activity timeline ----------
function eventHtml(e, t0, fresh) {
  const extra = [];
  if (e.reason) extra.push(esc(e.reason));
  if (e.iou) extra.push(Object.entries(e.iou).map(([v, x]) => `${v} <span class="${x < 0.85 ? "bad" : "ok"}">${x.toFixed(2)}</span>`).join(" · ") + " silhouette IoU");
  if (e.cd != null) extra.push(`Cd ${e.cd.toFixed(3)}`);
  if (e.change != null) extra.push(`drag changes ${(e.change * 100).toFixed(1)}% between halves of the record`);
  if (e.gb != null) extra.push(`${e.gb.toFixed(2)} GB`);
  if (e.d_cd != null) extra.push(`ΔCd ${(e.d_cd * 100).toFixed(1)}% (tol ${(e.tol * 100).toFixed(0)}%)`);
  if (e.mach_max != null) extra.push(`max Mach ${e.mach_max}`);
  if (e.notes) extra.push(esc(e.notes));
  const cls = [e.failed ? (e.soft ? "soft" : "fail") : e.fix ? "fix" : "", fresh ? "new" : ""].join(" ");
  return `<li class="${cls}"><span class="t">+${fmtDur(e.t - t0)}</span><span class="actor ${esc(e.actor)}">${esc(e.actor)}</span><div class="msg"><span class="stage-tag">${esc(e.stage)}</span>${esc(e.msg)}${extra.length ? `<div class="extra">${extra.join("<br>")}</div>` : ""}${e.diagnosis ? `<div class="diag">${esc(e.diagnosis)}</div>` : ""}</div></li>`;
}

function renderTimeline() {
  const s = selectedSample();
  if (!s) return;
  const where = s.status === "running" ? `${s.stage}${s.gpu != null ? `, GPU ${s.gpu}` : ""}` : s.status;
  $("activity-sample").innerHTML = `${selected ? "Showing" : "Following"} <b>${s.id} · ${esc(s.title)}</b> (${esc(where)})`;
  $("activity-note").textContent = `${s.log.length} events`;
  const t0 = s.log[0]?.t ?? 0;
  const first = renderTimeline.last !== s.id;
  renderTimeline.last = s.id;
  const html = s.log.map((e) => {
    const key = `${s.id}|${e.t}|${e.msg}`;
    const fresh = !first && !seen.has(key);
    seen.add(key);
    return eventHtml(e, t0, fresh);
  }).reverse().join("");
  if ($("timeline").dataset.html !== html) {
    $("timeline").innerHTML = html;
    $("timeline").dataset.html = html;
  }
}

// ---------- sample viewer ----------
function renderSample() {
  const s = selectedSample();
  const c = s.concept || {};
  const checks = s.log.filter((e) => e.check);
  const ious = s.log.filter((e) => e.iou);
  const where = s.status === "running" ? `Running now · ${s.stage}${s.gpu != null ? ` · GPU ${s.gpu}` : ""}` : s.status === "done" ? "Finished" : s.status;
  $("h-sample").textContent = s.title;
  $("sh-meta").textContent = [where, s.bucket, c.reynolds ? `Re ${fmtRe(c.reynolds)}` : ""].filter(Boolean).join(" · ");
  $("sh-meta").className = `shape-meta ${s.status}`;
  $("sh-desc").textContent = c.description && c.description !== s.title ? c.description : "";
  const facts = `
    <div>
      <dl class="facts">
        <dt>Bucket</dt><dd>${esc(s.bucket)}</dd>
        <dt>Reynolds</dt><dd>${c.reynolds ? fmtRe(c.reynolds) : "–"}</dd>
        <dt>Yaw</dt><dd>${c.yaw_deg ?? 0}°</dd>
        <dt>Facing</dt><dd>${esc(c.facing || "–")}</dd>
        <dt>Setup</dt><dd>${c.ground ? "ground plane" : "free stream"}</dd>
        <dt>Status</dt><dd>${esc(s.status)}${s.status === "running" ? ` (${esc(s.stage)}${s.gpu != null ? `, GPU ${s.gpu}` : ""})` : ""}</dd>
        <dt>GPU time</dt><dd>${s.gpu_seconds ? fmtDur(s.gpu_seconds) : "–"}</dd>
        <dt>Gemini</dt><dd>${usage(s.gemini)}</dd>
        <dt>Output</dt><dd>${output(s)}</dd>
      </dl>
      <ul class="checks">${checks.map((e) => `<li><span>${esc(e.stage)} · ${esc(e.check)}</span><span class="${e.failed ? (e.soft ? "warn" : "bad") : "ok"}">${e.failed ? (e.soft ? "⚠ soft fail" : "✕ fail") : "✓ pass"}</span></li>`).join("") || "<li class='muted'>no checks yet</li>"}</ul>
    </div>`;
  const iou = `<div><h3 style="margin-top:0">Silhouette IoU per mesh attempt</h3>${ious.length ? iouChart(ious) : "<p class='muted small'>Mesh not reviewed yet.</p>"}</div>`;
  const conv = `<div><h3 style="margin-top:0">${s.convergence ? "Convergence: running mean drag vs t (L/U)" : "Simulation results"}</h3>${s.convergence ? convChart(s.convergence) : s.sim ? statsTable(s) : "<p class='muted small'>Simulation not finished.</p>"}</div>`;
  $("sample-body").innerHTML = facts + iou + conv;
  bindHover($("sample-body"));
  renderMedia(s);
  loadPrompts(s);
  loadSimilar(s);
}

// The nearest concepts in the registry (Atlas Vector Search on the Gemini embeddings).
const similarCache = new Map();
async function loadSimilar(s) {
  const id = s.id;
  if (!similarCache.has(id)) {
    similarCache.set(id, fetch(`api/similar?id=${encodeURIComponent(id)}&k=12&start=${start}`).then((r) => r.json()).catch(() => ({ results: [] })));
  }
  const r = await similarCache.get(id);
  if (selectedSample()?.id !== id) return;
  const byId = new Map(state.samples.map((x) => [x.id, x]));
  const pic = (x) => byId.get(x.id) && viewUrl(byId.get(x.id));
  // Nearest first, but shapes with pictures before concepts still waiting for their images.
  // Only shapes with pictures: a grey "no images yet" tile reads as broken on stage.
  const rows = (r.results || []).filter(pic).slice(0, 6);
  $("similar-head").hidden = $("similar").hidden = !rows.length;
  const engines = { "vector-search": "Atlas Vector Search", mock: "mock" };
  $("similar-note").textContent = rows.length ? `nearest concepts · ${engines[r.engine] || ""}` : "";
  $("similar").innerHTML = rows.map((x) => {
    const alike = x.similarity > 0 ? `${Math.round(x.similarity * 100)}% alike · ` : "";
    return `<button type="button" class="sim-card" data-id="${esc(x.id)}"><img src="${esc(pic(x))}" alt="" loading="lazy"><span class="cap">${esc(x.name || x.id)}<small>${alike}${esc(x.bucket || "")}</small></span></button>`;
  }).join("");
  $("similar").querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => select(b.dataset.id)));
}

function usage(g) {
  if (!g?.calls) return "–";
  const by = Object.entries(g.by_model).map(([m, x]) => `${esc(m)}: ${x.calls}${x.tokens ? ` · ${fmtTok(x.tokens)} tok` : ""}`).join("<br>");
  return `<span title="calls · tokens per model">${g.calls} calls${g.tokens ? ` · ${fmtTok(g.tokens)} tokens` : ""}</span><div class="muted small">${by}</div>`;
}

function output(s) {
  const size = s.zarr_gb != null ? `${s.zarr_gb.toFixed(2)} GB Zarr` : s.status === "done" ? "packed" : "not packed yet";
  const link = s.hf ? ` · <a href="${esc(s.hf)}" target="_blank" rel="noopener">files on HF</a>` : "";
  return size + (s.published ? " · published" : "") + link;
}

// Every Gemini call for the sample, newest first, each folded to one line until opened.
async function loadPrompts(s) {
  const el = $("prompts");
  const id = s.id;
  if (!s.gemini.calls) {
    $("prompts-note").textContent = "";
    return (el.innerHTML = "<p class='muted small'>No Gemini calls logged for this sample.</p>");
  }
  const r = await fetch(`api/sample?id=${encodeURIComponent(id)}&start=${start}`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
  if (selectedSample()?.id !== id) return;
  const calls = r?.calls || [];
  const open = new Set([...el.querySelectorAll("details[open]")].map((d) => d.dataset.k));
  $("prompts-note").textContent = `${calls.length} calls`;
  el.innerHTML = calls.map((c) => {
    const k = `${id}|${c.t}`;
    const head = `<span class="stage-tag">${esc(c.stage)}</span><b>${esc(c.model)}</b> <span class="muted">${c.seconds != null ? `${c.seconds}s` : ""}${c.tokens ? ` · ${fmtTok(c.tokens)} tokens` : ""}</span> <span class="gist">${esc((c.prompt || "").slice(0, 120))}</span>`;
    return `<details data-k="${esc(k)}" ${open.has(k) ? "open" : ""}><summary>${head}</summary><h4>Prompt</h4><pre>${esc(c.prompt)}</pre><h4>Reply</h4><pre>${esc(c.reply)}</pre></details>`;
  }).reverse().join("") || "<p class='muted small'>Couldn't load the prompts.</p>";
}

// ---------- views and mesh ----------
const VIEWS = ["three-quarter", "front", "side", "top"];
const mediaSig = (s) => (s.media ? [...Object.values(s.media.views), ...s.media.meshes, s.media.video].filter(Boolean).map((m) => m.url).join(",") : "");

// Each mesh attempt runs the same checks, so the n-th result of a check judges attempt n.
function meshVerdicts(s) {
  const count = {}, out = [];
  for (const e of s.log) {
    if (e.stage !== "mesh" || !e.check || e.check === "views_consistent") continue;
    const n = (count[e.check] = (count[e.check] || 0) + 1) - 1;
    if (out[n] !== "fail") out[n] = e.failed && !e.soft ? "fail" : "pass";
  }
  return out;
}

function renderFlow(s) {
  const v = s.media?.video, el = $("flow-video");
  $("flow-empty").hidden = Boolean(v);
  // No airflow yet: drop the column rather than show an empty box.
  $("flow-col").hidden = !v;
  $("sample-media").classList.toggle("no-flow", !v);
  el.hidden = !v;
  $("flow-note").textContent = v && s.sim?.cd_mean != null ? `Mean drag coefficient ${s.sim.cd_mean.toFixed(3)}` : "";
  if (!v) return el.removeAttribute("src");
  if (el.getAttribute("src") !== v.url) {
    el.src = v.url;
    el.play().catch(() => {}); // autoplay can be refused until the page is clicked
  }
}

function renderMedia(s) {
  $("sample-media").hidden = false;
  renderFlow(s);
  const views = s.media?.views || {};
  $("views").innerHTML = VIEWS.map((v) => {
    const m = views[v];
    return m
      ? `<figure class="view" data-src="${esc(m.url)}" data-cap="${esc(v)}${m.attempt > 1 ? ` · redrawn (attempt ${m.attempt})` : ""}"><img src="${esc(m.url)}" alt="${esc(s.title)}, ${esc(v)} view" loading="lazy"><figcaption>${esc(v)}${m.attempt > 1 ? " ↻" : ""}</figcaption></figure>`
      : `<figure class="view empty"><div></div><figcaption>${esc(v)}</figcaption></figure>`;
  }).join("");
  $("views").querySelectorAll(".view[data-src]").forEach((el) => {
    el.addEventListener("mousemove", (ev) => showTip(`<img class="tip-img" src="${esc(el.dataset.src)}" alt=""><div>${esc(el.dataset.cap)}</div>`, ev));
    el.addEventListener("mouseleave", hideTip);
  });

  const meshes = s.media?.meshes || [];
  const verdicts = meshVerdicts(s);
  const pick = meshes.find((m) => m.attempt === meshPick[s.id]) || meshes[meshes.length - 1];
  // An attempt that errored before making a mesh left no file: show it, greyed out, so the
  // attempts read 1, 2, 3… Only gaps before the latest mesh, never the attempt still running.
  const tries = Array.from({ length: meshes.length ? meshes[meshes.length - 1].attempt : 0 }, (_, i) => meshes.find((m) => m.attempt === i + 1) || { attempt: i + 1 });
  $("mesh-tabs").innerHTML = tries.length > 1
    ? tries.map((m) => {
        if (!m.url) return `<button class="tab" type="button" disabled title="This attempt errored before it made a mesh">Attempt ${m.attempt} · no mesh</button>`;
        const v = verdicts[m.attempt - 1];
        return `<button class="tab${m === pick ? " on" : ""}" data-attempt="${m.attempt}">Attempt ${m.attempt} ${v === "fail" ? "<span class='bad'>✕</span>" : v === "pass" ? "<span class='ok'>✓</span>" : ""}</button>`;
      }).join("")
    : "";
  $("mesh-tabs").querySelectorAll("button[data-attempt]").forEach((b) =>
    b.addEventListener("click", () => {
      meshPick[s.id] = Number(b.dataset.attempt);
      renderMedia(s);
    }),
  );
  $("mesh-empty").hidden = Boolean(pick);
  $("mesh-view").classList.toggle("has-mesh", Boolean(pick));
  // The last mesh of a sample that moved past the mesh stage is the one it used, whatever its
  // check said (Argon can accept a soft failure); only a replaced attempt shows as failed.
  const used = pick && pick === meshes[meshes.length - 1] && STAGES.indexOf(s.stage === "done" ? "package" : s.stage) > STAGES.indexOf("mesh");
  const failed = pick && !used && verdicts[pick.attempt - 1] === "fail";
  $("mesh-note").textContent = failed ? "This attempt failed the mesh check · drag to rotate · scroll to zoom" : used ? "The mesh used for the simulation · drag to rotate · scroll to zoom" : "Drag to rotate · scroll to zoom";
  if (!pick) return viewerP?.then((v) => v.clear());
  viewerP ??= import("./mesh.js").then((m) => m.createViewer($("mesh-view")));
  viewerP
    .then((v) => v.show(pick.url, { failed }))
    .catch((e) => {
      console.error(e);
      $("mesh-note").textContent = "Couldn't load the mesh viewer.";
    });
}

// Grouped bars: one group per view, one bar per attempt. Two series max.
function iouChart(events) {
  const views = Object.keys(events[0].iou);
  const perView = views.length > 1;
  const thr = 0.85;
  const W = 300, H = 170, L = 30, B = 22, T = 8;
  const y = (v) => T + (1 - (v - 0.5) / 0.5) * (H - T - B);
  const gw = (W - L) / views.length, bw = Math.min(22, (gw - 16) / events.length);
  const colors = events.map((_, k) => (k === events.length - 1 ? "var(--series-1)" : "var(--series-2)"));
  let g = "";
  for (const v of [0.5, 0.75, 1]) g += `<line class="gridline" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  views.forEach((view, i) => {
    const x0 = L + i * gw + (gw - bw * events.length - 2 * (events.length - 1)) / 2;
    events.forEach((e, k) => {
      const val = e.iou[view] ?? 0;
      const x = x0 + k * (bw + 2), top = y(Math.max(val, 0.5));
      g += `<path d="${barPath(x, top, bw, y(0.5) - top)}" fill="${colors[k % colors.length]}" data-tip="${esc(`<b>${esc(view)}</b>, attempt ${k + 1}<br>IoU ${val.toFixed(2)}${perView ? ` ${val < thr ? "✕ below" : "✓ above"} ${thr}` : ""}${e.failed ? "<br>mesh check failed" : ""}`)}"/>`;
    });
    g += `<text x="${L + i * gw + gw / 2}" y="${H - 6}" text-anchor="middle">${view}</text>`;
  });
  if (perView) g += `<line x1="${L}" x2="${W}" y1="${y(thr)}" y2="${y(thr)}" stroke="var(--critical)" stroke-dasharray="4 3" stroke-width="1.5"/><text x="${L + 2}" y="${y(thr) - 4}">min ${thr}</text>`;
  g += `<line class="axis" x1="${L}" x2="${W}" y1="${y(0.5)}" y2="${y(0.5)}"/>`;
  const legend = events.length > 1
    ? `<div class="legend-row"><span><span class="swatch" style="background:var(--series-2)"></span>earlier attempt${events.length > 2 ? "s" : ""}</span><span><span class="swatch" style="background:var(--series-1)"></span>attempt ${events.length}${events[events.length - 1].failed ? " (failed)" : ""}</span></div>`
    : "";
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Silhouette IoU per view">${g}</svg></div>${legend}`;
}

function barPath(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function convChart(conv) {
  const lv = conv.levels;
  const W = 380, H = 190, L = 40, R = 46, B = 24, T = 10;
  const all = lv.flatMap((l) => l.cd_mean.slice(2));
  let lo = Math.min(...all), hi = Math.max(...all);
  const fin = lv[lv.length - 1].cd, tol = conv.tol.cd;
  lo = Math.min(lo, fin * (1 - tol)); hi = Math.max(hi, fin * (1 + tol));
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const t0 = lv[0].t[0], t1 = lv[0].t[lv[0].t.length - 1];
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const colors = ["var(--series-2)", "var(--series-1)"];
  let g = "";
  const ticks = niceTicks(lo, hi, 4);
  for (const v of ticks) g += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`;
  for (const t of [10, 20, 30, 40]) if (t >= t0 && t <= t1) g += `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${t}</text>`;
  g += `<rect x="${L}" width="${W - L - R}" y="${y(fin * (1 + tol))}" height="${y(fin * (1 - tol)) - y(fin * (1 + tol))}" fill="var(--series-1)" opacity=".10"/>`;
  const clip = `clip-${Math.random().toString(36).slice(2)}`;
  g += `<clipPath id="${clip}"><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"/></clipPath>`;
  lv.forEach((l, k) => {
    const d = l.t.map((t, i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(l.cd_mean[i]).toFixed(1)}`).join("");
    const last = l.cd_mean[l.cd_mean.length - 1];
    g += `<path d="${d}" fill="none" stroke="${colors[k % 2]}" stroke-width="2" stroke-linejoin="round" clip-path="url(#${clip})"/>`;
    g += `<text x="${W - R + 4}" y="${y(last) + 4}" style="fill:var(--ink-2)">${l.cells}</text>`;
  });
  g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>`;
  g += `<line class="crosshair" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="var(--axis)" visibility="hidden"/>`;
  g += `<rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>`;
  const rows = [["Mean Cd", "cd"], ["RMS Cl", "cl_rms"], ["Strouhal", "st"]].map(([name, key]) => {
    const a = lv[lv.length - 2]?.[key], b = lv[lv.length - 1][key];
    const d = a ? Math.abs(b - a) / Math.abs(b) : null, ok = d != null && d <= conv.tol[key];
    return `<tr><td>${name}</td>${lv.map((l) => `<td>${l[key].toFixed(3)}</td>`).join("")}<td class="${ok ? "ok" : "bad"}">${d == null ? "–" : `${(d * 100).toFixed(1)}% ${ok ? "✓" : "✕"}`}</td><td>${(conv.tol[key] * 100).toFixed(0)}%</td></tr>`;
  }).join("");
  const legend = `<div class="legend-row">${lv.map((l, k) => `<span><span class="swatch line" style="background:${colors[k % 2]}"></span>${l.cells} cells/L</span>`).join("")}<span><span class="swatch" style="background:var(--series-1);opacity:.25;border-radius:2px"></span>±${(tol * 100).toFixed(0)}% of finest</span></div>`;
  const table = `<table class="qoi"><thead><tr><th>QoI</th>${lv.map((l) => `<th>${l.cells}</th>`).join("")}<th>change</th><th>tol</th></tr></thead><tbody>${rows}</tbody></table>`;
  const id = `conv-${Math.random().toString(36).slice(2)}`;
  setTimeout(() => bindCrosshair(id, conv, x, L, W - R), 0);
  return `<div class="chart" id="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running mean drag coefficient per grid level">${g}</svg></div>${legend}${table}`;
}

// One grid level: the solver's own statistics and the runner's limits (flowarc/pipeline.py).
function statsTable(s) {
  const st = s.sim;
  const rows = [
    ["Mean Cd", st.cd_mean, null],
    ["RMS Cl", st.cl_rms, null],
    ["RMS Cs", st.cs_rms, null],
    ["Strouhal", st.st, null],
    ["Drag change, 1st vs 2nd half", st.cd_half_change, 0.05, true],
    ["Max Mach", st.mach_max, 0.5],
    ["Mass drift", st.mass_drift, 0.01, true],
  ].filter(([, v]) => v != null);
  const fmt = (v, pct) => (pct ? `${(v * 100).toFixed(2)}%` : v.toFixed(3));
  const body = rows.map(([name, v, lim, pct]) => {
    const ok = lim == null || v < lim;
    return `<tr><td>${name}</td><td>${fmt(v, pct)}</td><td class="${lim == null ? "" : ok ? "ok" : "bad"}">${lim == null ? "" : `${ok ? "✓" : "✕"} &lt; ${fmt(lim, pct)}`}</td></tr>`;
  }).join("");
  const gb = s.zarr_gb != null ? `<p class="muted small">Packed: ${s.zarr_gb.toFixed(2)} GB Zarr</p>` : "";
  return `<table class="qoi"><thead><tr><th>Quantity</th><th>Value</th><th>Limit</th></tr></thead><tbody>${body}</tbody></table>${gb}`;
}

function bindCrosshair(id, conv, x, x0, x1) {
  const el = $(id);
  if (!el) return;
  const svg = el.querySelector("svg"), hit = el.querySelector(".hit"), ch = el.querySelector(".crosshair");
  const lv = conv.levels, ts = lv[0].t;
  hit.addEventListener("mousemove", (ev) => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    let i = 0, best = Infinity;
    ts.forEach((t, k) => { const d = Math.abs(x(t) - p.x); if (d < best) { best = d; i = k; } });
    ch.setAttribute("x1", x(ts[i])); ch.setAttribute("x2", x(ts[i])); ch.setAttribute("visibility", "visible");
    showTip(`<b>t = ${ts[i]} L/U</b><br>${lv.map((l) => `${l.cells} cells/L: Cd ${l.cd_mean[i].toFixed(3)}`).join("<br>")}`, ev);
  });
  hit.addEventListener("mouseleave", () => { ch.setAttribute("visibility", "hidden"); hideTip(); });
}

function niceTicks(lo, hi, n) {
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function bindHover(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (ev) => showTip(el.dataset.tip, ev));
    el.addEventListener("mouseleave", hideTip);
  });
}

// ---------- diversity map ----------
function renderDiversity() {
  const pts = map.points || [];
  if (!pts.length) { $("divmap").innerHTML = "<p class='muted small'>No embeddings yet.</p>"; $("coverage").innerHTML = ""; return; }
  const W = 520, H = 340, P = 14;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (v) => P + ((v - x0) / (x1 - x0)) * (W - 2 * P), sy = (v) => H - P - ((v - y0) / (y1 - y0)) * (H - 2 * P);
  const color = { flowarc: "var(--series-1)", car_baseline: "var(--series-2)" };
  const ids = new Set(state.samples.map((s) => s.id));
  const order = [...pts].sort((a, b) => (b.source === "car_baseline") - (a.source === "car_baseline"));
  let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="none" stroke="var(--grid)" rx="8"/>`;
  const thumb = new Map(state.samples.map((x) => [x.id, viewUrl(x)]));
  g += `<defs><clipPath id="dot" clipPathUnits="objectBoundingBox"><circle cx=".5" cy=".5" r=".5"/></clipPath></defs>`;
  for (const p of order) {
    const mine = ids.has(p.id), r = mine ? 5.5 : 4;
    const img = mine && thumb.get(p.id);
    if (img) { // our finished shapes show as their own picture
      const T = 30, x = sx(p.x) - T / 2, y = sy(p.y) - T / 2;
      const tipHtml = esc(`<b>${esc(p.label)}</b><br>${esc(p.bucket)} · FlowArc`);
      g += `<g class="thumb" data-id="${p.id}" data-tip="${tipHtml}" style="cursor:pointer"><circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${T / 2 + 2}" fill="var(--page)" stroke="var(--series-1)" stroke-width="1.5"/><g clip-path="url(#dot)"><image href="${esc(img)}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${T}" height="${T}" preserveAspectRatio="xMidYMid meet" filter="url(#line-art)"/></g></g>`;
      if (p.id === selectedSample()?.id) g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="${T / 2 + 6}" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
      continue;
    }
    g += `<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${r}" fill="${color[p.source] || "var(--muted)"}" stroke="var(--surface)" stroke-width="1.5" opacity="${p.source === "car_baseline" ? 0.85 : 1}" data-tip="${esc(`<b>${esc(p.label)}</b><br>${esc(p.bucket)} · ${p.source === "car_baseline" ? "car baseline" : "FlowArc"}`)}" ${mine ? `data-id="${p.id}" style="cursor:pointer"` : ""}/>`;
    if (p.id === selectedSample()?.id) g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="10" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
  }
  // Name the car cluster on the map itself, just above it (below when it sits at the top).
  const cars = pts.filter((p) => p.source === "car_baseline");
  if (cars.length) {
    const cx = cars.reduce((a, p) => a + sx(p.x), 0) / cars.length;
    const top = Math.min(...cars.map((p) => sy(p.y))), bottom = Math.max(...cars.map((p) => sy(p.y)));
    const above = top > 34, y = above ? top - 18 : bottom + 16;
    const x = Math.min(Math.max(cx, 60), W - 60);
    const name = esc((map.baseline || "car baseline").replace(/\s*\(.*\)\s*$/, ""));
    g += `<text class="cluster-label" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${name}</text><text class="cluster-label sub" x="${x.toFixed(1)}" y="${(y + 9).toFixed(1)}" text-anchor="middle">every one a car</text>`;
  }
  $("divmap").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shape embedding map, FlowArc samples versus a car-only baseline">${g}</svg>`;
  bindHover($("divmap"));
  $("divmap").querySelectorAll("[data-id]").forEach((c) => c.addEventListener("click", () => select(c.dataset.id)));
  const n = (src) => pts.filter((p) => p.source === src).length;
  const spread = (src) => { const q = pts.filter((p) => p.source === src); if (!q.length) return 0; const mx = q.reduce((a, p) => a + p.x, 0) / q.length, my = q.reduce((a, p) => a + p.y, 0) / q.length; return Math.sqrt(q.reduce((a, p) => a + (p.x - mx) ** 2 + (p.y - my) ** 2, 0) / q.length); };
  $("div-legend").innerHTML = `<span><span class="swatch" style="background:var(--series-1)"></span>FlowArc (${n("flowarc")}, spread ${spread("flowarc").toFixed(2)})</span><span><span class="swatch" style="background:var(--series-2)"></span>${esc(map.baseline || "car baseline")} (${n("car_baseline")}, spread ${spread("car_baseline").toFixed(2)})</span>`;
  const buckets = {};
  for (const p of pts) if (p.source === "flowarc") buckets[p.bucket] = (buckets[p.bucket] || 0) + 1;
  const max = Math.max(...Object.values(buckets));
  $("coverage").innerHTML = Object.entries(buckets).sort((a, b) => b[1] - a[1]).map(([b, k]) => `<div class="cov-row"><span>${esc(b)}</span><div class="bar-track"><div class="bar-fill" style="width:${(100 * k) / max}%"></div></div><span class="n">${k}</span></div>`).join("");
}

// ---------- needs a look ----------
// Flagged and failed shapes with the reason, newest first, plus any approval the pipeline asks for.
function lookReason(s) {
  const log = s.log.filter((x) => !x.review).reverse();
  const e = log.find((x) => x.failed && !x.soft) || log.find((x) => x.failed) || log[0];
  if (!e) return { what: s.status, why: "" };
  const tries = s.attempts?.[e.stage] > 1 ? ` after ${s.attempts[e.stage]} attempts` : "";
  return { what: `${e.stage} · ${e.check ? `${e.check} check failed` : e.msg}${tries}`, why: e.reason || e.diagnosis || "" };
}
function renderApprovals() {
  if (reviewOpen && document.activeElement?.closest(".look-form")) return; // don't redraw under someone typing
  const kinds = { publish: "Publish dataset", over_budget: "Over compute budget", flagged: "Flagged sample" };
  const list = state.approvals;
  const pending = list.filter((a) => a.status === "pending").length;
  const look = state.samples.filter((s) => s.status === "flagged" || s.status === "failed").sort((a, b) => b.last_t - a.last_t);
  $("approve-count").textContent = [look.length && `${look.length} shape${look.length === 1 ? "" : "s"}`, pending && `${pending} to approve`].filter(Boolean).join(" · ");
  const asks = list.map((a) => `
    <div class="approval ${a.status !== "pending" ? "decided" : ""}">
      <div class="kind">${esc(kinds[a.kind] || a.kind)}</div>
      <h3>${esc(a.title)}</h3>
      <p>${esc(a.detail)}</p>
      <div class="actions">${a.status === "pending"
        ? `<button class="btn approve" data-id="${a.id}" data-d="approved">Approve</button><button class="btn reject" data-id="${a.id}" data-d="rejected">Reject</button>${a.sample ? `<button class="ghost small" data-open="${a.sample}">Open sample</button>` : ""}`
        : `<span class="verdict ${a.status === "approved" ? "ok" : "bad"}">${a.status === "approved" ? "✓ Approved" : "✕ Rejected"}</span>`}</div>
    </div>`).join("");
  const rows = look.map((s) => {
    const r = lookReason(s);
    const open = reviewOpen === s.id;
    const done = s.review && !s.review.acted;
    const said = done ? `<p class="look-said">You said <b>${esc(REVIEW_SAID[s.review.decision] || s.review.decision)}</b>${s.review.note ? `: “${esc(s.review.note)}”` : ""} · waiting for the runner</p>` : "";
    const form = open ? `<div class="look-form"><input type="text" maxlength="500" placeholder="Note for Argon (optional), e.g. thicken the handle" aria-label="Note for Argon" value="${esc(reviewNote)}">
        <div class="actions">${REVIEWS.map(([d, l]) => `<button type="button" class="btn ${d === "retry" ? "approve" : "reject"}" data-review="${d}" data-sample="${esc(s.id)}">${l}</button>`).join("")}<button type="button" class="ghost small" data-cancel>Cancel</button></div></div>`
      : done ? "" : `<div class="actions"><button type="button" class="ghost small" data-review-open="${esc(s.id)}">Review</button><button type="button" class="ghost small" data-open="${esc(s.id)}">Open</button></div>`;
    return `<div class="look ${s.status}${open ? " open" : ""}"><button type="button" class="look-head" data-open="${esc(s.id)}"><span class="look-tag">${s.status === "failed" ? "✕ failed" : "⚑ flagged"}</span><b>${esc(s.title)}</b><span class="look-what">${esc(r.what)}</span>${r.why ? `<span class="look-why">${esc(r.why)}</span>` : ""}</button>${said}${form}</div>`;
  }).join("");
  const html = asks + (rows ? `<div class="looks">${rows}</div>` : "") || "<p class='muted'>Nothing needs a look. Every check has passed or Argon fixed it.</p>";
  if ($("approvals").dataset.html === html) return;
  const el = $("approvals");
  el.innerHTML = el.dataset.html = html;
  el.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => decide(b.dataset.id, b.dataset.d)));
  el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => select(b.dataset.open)));
  el.querySelectorAll("[data-review-open]").forEach((b) => b.addEventListener("click", () => { reviewOpen = b.dataset.reviewOpen; reviewNote = ""; renderApprovals(); el.querySelector(".look-form input")?.focus(); }));
  el.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", () => { reviewOpen = null; renderApprovals(); }));
  const input = el.querySelector(".look-form input");
  input?.addEventListener("input", () => (reviewNote = input.value)); // kept across the 2 s redraws
  input?.addEventListener("keydown", (e) => { if (e.key === "Escape") { reviewOpen = null; renderApprovals(); } });
  el.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", () => review(b.dataset.sample, b.dataset.review, reviewNote)));
}

// A person's call on a flagged or failed shape, with an optional note for Argon. The runner reads
// it from Atlas (`reviews`); until it acts, the card says what was asked.
const REVIEWS = [["accept", "Accept"], ["retry", "Retry"], ["drop", "Drop"]];
const REVIEW_SAID = { accept: "accept it as is", retry: "retry", drop: "drop it" };
let reviewOpen = null, reviewNote = "";
async function review(sample, decision, note) {
  const r = await post("api/review", { sample, decision, note });
  if (!r) return;
  reviewOpen = null;
  reviewNote = "";
  toast(`${{ accept: "✓ Accepted", retry: "↻ Retry asked", drop: "✕ Dropped" }[decision]}: ${state.samples.find((s) => s.id === sample)?.title || sample}`, decision === "drop" ? "bad" : "good");
  load();
}

// POST with the approval token, asking for it once per browser. Returns the response, or null.
async function post(url, body) {
  let token = localStorage.getItem("approvalToken") || "";
  for (let tries = 0; tries < 2; tries++) {
    const r = await fetch(`${url}?start=${start}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-approval-token": token },
      body: JSON.stringify(body),
    }).catch(() => null);
    if (r?.status === 401) {
      token = prompt("Approval token") || "";
      if (!token) return null;
      try { localStorage.setItem("approvalToken", token); } catch {}
      continue;
    }
    if (!r?.ok) { alert((await r?.json().catch(() => null))?.error || "Could not save that. Try again."); return null; }
    return r;
  }
  return null;
}

async function decide(id, decision) {
  if (!(await post("api/approve", { id, decision }))) return;
  localApprovals[id] = { status: decision };
  Object.assign(state.approvals.find((a) => a.id === id), localApprovals[id]);
  toast(decision === "approved" ? "✓ Approved by a human" : "✕ Rejected", decision === "approved" ? "good" : "bad");
  $("approvals").dataset.html = "";
  renderApprovals();
}

// ---------- search ----------
// Search by meaning or name (Atlas hybrid search). Arrow keys pick a result, Enter opens it,
// / jumps to the box from anywhere, and an empty box offers a few things to try.
const TRY = ["something that flies", "kitchen tools", "sea creatures", "tall buildings"];
let searchTimer, hits = [], hit = 0;
function showResults(html) { $("results").innerHTML = html; $("results").hidden = false; }
function paintHits(engine) {
  const engines = { hybrid: "Atlas hybrid search · meaning + keywords", "hybrid-descriptions": "Atlas hybrid search (descriptions only)", "atlas-search": "Atlas Search", regex: "Atlas", mock: "Local replay" };
  const row = (x, i) => {
    const s = state?.samples.find((t) => t.id === x.id);
    const img = s && viewUrl(s);
    return `<button type="button" data-id="${esc(x.id)}" class="${i === hit ? "on" : ""}">${img ? `<img src="${esc(img)}" alt="">` : `<span class="noimg"></span>`}
      <span class="r-name">${esc(x.name)}<small>${esc([s?.bucket, x.status].filter(Boolean).join(" · "))}</small></span></button>`;
  };
  showResults((hits.map(row).join("") || "<div class='engine'>No matches. Try describing the shape.</div>") + `<div class="engine">${engines[engine] || ""}</div>`);
  $("results").querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => openHit(b.dataset.id)));
}
function openHit(id) {
  $("results").hidden = true;
  $("q").value = "";
  $("q").blur();
  select(id);
}
function suggest() {
  showResults(`<div class="engine">Try</div>${TRY.map((t) => `<button type="button" class="try" data-q="${esc(t)}">${esc(t)}</button>`).join("")}`);
  $("results").querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => { $("q").value = b.dataset.q; $("q").focus(); search(); }));
}
function search() {
  clearTimeout(searchTimer);
  const q = $("q").value.trim();
  hits = []; hit = 0;
  if (!q) return suggest();
  showResults("<div class='engine'>Searching…</div>");
  searchTimer = setTimeout(async () => {
    const r = await fetch(`api/search?q=${encodeURIComponent(q)}&start=${start}`).then((r) => r.json()).catch(() => ({ results: [] }));
    if ($("q").value.trim() !== q) return;
    hits = r.results || [];
    paintHits(r.engine);
  }, 200);
}
$("q").addEventListener("input", search);
$("q").addEventListener("focus", () => { if (!$("q").value.trim()) suggest(); });
$("q").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("q").value = ""; $("results").hidden = true; $("q").blur(); }
  else if (e.key === "Enter" && hits[hit]) openHit(hits[hit].id);
  else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && hits.length) {
    e.preventDefault();
    hit = (hit + (e.key === "ArrowDown" ? 1 : -1) + hits.length) % hits.length;
    $("results").querySelectorAll("[data-id]").forEach((b, i) => b.classList.toggle("on", i === hit));
  }
});
addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.target.closest("input, textarea, select") || document.body.classList.contains("present") || finaleOpen()) return;
  e.preventDefault();
  $("q").focus();
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("results").hidden = true; });

$("restart").addEventListener("click", () => {
  start = Math.floor(Date.now() / 1000);
  selected = null;
  sampleSig = "";
  for (const k in localApprovals) delete localApprovals[k];
  load().then(loadMap);
});


load().then(loadMap);
setInterval(load, POLL_MS);
setInterval(loadMap, MAP_MS);
setInterval(liveTick, 1000);

// ---------- tabs ----------
// A small site: one job per tab, each with its own link (#live, #shapes, #about), and one per
// shape (#shape/<id>), so a refresh or a shared link opens the same shape.
const PAGES = ["home", "live", "shapes", "shape", "about"];
function go(route) {
  if (location.hash.slice(1) !== route) history.pushState(null, "", `#${route}`);
  showPage(route);
}
function showPage(route = location.hash.slice(1)) {
  let [page, id] = route.split("/");
  const want = id ? decodeURIComponent(id) : null; // #shape alone follows the live sample
  if (page === "shape" && want !== selected) {
    selected = want;
    sampleSig = "";
    if (state) render();
  }
  if (page === "run") page = "live";
  if (!PAGES.includes(page)) page = "home";
  document.querySelectorAll(".page").forEach((el) => (el.hidden = el.dataset.page !== page));
  document.querySelectorAll(".tabs-nav a").forEach((a) => a.toggleAttribute("aria-current", a.getAttribute("href") === `#${page === "shape" ? "shapes" : page}`));
  document.body.dataset.page = page;
  if (page === "home") renderHome();
  if (page === "about") { renderDeck(); $("deck").focus({ preventScroll: true }); }
  if (page === "shapes" && id === "all") return void requestAnimationFrame(() => $("card-all").scrollIntoView());
  scrollTo(0, 0);
}
addEventListener("hashchange", () => showPage());

// ---------- home: the landing page ----------
// The pitch in one scroll: what FlowArc is, then the slides' sections, with a way into the live run.
let homeSig = "";
function renderHome() {
  const samples = state?.samples || [];
  const done = samples.filter((s) => s.status === "done");
  // The same shape the Live hero shows, so "Watch it live" lands on it.
  const f = state && featured();
  const live = f?.status === "running" ? f : samples.find((s) => s.status === "running");
  const pic = done.filter((s) => viewUrl(s)).sort((a, b) => b.last_t - a.last_t)[0]; // the newest finished shape
  const age = Date.now() / 1000 - (pic?.last_t || 0); // to the minute, so the page only redraws when it changes
  const when = pic?.last_t > 1e9 ? ` · finished ${age < 60 ? "just now" : age < 3600 ? `${Math.floor(age / 60)} min ago` : `${(age / 3600).toFixed(1)} h ago`}` : "";
  const kinds = new Set(done.map((s) => s.bucket)).size;
  const html = `<section class="l-hero">
      <div class="l-copy"><p class="kick">AI4Physics datasets · Encode London 2026</p>
        <h1 class="l-title">Text in.<br>Checked flow<br>simulation out.</h1>
        <p class="lead">FlowArc is an agent that turns a sentence into a 3D shape and a verified airflow simulation, so flow models can learn from more than cars.</p>
        <div class="l-cta"><a class="btn approve" href="#live">Watch it live →</a></div>
        <p class="l-live">${live ? `<span class="dot"></span>Running now: <b>${esc(live.title)}</b><br>` : ""}${done.length} shapes checked · ${kinds} kinds of object${state ? ` · in ${runSpan()}` : ""}</p></div>
      <button class="l-next" type="button" aria-label="Next">↓</button>
      ${pic ? `<figure class="l-pic"><p class="l-pic-label"><span class="dot"></span>Latest finished shape <span>updates as the run goes</span></p><img src="${esc(viewUrl(pic))}" alt="${esc(pic.title)}"><figcaption><b>${esc(pic.title)}</b> · ${esc(pic.bucket)}${when}</figcaption></figure>` : ""}
    </section>
    ${slides().slice(1).map((x, i, all) => `<section class="slide l-sec">${x}${i < all.length - 1
      ? `<button class="l-next" type="button" aria-label="Next">↓</button>`
      : `<div class="l-cta"><a class="btn approve" href="#live">Watch it live →</a></div>`}</section>`).join("")}`;
  if (html === homeSig) return;
  homeSig = html;
  $("page-home").innerHTML = html;
}

// The ↓ under each section scrolls to the next one, like a slide.
$("page-home").addEventListener("click", (e) => {
  e.target.closest(".l-next")?.closest("section").nextElementSibling?.scrollIntoView({ behavior: "smooth" });
});

// ---------- about: slides ----------
// The pitch as slides, with the run's own numbers. ← and → (or space) move between them.
let slide = 0;
function slides() {
  const samples = state?.samples || [];
  const done = samples.filter((s) => s.status === "done");
  const kinds = new Set(done.map((s) => s.bucket)).size;
  const fixes = samples.flatMap((s) => s.log.filter((e) => e.fix).map((e) => ({ s, e })));
  const last = fixes[fixes.length - 1];
  const pics = done.filter((s) => viewUrl(s)).slice(0, 6);
  const step = (n, t, who, d) => `<li><span class="n">${n}</span><b>${t}</b><small>${who}</small><p>${d}</p></li>`;
  // About a minute of talk before the live walkthrough: six slides, in the order of the script.
  return [
    `<p class="kick">Encode London 2026</p><h2 class="big">FlowArc</h2><p class="lead">Text in. Checked flow simulation out.</p>`,
    `<p class="kick">The problem</p><h2>A flow simulation dataset takes months to build.</h2>
     <p class="lead">Cars, aircraft and medical devices are designed with fluid simulations. AI can predict the flow in seconds, but only around shapes like the ones it trained on.</p>
     <div class="facts"><div><b>8,000</b><span>shapes in DrivAerNet++, every one a car</span></div><div><b>1–2 weeks</b><span>for an engineer to mesh one new shape</span></div><div><b>Months</b><span>to simulate and check a dataset</span></div></div>`,
    `<p class="kick">How FlowArc does it</p><h2>An agent in every stage.</h2>
     <ol class="pipe">${step(1, "Concept", "Argon + Atlas", "proposes a shape the dataset is missing")}${step(2, "Images", "Nano Banana", "draws it from four sides, checked for agreement")}${step(3, "Mesh", "Image-to-3D", "viewed from the same angles; regenerated or repaired")}${step(4, "Simulation", "FluidX3D", "runs the flow, checked for physical consistency")}${step(5, "Package", "Atlas + Hugging Face", "text, images and mesh in Atlas; flow fields on Hugging Face")}</ol>
     <ul class="uses"><li><b>MongoDB Atlas is the agent's memory:</b> Vector Search stops repeats, hybrid search finds any shape, GridFS holds every file</li></ul>`,
    `<p class="kick">Argon, the supervisor</p><h2>When a check fails, Argon reads why and picks the fix.</h2>
     <div class="facts"><div><b>${fixes.length}</b><span>${fixes.length === 1 ? "problem" : "problems"} fixed without a person</span></div><div><b>3</b><span>ways to fix: new images, new mesh, or repair</span></div></div>
     ${last ? `<blockquote class="argon-quote"><span class="who">Argon · latest fix</span>${last.e.diagnosis ? `<p>“${esc(last.e.diagnosis)}”</p>` : ""}<small><b>${esc(last.s.title)}</b>: ${esc(fixText(last.e.msg))}</small></blockquote>` : ""}`,
    `<p class="kick">So far</p><h2>In ${state ? fmtSpan(runTime()) : "–"}, ${done.length} checked simulations of ${kinds} kinds of object.</h2>
     <div class="strip">${pics.map((s) => `<figure><img src="${esc(viewUrl(s))}" alt=""><figcaption>${esc(s.title)}</figcaption></figure>`).join("")}</div>`,
    `<p class="kick">Who it's for</p><h2>Diverse flow datasets in days, not months.</h2><p class="lead">For frontier AI teams, researchers, and us.</p>`,
  ];
}
function renderDeck() {
  const all = slides();
  slide = Math.max(0, Math.min(slide, all.length - 1));
  $("deck").innerHTML = `<div class="slide">${all[slide]}</div>
    <div class="deck-nav"><button class="ghost" type="button" data-d="-1" aria-label="Previous slide">←</button>
    <span>${slide + 1} / ${all.length}</span><button class="ghost" type="button" data-d="1" aria-label="Next slide">→</button></div>`;
  $("deck").querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => { slide += Number(b.dataset.d); renderDeck(); }));
}
addEventListener("keydown", (e) => {
  if (document.body.dataset.page !== "about" || e.target.closest("input, textarea, select") || finaleOpen() || document.body.classList.contains("present")) return;
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); slide++; renderDeck(); }
  else if (e.key === "ArrowLeft") { slide--; renderDeck(); }
});

// ---------- presenter mode ----------
// The dark stage view (stage.js), and when nothing is happening it walks through finished
// shapes so the screen keeps moving while you talk. ?present, the Present button, or P.
const IDLE_MS = 60000, CYCLE_MS = 15000;
let lastTouch = 0, cycleTimer = null;
function present(on) {
  document.body.classList.toggle("present", on);
  window.stageShow?.(on);
  $("present").textContent = on ? "■ Exit" : "▶ Present";
  clearInterval(cycleTimer);
  if (on) cycleTimer = setInterval(cycle, CYCLE_MS);
}
function cycle() {
  if (!state || Date.now() - lastTouch < IDLE_MS) return;
  if (state.samples.some((s) => s.status === "running") && !selected) return; // the live one is the show
  const pool = state.samples.filter((s) => s.status === "done" && s.media && (s.media.video || s.media.meshes?.length || viewUrl(s)));
  if (!pool.length) return;
  const i = pool.findIndex((s) => s.id === selected);
  selected = pool[(i + 1) % pool.length].id;
  render();
}
const touch = (e) => { if (e.isTrusted) lastTouch = Date.now(); };
["pointerdown", "keydown", "wheel"].forEach((t) => addEventListener(t, touch, { passive: true }));
$("present").addEventListener("click", () => present(!document.body.classList.contains("present")));
addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "p" || e.metaKey || e.ctrlKey || e.target.closest("input, textarea, select")) return;
  present(!document.body.classList.contains("present"));
});
if (new URLSearchParams(location.search).has("present")) present(true);

// ---------- finale ----------
// The closing shot: everything the batch made, each shape as picture, mesh and flow, with the
// totals against a hand-built dataset. A spotlight steps through the shapes on its own.
const SPOT_MS = 7000;
let spotId = null, spotTimer = null, spotViewer = null;
const finaleOpen = () => !$("finale").hidden;
const finished = () => state.samples.filter((s) => s.status === "done" && viewUrl(s));

function finale(on) {
  $("finale").hidden = !on;
  document.body.classList.toggle("finale-on", on);
  clearInterval(spotTimer);
  if (!on) return $("spot-video").pause();
  spotId = null;
  renderFinale();
  spot(nextSpot());
  spotTimer = setInterval(() => spot(nextSpot()), SPOT_MS);
}

function nextSpot() {
  const pool = finished();
  const withFlow = pool.filter((s) => s.media.video); // shapes with a flow first
  const order = [...withFlow, ...pool.filter((s) => !s.media.video)];
  const i = order.findIndex((s) => s.id === spotId);
  return order[(i + 1) % order.length]?.id;
}

function renderFinale() {
  if (!state || !finaleOpen()) return;
  const pool = finished();
  const kinds = new Set(pool.map((s) => s.bucket)).size;
  const flows = pool.filter((s) => s.media.video).length;
  const t0 = Math.min(...state.samples.map((s) => s.log[0]?.t).filter(Boolean));
  const t1 = Math.max(...pool.map((s) => s.last_t));
  const span = pool.length && t1 > t0 ? fmtSpan(t1 - t0) : "–";
  const stats = `<div class="fs-head"><span class="brand">≋ FlowArc</span> made by Argon, checked at every step</div>
    <div class="fs-row">
      <div><b>${pool.length}</b><span>shapes</span></div>
      <div><b>${kinds}</b><span>kinds of shape</span></div>
      <div><b>${flows}</b><span>airflow simulations</span></div>
      <div><b>${span}</b><span>start to finish</span></div>
    </div>
    <div class="fs-vs">DrivAerNet++: <b>1 kind</b> (cars), months of expert work</div>`;
  if ($("finale-stats").dataset.html !== stats) $("finale-stats").innerHTML = $("finale-stats").dataset.html = stats;
  const grid = pool.map((s) => `<button class="ftile${s.id === spotId ? " on" : ""}" type="button" data-id="${esc(s.id)}">
      <img src="${esc(viewUrl(s))}" alt="" loading="lazy">${s.media.video ? `<span class="tag flow">airflow</span>` : ""}
      <span class="cap">${esc(s.title)}<small>${esc(s.bucket)}</small></span></button>`).join("");
  const el = $("finale-grid");
  if (el.dataset.html === grid) return;
  el.innerHTML = el.dataset.html = grid;
  el.querySelectorAll(".ftile").forEach((t) => t.addEventListener("click", () => {
    spot(t.dataset.id);
    clearInterval(spotTimer); // the presenter took over; resume after a pause
    spotTimer = setInterval(() => spot(nextSpot()), SPOT_MS * 2);
  }));
}

function spot(id) {
  const s = state.samples.find((x) => x.id === id);
  if (!s) return;
  spotId = id;
  $("spot-img").src = viewUrl(s);
  $("spot-cap").innerHTML = `<b>${esc(s.title)}</b> · ${esc(s.bucket)}${s.concept?.reynolds ? ` · Re ${fmtRe(s.concept.reynolds)}` : ""}${s.log.some((e) => e.fix) ? ` · <span class="argon-ink">fixed by Argon</span>` : ""}`;
  const v = $("spot-video"), url = s.media.video?.url || "";
  $("spot-noflow").hidden = Boolean(url);
  if (v.getAttribute("src") !== url) {
    if (url) { v.src = url; v.play().catch(() => {}); } else { v.removeAttribute("src"); v.load(); }
  }
  const mesh = s.media.meshes?.[s.media.meshes.length - 1];
  spotViewer ??= import("./mesh.js").then((m) => m.createViewer($("spot-mesh")));
  spotViewer.then((vw) => (mesh ? vw.show(mesh.url) : vw.clear())).catch(() => {});
  $("finale-grid").querySelectorAll(".ftile").forEach((t) => t.classList.toggle("on", t.dataset.id === id));
}

$("finale-open").addEventListener("click", () => finale(true));
$("finale-close").addEventListener("click", () => finale(false));
addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.target.closest("input, textarea, select")) return;
  if (e.key.toLowerCase() === "f") finale(!finaleOpen());
  else if (e.key === "Escape" && finaleOpen()) finale(false);
  else if (finaleOpen() && (e.key === "ArrowRight" || e.key === " ")) { e.preventDefault(); spot(nextSpot()); }
});
if (new URLSearchParams(location.search).has("finale")) addEventListener("load", () => setTimeout(() => state && finale(true), 2500));

// Start on the tab in the link, once everything above is defined.
showPage();

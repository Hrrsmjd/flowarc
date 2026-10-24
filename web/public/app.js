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
  if (selected && !state.samples.find((s) => s.id === selected)) selected = null;
  render();
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
  const el = $("live");
  el.classList.toggle("stale", Boolean(lastError) || !lastOk || age > 10);
  el.title = lastError;
  if (lastError) return ($("live-text").textContent = `API error: ${lastError.slice(0, 60)}`);
  const src = state?.mode === "atlas" ? `MongoDB Atlas · ${state.db}` : "mock replay";
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
  renderNow(run, samples);
  renderStages(samples);
  renderPicker(samples);
  renderApprovals();
  if (!samples.length) return renderEmpty();
  const s = selectedSample();
  const sig = `${s.id}|${s.status}|${s.stage}|${s.log.length}|${s.gemini.calls}|${mediaSig(s)}`;
  if (sig !== sampleSig) {
    sampleSig = sig;
    renderSample();
    renderDiversity();
  }
  renderTimeline();
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
  render();
}

const fmtTok = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

// What each GPU is doing right now, plus the run totals.
function renderNow(run, samples) {
  const n = (st) => samples.filter((s) => s.status === st).length;
  const now = Date.now() / 1000;
  const g = run.gemini || { calls: 0, tokens: 0 };
  $("now-note").innerHTML = [
    `<b>${n("done")}</b> / ${run.target_samples} done`,
    `<b>${n("running")}</b> running`,
    `<b>${n("pending")}</b> waiting`,
    `<span class="${n("flagged") ? "warn" : ""}"><b>${n("flagged")}</b> flagged</span>`,
    `<span class="${n("failed") ? "bad" : ""}"><b>${n("failed")}</b> failed</span>`,
    `<b>${run.gpu_hours.toFixed(1)}</b> GPU-hours`,
    `<b>${g.calls}</b> Gemini calls${g.tokens ? ` · ${fmtTok(g.tokens)} tokens` : ""}`,
  ].join(" · ");
  const running = samples.filter((s) => s.status === "running").sort((a, b) => (a.gpu ?? 99) - (b.gpu ?? 99));
  $("now").innerHTML = running.length
    ? `<thead><tr><th>GPU</th><th>Sample</th><th>Stage</th><th>In stage for</th><th>Progress</th></tr></thead><tbody>${running.map((s) => {
        const p = s.progress?.of ? `${s.progress.frames} / ${s.progress.of} frames` : "";
        const tries = s.attempts?.[s.stage] > 1 ? ` <span class="muted">try ${s.attempts[s.stage]}</span>` : "";
        return `<tr data-id="${s.id}" class="${s.id === selectedSample()?.id ? "sel" : ""}"><td>${s.gpu ?? "–"}</td><td><span class="id">${s.id}</span> ${esc(s.title)}</td><td>${esc(s.stage)}${tries}</td><td>${s.stage_since ? fmtDur(now - s.stage_since) : "–"}</td><td>${p}</td></tr>`;
      }).join("")}</tbody>`
    : `<tbody><tr><td class="muted">Nothing running.</td></tr></tbody>`;
  $("now").querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.id)));
}

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

function renderStages(samples) {
  const head = `<thead><tr><th>Sample</th>${STAGES.map((s) => `<th>${s}</th>`).join("")}</tr></thead>`;
  const rows = samples.map((s) => {
    const cells = STAGES.map((st) => {
      const c = stageState(s, st);
      const tries = s.attempts?.[st];
      const label = `${st}: ${c.cls}${c.retried ? ", failed a check then fixed" : ""}${tries ? `, ${tries} attempts` : ""}`;
      return `<td><div class="cell ${c.cls}${c.retried ? " retried" : ""}" title="${esc(label)}">${c.txt}${tries > 1 ? `<sup>${tries}</sup>` : ""}</div></td>`;
    }).join("");
    return `<tr data-id="${s.id}" class="${s.id === selectedSample()?.id ? "sel" : ""}"><td class="name"><span class="id">${s.id}</span>${esc(s.title)}</td>${cells}</tr>`;
  }).join("");
  $("stages").innerHTML = head + `<tbody>${rows}</tbody>`;
  $("stages").querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.id)));
  const running = samples.filter((s) => s.status === "running").length;
  $("progress-note").textContent = `${samples.length} samples · ${running} on GPUs`;
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
  const facts = `
    <div>
      <h3 style="margin-top:0">${esc(s.title)}</h3>
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
  $("mesh-tabs").innerHTML = meshes.length > 1
    ? meshes.map((m) => {
        const v = verdicts[m.attempt - 1];
        return `<button class="tab${m === pick ? " on" : ""}" data-attempt="${m.attempt}">Attempt ${m.attempt} ${v === "fail" ? "<span class='bad'>✕</span>" : v === "pass" ? "<span class='ok'>✓</span>" : ""}</button>`;
      }).join("")
    : "";
  $("mesh-tabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      meshPick[s.id] = Number(b.dataset.attempt);
      renderMedia(s);
    }),
  );
  $("mesh-empty").hidden = Boolean(pick);
  $("mesh-view").classList.toggle("has-mesh", Boolean(pick));
  const failed = pick && verdicts[pick.attempt - 1] === "fail";
  $("mesh-note").textContent = failed ? "This attempt failed the mesh check · drag to rotate · scroll to zoom" : "Drag to rotate · scroll to zoom";
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
const viewUrl = (s) => s.media && (s.media.views["three-quarter"] || Object.values(s.media.views)[0])?.url;
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
      g += `<g class="thumb" data-id="${p.id}" data-tip="${tipHtml}" style="cursor:pointer"><circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${T / 2 + 2}" fill="var(--surface)" stroke="var(--series-1)" stroke-width="2"/><image href="${esc(img)}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${T}" height="${T}" clip-path="url(#dot)" preserveAspectRatio="xMidYMid slice"/></g>`;
      if (p.id === selectedSample()?.id) g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="${T / 2 + 6}" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
      continue;
    }
    g += `<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${r}" fill="${color[p.source] || "var(--muted)"}" stroke="var(--surface)" stroke-width="1.5" opacity="${p.source === "car_baseline" ? 0.85 : 1}" data-tip="${esc(`<b>${esc(p.label)}</b><br>${esc(p.bucket)} · ${p.source === "car_baseline" ? "car baseline" : "FlowArc"}`)}" ${mine ? `data-id="${p.id}" style="cursor:pointer"` : ""}/>`;
    if (p.id === selectedSample()?.id) g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="10" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
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

// ---------- approvals ----------
function renderApprovals() {
  const kinds = { publish: "Publish dataset", over_budget: "Over compute budget", flagged: "Flagged sample" };
  const list = state.approvals;
  $("approve-count").textContent = `${list.filter((a) => a.status === "pending").length} pending`;
  $("approvals").innerHTML = list.map((a) => `
    <div class="approval ${a.status !== "pending" ? "decided" : ""}">
      <div class="kind">${esc(kinds[a.kind] || a.kind)}</div>
      <h3>${esc(a.title)}</h3>
      <p>${esc(a.detail)}</p>
      <div class="actions">${a.status === "pending"
        ? `<button class="btn approve" data-id="${a.id}" data-d="approved">Approve</button><button class="btn reject" data-id="${a.id}" data-d="rejected">Reject</button>${a.sample ? `<button class="ghost small" data-open="${a.sample}">Open sample</button>` : ""}`
        : `<span class="verdict ${a.status === "approved" ? "ok" : "bad"}">${a.status === "approved" ? "✓ Approved" : "✕ Rejected"}</span>`}</div>
    </div>`).join("") || "<p class='muted'>Nothing waiting.</p>";
  $("approvals").querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => decide(b.dataset.id, b.dataset.d)));
  $("approvals").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { select(b.dataset.open); $("h-sample").scrollIntoView({ behavior: "smooth" }); }));
}

async function decide(id, decision) {
  let token = localStorage.getItem("approvalToken") || "";
  for (let tries = 0; tries < 2; tries++) {
    const r = await fetch(`api/approve?start=${start}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-approval-token": token },
      body: JSON.stringify({ id, decision }),
    }).catch(() => null);
    if (r?.status === 401) {
      token = prompt("Approval token") || "";
      if (!token) return;
      try { localStorage.setItem("approvalToken", token); } catch {}
      continue;
    }
    if (!r?.ok) return alert((await r?.json().catch(() => null))?.error || "Could not record the decision. Try again.");
    localApprovals[id] = { status: decision };
    Object.assign(state.approvals.find((a) => a.id === id), localApprovals[id]);
    toast(decision === "approved" ? "✓ Approved by a human" : "✕ Rejected", decision === "approved" ? "good" : "bad");
    return renderApprovals();
  }
}

// ---------- search ----------
let searchTimer;
$("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) return ($("results").hidden = true);
  searchTimer = setTimeout(async () => {
    const r = await fetch(`api/search?q=${encodeURIComponent(q)}&start=${start}`).then((r) => r.json()).catch(() => ({ results: [] }));
    const engines = { "atlas-search": "Atlas Search", regex: "Atlas (no search index)", mock: "mock" };
    $("results").innerHTML = (r.results.map((x) => `<button type="button" data-id="${esc(x.id)}"><span>${esc(x.name)}</span><span class="muted small">${esc(x.status)}</span></button>`).join("") || "<div class='engine'>No matches</div>") +
      `<div class="engine">${engines[r.engine] || ""}</div>`;
    $("results").hidden = false;
    $("results").querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => {
      $("results").hidden = true;
      $("q").value = "";
      select(b.dataset.id);
      $("h-sample").scrollIntoView({ behavior: "smooth" });
    }));
  }, 200);
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("results").hidden = true; });

$("restart").addEventListener("click", () => {
  start = Math.floor(Date.now() / 1000);
  selected = null;
  sampleSig = "";
  for (const k in localApprovals) delete localApprovals[k];
  load().then(loadMap);
});

// ---------- theme ----------
$("theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
});

load().then(loadMap);
setInterval(load, POLL_MS);
setInterval(loadMap, MAP_MS);
setInterval(liveTick, 1000);

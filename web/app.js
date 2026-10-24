// FlowArc dashboard. Reads /api/state (python -m flowarc.dashboard), or mock.json when served statically.

const STAGES = ["concept", "images", "mesh", "sim", "render", "package"];
const POLL_MS = 5000;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtRe = (re) => { const e = Math.floor(Math.log10(re)); const m = re / 10 ** e; return e < 4 ? Math.round(re).toLocaleString() : `${m.toFixed(1)}×10${sup(e)}`; };
const sup = (n) => String(n).split("").map((d) => "⁰¹²³⁴⁵⁶⁷⁸⁹"[d]).join("");
const fmtDur = (s) => (s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s` : `${(s / 3600).toFixed(1)}h`);

let state = null;
let staticMode = false;
let selected = null;
let replayTimer = null;
const localApprovals = {};

// ---------- data ----------
async function load() {
  try {
    const r = await fetch("api/state", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    state = await r.json();
  } catch {
    staticMode = true;
    const r = await fetch("mock.json", { cache: "no-store" });
    state = await r.json();
    // Shift mock timestamps so the run looks current.
    const shift = Date.now() / 1000 - state.generated_at;
    state.run.started_at += shift;
    for (const s of state.samples) for (const e of s.log) e.t += shift;
  }
  for (const a of state.approvals) Object.assign(a, localApprovals[a.id] || {});
  if (!selected || !state.samples.find((s) => s.id === selected)) selected = state.run.featured;
  render();
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
  const elapsed = Date.now() / 1000 - run.started_at;
  $("run-sub").textContent = `Phase 1 ${run.phase} · ${run.cells_per_length.join(" → ")} cells/L · ${run.gpus} GPUs · running ${fmtDur(elapsed)}`;
  renderKpis(run, samples);
  renderStages(samples);
  renderPicker(samples);
  renderSample();
  if (!replayTimer) renderTimeline(featured().log);
  renderDiversity();
  renderApprovals();
}

const featured = () => state.samples.find((s) => s.id === state.run.featured) || state.samples[0];
const selectedSample = () => state.samples.find((s) => s.id === selected) || featured();

function renderKpis(run, samples) {
  const n = (st) => samples.filter((s) => s.status === st).length;
  const done = n("done");
  const pct = Math.min(100, (100 * done) / run.target_samples);
  const tiles = [
    ["Samples done", `${done}<small> / ${run.target_samples}</small>`, `<div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>`],
    ["Running", n("running"), ""],
    ["<span class='bad'>⚑</span> Flagged", n("flagged"), ""],
    ["<span class='bad'>✕</span> Failed", n("failed"), ""],
    ["Samples / hour", run.samples_per_hour.toFixed(1), ""],
    ["GPU-hours", run.gpu_hours.toFixed(1), ""],
  ];
  $("kpis").innerHTML = tiles.map(([l, v, x]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div>${x}</div>`).join("");
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
    return `<tr data-id="${s.id}" class="${s.id === selected ? "sel" : ""}"><td class="name"><span class="id">${s.id}</span>${esc(s.title)}</td>${cells}</tr>`;
  }).join("");
  $("stages").innerHTML = head + `<tbody>${rows}</tbody>`;
  $("stages").querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => { selected = tr.dataset.id; render(); }));
  const running = samples.filter((s) => s.status === "running").length;
  $("progress-note").textContent = `${samples.length} samples · ${running} on GPUs`;
  $("stage-legend").innerHTML = [
    ["done", "✓ passed"], ["running", "running"], ["flagged", "⚑ flagged"], ["failed", "✕ failed"], ["done retried", "✓ fixed after a failed check"],
  ].map(([c, t]) => `<span><span class="cell ${c}" style="display:inline-flex;width:22px;height:14px;font-size:10px;vertical-align:-2px"></span> ${t}</span>`).join("");
}

function renderPicker(samples) {
  $("sample-pick").innerHTML = samples.map((s) => `<option value="${s.id}" ${s.id === selected ? "selected" : ""}>${s.id} · ${esc(s.title)}</option>`).join("");
}
$("sample-pick").addEventListener("change", (e) => { selected = e.target.value; render(); });

// ---------- activity timeline ----------
function eventHtml(e, t0) {
  const extra = [];
  if (e.iou) extra.push(Object.entries(e.iou).map(([v, x]) => `${v} <span class="${x < (e.threshold ?? 0.85) ? "bad" : "ok"}">${x.toFixed(2)}</span>`).join(" · ") + ` (min ${e.threshold})`);
  if (e.d_cd != null) extra.push(`ΔCd ${(e.d_cd * 100).toFixed(1)}% (tol ${(e.tol * 100).toFixed(0)}%)`);
  if (e.mach_max != null) extra.push(`max Mach ${e.mach_max}`);
  if (e.notes) extra.push(esc(e.notes));
  const cls = e.failed ? "fail" : e.fix ? "fix" : "";
  const actor = e.actor || "system";
  return `<li class="${cls}"><span class="t">+${fmtDur(e.t - t0)}</span><span class="actor ${esc(actor)}">${esc(actor)}</span><div class="msg"><span class="stage-tag">${esc(e.stage)}</span>${esc(e.msg)}${extra.length ? `<div class="extra">${extra.join("<br>")}</div>` : ""}</div></li>`;
}

function renderTimeline(log, upto = log.length) {
  const s = featured();
  $("activity-sample").innerHTML = `Following <b>${s.id} · ${esc(s.title)}</b>, ${s.status}`;
  const t0 = log[0]?.t ?? 0;
  $("timeline").innerHTML = log.slice(0, upto).map((e) => eventHtml(e, t0)).reverse().join("");
}

$("replay").addEventListener("click", () => {
  if (replayTimer) return stopReplay();
  const log = featured().log;
  let i = 0;
  renderTimeline(log, 0);
  $("replay").textContent = "■ Stop";
  replayTimer = setInterval(() => {
    i += 1;
    renderTimeline(log, i);
    if (i >= log.length) stopReplay();
  }, 1100);
});
function stopReplay() {
  clearInterval(replayTimer);
  replayTimer = null;
  $("replay").textContent = "▶ Replay";
  renderTimeline(featured().log);
}

// ---------- sample viewer ----------
function renderSample() {
  const s = selectedSample();
  const c = s.concept || {};
  const checks = s.log.filter((e) => /^check /.test(e.msg));
  const ious = s.log.filter((e) => e.iou);
  const facts = `
    <div>
      <h3 style="margin-top:0">${esc(s.title)}</h3>
      <dl class="facts">
        <dt>Bucket</dt><dd>${esc(s.bucket)}</dd>
        <dt>Reynolds</dt><dd>${c.re ? fmtRe(c.re) : "–"}</dd>
        <dt>Angle</dt><dd>${c.angle ?? 0}°</dd>
        <dt>Setup</dt><dd>${c.ground ? "ground plane" : "free stream"}</dd>
        <dt>Status</dt><dd>${esc(s.status)}${s.status === "running" ? ` (${esc(s.stage)}, GPU ${s.gpu})` : ""}</dd>
        <dt>GPU time</dt><dd>${fmtDur(s.gpu_seconds || 0)}</dd>
      </dl>
      <ul class="checks">${checks.map((e) => `<li><span>${esc(e.stage)} · ${esc(e.msg.replace(/^check |: .*$/g, ""))}</span><span class="${e.failed ? "bad" : "ok"}">${e.failed ? "✕ fail" : "✓ pass"}</span></li>`).join("") || "<li class='muted'>no checks yet</li>"}</ul>
    </div>`;
  const iou = `<div><h3 style="margin-top:0">Silhouette IoU vs reference views</h3>${ious.length ? iouChart(ious) : "<p class='muted small'>Mesh stage not reached.</p>"}</div>`;
  const conv = `<div><h3 style="margin-top:0">Convergence: running mean drag vs t (L/U)</h3>${s.convergence ? convChart(s.convergence) : "<p class='muted small'>Simulation not finished.</p>"}</div>`;
  $("sample-body").innerHTML = facts + iou + conv;
  bindHover($("sample-body"));
}

// Grouped bars: one group per view, one bar per attempt. Two series max.
function iouChart(events) {
  const views = Object.keys(events[0].iou);
  const thr = events[0].threshold ?? 0.85;
  const W = 300, H = 170, L = 30, B = 22, T = 8;
  const y = (v) => T + (1 - (v - 0.5) / 0.5) * (H - T - B);
  const gw = (W - L) / views.length, bw = Math.min(22, (gw - 16) / events.length);
  const colors = events.length > 1 ? ["var(--series-2)", "var(--series-1)"] : ["var(--series-1)"];
  let g = "";
  for (const v of [0.5, 0.75, 1]) g += `<line class="gridline" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  views.forEach((view, i) => {
    const x0 = L + i * gw + (gw - bw * events.length - 2 * (events.length - 1)) / 2;
    events.forEach((e, k) => {
      const val = e.iou[view];
      const x = x0 + k * (bw + 2), top = y(Math.max(val, 0.5));
      g += `<path d="${barPath(x, top, bw, y(0.5) - top)}" fill="${colors[k % colors.length]}" data-tip="<b>${view}</b>, attempt ${k + 1}<br>IoU ${val.toFixed(2)} ${val < thr ? "✕ below" : "✓ above"} ${thr}"/>`;
    });
    g += `<text x="${L + i * gw + gw / 2}" y="${H - 6}" text-anchor="middle">${view}</text>`;
  });
  g += `<line x1="${L}" x2="${W}" y1="${y(thr)}" y2="${y(thr)}" stroke="var(--critical)" stroke-dasharray="4 3" stroke-width="1.5"/><text x="${L + 2}" y="${y(thr) - 4}">min ${thr}</text>`;
  g += `<line class="axis" x1="${L}" x2="${W}" y1="${y(0.5)}" y2="${y(0.5)}"/>`;
  const legend = events.length > 1
    ? `<div class="legend-row"><span><span class="swatch" style="background:var(--series-2)"></span>attempt 1 (failed)</span><span><span class="swatch" style="background:var(--series-1)"></span>attempt ${events.length} (after Argon's fix)</span></div>`
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
  const pts = state.diversity.points || [];
  if (!pts.length) { $("divmap").innerHTML = "<p class='muted small'>No embeddings yet.</p>"; $("coverage").innerHTML = ""; return; }
  const W = 520, H = 340, P = 14;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (v) => P + ((v - x0) / (x1 - x0)) * (W - 2 * P), sy = (v) => H - P - ((v - y0) / (y1 - y0)) * (H - 2 * P);
  const color = { flowarc: "var(--series-1)", car_baseline: "var(--series-2)" };
  const ids = new Set(state.samples.map((s) => s.id));
  const order = [...pts].sort((a, b) => (a.source === "car_baseline") - (b.source === "car_baseline"));
  let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="none" stroke="var(--grid)" rx="8"/>`;
  for (const p of order) {
    const mine = ids.has(p.id), r = mine ? 5.5 : 4;
    g += `<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${r}" fill="${color[p.source] || "var(--muted)"}" stroke="var(--surface)" stroke-width="1.5" opacity="${p.source === "car_baseline" ? 0.85 : 1}" data-tip="<b>${esc(p.label)}</b><br>${esc(p.bucket)} · ${p.source === "car_baseline" ? "car baseline" : "FlowArc"}" ${mine ? `data-id="${p.id}" style="cursor:pointer"` : ""}/>`;
    if (p.id === selected) g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="10" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
  }
  $("divmap").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shape embedding map, FlowArc samples versus a car-only baseline">${g}</svg>`;
  bindHover($("divmap"));
  $("divmap").querySelectorAll("[data-id]").forEach((c) => c.addEventListener("click", () => { selected = c.dataset.id; render(); }));
  const n = (src) => pts.filter((p) => p.source === src).length;
  const spread = (src) => { const q = pts.filter((p) => p.source === src); if (!q.length) return 0; const mx = q.reduce((a, p) => a + p.x, 0) / q.length, my = q.reduce((a, p) => a + p.y, 0) / q.length; return Math.sqrt(q.reduce((a, p) => a + (p.x - mx) ** 2 + (p.y - my) ** 2, 0) / q.length); };
  $("div-legend").innerHTML = `<span><span class="swatch" style="background:var(--series-1)"></span>FlowArc (${n("flowarc")}, spread ${spread("flowarc").toFixed(2)})</span><span><span class="swatch" style="background:var(--series-2)"></span>${esc(state.diversity.baseline || "car baseline")} (${n("car_baseline")}, spread ${spread("car_baseline").toFixed(2)})</span>`;
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
  $("approvals").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { selected = b.dataset.open; render(); $("h-sample").scrollIntoView({ behavior: "smooth" }); }));
}

async function decide(id, decision) {
  localApprovals[id] = { status: decision };
  if (!staticMode) {
    await fetch("api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, decision }) }).catch(() => {});
  }
  Object.assign(state.approvals.find((a) => a.id === id), localApprovals[id]);
  renderApprovals();
}

// ---------- theme ----------
$("theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
});

load();
setInterval(() => { if (!staticMode && !replayTimer) load(); }, POLL_MS);

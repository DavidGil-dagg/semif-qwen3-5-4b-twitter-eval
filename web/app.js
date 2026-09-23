const $ = (id) => document.getElementById(id);

const state = {
  status: "idle",
  error: null,
  labels: [],
  metrics: null,
  progress: { done: 0, total: 0 },
  recent: [],
  dataset: null,
  settings: null,
  semif: null,
};

const isRunning = () => ["waiting_ready", "running", "paused"].includes(state.status);

const pct = (value) => (value == null ? "—" : (value * 100).toFixed(1) + "%");
const ms = (value) => (value == null ? "—" : Math.round(value) + " ms");

function duration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- rendering ---------------- */

function renderSemif() {
  const probe = state.semif || {};
  const dot = $("api-dot");
  dot.className = "dot " + (probe.ready ? "ready" : probe.reachable ? "loading" : "error");
  const label = probe.ready ? "ready" : probe.reachable ? probe.status || "loading" : "unreachable";
  $("api-info").innerHTML = `API SemIf: <b>${escapeHtml(label)}</b>` +
    (probe.model ? ` · ${escapeHtml(probe.model)}` : "") +
    (probe.device ? ` · ${escapeHtml(probe.device)}` : "");
}

function renderStatus() {
  const badge = $("status-badge");
  badge.className = "badge " + state.status;
  badge.textContent = state.status;

  const messages = {
    idle: "Listo para clasificar.",
    waiting_ready: "Esperando a que el modelo cargue en la API SemIf…",
    running: "Clasificando…",
    paused: "Pausado. Pulsa Reanudar para continuar.",
    done: "Clasificación completa. Comparando con las etiquetas originales.",
    stopped: "Detenido antes de terminar.",
    error: state.error || "Error durante la ejecución.",
  };
  $("status-line").textContent = messages[state.status] || state.status;

  $("start").disabled = isRunning();
  $("pause").disabled = !isRunning();
  $("stop").disabled = !isRunning();
  $("pause").textContent = state.status === "paused" ? "Reanudar" : "Pausar";
}

function renderProgress() {
  const { done = 0, total = 0, avg_ms, eta_s } = state.progress || {};
  $("s-progress").textContent = `${done} / ${total}`;
  $("s-lat").textContent = ms(avg_ms);
  $("s-eta").textContent = duration(eta_s);
  const ratio = total ? done / total : 0;
  $("bar-fill").style.width = (ratio * 100).toFixed(1) + "%";

  const metrics = state.metrics;
  $("s-acc").textContent = metrics && metrics.evaluated ? pct(metrics.accuracy) : "—";
  $("s-err").textContent = metrics ? metrics.errors : 0;
}

function scoreBars(scores, predicted) {
  const labels = state.labels.length ? state.labels : Object.keys(scores || {});
  if (!labels.length) return "";
  return `<div class="scores">${labels.map((label) => {
    const value = (scores || {})[label] ?? 0;
    const winner = label === predicted ? " winner" : "";
    return `<div class="score-row${winner}">
      <span>${escapeHtml(label)}</span>
      <span class="track"><span class="fill" style="width:${(value * 100).toFixed(1)}%"></span></span>
      <span class="num">${(value * 100).toFixed(1)}%</span>
    </div>`;
  }).join("")}</div>`;
}

function renderCurrent() {
  const row = state.recent[state.recent.length - 1];
  const box = $("current");
  if (!row) {
    box.className = "current empty";
    box.textContent = "Sin clasificaciones todavía.";
    return;
  }
  box.className = "current";
  const verdict = row.error
    ? `<span class="chip bad">error</span>`
    : row.correct
      ? `<span class="chip good">acierto</span>`
      : `<span class="chip bad">fallo</span>`;
  box.innerHTML = `
    <div class="head">
      <span class="chip">#${row.index}</span>
      <span class="chip">${escapeHtml(row.topic || "—")}</span>
      <span class="chip">real: ${escapeHtml(row.gold)}</span>
      <span class="chip">pred: ${escapeHtml(row.predicted ?? "—")}</span>
      ${verdict}
      <span class="muted">${ms(row.elapsed_ms)}</span>
    </div>
    <div class="text">${escapeHtml(row.text)}</div>
    ${row.error ? `<p class="muted">${escapeHtml(row.error)}</p>` : scoreBars(row.scores, row.predicted)}`;
}

function renderConfusion() {
  const box = $("confusion");
  const metrics = state.metrics;
  if (!metrics) { box.className = "empty"; box.textContent = "—"; return; }
  const { labels, confusion } = metrics;
  box.className = "";
  const header = `<tr><th class="row-head">real \\ pred</th>${labels.map((l) => `<th>${escapeHtml(l)}</th>`).join("")}</tr>`;
  const body = labels.map((label, i) => {
    const rowMax = Math.max(1, ...confusion[i]);
    const cells = labels.map((_, j) => {
      const value = confusion[i][j];
      if (!value) return `<td class="cell" style="color:var(--muted)">·</td>`;
      const alpha = (0.12 + 0.8 * (value / rowMax)).toFixed(2);
      const colour = i === j ? "53,192,127" : "79,140,255";
      const diagonal = i === j ? " diag" : "";
      return `<td class="cell${diagonal}" style="background:rgba(${colour},${alpha})">${value}</td>`;
    }).join("");
    return `<tr><td class="row-head">${escapeHtml(label)}</td>${cells}</tr>`;
  }).join("");
  box.innerHTML = `<table class="cm">${header}${body}</table>`;
}

function bar(label, value, colour) {
  return `<div class="pc-bars">
    <span class="lbl">${label}</span>
    <span class="track"><span class="fill" style="width:${(value * 100).toFixed(1)}%;background:${colour}"></span></span>
    <span class="num">${(value * 100).toFixed(0)}%</span>
  </div>`;
}

function renderPerClass() {
  const box = $("per-class");
  const metrics = state.metrics;
  if (!metrics) { box.className = "empty"; box.textContent = "—"; return; }
  box.className = "pc";
  box.innerHTML = metrics.per_class.map((row) => `
    <div class="pc-row">
      <div class="pc-head">
        <b>${escapeHtml(row.label)}</b>
        <span class="sup">support ${row.support} · predicho ${row.predicted}</span>
      </div>
      ${bar("precision", row.precision, "var(--accent)")}
      ${bar("recall", row.recall, "var(--warn)")}
      ${bar("f1", row.f1, "var(--good)")}
    </div>`).join("") +
    `<div class="pc-head" style="margin-top:6px">
      <span class="sup">macro F1 <b>${pct(metrics.macro.f1)}</b></span>
      <span class="sup">weighted F1 <b>${pct(metrics.weighted.f1)}</b></span>
    </div>`;
}

function renderRecent() {
  const body = $("recent").querySelector("tbody");
  const rows = [...state.recent].reverse().slice(0, 100);
  $("recent-count").textContent = state.recent.length ? `(${state.recent.length} en memoria)` : "";
  body.innerHTML = rows.map((row) => {
    const verdict = row.error ? "chip bad" : row.correct ? "chip good" : "chip bad";
    const label = row.error ? "error" : row.correct ? "acierto" : "fallo";
    const score = row.predicted && row.scores ? (row.scores[row.predicted] ?? 0) : null;
    return `<tr>
      <td>${row.index}</td>
      <td class="muted" title="${escapeHtml(row.text)}">${escapeHtml(row.text.slice(0, 110))}${row.text.length > 110 ? "…" : ""}</td>
      <td>${escapeHtml(row.gold)}</td>
      <td>${escapeHtml(row.predicted ?? "—")} <span class="${verdict}">${label}</span></td>
      <td>${score == null ? "—" : (score * 100).toFixed(0) + "%"}</td>
    </tr>`;
  }).join("");
}

function renderDataset() {
  const data = state.dataset;
  const dist = $("gold-dist");
  if (!data) { dist.className = "empty"; dist.textContent = "—"; $("dataset-meta").textContent = ""; return; }
  dist.className = "dist";
  const distribution = data.gold_distribution || {};
  const max = Math.max(1, ...Object.values(distribution));
  dist.innerHTML = Object.entries(distribution).map(([label, count]) => `
    <div class="row">
      <span class="lbl">${escapeHtml(label)}</span>
      <span class="track"><span class="fill" style="width:${((count / max) * 100).toFixed(1)}%"></span></span>
      <span class="num">${count}</span>
    </div>`).join("");
  $("dataset-meta").innerHTML = `
    <b>${escapeHtml(data.path)}</b><br>
    filas: <b>${data.total_rows}</b> · elegibles: <b>${data.eligible}</b> · seleccionadas: <b>${data.selected}</b><br>
    descartadas: <b>${data.skipped_empty}</b> sin texto · <b>${data.skipped_label}</b> sin etiqueta conocida`;
}

function renderFinal(payload) {
  const metrics = payload.metrics || state.metrics;
  if (!metrics) return;
  $("final").hidden = false;
  const cards = [
    ["Accuracy", pct(metrics.accuracy)],
    ["Evaluadas", `${metrics.evaluated}`],
    ["Aciertos", `${metrics.correct}`],
    ["Errores", `${metrics.errors}`],
    ["Macro F1", pct(metrics.macro.f1)],
    ["Weighted F1", pct(metrics.weighted.f1)],
    ["Latencia media", ms(metrics.latency_ms_avg)],
    ["Tiempo total", duration(metrics.seconds)],
  ];
  $("final-summary").innerHTML = cards.map(([k, v]) =>
    `<div class="stat"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("");
  const dir = (state.settings && state.settings.results_dir) || "results";
  $("artifacts").textContent = `Artefactos escritos en ${dir}/: predictions.jsonl, metrics.json, confusion_matrix.csv`;
  loadMisclassified();
}

async function loadMisclassified() {
  try {
    const response = await fetch("/api/misclassified?limit=100");
    if (!response.ok) return;
    const rows = await response.json();
    $("errors").querySelector("tbody").innerHTML = rows.length
      ? rows.map((row) => `<tr>
          <td>${row.index}</td>
          <td class="muted">${escapeHtml(row.text.slice(0, 140))}${row.text.length > 140 ? "…" : ""}</td>
          <td>${escapeHtml(row.gold)}</td>
          <td>${escapeHtml(row.predicted ?? "error")}</td>
        </tr>`).join("")
      : `<tr><td colspan="4" class="muted">Ninguna: todas las filas evaluadas coincidieron.</td></tr>`;
  } catch (error) { /* ignore */ }
}

function renderAll() {
  state.labels = (state.metrics && state.metrics.labels) || (state.settings && state.settings.labels.map((l) => l.id)) || [];
  renderSemif();
  renderStatus();
  renderProgress();
  renderCurrent();
  renderConfusion();
  renderPerClass();
  renderRecent();
  renderDataset();
}

/* ---------------- events ---------------- */

function applySnapshot(payload) {
  state.status = payload.status || "idle";
  state.error = payload.error || null;
  state.semif = payload.semif || null;
  state.metrics = payload.metrics || null;
  state.progress = payload.progress || state.progress;
  state.recent = payload.recent || [];
  state.dataset = payload.dataset || null;
  state.settings = payload.settings || null;
  if (state.dataset) $("final").hidden = state.status === "done";
  if (state.dataset) $("limit").value = state.dataset.selected || 0;
  renderAll();
}

function handle(payload) {
  switch (payload.type) {
    case "snapshot":
      applySnapshot(payload);
      break;
    case "semif":
      state.semif = payload.semif;
      renderSemif();
      break;
    case "status":
      state.status = payload.status;
      state.error = payload.error || null;
      renderStatus();
      break;
    case "dataset":
      state.dataset = payload.dataset;
      state.settings = payload.settings;
      state.recent = [];
      state.metrics = null;
      state.progress = { done: 0, total: payload.dataset.selected };
      $("final").hidden = true;
      $("errors").querySelector("tbody").innerHTML = "";
      renderAll();
      break;
    case "row":
      state.recent.push(payload.row);
      if (state.recent.length > 60) state.recent.shift();
      state.metrics = payload.metrics;
      state.progress = payload.progress;
      state.labels = payload.metrics.labels;
      renderProgress();
      renderCurrent();
      renderConfusion();
      renderPerClass();
      renderRecent();
      break;
    case "done":
      state.status = payload.status;
      if (payload.metrics) state.metrics = payload.metrics;
      if (payload.progress) state.progress = payload.progress;
      renderStatus();
      renderProgress();
      renderConfusion();
      renderPerClass();
      if (payload.status === "done") renderFinal(payload);
      break;
  }
}

function connect() {
  const source = new EventSource("/events");
  source.onmessage = (event) => {
    try { handle(JSON.parse(event.data)); } catch (error) { console.error(error); }
  };
  source.onerror = () => { /* EventSource reconnects and resends a snapshot */ };
}

/* ---------------- controls ---------------- */

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    alert(detail.detail || `HTTP ${response.status}`);
    return null;
  }
  return response.json();
}

$("start").addEventListener("click", async () => {
  const limit = Number($("limit").value) || 0;
  const sample = $("sample").value;
  $("final").hidden = true;
  if (await post("/api/start", { limit, sample })) {
    state.status = "waiting_ready";
    renderStatus();
  }
});

$("pause").addEventListener("click", () => {
  post(state.status === "paused" ? "/api/resume" : "/api/pause");
});

$("stop").addEventListener("click", () => post("/api/stop"));

(async function init() {
  const response = await fetch("/api/snapshot");
  if (response.ok) applySnapshot(await response.json());
  connect();
})();

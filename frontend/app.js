// River Outlook frontend: no build step, no framework.
// Flow: POST /api/forecasts -> poll GET /api/forecasts/{id} until completed.

const API = (window.RIVER_API_BASE || "").replace(/\/$/, "");
const POLL_MS = 1500;
const CLIENT_TIMEOUT_MS = 180_000;

const GAUGES = [
  ["01646500", "Potomac River near Washington, DC"],
  ["07010000", "Mississippi River at St. Louis, MO"],
  ["06934500", "Missouri River at Hermann, MO"],
  ["14105700", "Columbia River at The Dalles, OR"],
  ["09380000", "Colorado River at Lees Ferry, AZ"],
  ["08158000", "Colorado River at Austin, TX"],
  ["01463500", "Delaware River at Trenton, NJ"],
  ["03049500", "Allegheny River at Natrona, PA"],
  ["02489500", "Pearl River near Bogalusa, LA"],
];
// A real gauge that does not report discharge: shows input validation end to end.
const NO_FLOW_GAUGE = ["03085000", "Monongahela River at Braddock, PA (no flow data)"];
const FAULTS = [
  ["openmeteo_down", "Open-Meteo down"],
  ["usgs_rate_limit", "USGS rate limit (429)"],
  ["usgs_down", "USGS down"],
  ["gpu_down", "Runpod GPU unavailable"],
];

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "style") n.style.cssText = v; else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (v) => v === 0 ? "0" : v >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(v < 10 ? 2 : 0);

class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || (body && body.detail) || `Request failed (HTTP ${status})`);
    this.status = status;
    this.code = e.code || "http_error";
    this.service = e.service;
    this.retryAfter = e.retry_after;
  }
}

async function api(path, opts = {}) {
  let resp;
  try {
    resp = await fetch(API + path, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch {
    throw new ApiError(0, { error: { code: "network", message: "Can't reach the gateway. Is the Runpod pod running?" } });
  }
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body);
  return body;
}

// Start a forecast and poll until it completes. onUpdate sees every state.
async function forecastJob(siteId, horizon, faults, onUpdate) {
  const q = faults.length ? `?simulate=${faults.join(",")}` : "";
  let job = await api(`/api/forecasts${q}`, {
    method: "POST", body: JSON.stringify({ site_id: siteId, horizon_days: horizon }),
  });
  const started = Date.now();
  let misses = 0;
  onUpdate(job);
  while (job.status !== "completed") {
    if (Date.now() - started > CLIENT_TIMEOUT_MS) {
      throw new ApiError(0, { error: { code: "client_timeout", message: "The forecast took too long. Try again." } });
    }
    await sleep(POLL_MS);
    try {
      job = await api(`/api/forecasts/${job.job_id}`);
      misses = 0;
    } catch (err) {
      // Polls are idempotent: ride out a few network blips before giving up.
      if (err.code !== "network" || ++misses > 3) throw err;
      continue;
    }
    onUpdate(job);
  }
  return job;
}

// ------------------------------------------------------------------ form
function initForm() {
  for (const [id, name] of [...GAUGES, NO_FLOW_GAUGE]) $("preset").append(el("option", { value: id }, name));
  $("preset").addEventListener("change", () => { $("site").value = ""; });

  api("/api/health").then((h) => {
    if (!h.fault_injection) return;
    $("drills").hidden = false;
    for (const [key, label] of FAULTS) {
      $("faults").append(el("label", { class: "fault" }, el("input", { type: "checkbox", value: key }), label));
    }
  }).catch(() => {});

  $("form").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  $("retry").addEventListener("click", submit);
  $("burst").addEventListener("click", burst);
}

function readForm() {
  const site = $("site").value.trim() || $("preset").value;
  const horizon = Number($("horizon").value);
  if (!/^\d{8,15}$/.test(site)) return { error: "A USGS site id is 8 to 15 digits, e.g. 01646500." };
  if (!Number.isInteger(horizon) || horizon < 1 || horizon > 14) return { error: "Days ahead must be 1 to 14." };
  const faults = [...document.querySelectorAll("#faults input:checked")].map((i) => i.value);
  return { site, horizon, faults };
}

let ticker = null;
async function submit() {
  const input = readForm();
  $("form-error").hidden = !input.error;
  if (input.error) { $("form-error").textContent = input.error; return; }

  $("go").disabled = true;
  $("error").hidden = true;
  $("result").hidden = true;
  $("progress").hidden = false;
  setSteps({ status: "fetching" });
  const t0 = performance.now();
  ticker = setInterval(() => { $("elapsed").textContent = ((performance.now() - t0) / 1000).toFixed(1); }, 100);

  try {
    const job = await forecastJob(input.site, input.horizon, input.faults, setSteps);
    renderResult(job);
  } catch (err) {
    showError(err);
  } finally {
    clearInterval(ticker);
    $("go").disabled = false;
  }
}

function setSteps(job) {
  const order = ["fetch", "queued", "running", "done"];
  let active = "fetch", skipped = [];
  if (job.status === "queued") active = "queued";
  else if (job.status === "running") active = "running";
  else if (job.status === "completed") {
    active = "done";
    if (job.mode === "baseline") skipped = ["queued", "running"];
  }
  $("rp-status").textContent = job.runpod_status || "-";
  for (const li of document.querySelectorAll(".steps li")) {
    const s = li.dataset.step;
    li.className = skipped.includes(s) ? "skipped"
      : s === active ? (s === "done" ? "done" : "active")
      : order.indexOf(s) < order.indexOf(active) ? "done" : "";
  }
}

function showError(err) {
  $("progress").hidden = true;
  $("error").hidden = false;
  const titles = {
    upstream_rate_limited: `${err.service || "An upstream API"} is rate limiting us`,
    upstream_unavailable: `${err.service || "An upstream API"} is unavailable`,
    rate_limited: "Slow down a little",
    invalid_input: "Check your input",
    no_discharge_data: "This gauge doesn't measure flow",
    insufficient_data: "Not enough data to forecast",
    site_not_found: "Gauge not found",
    network: "Gateway unreachable",
  };
  $("error-title").textContent = titles[err.code] || "Something went wrong";
  $("error-msg").textContent = err.message;

  const btn = $("retry");
  if (err.retryAfter) {
    let left = err.retryAfter;
    btn.disabled = true;
    const tick = () => {
      btn.textContent = left > 0 ? `Try again in ${left}s` : "Try again";
      if (left-- <= 0) { btn.disabled = false; clearInterval(t); }
    };
    const t = setInterval(tick, 1000); tick();
  } else {
    btn.disabled = false;
    btn.textContent = "Try again";
  }
}

// ---------------------------------------------------------------- result
function renderResult(job) {
  $("progress").hidden = true;
  $("result").hidden = false;

  $("notices").replaceChildren(...job.notices.map((n) => el("div", { class: "notice" }, n)));
  $("site-name").textContent = job.site.name;
  $("site-meta").textContent = `USGS ${job.site.id}${job.site.state ? " · " + job.site.state : ""}`;

  const m = job.model || {};
  const badge = $("model-badge");
  badge.className = "badge" + (job.mode === "gpu" ? " gpu" : "");
  badge.textContent = job.mode === "gpu"
    ? `Chronos-2 · ${m.device || "GPU"} · ${m.covariates ? "rain-aware" : "flow only"}`
    : `${m.name} · fallback`;

  const last = job.history[job.history.length - 1];
  const end = job.forecast[job.forecast.length - 1];
  const rainAhead = job.rain ? job.rain.future.reduce((a, r) => a + r.mm, 0) : null;
  $("stats").replaceChildren(
    stat(`${fmt(last.value)} cfs`, `Latest daily flow (${last.date})`),
    stat(`${fmt(end.p50)} cfs`, `Median in ${job.horizon} days`),
    stat(`${fmt(end.p10)} to ${fmt(end.p90)}`, "80% range, cfs"),
    stat(rainAhead == null ? "n/a" : `${rainAhead.toFixed(0)} mm`, `Rain forecast, next ${job.horizon} days`),
  );

  drawCharts(job);
  renderTable(job);
  renderTrace(job.trace);
}

const stat = (v, k) => el("div", { class: "stat" }, el("div", { class: "v" }, v), el("div", { class: "k" }, k));

function renderTable(job) {
  const rain = new Map((job.rain?.future || []).map((r) => [r.date, r.mm]));
  $("table").replaceChildren(
    el("tr", {}, ...["Date", "p10 (cfs)", "Median (cfs)", "p90 (cfs)", "Rain (mm)"].map((h) => el("th", {}, h))),
    ...job.forecast.map((f) => el("tr", {},
      el("td", {}, f.date), el("td", {}, fmt(f.p10)), el("td", {}, fmt(f.p50)), el("td", {}, fmt(f.p90)),
      el("td", {}, rain.has(f.date) ? rain.get(f.date).toFixed(1) : "-"))),
  );
}

function renderTrace(spans) {
  const total = Math.max(1, ...spans.map((s) => s.start_ms + s.ms));
  $("trace").replaceChildren(...spans.map((s) => {
    const cls = "span" + (s.name.startsWith("Runpod") ? " runpod" : "") + (s.ok ? "" : " fail");
    const bar = el("div", { class: "bar", style: `left:${(s.start_ms / total) * 100}%;width:${(s.ms / total) * 100}%` });
    const row = el("div", { class: cls }, el("div", {}, s.name), el("div", { class: "track" }, bar),
      el("div", { class: "ms" }, s.ms >= 1000 ? `${(s.ms / 1000).toFixed(1)} s` : `${s.ms} ms`));
    if (s.detail) row.append(el("div", { class: "detail" }, s.detail));
    return row;
  }));
}

// ----------------------------------------------------------------- charts
// Flow and rain have different units, so they get two stacked charts that
// share one time axis instead of a dual-axis chart.
const SVGNS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const W = 900, PAD = { l: 64, r: 16, t: 10, b: 22 };

function niceTicks(max, count = 4) {
  const step0 = max / count, mag = 10 ** Math.floor(Math.log10(step0 || 1));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, i) => i * step);
}

const CHART_DAYS = 45; // zoom in so the forecast is readable; the table has the rest

function drawCharts(fullJob) {
  const job = { ...fullJob, history: fullJob.history.slice(-CHART_DAYS) };
  const days = [...job.history.map((h) => h.date), ...job.forecast.map((f) => f.date)];
  const x = (i) => PAD.l + (i / (days.length - 1)) * (W - PAD.l - PAD.r);
  const nHist = job.history.length;

  // Flow chart
  const H = 260;
  const ymax = Math.max(...job.history.map((h) => h.value), ...job.forecast.map((f) => f.p90)) * 1.05;
  const ticks = niceTicks(ymax);
  const top = ticks[ticks.length - 1];
  const y = (v) => H - PAD.b - (v / top) * (H - PAD.t - PAD.b);
  const flow = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Daily discharge for ${job.site.name}, observed and forecast` });
  for (const t of ticks) {
    flow.append(svg("line", { x1: PAD.l, x2: W - PAD.r, y1: y(t), y2: y(t), stroke: "var(--grid)" }));
    const lbl = svg("text", { x: PAD.l - 8, y: y(t) + 4, "text-anchor": "end" });
    lbl.textContent = fmt(t);
    flow.append(lbl);
  }
  const ylab = svg("text", { x: 12, y: H / 2, transform: `rotate(-90 12 ${H / 2})`, "text-anchor": "middle" });
  ylab.textContent = "cfs";
  flow.append(ylab);
  dateTicks(flow, days, x, H);

  // Forecast band, anchored to the last observation so the line is continuous.
  const fx = (i) => x(nHist - 1 + i);
  const lastV = job.history[nHist - 1].value;
  const band = [[fx(0), y(lastV)], ...job.forecast.map((f, i) => [fx(i + 1), y(f.p90)]),
    ...job.forecast.map((f, i) => [fx(i + 1), y(f.p10)]).reverse()];
  flow.append(svg("polygon", { points: band.map((p) => p.join(",")).join(" "), fill: "var(--series-2)", "fill-opacity": 0.18 }));
  flow.append(svg("polyline", { points: job.history.map((h, i) => `${x(i)},${y(h.value)}`).join(" "),
    fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round" }));
  flow.append(svg("polyline", { points: [[fx(0), y(lastV)], ...job.forecast.map((f, i) => [fx(i + 1), y(f.p50)])].map((p) => p.join(",")).join(" "),
    fill: "none", stroke: "var(--series-2)", "stroke-width": 2, "stroke-dasharray": "5 4" }));
  flow.append(svg("line", { x1: x(nHist - 1), x2: x(nHist - 1), y1: PAD.t, y2: H - PAD.b,
    stroke: "var(--text-muted)", "stroke-dasharray": "2 3" }));

  // Rain chart (only when Open-Meteo answered)
  const rainHost = $("rain-chart");
  rainHost.replaceChildren();
  let rainByDate = new Map();
  if (job.rain) {
    const RH = 100;
    const all = [...job.rain.past, ...job.rain.future];
    rainByDate = new Map(all.map((r) => [r.date, r.mm]));
    const rmax = niceTicks(Math.max(5, ...all.map((r) => r.mm)), 2);
    const rtop = rmax[rmax.length - 1];
    const ry = (v) => RH - PAD.b - (v / rtop) * (RH - PAD.t - PAD.b);
    const rain = svg("svg", { viewBox: `0 0 ${W} ${RH}`, role: "img", "aria-label": "Daily rainfall at the gauge, past and forecast" });
    for (const t of rmax) {
      rain.append(svg("line", { x1: PAD.l, x2: W - PAD.r, y1: ry(t), y2: ry(t), stroke: "var(--grid)" }));
      const l = svg("text", { x: PAD.l - 8, y: ry(t) + 4, "text-anchor": "end" });
      l.textContent = `${t} mm`;
      rain.append(l);
    }
    const bw = Math.max(1, (W - PAD.l - PAD.r) / days.length - 2);
    days.forEach((d, i) => {
      const mm = rainByDate.get(d);
      if (!mm) return;
      rain.append(svg("rect", { x: x(i) - bw / 2, y: ry(mm), width: bw, height: Math.max(1, ry(0) - ry(mm)),
        rx: Math.min(2, bw / 2), fill: "var(--series-3)", "fill-opacity": i >= nHist ? 0.55 : 1 }));
    });
    rainHost.append(rain);
  }

  $("legend").replaceChildren(
    el("span", { style: "--c:var(--series-1)" }, "Observed flow (USGS)"),
    el("span", { style: "--c:var(--series-2)" }, "Forecast median"),
    el("span", { class: "band", style: "--c:var(--series-2)" }, "80% range"),
    ...(job.rain ? [el("span", { style: "--c:var(--series-3)" }, "Rain, mm/day (Open-Meteo; faded = forecast)")] : []),
  );

  $("flow-chart").replaceChildren(flow);
  attachHover(job, days, x, y, flow, rainByDate);
}

function dateTicks(root, days, x, H) {
  const every = Math.ceil(days.length / 6);
  days.forEach((d, i) => {
    if (i % every) return;
    const t = svg("text", { x: x(i), y: H - 6, "text-anchor": "middle" });
    t.textContent = d.slice(5);
    root.append(t);
  });
}

function attachHover(job, days, x, y, flow, rainByDate) {
  const tip = $("tooltip");
  const cross = svg("line", { y1: PAD.t, y2: 260 - PAD.b, stroke: "var(--text-secondary)", visibility: "hidden" });
  const dot = svg("circle", { r: 4, fill: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" });
  flow.append(cross, dot);
  const hist = new Map(job.history.map((h) => [h.date, h.value]));
  const fc = new Map(job.forecast.map((f) => [f.date, f]));

  const hit = svg("rect", { x: PAD.l, y: 0, width: W - PAD.l - PAD.r, height: 260, fill: "transparent" });
  flow.append(hit);
  hit.addEventListener("mousemove", (ev) => {
    const box = flow.getBoundingClientRect();
    const sx = ((ev.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(days.length - 1, Math.round(((sx - PAD.l) / (W - PAD.l - PAD.r)) * (days.length - 1))));
    const d = days[i], obs = hist.get(d), f = fc.get(d), mm = rainByDate.get(d);
    const v = obs ?? f.p50;
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(v)); dot.setAttribute("visibility", "visible");
    dot.setAttribute("stroke", obs != null ? "var(--series-1)" : "var(--series-2)");
    const lines = [d, obs != null ? `Observed: ${fmt(obs)} cfs`
      : `Forecast: ${fmt(f.p50)} cfs (${fmt(f.p10)} to ${fmt(f.p90)})`];
    if (mm != null) lines.push(`Rain: ${mm.toFixed(1)} mm`);
    tip.replaceChildren(...lines.map((l, k) => el("div", k ? {} : { style: "font-weight:600" }, l)));
    tip.hidden = false;
    const card = tip.parentElement.getBoundingClientRect();
    const left = ev.clientX - card.left + 14;
    tip.style.left = `${Math.min(left, card.width - tip.offsetWidth - 8)}px`;
    tip.style.top = `${ev.clientY - card.top + 14}px`;
  });
  hit.addEventListener("mouseleave", () => {
    tip.hidden = true; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
  });
}

// ------------------------------------------------------------------ burst
async function burst() {
  const btn = $("burst");
  btn.disabled = true;
  const chips = new Map(GAUGES.map(([id, name]) => {
    const s = el("div", { class: "s" }, "submitting");
    return [id, { root: el("div", { class: "chip" }, el("div", {}, name), s), s }];
  }));
  $("burst-grid").replaceChildren(...[...chips.values()].map((c) => c.root));
  const t0 = performance.now();

  await Promise.all(GAUGES.map(async ([id]) => {
    const c = chips.get(id);
    try {
      const job = await forecastJob(id, 7, [], (j) => {
        c.s.textContent = j.status === "completed" ? "" : `${j.runpod_status || j.status} · ${j.elapsed_s}s`;
      });
      const end = job.forecast[job.forecast.length - 1];
      c.root.classList.add(job.mode);
      c.s.textContent = `${job.mode === "gpu" ? job.model.device : "baseline"} · day 7: ${fmt(end.p50)} cfs`;
    } catch (err) {
      c.root.classList.add("failed");
      c.s.textContent = err.message;
    }
  }));
  btn.disabled = false;
  btn.textContent = `Run burst (last: ${((performance.now() - t0) / 1000).toFixed(1)} s)`;
}

initForm();

/* Writer page + navigation + mini-mode handoff. */
(() => {
"use strict";
const { $, $$, api, icon, fmtDur, fmtClock, words, toast } = C;
C.hydrateIcons();

// ------------------------------------------------------------------ navigation
$$(".nav-btn[data-view]").forEach(b => b.addEventListener("click", () => showView(b.dataset.view)));
function showView(v, animate = true) {
  const a = api();
  if (a && animate) a.set_ui("last_page", v);
  $$(".nav-btn[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === v));
  const prev = $(".view.active");
  if (prev && animate && prev.id !== `view-${v}` && !document.documentElement.classList.contains("no-motion")) {
    prev.classList.add("leaving");
    setTimeout(() => prev.classList.remove("leaving"), 220);
  }
  $$(".view").forEach(s => s.classList.toggle("active", s.id === `view-${v}`));
  moveNavIndicator(animate);
  const view = $(`#view-${v}`);
  if (view && animate) C.enterView(view);
  requestAnimationFrame(() => C.refreshSegs(view || document));   // thumbs need a visible layout
  document.dispatchEvent(new CustomEvent("viewshown", { detail: v }));
}
function moveNavIndicator(animate) {
  const ind = $(".nav-ind"), b = $(".nav-btn.active");
  if (!ind || !b) return;
  ind.classList.toggle("no-anim", !animate || !ind.classList.contains("ready"));
  ind.style.setProperty("--y", `${b.offsetTop + (b.offsetHeight - 20) / 2}px`);
  requestAnimationFrame(() => { ind.classList.add("ready"); ind.classList.remove("no-anim"); });
}
window.addEventListener("resize", () => moveNavIndicator(false));
window.App = { show: showView };

// ------------------------------------------------------------------ settings model
const S = {
  speed_mode: "wpm", wpm: 55, target_minutes: 30, speed_variance: 0.30,
  typo_rate: 0.03, revise_enabled: true, revision_amount: "Some", revise_when: "Mixed",
  rethink_enabled: true, word_jumps: true, empty_doc: false,
  punct_pause_scale: 1.0, thinking_freq: 0.04, burst_enabled: true, fatigue_enabled: true,
  break_enabled: false, break_every_min: 10, break_length_min: 2,
  countdown: 5, focus_lock: true, auto_mini: true, sounds: false, shift_enter: false,
};
let preset = "Natural";
let presetList = [{ name: "Natural", builtin: true }, { name: "Fast & Clean", builtin: true },
                  { name: "Casual", builtin: true }, { name: "Slow & Careful", builtin: true }];
const PRESET_KEYS = new Set(["wpm", "speed_variance", "typo_rate", "revise_enabled", "revision_amount", "revise_when",
  "rethink_enabled", "punct_pause_scale", "thinking_freq", "burst_enabled", "fatigue_enabled"]);

const variance = v => v < 0.08 ? "Robotic" : v < 0.2 ? "Low" : v < 0.42 ? "Natural" : "Jittery";
const SCHEMA = [
  { title: "Speed", icon: "gauge", rows: [
    { k: "speed_mode", type: "seg", opts: [["wpm", "Words per minute"], ["duration", "Target duration"]] },
    { k: "wpm", type: "slider", label: "Typing speed", min: 15, max: 150, step: 1, fmt: v => `${Math.round(v)} wpm`, show: () => S.speed_mode === "wpm" },
    { k: "target_minutes", type: "duration", label: "Finish in", desc: "Minutes, or h:mm", show: () => S.speed_mode === "duration" },
    { k: "speed_variance", type: "slider", label: "Speed variance", min: 0, max: 0.6, step: 0.01, fmt: v => variance(v) },
    { type: "note", id: "speed-note" },
  ]},
  { title: "Mistakes", icon: "crosshair", rows: [
    { k: "typo_rate", type: "slider", label: "Typo rate", desc: "Neighbouring keys, doubled and swapped letters, mostly caught within a few characters.",
      min: 0, max: 0.10, step: 0.0025, fmt: v => `${(v * 100).toFixed(1)}%` },
  ]},
  { title: "Revise later", icon: "pen-line", rows: [
    { k: "revise_enabled", type: "toggle", label: "Revise later", desc: "Leave some mistakes and rough wording in, then go back with the arrow keys and fix them." },
    { k: "revision_amount", type: "seg", label: "How many", opts: ["Few", "Some", "Many"], dep: "revise_enabled" },
    { k: "revise_when", type: "seg", label: "When", opts: [["After paragraphs", "Paragraphs"], ["At the end", "At the end"], ["Mixed", "Mixed"]], dep: "revise_enabled" },
    { k: "rethink_enabled", type: "toggle", label: "Rethink words", desc: "Types a word, deletes it, picks another." },
    { k: "word_jumps", type: "toggle", label: "Ctrl + arrow word jumps", desc: "Faster navigation, only where every editor agrees." },
    { k: "empty_doc", type: "toggle", label: "Document holds only this text", desc: "Enables Ctrl+Home/End and re-finding the cursor after a pause." },
  ]},
  { title: "Pauses & rhythm", icon: "hourglass", rows: [
    { k: "punct_pause_scale", type: "slider", label: "Pauses after , . and paragraphs", min: 0, max: 3, step: 0.1, fmt: v => `${(+v).toFixed(1)}×` },
    { k: "thinking_freq", type: "slider", label: "Thinking pauses", min: 0, max: 0.2, step: 0.005, fmt: v => v < 0.001 ? "Off" : `${Math.round(v * 100)}% of words` },
    { k: "burst_enabled", type: "toggle", label: "Burst-type common words", desc: "“the”, “and”, “-ing” come out faster." },
    { k: "fatigue_enabled", type: "toggle", label: "Fatigue", desc: "Gradually slows down over long texts." },
  ]},
  { title: "Sessions", icon: "coffee", rows: [
    { k: "break_enabled", type: "toggle", label: "Break mode", desc: "Type in chunks with breaks in between." },
    { k: "break_every_min", type: "slider", label: "Type for", min: 1, max: 60, step: 1, fmt: v => `${Math.round(v)} min`, dep: "break_enabled" },
    { k: "break_length_min", type: "slider", label: "Then break for", min: 0.5, max: 15, step: 0.5, fmt: v => `${(+v).toFixed(1)} min`, dep: "break_enabled" },
  ]},
  { title: "Safety & convenience", icon: "shield", rows: [
    { k: "countdown", type: "slider", label: "Countdown before typing", min: 0, max: 15, step: 1, fmt: v => `${Math.round(v)} s` },
    { k: "focus_lock", type: "toggle", label: "Focus lock", desc: "Pause if the active window changes. Return with Alt+Tab, then F8." },
    { k: "auto_mini", type: "toggle", label: "Mini mode while typing", desc: "Shrinks Cadence into a small always-on-top panel." },
    { k: "sounds", type: "toggle", label: "Keyboard click sounds" },
    { k: "shift_enter", type: "toggle", label: "New lines with Shift+Enter", desc: "For chat apps where Enter sends." },
  ]},
];
const ADVANCED_FIRST = "Revise later";
let collapsed = new Set(["Revise later", "Pauses & rhythm", "Sessions", "Safety & convenience"]);
const ROWS = Object.fromEntries(SCHEMA.flatMap(c => c.rows).filter(r => r.k).map(r => [r.k, r]));

function renderSettings() {
  let html = `<div class="card set-card"><div class="card-title"><h3>Preset</h3><button class="chip" id="btn-manage-presets">${icon("layers", "sm")}Manage</button></div>
    <div class="presets" style="padding:4px 0 12px">${presetList.map(p => `<button class="chip ${p.name === preset ? "on" : ""}" data-preset="${C.esc(p.name)}">${C.esc(p.name)}</button>`).join("")}
    <button class="chip" id="btn-save-preset">${icon("plus", "sm")}Save</button></div></div>`;
  for (const card of SCHEMA) {
    if (card.title === ADVANCED_FIRST) html += `<div class="adv-label eyebrow">Advanced</div>`;
    const folded = collapsed.has(card.title);
    html += `<div class="card set-card fold ${folded ? "collapsed" : ""}" data-sec="${card.title}">
      <button type="button" class="card-title sec-toggle" aria-expanded="${!folded}">
        <h3>${card.title}</h3><span class="sec-right"><span class="ic">${icon(card.icon, "sm")}</span>${icon("chevron-down", "sm chev")}</span></button>
      <div class="set-body"><div class="set-inner">`;
    for (const r of card.rows) html += rowHTML(r);
    html += `</div></div></div>`;
  }
  $("#writer-settings").innerHTML = html;
  refreshSettings();
}
function rowHTML(r) {
  const attrs = `data-row="${r.k || r.id || ""}"`;
  if (r.type === "toggle") return `<div class="row" ${attrs}><div class="row-head"><div><div class="row-label">${r.label}</div>${r.desc ? `<div class="row-desc">${r.desc}</div>` : ""}</div>
      <label class="switch"><input type="checkbox" data-k="${r.k}" aria-label="${r.label}"><span class="track"></span><span class="knob"></span></label></div></div>`;
  if (r.type === "slider") return `<div class="row" ${attrs}><div class="row-head"><div class="row-label">${r.label}</div><div class="row-val" data-val="${r.k}"></div></div>
      ${r.desc ? `<div class="row-desc">${r.desc}</div>` : ""}<input type="range" data-k="${r.k}" min="${r.min}" max="${r.max}" step="${r.step}" aria-label="${r.label}"></div>`;
  if (r.type === "seg") return `<div class="row" ${attrs}>${r.label ? `<div class="row-label">${r.label}</div>` : ""}${C.segHTML(r.k, r.opts)}</div>`;
  if (r.type === "duration") return `<div class="row" ${attrs}><div class="row-head"><div><div class="row-label">${r.label}</div><div class="row-desc">${r.desc}</div></div>
      <input class="input num" data-k="${r.k}" aria-label="${r.label}"></div></div>`;
  if (r.type === "note") return `<div class="note" id="${r.id}"></div>`;
  return "";
}

const host = $("#writer-settings");
host.addEventListener("input", e => {
  const el = e.target, k = el.dataset.k;
  if (!k) return;
  if (el.type === "checkbox") set(k, el.checked);
  else if (el.type === "range") set(k, +el.value);
  else if (ROWS[k] && ROWS[k].type === "duration") {
    const m = parseMinutes(el.value);
    el.classList.toggle("bad", m === null);
    if (m !== null) set(k, m, false);
  }
});
host.addEventListener("click", async e => {
  const tog = e.target.closest(".sec-toggle");
  if (tog) {
    const card = tog.closest(".set-card"), name = card.dataset.sec;
    const fold = !card.classList.contains("collapsed");
    card.classList.toggle("collapsed", fold);
    tog.setAttribute("aria-expanded", String(!fold));
    fold ? collapsed.add(name) : collapsed.delete(name);
    const a = api(); if (a) a.set_ui("collapsed", [...collapsed]);
    if (!fold) requestAnimationFrame(() => C.refreshSegs(card));
    return;
  }
  const b = e.target.closest(".seg button");
  if (b) set(b.parentElement.dataset.k, b.dataset.v);
  const p = e.target.closest("[data-preset]");
  if (p) applyPreset(p.dataset.preset);
  if (e.target.closest("#btn-save-preset")) savePreset();
  if (e.target.closest("#btn-manage-presets")) showView("presets");
});

function parseMinutes(t) {
  t = t.trim().toLowerCase().replace(/\s/g, "");
  let m = null;
  if (/^\d+:\d{1,2}$/.test(t)) { const [h, mm] = t.split(":"); m = +h * 60 + +mm; }
  else if (/^\d+(\.\d+)?h$/.test(t)) m = parseFloat(t) * 60;
  else if (/^\d+(\.\d+)?m?$/.test(t)) m = parseFloat(t);
  return m !== null && m >= 0.5 && m <= 1440 ? m : null;
}
function set(k, v, rerender = true) {
  S[k] = v;
  if (PRESET_KEYS.has(k)) { preset = "Custom"; $$("[data-preset]").forEach(c => c.classList.remove("on")); }
  const a = api();
  if (a) a.set_writer_setting(k, v);
  if (rerender) refreshSettings();
  scheduleEstimate();
  document.dispatchEvent(new CustomEvent("presetchange", { detail: preset }));
}
function refreshSettings() {
  for (const [k, r] of Object.entries(ROWS)) {
    const row = $(`[data-row="${k}"]`);
    if (!row) continue;
    row.style.display = r.show && !r.show() ? "none" : "";
    row.classList.toggle("disabled", !!(r.dep && !S[r.dep]));
    if (r.type === "toggle") $("input", row).checked = !!S[k];
    if (r.type === "slider") {
      const inp = $("input", row);
      if (document.activeElement !== inp) inp.value = S[k];
      C.sliderFill(inp);
      $(`[data-val="${k}"]`, row).textContent = r.fmt(S[k]);
    }
    if (r.type === "seg") C.setSeg($(".seg", row), S[k]);
    if (r.type === "duration") { const inp = $("input", row); if (document.activeElement !== inp) inp.value = fmtMinutes(S[k]); }
  }
  C.bump($("#st-wpm"), S.speed_mode === "wpm" ? Math.round(S.wpm) : "auto");
  C.bump($("#st-typo"), `${(S.typo_rate * 100).toFixed(1)}%`);
  $("#gauge-target-num").textContent = S.speed_mode === "wpm" ? Math.round(S.wpm) : "auto";
  setTargetMarker(S.speed_mode === "wpm" ? S.wpm : null);
}
const fmtMinutes = m => m >= 60 ? `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, "0")}` : `${+(+m).toFixed(1)}`;

async function applyPreset(name) {
  preset = name;
  const a = api();
  if (a) Object.assign(S, await a.apply_preset(name));
  else Object.assign(S, DEMO_PRESETS[name] || {});
  renderSettings(); scheduleEstimate();
  document.dispatchEvent(new CustomEvent("presetchange", { detail: preset }));
}
async function savePreset() {
  const name = await C.ask("Save preset", "Name for these typing settings");
  if (!name) return;
  const a = api();
  if (!a) { presetList.push({ name }); preset = name; renderSettings(); return; }
  const res = await a.save_preset(name);
  if (!res.ok) return toast(res.error, "warn");
  setPresets(res.presets, name);
  toast(`Saved “${name}”`);
}
function setPresets(list, active) {
  presetList = list;
  if (active !== undefined) preset = active;
  renderSettings();
  document.dispatchEvent(new CustomEvent("presetchange", { detail: preset }));
}
const DEMO_PRESETS = {
  "Natural": { wpm: 55, speed_variance: 0.30, typo_rate: 0.03, revise_enabled: true, revision_amount: "Some", thinking_freq: 0.04, punct_pause_scale: 1 },
  "Fast & Clean": { wpm: 95, speed_variance: 0.15, typo_rate: 0.005, revise_enabled: false, revision_amount: "Few", thinking_freq: 0.01, punct_pause_scale: 0.5 },
  "Casual": { wpm: 70, speed_variance: 0.35, typo_rate: 0.05, revise_enabled: true, revision_amount: "Few", thinking_freq: 0.03, punct_pause_scale: 0.8 },
  "Slow & Careful": { wpm: 32, speed_variance: 0.25, typo_rate: 0.015, revise_enabled: true, revision_amount: "Many", thinking_freq: 0.08, punct_pause_scale: 1.6 },
};

// ------------------------------------------------------------------ gauge
const G = { cx: 126, cy: 126, r: 100, max: 150, sweep: 270, start: 135 };
const CIRC = 2 * Math.PI * G.r;
const polar = (deg, r) => { const a = deg * Math.PI / 180; return [G.cx + r * Math.cos(a), G.cy + r * Math.sin(a)]; };
function buildGauge() {
  for (const el of [$("#gauge-track"), $("#gauge-value")]) el.setAttribute("transform", `rotate(${G.start} ${G.cx} ${G.cy})`);
  $("#gauge-track").setAttribute("stroke-dasharray", `${CIRC * G.sweep / 360} ${CIRC}`);
  let t = "";
  for (let v = 0; v <= G.max; v += 5) {
    const deg = G.start + G.sweep * v / G.max, major = v % 30 === 0;
    const [x1, y1] = polar(deg, G.r + 13), [x2, y2] = polar(deg, G.r + (major ? 21 : 17));
    t += `<line class="tick ${major ? "major" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-width="${major ? 2 : 1.2}" stroke-linecap="round"/>`;
  }
  for (let v = 0; v <= G.max; v += 30) {
    const [x, y] = polar(G.start + G.sweep * v / G.max, G.r - 22);
    t += `<text class="tick-label" x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central">${v}</text>`;
  }
  $("#gauge-ticks").innerHTML = t;
  setGauge(0);
}
let gaugeShown = -1;
function setGauge(wpm) {
  C.glide("gauge", wpm, w => {
    const f = Math.max(0, Math.min(1, w / G.max));
    const v = $("#gauge-value");
    v.setAttribute("stroke-dasharray", `${Math.max(0.001, CIRC * G.sweep / 360 * f)} ${CIRC}`);
    v.style.opacity = f > 0.002 ? 1 : 0;
    const n = Math.round(w);
    if (n !== gaugeShown) { $("#gauge-num").textContent = n; gaugeShown = n; }
  }, 260);
}
function setTargetMarker(wpm) {
  const g = $("#gauge-target");
  if (wpm == null) { g.style.opacity = 0; return; }
  g.style.opacity = 1;
  g.setAttribute("transform", `rotate(${G.start + G.sweep * Math.min(wpm, G.max) / G.max + 90} ${G.cx} ${G.cy})`);
}

const FUEL = 32;
$("#fuel").innerHTML = Array.from({ length: FUEL }, (_, i) => `<i style="transition-delay:${i * 8}ms"></i>`).join("");
let fuelLit = -1;
function setFuel(p) {
  const lit = Math.round(p * FUEL);
  if (lit === fuelLit) return;
  fuelLit = lit;
  $$("#fuel i").forEach((el, i) => el.classList.toggle("on", i < lit));
}

// ------------------------------------------------------------------ text
const ta = $("#writer-text");
ta.addEventListener("input", () => { updateCounts(); scheduleEstimate(); });
$("#btn-clear").addEventListener("click", () => { ta.value = ""; updateCounts(); scheduleEstimate(); });
$("#btn-paste").addEventListener("click", async () => {
  const a = api();
  try { ta.value = a ? await a.clipboard_text() : await navigator.clipboard.readText(); } catch (e) {}
  updateCounts(); scheduleEstimate();
});
function updateCounts() {
  const t = ta.value;
  $("#writer-counts").textContent = `${words(t).toLocaleString()} words · ${t.length.toLocaleString()} characters`;
  C.bump($("#st-words"), words(t).toLocaleString());
}

// ------------------------------------------------------------------ estimate
let estTimer = null, estimate = null, estSeq = 0;
function scheduleEstimate() { clearTimeout(estTimer); estTimer = setTimeout(runEstimate, 250); }
async function runEstimate() {
  const t = ta.value, seq = ++estSeq;
  if (!t.trim()) { showEstimate(null); return; }
  const a = api();
  let e;
  if (a) e = await a.estimate(t);
  else {
    const base = t.length / (S.wpm * 5) * 60;
    const total = S.speed_mode === "duration" ? S.target_minutes * 60 : base * (1.35 + S.punct_pause_scale * 0.15 + S.thinking_freq * 3);
    e = { total, effective_wpm: (t.length / 5) / (total / 60), mistakes: Math.round(t.length * S.typo_rate * 0.8), revision_passes: S.revise_enabled ? 3 : 0, chars: t.length };
  }
  if (seq === estSeq) showEstimate(e);
}
function showEstimate(e) {
  estimate = e;
  if (LIVE.has(run.state)) return;
  if (!e) {
    $("#st-time").textContent = "–"; $("#eta-time").textContent = "–:––"; $("#eta-time").classList.add("empty"); $("#eta-of").textContent = "";
    $("#speed-note").innerHTML = "Add text to see how long it will take.";
    $("#m-mistakes").textContent = "–"; $("#m-revisions").textContent = "–"; $("#m-chars").textContent = "0 / 0";
    return;
  }
  C.bump($("#st-time"), fmtDur(e.total));
  C.bump($("#eta-time"), fmtClock(e.total)); $("#eta-time").classList.remove("empty");
  $("#eta-of").textContent = `≈ ${Math.round(e.effective_wpm)} wpm overall`;
  C.bump($("#m-mistakes"), e.mistakes);
  C.bump($("#m-revisions"), e.revision_passes);
  $("#m-chars").textContent = `0 / ${e.chars.toLocaleString()}`;
  $("#speed-note").innerHTML = S.speed_mode === "duration"
    ? `Typing at <b>≈${Math.round(e.effective_wpm)} wpm</b> overall to finish in <b>${fmtDur(e.total)}</b>.`
    : `Estimated <b>${fmtDur(e.total)}</b>, including pauses, mistakes and revisions.`;
}

// ------------------------------------------------------------------ run state (pushed from Python)
const LIVE = new Set(["countdown", "typing", "paused", "break", "resuming"]);
const run = { state: "idle" };
const STATE_TEXT = { idle: "Ready", countdown: "Starting", typing: "Typing", paused: "Paused", break: "On a break",
                     resuming: "Resuming", done: "Finished", stopped: "Stopped", error: "Error" };
let wasLive = false;
window.cadence.status = function (st) {
  run.state = st.state;
  const live = LIVE.has(st.state);
  const chip = $("#status-chip");
  chip.classList.toggle("live", st.state === "typing");
  chip.classList.toggle("warn", st.state === "paused" || st.state === "error");
  let label = STATE_TEXT[st.state] || st.state;
  if ((st.state === "countdown" || st.state === "resuming") && st.countdown > 0) label += ` · ${Math.ceil(st.countdown)}`;
  $("#status-text").textContent = label;
  $("#gauge-hint").textContent = st.state === "typing" ? "live" : (live ? STATE_TEXT[st.state].toLowerCase() : "idle");
  setGauge(st.state === "typing" ? st.wpm : 0);
  $("#gauge-avg").textContent = st.avg_wpm ? Math.round(st.avg_wpm) : "–";
  setFuel(st.progress);
  C.bump($("#st-progress"), `${Math.round(st.progress * 100)}%`);
  if (live || st.state === "done") {
    $("#eta-time").textContent = fmtClock(st.remaining); $("#eta-time").classList.remove("empty");
    $("#eta-of").textContent = st.state === "done" ? "done" : `left of ${fmtDur(st.total)}`;
    $("#st-time").textContent = fmtDur(st.remaining);
    const fin = new Date(Date.now() + st.remaining * 1000);
    $("#eta-clock").textContent = st.state === "typing" ? `done ≈ ${fin.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "";
  } else $("#eta-clock").textContent = "";
  $("#m-chars").textContent = `${st.typed_chars.toLocaleString()} / ${st.total_chars.toLocaleString()}`;
  const msg = $("#run-msg");
  msg.textContent = st.message && st.state !== "done" ? st.message : (st.state === "typing" && st.target_title ? `Typing into “${st.target_title}”` : "");
  msg.classList.toggle("warn", st.state === "paused" || st.state === "error");
  $("#start-label").textContent = st.state === "paused" ? "Resume" : "Start";
  $("#btn-start").disabled = live && st.state !== "paused";
  $("#btn-pause").disabled = !["typing", "break", "countdown"].includes(st.state);
  $("#btn-stop").disabled = !live;
  ta.readOnly = live;
  if (!live && wasLive) {
    if (st.state === "error") toast(st.message, "warn");
    if (document.body.dataset.inMini === "1") restoreFromMini();
    scheduleEstimate();
  }
  if (mini) mini.update(st);
  wasLive = live;
};

$("#btn-start").addEventListener("click", start);
$("#btn-pause").addEventListener("click", () => { const a = api(); a ? a.pause() : demo.pause(); });
$("#btn-stop").addEventListener("click", () => { const a = api(); a ? a.stop() : demo.stop(); });
$("#btn-mini").addEventListener("click", enterMini);

async function start() {
  const a = api();
  if (!a) return demo.start();
  if (run.state === "paused") return a.resume();
  const res = await a.start_or_resume(ta.value);
  if (!res.ok) return toast(res.error, "warn");
  if (res.auto_mini) enterMini();
}

// ------------------------------------------------------------------ mini mode
let mini = null;
const miniHost = $("#mini-host");
const miniHandlers = {
  toggle: () => { const a = api(); if (run.state === "paused") { a ? a.resume() : demo.start(); } else { a ? a.pause() : demo.pause(); } },
  stop: () => { const a = api(); a ? a.stop() : demo.stop(); },
  expand: () => restoreFromMini(),
  quit: () => quitApp(),
  collapse: () => {},
};
function enterMini() {
  if (document.body.dataset.inMini === "1") return;
  document.body.dataset.inMini = "1";
  $(".app").classList.add("to-mini");                       // shrink toward the top-right corner
  const a = api();
  if (a) { setTimeout(() => a.enter_mini(), 300); return; } // Python swaps to the mini window
  if (!mini) { mini = MiniPanel.mount(miniHost, miniHandlers); MiniPanel.makeDraggable(miniHost); }
  setTimeout(() => { miniHost.classList.remove("hidden"); miniHost.classList.add("pop"); }, 220);
}
function restoreFromMini() {
  document.body.dataset.inMini = "";
  const a = api();
  if (a) { a.leave_mini(); return; }                        // Python shows us and calls cadence.restore()
  miniHost.classList.add("hidden"); miniHost.classList.remove("pop");
  requestAnimationFrame(() => $(".app").classList.remove("to-mini"));
}
window.cadence.enterMini = enterMini;
window.cadence.restore = () => {
  document.body.dataset.inMini = "";
  requestAnimationFrame(() => requestAnimationFrame(() => $(".app").classList.remove("to-mini")));
};
function quitApp() {
  const a = api();
  if (a) a.quit();
  else { demo.stop(); restoreFromMini(); }
}
$("#btn-quit").addEventListener("click", () => {
  if (!LIVE.has(run.state)) return quitApp();
  C.modal({ title: "Quit Cadence?", body: `<p class="muted">Typing is still running. Quitting stops it right away.</p>`,
            actions: [{ label: "Keep typing" }, { label: "Stop and quit", primary: true, onClick: quitApp }] });
});

// ------------------------------------------------------------------ demo (plain browser only)
const demo = {
  timer: null, st: null,
  start() {
    if (this.st && this.st.state === "paused") { this.st.state = "typing"; this.st.message = ""; return; }
    if (!ta.value.trim()) { ta.value = SAMPLE; updateCounts(); }
    const total = estimate ? estimate.total : 120;
    this.st = { state: "countdown", countdown: 3, progress: 0, remaining: total, total, wpm: 0, avg_wpm: 0,
                typed_chars: 0, total_chars: ta.value.length, message: "Click into the target window", target_title: "Untitled – Notepad" };
    if (S.auto_mini) enterMini();
    clearInterval(this.timer);
    let last = performance.now();
    this.timer = setInterval(() => {
      const now = performance.now(), dt = (now - last) / 1000; last = now;
      const s = this.st;
      if (s.state === "countdown") { s.countdown -= dt; if (s.countdown <= 0) { s.state = "typing"; s.message = ""; } }
      else if (s.state === "typing") {
        s.remaining = Math.max(0, s.remaining - dt * 12);
        s.progress = 1 - s.remaining / s.total;
        s.typed_chars = Math.round(s.total_chars * s.progress);
        const target = S.speed_mode === "wpm" ? S.wpm : (estimate ? estimate.effective_wpm * 1.4 : 60);
        s.wpm += ((target * (0.75 + Math.random() * 0.5)) - s.wpm) * 0.25;
        s.avg_wpm = s.avg_wpm ? s.avg_wpm * 0.97 + s.wpm * 0.03 : s.wpm;
        if (s.remaining <= 0) { s.state = "done"; s.message = "Finished"; s.progress = 1; clearInterval(this.timer); }
      }
      window.cadence.status(s);
    }, 100);
  },
  pause() { if (this.st) { this.st.state = "paused"; this.st.message = "Paused. Press F8 to resume."; window.cadence.status(this.st); } },
  stop() { clearInterval(this.timer); if (this.st) { this.st.state = "stopped"; this.st.message = "Stopped"; this.st.wpm = 0; window.cadence.status(this.st); } },
};
const SAMPLE = "The quick brown fox jumps over the lazy dog. Typing like a person means uneven rhythm, small pauses after commas, longer ones after sentences, and the occasional mistake that gets fixed a moment later.\n\nCadence plans every keystroke before it starts, so the time estimate is exact. ";

// ------------------------------------------------------------------ public
window.Writer = {
  setText(t) { ta.value = t; updateCounts(); scheduleEstimate(); },
  init(state) {
    Object.assign(S, state.writer); preset = state.preset; presetList = state.presets;
    if (state.ui && Array.isArray(state.ui.collapsed)) collapsed = new Set(state.ui.collapsed);
    renderSettings(); scheduleEstimate();
  },
  get preset() { return preset; },
  get settings() { return S; },
  setPresets, applyPreset, savePreset,
};

buildGauge();
renderSettings();
updateCounts();
requestAnimationFrame(() => { moveNavIndicator(false); C.enterView($(".view.active")); C.refreshSegs(); });
window.cadence.status({ state: "idle", progress: 0, remaining: 0, total: 0, wpm: 0, avg_wpm: 0, typed_chars: 0, total_chars: 0, message: "" });
if (!api() && /running|mini|collapsed|filled/.test(location.hash)) {
  ta.value = SAMPLE.repeat(3); updateCounts(); scheduleEstimate();
  if (/running|mini|collapsed/.test(location.hash)) {
    if (!/mini|collapsed/.test(location.hash)) S.auto_mini = false;
    setTimeout(() => demo.start(), 400);
    if (/collapsed/.test(location.hash)) setTimeout(() => $('[data-act="collapse"]', miniHost).click(), 2400);
  }
}
})();

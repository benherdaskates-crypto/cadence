/* Shared helpers for every page (window.C). */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = () => (window.pywebview && window.pywebview.api) || null;
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function icon(name, cls = "") {
  return `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${(window.ICONS || {})[name] || ""}</svg>`;
}
function hydrateIcons(root = document) {
  $$("[data-icon]", root).forEach(el => { el.outerHTML = icon(el.dataset.icon, el.dataset.cls || ""); });
}
const fmtDur = s => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(r).padStart(2, "0")}s`;
  return `${r}s`;
};
const fmtClock = s => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
};
const words = t => (t.trim() ? t.trim().split(/\s+/).length : 0);

// ---- toast
let toastTimer = null;
function toast(msg, kind = "") {
  let el = $("#toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
  el.className = `toast show ${kind}`;
  el.innerHTML = `${icon(kind === "warn" ? "triangle-alert" : "check", "sm")}<span>${esc(msg)}</span>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3400);
}

// ---- custom select (pill button + popover list)
function select(host, { options, value, onChange, placeholder = "Select", disabled = false }) {
  host.classList.add("select");
  const state = { options, value, disabled };
  function render() {
    const cur = state.options.find(o => o.value === state.value);
    host.innerHTML = `<button class="pill select-btn" type="button" aria-haspopup="listbox" ${state.disabled ? "disabled" : ""}>
        <span class="select-label">${esc(cur ? cur.label : placeholder)}</span>${icon("chevron-down", "sm")}</button>
      <div class="select-pop" role="listbox" hidden>${state.options.map(o =>
        `<button type="button" role="option" class="select-opt ${o.value === state.value ? "on" : ""}" data-v="${esc(o.value)}">
           <span>${esc(o.label)}</span>${o.hint ? `<span class="muted">${esc(o.hint)}</span>` : ""}</button>`).join("") ||
        `<div class="select-empty muted">Nothing here yet</div>`}</div>`;
  }
  render();
  host.addEventListener("click", e => {
    const pop = $(".select-pop", host);
    if (e.target.closest(".select-btn")) { pop.hidden = !pop.hidden; host.classList.toggle("open", !pop.hidden); return; }
    const opt = e.target.closest(".select-opt");
    if (opt) { state.value = opt.dataset.v; pop.hidden = true; host.classList.remove("open"); render(); onChange && onChange(state.value); }
  });
  document.addEventListener("click", e => { if (!host.contains(e.target)) { const p = $(".select-pop", host); if (p) p.hidden = true; host.classList.remove("open"); } });
  return {
    set(v) { state.value = v; render(); },
    setOptions(opts, v) { state.options = opts; if (v !== undefined) state.value = v; render(); },
    setDisabled(d) { state.disabled = d; render(); },
    get value() { return state.value; },
  };
}

// ---- modal
function modal({ title, body, actions = [] }) {
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  wrap.innerHTML = `<div class="modal card" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="card-title"><h3>${esc(title)}</h3><button class="mini-btn" data-close aria-label="Close">${icon("x", "sm")}</button></div>
      <div class="modal-body">${body}</div>
      <div class="modal-actions">${actions.map((a, i) => `<button class="pill ${a.primary ? "primary" : ""}" data-i="${i}">${a.label}</button>`).join("")}</div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.classList.add("closing"); setTimeout(() => wrap.remove(), 160); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  wrap.addEventListener("click", e => {
    if (e.target === wrap || e.target.closest("[data-close]")) return close();
    const b = e.target.closest("[data-i]");
    if (b) { const a = actions[+b.dataset.i]; if (!a.onClick || a.onClick(wrap) !== false) close(); }
  });
  const first = $("input, textarea, .pill.primary", wrap);
  setTimeout(() => first && first.focus(), 30);
  return { el: wrap, close };
}

function ask(title, label, value = "") {
  return new Promise(resolve => {
    modal({
      title,
      body: `<label class="row-label" for="ask-input">${esc(label)}</label><input id="ask-input" class="input wide" value="${esc(value)}" autocomplete="off">`,
      actions: [{ label: "Cancel", onClick: () => resolve(null) },
                { label: "Save", primary: true, onClick: w => resolve($("#ask-input", w).value.trim()) }],
    });
    setTimeout(() => {
      const inp = $("#ask-input");
      inp && inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $(".modal .pill.primary").click(); } });
    }, 40);
  });
}

function segHTML(key, opts, attrs = "") {
  return `<div class="seg" role="radiogroup" data-k="${key}" ${attrs}>${opts.map(o => {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    return `<button type="button" role="radio" data-v="${esc(v)}">${esc(l)}</button>`;
  }).join("")}</div>`;
}
// Segmented control with a sliding thumb behind the selected option.
function setSeg(el, v) {
  if (!el) return;
  $$("button", el).forEach(b => { const on = b.dataset.v === String(v); b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  placeThumb(el);
}
function placeThumb(el) {
  let t = el.querySelector(":scope > .seg-thumb");
  const first = !t;
  if (!t) {
    t = document.createElement("span"); t.className = "seg-thumb"; el.prepend(t);
    new ResizeObserver(() => placeThumb(el)).observe(el);
  }
  const b = el.querySelector("button.on");
  if (!b || !el.offsetWidth) { t.style.opacity = 0; el.dataset.placed = ""; return; }
  const jump = first || !el.dataset.placed;         // first placement: no sweep from the left edge
  if (jump) el.classList.add("no-anim");
  t.style.opacity = 1;
  t.style.width = `${b.offsetWidth}px`;
  t.style.transform = `translateX(${b.offsetLeft}px)`;
  el.dataset.placed = "1";
  if (jump) requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("no-anim")));
}
function refreshSegs(root = document) { $$(".seg", root).forEach(placeThumb); }

// Set text and give it a small rise-in when the value actually changes.
function bump(el, text) {
  if (!el) return;
  text = String(text);
  if (el.textContent === text) return;
  el.textContent = text;
  el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
}

// Stagger the entrance of a view's stats and cards.
function enterView(view) {
  $$(".stat", view).forEach((s, i) => s.style.setProperty("--i", i));
  $$(".card, .action-bar", view).forEach((c, i) => c.style.setProperty("--i", Math.min(i, 8)));
  view.classList.remove("enter"); void view.offsetWidth; view.classList.add("enter");
  clearTimeout(view._enterT);
  view._enterT = setTimeout(() => view.classList.remove("enter"), 1100);   // later re-renders shouldn't replay it
}

// Ease a number toward a target (gauge readouts).
function tweenNumber(el, to, ms = 380) {
  const from = +el.dataset.v || 0;
  if (Math.round(from) === Math.round(to)) { el.dataset.v = to; return; }
  const t0 = performance.now();
  cancelAnimationFrame(el._raf);
  const step = now => {
    const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    const v = from + (to - from) * e;
    el.textContent = Math.round(v); el.dataset.v = v;
    if (k < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}
function sliderFill(inp) { inp.style.setProperty("--p", `${((inp.value - inp.min) / (inp.max - inp.min)) * 100}%`); }

// Appearance: size (CSS zoom), animations, stat pills.
function applyUI(ui) {
  if (!ui) return;
  const root = document.documentElement;
  if (ui.scale) { root.style.zoom = ui.scale; root.style.setProperty("--zoom", ui.scale); }
  if (ui.motion !== undefined) root.classList.toggle("no-motion", !ui.motion);
  if (ui.stats !== undefined) root.classList.toggle("hide-stats", !ui.stats);
  requestAnimationFrame(() => refreshSegs());
}
function revealApp() {
  const root = document.documentElement;
  if (!root.classList.contains("booting")) return;
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("booting")));
}

// ---- glide: ease a value toward its target every frame (critically damped, no overshoot).
// Live readouts arrive ~10x a second; gliding between them looks continuous instead of steppy.
const glides = new Map();
function glide(key, target, apply, tau = 160) {
  let g = glides.get(key);
  if (!g) { g = { v: target, t: target, apply, last: 0, raf: 0 }; glides.set(key, g); apply(target); return; }
  g.t = target; g.apply = apply;
  if (document.documentElement.classList.contains("no-motion")) { g.v = target; apply(target); return; }
  if (g.raf) return;
  g.last = performance.now();
  const step = now => {
    const dt = Math.min(64, now - g.last); g.last = now;
    g.v += (g.t - g.v) * (1 - Math.exp(-dt / tau));
    if (Math.abs(g.t - g.v) < 0.002 * Math.max(1, Math.abs(g.t))) g.v = g.t;
    g.apply(g.v);
    g.raf = g.v === g.t ? 0 : requestAnimationFrame(step);
  };
  g.raf = requestAnimationFrame(step);
}

// ---- cursor spotlight: a soft light follows the pointer over cards and buttons.
const SPOT = ".card, .pill, .chip:not(.static), .stat, .nav-btn, .hist-item, .style-item, .mini-btn";
let spotEl = null, spotEv = null, spotRaf = 0;
document.addEventListener("pointermove", e => {
  const el = e.target.closest && e.target.closest(SPOT);
  if (!el) return;
  if (!el.classList.contains("spot")) el.classList.add("spot");
  spotEl = el; spotEv = e;
  if (spotRaf) return;
  spotRaf = requestAnimationFrame(() => {
    spotRaf = 0;
    const r = spotEl.getBoundingClientRect();
    const z = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--zoom")) || 1;
    spotEl.style.setProperty("--mx", `${(spotEv.clientX - r.left) / z}px`);
    spotEl.style.setProperty("--my", `${(spotEv.clientY - r.top) / z}px`);
  });
}, { passive: true });

window.C = { $, $$, api, esc, icon, hydrateIcons, applyUI, revealApp, glide, fmtDur, fmtClock, words, toast, select, modal, ask, segHTML, setSeg,
              sliderFill, refreshSegs, bump, enterView, tweenNumber };
window.cadence = window.cadence || {};
window.cadence.toast = msg => toast(msg, "warn");
window.cadence.uiScale = s => applyUI({ scale: s });
window.cadence.uiMotion = m => applyUI({ motion: m });
})();

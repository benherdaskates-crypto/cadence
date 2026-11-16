/* Presets and Settings pages, plus app boot. */
(() => {
"use strict";
const { $, api, icon, esc, toast } = C;

// ------------------------------------------------------------------ presets
let presets = [];
const pct = v => `${(v * 100).toFixed(1)}%`;
function renderPresets() {
  const active = Writer.preset;
  $("#preset-grid").innerHTML = presets.map(p => {
    const v = p.values || {};
    return `<div class="card preset-card ${p.name === active ? "active" : ""}">
      <div class="card-title"><h3>${esc(p.name)}</h3><span class="tag">${p.builtin ? "Built-in" : "Custom"}</span></div>
      <div class="preset-facts">
        <div><span class="k">Speed</span><span class="v num">${Math.round(v.wpm || 0)} wpm</span></div>
        <div><span class="k">Typos</span><span class="v num">${pct(v.typo_rate || 0)}</span></div>
        <div><span class="k">Revisions</span><span class="v">${v.revise_enabled ? esc(v.revision_amount || "") : "Off"}</span></div>
        <div><span class="k">Pauses</span><span class="v num">${(v.punct_pause_scale ?? 1).toFixed(1)}×</span></div>
      </div>
      <div class="preset-actions">
        <button class="pill ${p.name === active ? "in-use" : ""}" data-apply="${esc(p.name)}">${p.name === active ? `${icon("check", "sm")}In use` : "Apply"}</button>
        ${p.builtin ? "" : `<button class="pill icon" data-delete="${esc(p.name)}" aria-label="Delete ${esc(p.name)}" title="Delete">${icon("trash-2", "sm")}</button>`}
      </div></div>`;
  }).join("") + `<button class="card preset-card add" id="p-add">${icon("plus", "lg")}<span>Save current Writer settings as a preset</span></button>`;
}
$("#preset-grid").addEventListener("click", async e => {
  const ap = e.target.closest("[data-apply]");
  if (ap) { await Writer.applyPreset(ap.dataset.apply); renderPresets(); toast(`Applied “${ap.dataset.apply}”`); }
  const del = e.target.closest("[data-delete]");
  if (del) {
    const name = del.dataset.delete;
    C.modal({ title: "Delete preset?", body: `<p class="muted">“${esc(name)}” will be removed. This can't be undone.</p>`,
      actions: [{ label: "Cancel" }, { label: "Delete", primary: true, onClick: async () => {
        const a = api(); if (!a) return;
        const res = await a.delete_preset(name);
        if (!res.ok) return toast(res.error, "warn");
        presets = res.presets; Writer.setPresets(presets, Writer.preset === name ? "Custom" : undefined); renderPresets();
      } }] });
  }
  if (e.target.closest("#p-add")) save();
});
$("#p-save").addEventListener("click", save);
async function save() { await Writer.savePreset(); }
document.addEventListener("presetchange", () => { const a = api(); if (a) a.list_presets().then(l => { presets = l; renderPresets(); }); else renderPresets(); });

// ------------------------------------------------------------------ settings
let ollama = null, cfgDir = "", version = "", ui = { size: "Compact", motion: true, stats: true, start_page: "writer" }, sizes = ["Compact", "Comfortable", "Large", "Extra large"];
function renderSettings() {
  const ready = !!ollama && ollama.running && ollama.models.length;
  const checking = !ollama;
  const ol = ollama || { running: false, models: [], version: "" };
  $("#settings-grid").innerHTML = `
  <div class="card set-card">
    <div class="card-title"><h3>Appearance</h3><span class="ic">${icon("sliders-horizontal", "sm")}</span></div>
    <div class="row"><div class="row-label">Size</div>
      <div class="row-desc">Compact fits more on screen; pick a bigger size if text feels small.</div>
      ${C.segHTML("ui-size", sizes)}</div>
    <div class="row"><div class="row-head"><div><div class="row-label">Animations</div><div class="row-desc">Turn off for the simplest, snappiest feel.</div></div>
      <label class="switch"><input type="checkbox" id="ui-motion" ${ui.motion ? "checked" : ""} aria-label="Animations"><span class="track"></span><span class="knob"></span></label></div></div>
    <div class="row"><div class="row-head"><div><div class="row-label">Stat pills</div><div class="row-desc">The row of numbers at the top of the Writer and Humanizer.</div></div>
      <label class="switch"><input type="checkbox" id="ui-stats" ${ui.stats ? "checked" : ""} aria-label="Stat pills"><span class="track"></span><span class="knob"></span></label></div></div>
    <div class="row"><div class="row-label">Open on</div>
      ${C.segHTML("ui-start", [["writer", "Writer"], ["humanizer", "Humanizer"], ["last", "Last page used"]])}</div>
  </div>`;
  $("#settings-grid").innerHTML += `
  <div class="card set-card">
    <div class="card-title"><h3>Local AI (Ollama)</h3><span class="ic">${icon("brain-circuit", "sm")}</span></div>
    <div class="row"><div class="row-head"><div><div class="row-label">Status</div>
      <div class="row-desc">${checking ? "Checking…" : ready ? `Running${ol.version ? ` · version ${esc(ol.version)}` : ""} at localhost:11434` : ol.running ? "Running, but no models are installed yet." : "Not found. Install it to use Local AI; the rule-based engine works without it."}</div></div>
      <span class="status-chip ${ready ? "ok" : checking ? "" : "warn"}"><i class="dot"></i>${checking ? "Checking" : ready ? "Ready" : ol.running ? "No models" : "Not found"}</span></div></div>
    <div class="row"><div class="row-label">Installed models</div>
      <div class="presets" style="margin-top:8px">${ol.models.length ? ol.models.map(m => `<span class="chip static">${esc(m)}</span>`).join("") : `<span class="muted">${checking ? "Checking…" : "None yet"}</span>`}</div></div>
    <div class="row"><div class="presets"><button class="chip" id="s-check">${icon("refresh-cw", "sm")}Check again</button>
      <button class="chip" id="s-help">${icon("circle-help", "sm")}How to install</button></div></div>
  </div>
  <div class="card set-card">
    <div class="card-title"><h3>Hotkeys</h3><span class="ic">${icon("keyboard", "sm")}</span></div>
    ${[["F8", "Start typing, or resume after a pause"], ["F9", "Pause"], ["F10", "Emergency stop, works instantly"]].map(([k, d]) =>
      `<div class="row"><div class="row-head"><div class="row-label">${d}</div><kbd>${k}</kbd></div></div>`).join("")}
    <div class="note">These work from any window. While Cadence runs, F8–F10 are reserved for it so they don't trigger things in other apps (in Word, F8 would turn on Extend Selection).</div>
  </div>
  <div class="card set-card">
    <div class="card-title"><h3>In-app shortcuts</h3><span class="ic">${icon("zap", "sm")}</span></div>
    ${[["Ctrl+1 … 5", "Humanizer, Writer, My style, Presets, Settings"], ["Ctrl+Enter", "Humanize"],
       ["Ctrl+O", "Open a file into the current page"], ["Ctrl+S", "Save the humanized text"],
       ["Ctrl+H", "Humanizer history"], ["Ctrl+P", "Typing preview (Writer)"]].map(([k, d]) =>
      `<div class="row"><div class="row-head"><div class="row-label">${d}</div><kbd>${k}</kbd></div></div>`).join("")}
    <div class="note">You can also drag a .txt, .md or .docx file onto the Writer or Humanizer text box.</div>
  </div>
  <div class="card set-card">
    <div class="card-title"><h3>Files</h3><span class="ic">${icon("save", "sm")}</span></div>
    <div class="row"><div class="row-label">Settings, presets, styles, history and auto-saved drafts</div><div class="row-desc path">${esc(cfgDir || "%APPDATA%\\CadenceFree")}</div></div>
    <div class="row"><button class="chip" id="s-open">${icon("external-link", "sm")}Open folder</button></div>
  </div>
  <div class="card set-card">
    <div class="card-title"><h3>About</h3><span class="ic">${icon("info", "sm")}</span></div>
    <div class="row"><div class="row-label">Cadence ${esc(version)}</div><div class="row-desc">Everything runs on this PC. No account, no API key, no data sent anywhere.</div></div>
    <div class="row"><div class="row-desc">Inter typeface (SIL Open Font License) · Lucide icons (ISC License)</div></div>
  </div>`;
}
$("#settings-grid").addEventListener("click", async e => {
  const a = api();
  const seg = e.target.closest(".seg button");
  if (seg) {
    const k = seg.parentElement.dataset.k;
    if (k === "ui-size") { ui.size = seg.dataset.v; C.setSeg(seg.parentElement, ui.size); if (a) { const r = await a.set_ui("size", ui.size); C.applyUI({ scale: r.scale }); } }
    if (k === "ui-start") { ui.start_page = seg.dataset.v; C.setSeg(seg.parentElement, ui.start_page); if (a) a.set_ui("start_page", ui.start_page); }
    return;
  }
  if (e.target.closest("#s-check") && a) { ollama = await a.ollama_status(); renderSettings(); Humanizer.setStatus(ollama); toast(ollama.running && ollama.models.length ? "Local AI is ready" : "Local AI not found", ollama.running && ollama.models.length ? "" : "warn"); }
  if (e.target.closest("#s-help")) { App.show("humanizer"); document.querySelector("#h-install").click(); }
  if (e.target.closest("#s-open") && a) a.open_config_dir();
});
document.addEventListener("ollamastatus", e => { ollama = e.detail; renderSettings(); });
$("#settings-grid").addEventListener("change", e => {
  const a = api();
  if (e.target.id === "ui-motion") { ui.motion = e.target.checked; C.applyUI({ motion: ui.motion }); if (a) a.set_ui("motion", ui.motion); }
  if (e.target.id === "ui-stats") { ui.stats = e.target.checked; C.applyUI({ stats: ui.stats }); if (a) a.set_ui("stats", ui.stats); }
});
const syncAppearance = () => { C.setSeg($('[data-k="ui-size"]'), ui.size); C.setSeg($('[data-k="ui-start"]'), ui.start_page); };
document.addEventListener("viewshown", e => { if (e.detail === "settings") requestAnimationFrame(syncAppearance); });
// Local AI status arrives from Python after startup (the check runs in the background).
window.cadence.ollama = st => {
  ollama = st; renderSettings(); syncAppearance(); Humanizer.setStatus(st);
};

// ------------------------------------------------------------------ boot
renderSettings();
presets = [{ name: "Natural", builtin: true, values: { wpm: 55, typo_rate: 0.03, revise_enabled: true, revision_amount: "Some", punct_pause_scale: 1 } },
           { name: "Fast & Clean", builtin: true, values: { wpm: 95, typo_rate: 0.005, revise_enabled: false, punct_pause_scale: 0.5 } },
           { name: "Casual", builtin: true, values: { wpm: 70, typo_rate: 0.05, revise_enabled: true, revision_amount: "Few", punct_pause_scale: 0.8 } },
           { name: "Slow & Careful", builtin: true, values: { wpm: 32, typo_rate: 0.015, revise_enabled: true, revision_amount: "Many", punct_pause_scale: 1.6 } }];
renderPresets();

// Plain browser (design preview): show the page right away.
if (!(window.pywebview && window.pywebview.api)) setTimeout(() => { if (!window.pywebview) C.revealApp(); }, 400);
setTimeout(C.revealApp, 2500);   // never stay hidden if something goes wrong

window.addEventListener("pywebviewready", async () => {
  const state = await api().init_state();
  C.applyUI(state.ui);
  ui = state.ui; sizes = state.sizes || sizes;
  cfgDir = state.config_dir; version = state.version; ollama = state.ollama; presets = state.presets;
  Writer.init(state);
  Humanizer.init(state);
  Styles.init(state);
  Extras.restoreDrafts(state.drafts);
  Distribution.init(state);
  const start = ui.start_page === "last" ? ui.last_page : ui.start_page;
  if (start && start !== "writer") App.show(start, false);
  syncAppearance();
  C.revealApp();
  requestAnimationFrame(() => C.enterView($(".view.active")));
  renderPresets(); renderSettings();
  requestAnimationFrame(() => C.refreshSegs());
});
})();
// Browser review hook: index.html#view=humanizer etc.
{ const m = location.hash.match(/view=(\w+)/); if (m && !(window.pywebview && window.pywebview.api)) App.show(m[1]); }
// Browser review hook: #zoom=0.86 previews a UI size without the app.
{ const z = location.hash.match(/zoom=([\d.]+)/); if (z && !(window.pywebview && window.pywebview.api)) C.applyUI({ scale: +z[1] }); }

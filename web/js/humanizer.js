/* Humanizer page: Local AI (Ollama) or rule-based engine, streaming output, diff view. */
(() => {
"use strict";
const { $, $$, api, icon, esc, words, toast } = C;

const TONES = ["Casual", "Neutral", "Formal", "Student essay"];
const LEVELS = ["Middle school", "High school", "College", "Professional"];
const STRENGTHS = ["Light touch", "Moderate", "Heavy rewrite"];

const H = { engine: "auto", ollama_model: "", tone: "Neutral", strength: 1, reading_level: "High school", style_id: "", show_changes: false };
let styles = [];
let status = { running: false, models: [], default: null, version: "" };
let busy = false, outParas = null, renderQueued = false, lastInput = "";

const inp = $("#h-in"), out = $("#h-out"), diffEl = $("#h-diff");
$("#h-tone-host").innerHTML = C.segHTML("tone", TONES);
$("#h-level-host").innerHTML = C.segHTML("reading_level", LEVELS.map(l => [l, l.replace(" school", "")]));
const model = C.select($("#h-model"), { options: [], value: "", placeholder: "No models", onChange: v => save("ollama_model", v) });
const stylePick = C.select($("#h-style"), { options: [], value: "", placeholder: "None",
  onChange: v => { save("style_id", v); render(); } });
function styleOptions() {
  return [{ value: "", label: "None (default)" }].concat(styles.map(s => ({ value: s.id, label: s.name, hint: `${s.words} words` })));
}

function save(k, v) { H[k] = v; const a = api(); if (a) a.set_humanizer_setting(k, v); }
const engine = () => H.engine === "auto" ? (ready() ? "ollama" : "rules") : H.engine;
const ready = () => !!status && status.running && status.models.length > 0;

// ------------------------------------------------------------------ rendering
function render() {
  C.setSeg($("#h-engine"), engine());
  C.setSeg($('[data-k="tone"]'), H.tone);
  C.setSeg($('[data-k="reading_level"]'), H.reading_level);
  const s = $("#h-strength");
  s.value = H.strength; C.sliderFill(s);
  $("#h-strength-val").textContent = STRENGTHS[H.strength];
  const rules = engine() === "rules";
  $("#h-level-opt").classList.toggle("disabled", rules);

  $$("[data-rules-note]").forEach(n => n.hidden = !rules);
  $("#h-model-wrap").classList.toggle("hidden-soft", rules);
  if (H.style_id && !styles.some(s => s.id === H.style_id)) H.style_id = "";
  stylePick.setOptions(styleOptions(), H.style_id);
  C.bump($("#hs-engine"), rules ? "Rule-based" : "Local AI");
  $("#h-diff-toggle").checked = H.show_changes;
  renderStatus();
}
function renderStatus() {
  const chip = $("#h-engine-chip");
  chip.classList.remove("live", "warn", "ok");
  let text;
  if (!status) {
    $("#h-engine-text").textContent = "Checking local AI…";
    $("#h-install").hidden = true;
    model.setOptions([], ""); model.setDisabled(true);
    return;
  }
  if (ready()) {
    chip.classList.add("ok");
    text = `Local AI: ready (${model.value || status.default})`;
  } else if (status.running) {
    chip.classList.add("warn"); chip.classList.remove("ok");
    text = "Local AI: no models installed";
  } else {
    chip.classList.add("warn"); chip.classList.remove("ok");
    text = "Local AI: not found";
  }
  $("#h-engine-text").textContent = text;
  $("#h-install").hidden = ready();
  const opts = status.models.map(m => ({ value: m, label: m }));
  const cur = status.models.includes(H.ollama_model) ? H.ollama_model : (status.default || "");
  model.setOptions(opts, cur);
  model.setDisabled(!ready());
}
function counts() {
  const a = inp.value, b = out.value;
  $("#h-in-count").textContent = `${words(a).toLocaleString()} words · ${a.length.toLocaleString()} characters`;
  $("#h-out-count").textContent = `${words(b).toLocaleString()} words · ${b.length.toLocaleString()} characters`;
  C.bump($("#hs-in"), words(a).toLocaleString());
  C.bump($("#hs-out"), words(b).toLocaleString());
}

// ------------------------------------------------------------------ controls
$("#h-engine").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b || busy) return;
  save("engine", b.dataset.v); render();
  if (b.dataset.v === "ollama" && !ready()) showHelp();
});
$("#view-humanizer").addEventListener("click", e => {
  const b = e.target.closest(".seg button");
  if (!b || b.closest("#h-engine")) return;
  save(b.parentElement.dataset.k, b.dataset.v); render();
});
$("#h-strength").addEventListener("input", e => { save("strength", +e.target.value); render(); });
$("#h-style-manage").addEventListener("click", () => App.show("style"));
$("#h-refresh").addEventListener("click", refreshStatus);
$("#h-install").addEventListener("click", showHelp);
inp.addEventListener("input", counts);
out.addEventListener("input", counts);
$("#h-clear").addEventListener("click", () => { inp.value = ""; counts(); });
$("#h-paste").addEventListener("click", async () => { const a = api(); try { inp.value = a ? await a.clipboard_text() : await navigator.clipboard.readText(); } catch (e) {} counts(); });
$("#h-copy").addEventListener("click", async () => {
  if (!out.value) return toast("Nothing to copy yet.", "warn");
  const a = api(); const ok = a ? await a.copy_text(out.value) : (await navigator.clipboard.writeText(out.value), true);
  toast(ok ? "Copied to clipboard" : "Couldn't copy", ok ? "" : "warn");
});
$("#h-send").addEventListener("click", () => {
  const t = out.value.trim() || inp.value.trim();
  if (!t) return toast("There's no text to send yet.", "warn");
  Writer.setText(t); App.show("writer"); toast("Loaded into the Writer");
});
$("#h-go").addEventListener("click", () => busy ? cancel() : humanize());
$("#h-again").addEventListener("click", () => humanize());
$("#h-diff-toggle").addEventListener("change", e => { save("show_changes", e.target.checked); showDiff(); });

async function refreshStatus() {
  const a = api(); if (!a) return;
  const btn = $("#h-refresh"); btn.disabled = true;
  status = await a.ollama_status();
  btn.disabled = false;
  render();
  toast(ready() ? `Local AI ready: ${status.models.length} model${status.models.length > 1 ? "s" : ""}` : "Local AI still not found", ready() ? "" : "warn");
  document.dispatchEvent(new CustomEvent("ollamastatus", { detail: status }));
}

// ------------------------------------------------------------------ humanize
async function humanize() {
  const text = inp.value;
  if (!text.trim()) return toast("Paste the text you want to humanize first.", "warn");
  const a = api();
  if (!a) return toast("Humanizing runs inside the Cadence app.", "warn");
  const eng = engine();
  if (eng === "ollama" && !ready()) return showHelp();
  lastInput = text;
  const opts = { engine: eng, tone: H.tone, strength: H.strength, reading_level: H.reading_level,
                 style_id: H.style_id, model: model.value };
  if (eng === "rules") {
    const res = await a.humanize(text, opts);
    if (!res.ok) return toast(res.error, "warn");
    finish(res.text, { changed: res.changed, elapsed: res.elapsed });
    return;
  }
  busy = true; setBusy(true);
  outParas = text.split("\n").map(() => "");
  out.value = ""; counts(); showDiff();
  progress(0, text.split("\n").filter(p => p.trim()).length);
  const res = await a.humanize(text, opts);
  if (!res.ok) { busy = false; setBusy(false); toast(res.error, "warn"); }
}
function cancel() { const a = api(); if (a) a.cancel_humanize(); $("#h-msg").textContent = "Cancelling…"; }
function setBusy(on) {
  $("#h-go-label").textContent = on ? "Cancel" : "Humanize";
  $("#h-go").classList.toggle("primary", !on);
  $("#h-go").innerHTML = `${icon(on ? "circle-stop" : "wand-sparkles", "sm")}<span id="h-go-label">${on ? "Cancel" : "Humanize"}</span>`;
  $("#h-again").disabled = on; $("#h-send").disabled = on;
  out.readOnly = on;
  $$("#h-engine button").forEach(b => b.disabled = on);
  $("#h-progress").hidden = !on;
  $("#h-msg").textContent = on ? "Rewriting with local AI…" : "";
}
function progress(done, total) {
  $("#h-progress .bar i").style.transform = `scaleX(${total ? done / total : 0})`;
  $("#h-progress-text").innerHTML = `${icon("refresh-cw", "sm spin")} Paragraph ${Math.min(done + 1, total)} of ${total}`;
  if (done >= total) $("#h-progress-text").textContent = `${total} of ${total}`;
}
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; if (outParas) { out.value = outParas.join("\n"); out.scrollTop = out.scrollHeight; counts(); } });
}
function finish(text, info) {
  busy = false; setBusy(false); outParas = null;
  out.value = text; counts();
  C.bump($("#hs-changed"), `${Math.round((info.changed || 0) * 100)}%`);
  C.bump($("#hs-time"), info.elapsed < 1 ? `${Math.max(0.01, info.elapsed).toFixed(2)}s` : C.fmtDur(info.elapsed));
  out.classList.remove("flash"); void out.offsetWidth; out.classList.add("flash");   // result just landed
  let msg = `Done · ${Math.round((info.changed || 0) * 100)}% of words changed`;
  if (info.fallbacks) msg += ` · ${info.fallbacks} paragraph${info.fallbacks > 1 ? "s" : ""} used the rule engine to keep facts exact`;
  $("#h-msg").textContent = msg;
  showDiff();
}

// pushed from Python while Local AI streams
Object.assign(window.cadence, {
  hDelta(i, d) { if (outParas) { outParas[i] += d; queueRender(); } },
  hParagraph(i, t) { if (outParas) { outParas[i] = t; queueRender(); } },
  hProgress(done, total) { progress(done, total); },
  hDone(text, info) { finish(text, info); },
  hError(msg) {
    busy = false; setBusy(false);
    if (outParas) { out.value = outParas.join("\n").trim() ? outParas.join("\n") : ""; outParas = null; counts(); }
    $("#h-msg").textContent = msg === "Cancelled." ? "Cancelled. Finished paragraphs are kept." : "";
    if (msg !== "Cancelled.") toast(msg, "warn");
  },
});

// ------------------------------------------------------------------ diff view
async function showDiff() {
  const on = H.show_changes && !busy && out.value;
  diffEl.hidden = !on; out.hidden = !!on;
  if (!on) return;
  const a = api();
  const segs = a ? await a.diff(lastInput || inp.value, out.value) : [["eq", out.value]];
  diffEl.innerHTML = segs.map(([op, t]) => op === "eq" ? esc(t) : `<span class="d-${op}">${esc(t)}</span>`).join("");
}

// ------------------------------------------------------------------ install help
function showHelp() {
  const m = C.modal({
    title: "Set up free local AI",
    body: `<ol class="steps">
      <li><b>Install Ollama.</b> It's free and runs entirely on your PC. <button class="chip" data-url="https://ollama.com/download">${icon("external-link", "sm")}ollama.com</button></li>
      <li><b>Download a model.</b> Open a terminal and run:
        <div class="cmd"><code>ollama pull llama3.2</code><button class="chip" data-copy="ollama pull llama3.2">${icon("copy", "sm")}Copy</button></div>
        <span class="muted">Works on most PCs (about 2 GB). For better rewrites on a stronger PC (16 GB RAM or a graphics card):</span>
        <div class="cmd"><code>ollama pull qwen2.5:7b</code><button class="chip" data-copy="ollama pull qwen2.5:7b">${icon("copy", "sm")}Copy</button></div></li>
      <li><b>Keep Ollama running</b> (it starts with Windows, or open the Ollama app), then check again.</li>
    </ol>
    <p class="muted">No internet connection or account is needed after that. Until then, the rule-based engine works instantly.</p>`,
    actions: [{ label: "Use rule-based", onClick: () => { save("engine", "rules"); render(); } },
              { label: "Check again", primary: true, onClick: () => { refreshStatus(); } }],
  });
  m.el.addEventListener("click", async e => {
    const u = e.target.closest("[data-url]"); if (u) { const a = api(); a ? a.open_url(u.dataset.url) : window.open(u.dataset.url); }
    const c = e.target.closest("[data-copy]");
    if (c) { const a = api(); if (a) await a.copy_text(c.dataset.copy); else await navigator.clipboard.writeText(c.dataset.copy); toast("Copied"); }
  });
}

window.Humanizer = {
  init(state) {
    Object.assign(H, state.humanizer);
    status = state.ollama;   // may be null: the check runs in the background
    styles = state.styles || [];
    render(); counts();
  },
  setStatus(st) { status = st; render(); },
  setStyles(list, useId) { styles = list; if (useId !== undefined) save("style_id", useId); render(); },
  get styleId() { return H.style_id; },
};
render(); counts();
document.addEventListener("ollamastatus", e => { if (e.detail !== status) { status = e.detail; render(); } });
})();

/* My style page: saved samples of the user's own writing. */
(() => {
"use strict";
const { $, api, icon, esc, toast } = C;

let styles = [], editing = null;          // id of the style open in the editor (null = new)
const list = $("#style-list"), nameEl = $("#se-name"), textEl = $("#se-text");
const MIN = 60, GOOD = 200;

function renderList() {
  const active = window.Humanizer ? Humanizer.styleId : "";
  if (!styles.length) {
    list.innerHTML = `<div class="card style-empty">${icon("fingerprint", "lg")}
      <div><b>No styles yet</b><p class="muted">Paste a few paragraphs of your own writing on the right, give it a name and save it.</p></div></div>`;
    return;
  }
  list.innerHTML = styles.map((s, i) => `
    <button class="card style-item ${s.id === editing ? "sel" : ""}" data-id="${esc(s.id)}" style="--i:${i}">
      <div class="si-head"><span class="si-name">${esc(s.name)}</span>${s.id === active ? `<span class="tag on">${icon("circle-check", "sm")}In use</span>` : ""}</div>
      <div class="si-meta muted num">${s.words.toLocaleString()} words</div>
      <div class="si-traits">${s.summary.slice(0, 3).map(t => `<span class="mini-tag">${esc(t)}</span>`).join("")}</div>
    </button>`).join("");
}

function openEditor(id) {
  editing = id;
  const s = styles.find(x => x.id === id);
  $("#se-title").textContent = s ? "Edit style" : "New style";
  nameEl.value = s ? s.name : "";
  textEl.value = s ? s.text : "";
  $("#se-delete").hidden = !s;
  $("#se-use").hidden = !s;
  renderList();
  analyze();
  const ed = $("#style-editor");
  ed.classList.remove("swap"); void ed.offsetWidth; ed.classList.add("swap");
}

let timer = null;
const analyzeSoon = () => { clearTimeout(timer); timer = setTimeout(analyze, 250); };
async function analyze() {
  const v = textEl.value;
  const a = api();
  const res = a ? await a.analyze_style(v) : demoAnalyze(v);
  const words = res.words;
  const meter = $("#se-meter");
  meter.style.transform = `scaleX(${Math.min(1, words / GOOD)})`;
  meter.classList.toggle("low", words < MIN);
  $("#se-words").textContent = words < MIN ? `${words} words · need at least ${MIN}` :
    words < GOOD ? `${words} words · more helps (200+ is ideal)` : `${words.toLocaleString()} words · plenty`;
  $("#se-traits").innerHTML = res.sentences >= 3 && res.summary.length
    ? res.summary.map((t, i) => `<span class="chip static trait" style="--i:${i}">${esc(t)}</span>`).join("")
    : `<span class="muted">Start typing or paste to see your habits.</span>`;
}
function demoAnalyze(v) {   // browser preview only; the app measures this in Python
  const sents = v.split(/(?<=[.!?])\s+/).filter(s => s.trim());
  const words = v.trim() ? v.trim().split(/\s+/).length : 0;
  const avg = sents.length ? words / sents.length : 0;
  return { words, sentences: sents.length, summary: sents.length >= 3 ? [`~${Math.round(avg)} words per sentence`] : [] };
}

textEl.addEventListener("input", analyzeSoon);
list.addEventListener("click", e => { const b = e.target.closest("[data-id]"); if (b) openEditor(b.dataset.id); });
$("#st-new").addEventListener("click", () => { openEditor(null); nameEl.focus(); });
$("#se-paste").addEventListener("click", async () => {
  const a = api();
  try { textEl.value = a ? await a.clipboard_text() : await navigator.clipboard.readText(); } catch (e) {}
  analyze();
});
$("#se-save").addEventListener("click", async () => {
  const a = api();
  if (!a) return toast("Saving styles works inside the Cadence app.", "warn");
  const res = await a.save_style(nameEl.value, textEl.value, editing);
  if (!res.ok) return toast(res.error, "warn");
  styles = res.styles; editing = res.id;
  Humanizer.setStyles(styles);
  openEditor(editing);
  toast(`Saved “${nameEl.value.trim() || "My style"}”`);
});
$("#se-use").addEventListener("click", () => {
  if (!editing) return;
  Humanizer.setStyles(styles, editing);
  renderList();
  App.show("humanizer");
  toast("The Humanizer will follow this style");
});
$("#se-delete").addEventListener("click", () => {
  const s = styles.find(x => x.id === editing);
  if (!s) return;
  C.modal({ title: "Delete style?", body: `<p class="muted">“${esc(s.name)}” will be removed. This can't be undone.</p>`,
    actions: [{ label: "Cancel" }, { label: "Delete", primary: true, onClick: async () => {
      const res = await api().delete_style(s.id);
      styles = res.styles; Humanizer.setStyles(styles);
      openEditor(styles[0] ? styles[0].id : null);
    } }] });
});
document.addEventListener("viewshown", e => { if (e.detail === "style") renderList(); });

window.Styles = {
  init(state) { styles = state.styles || []; openEditor(styles[0] ? styles[0].id : null); },
};
openEditor(null);
})();

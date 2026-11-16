/* Auto-save, history, files (open / save / drag & drop), readability and shortcuts. */
(() => {
"use strict";
const { $, $$, api, icon, esc, toast } = C;

// ------------------------------------------------------------------ auto-save drafts
const DRAFT_BOXES = { "writer_text": "#writer-text", "h_in": "#h-in", "h_out": "#h-out" };
const draftTimers = {};
function saveDraft(key) {
  clearTimeout(draftTimers[key]);
  draftTimers[key] = setTimeout(() => { const a = api(); if (a) a.save_draft(key, $(DRAFT_BOXES[key]).value); }, 600);
}
for (const [key, sel] of Object.entries(DRAFT_BOXES)) {
  const el = $(sel);
  el.addEventListener("input", () => saveDraft(key));
  // programmatic changes (Paste, Send to Writer, Humanize results) don't fire "input": watch value changes
  let last = el.value;
  setInterval(() => { if (el.value !== last) { last = el.value; saveDraft(key); } }, 1500);
}
function restoreDrafts(drafts) {
  if (!drafts) return;
  if (drafts.writer_text && !$("#writer-text").value) Writer.setText(drafts.writer_text);
  if (drafts.h_in && !$("#h-in").value) { $("#h-in").value = drafts.h_in; $("#h-in").dispatchEvent(new Event("input")); }
  if (drafts.h_out && !$("#h-out").value) { $("#h-out").value = drafts.h_out; $("#h-out").dispatchEvent(new Event("input")); }
}

// ------------------------------------------------------------------ readability (Flesch)
function syllables(w) {
  w = w.toLowerCase().replace(/[^a-z]/g, "");
  if (!w) return 0;
  if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").replace(/^y/, "");
  const m = w.match(/[aeiouy]{1,2}/g);
  return Math.max(1, m ? m.length : 1);
}
function readability(text) {
  const words = text.match(/[A-Za-z][A-Za-z'’-]*/g) || [];
  const sents = Math.max(1, (text.match(/[.!?]+(?=\s|$)/g) || []).length);
  if (words.length < 20) return null;
  const syl = words.reduce((n, w) => n + syllables(w), 0);
  const wps = words.length / sents, spw = syl / words.length;
  const ease = 206.835 - 1.015 * wps - 84.6 * spw;
  const grade = Math.max(1, Math.round(0.39 * wps + 11.8 * spw - 15.59));
  const label = ease >= 80 ? "very easy" : ease >= 70 ? "easy" : ease >= 60 ? "plain English" : ease >= 50 ? "fairly hard" : ease >= 30 ? "hard" : "very hard";
  return { grade, label };
}
function showReadability(boxSel, outSel) {
  const r = readability($(boxSel).value), el = $(outSel);
  el.innerHTML = r ? `${icon("book-open", "sm")}Grade ${r.grade} · ${r.label}` : "";
  el.title = r ? "Flesch-Kincaid reading grade" : "";
}
const readTimers = {};
function readSoon(box, out) { clearTimeout(readTimers[box]); readTimers[box] = setTimeout(() => showReadability(box, out), 300); }
$("#h-in").addEventListener("input", () => readSoon("#h-in", "#h-in-read"));
$("#h-out").addEventListener("input", () => readSoon("#h-out", "#h-out-read"));
let lastOut = null;
setInterval(() => {                       // programmatic updates (Humanize results) don't fire "input"
  const v = $("#h-out").value;
  if (v !== lastOut) { lastOut = v; showReadability("#h-out", "#h-out-read"); }
}, 1200);

// ------------------------------------------------------------------ files
async function openInto(sel, after) {
  const a = api();
  if (!a) return toast("Opening files works inside the Cadence app.", "warn");
  const res = await a.open_file();
  if (!res.ok) { if (!res.cancelled) toast(res.error, "warn"); return; }
  after(res.text); toast(`Opened ${res.name}`);
}
$("#btn-open").addEventListener("click", () => openInto("#writer-text", t => Writer.setText(t)));
$("#h-open").addEventListener("click", () => openInto("#h-in", t => { $("#h-in").value = t; $("#h-in").dispatchEvent(new Event("input")); }));
$("#h-save").addEventListener("click", saveOutput);
async function saveOutput() {
  const t = $("#h-out").value;
  if (!t.trim()) return toast("There's no rewrite to save yet.", "warn");
  const a = api();
  if (!a) return toast("Saving works inside the Cadence app.", "warn");
  const res = await a.save_text_file(t, "humanized.txt");
  if (res.ok) toast(`Saved ${res.name}`); else if (!res.cancelled) toast(res.error, "warn");
}

// drag & drop a .txt / .md / .docx onto a text box
function dropZone(sel, after) {
  const box = $(sel), card = box.closest(".card");
  let depth = 0;
  card.addEventListener("dragenter", e => { if (hasFile(e)) { depth++; card.classList.add("drop"); e.preventDefault(); } });
  card.addEventListener("dragover", e => { if (hasFile(e)) e.preventDefault(); });
  card.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; card.classList.remove("drop"); } });
  card.addEventListener("drop", async e => {
    if (!hasFile(e)) return;
    e.preventDefault(); depth = 0; card.classList.remove("drop");
    const f = e.dataTransfer.files[0];
    if (!f) return;
    try {
      let text;
      if (/\.docx$/i.test(f.name)) {
        const a = api();
        if (!a) return toast("Word files open inside the Cadence app.", "warn");
        const b64 = await toB64(f);
        const res = await a.read_dropped(f.name, b64);
        if (!res.ok) return toast(res.error, "warn");
        text = res.text;
      } else if (/\.(txt|md|markdown|text)$/i.test(f.name) || f.type.startsWith("text/")) {
        text = await f.text();
      } else return toast("Cadence can open .txt, .md and .docx files.", "warn");
      after(text.replace(/\r\n?/g, "\n")); toast(`Opened ${f.name}`);
    } catch (err) { toast("Couldn't read that file.", "warn"); }
  });
}
const hasFile = e => [...(e.dataTransfer && e.dataTransfer.types || [])].includes("Files");
const toB64 = f => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res(String(r.result).split(",")[1] || "");
  r.onerror = rej; r.readAsDataURL(f);
});
dropZone("#writer-text", t => Writer.setText(t));
dropZone("#h-in", t => { $("#h-in").value = t; $("#h-in").dispatchEvent(new Event("input")); });
window.addEventListener("dragover", e => e.preventDefault());   // never navigate away on a stray drop
window.addEventListener("drop", e => e.preventDefault());

// ------------------------------------------------------------------ history
const STRENGTH = ["Light", "Moderate", "Heavy"];
function ago(ts) {
  const s = Math.max(1, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}
async function showHistory() {
  const a = api();
  const items = a ? await a.list_history() : [];
  const body = items.length ? `<div class="hist-list" id="hist-list">${items.map((h, i) => `
      <div class="hist-item" data-id="${esc(h.id)}" style="--i:${Math.min(i, 10)}" role="button" tabindex="0">
        <div class="hist-meta"><span class="tag">${h.engine === "ollama" ? "Local AI" : "Rule-based"}</span>
          <span class="muted">${esc(h.tone)} · ${STRENGTH[h.strength] || ""}${h.style ? ` · ${esc(h.style)}` : ""}</span>
          <span class="muted hist-ago">${ago(h.ts)}</span>
          <button class="mini-btn hist-del" data-del="${esc(h.id)}" aria-label="Delete">${icon("x", "sm")}</button></div>
        <div class="hist-text">${esc(h.preview)}${h.preview.length >= 140 ? "…" : ""}</div>
      </div>`).join("")}</div>`
    : `<div class="hist-empty muted">${icon("history", "lg")}<p>Your Humanizer runs show up here, so you can bring back an earlier version.</p></div>`;
  const m = C.modal({ title: "History", body,
    actions: items.length ? [{ label: "Clear all", onClick: async () => { await api().clear_history(); toast("History cleared"); } },
                             { label: "Close", primary: true }] : [{ label: "Close", primary: true }] });
  m.el.querySelector(".modal").classList.add("hist-modal");
  m.el.addEventListener("click", async e => {
    const del = e.target.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      await api().delete_history(del.dataset.del);
      const row = del.closest(".hist-item"); row.classList.add("gone"); setTimeout(() => row.remove(), 220);
      return;
    }
    const item = e.target.closest(".hist-item");
    if (item) {
      const h = await api().get_history(item.dataset.id);
      if (!h) return;
      $("#h-in").value = h.input; $("#h-in").dispatchEvent(new Event("input"));
      $("#h-out").value = h.output; $("#h-out").dispatchEvent(new Event("input"));
      m.close(); App.show("humanizer"); toast("Restored from history");
    }
  });
}
$("#h-history").addEventListener("click", showHistory);

// ------------------------------------------------------------------ preview button
$("#btn-preview").addEventListener("click", () => Preview.open($("#writer-text").value));

// ------------------------------------------------------------------ keyboard shortcuts
const VIEWS = ["humanizer", "writer", "style", "presets", "settings"];
document.addEventListener("keydown", e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  if (document.querySelector(".modal-wrap:not(.closing)")) return;  // a dialog is open
  const view = (document.querySelector(".view.active") || {}).id || "";
  const k = e.key.toLowerCase();
  if (/^[1-5]$/.test(k)) { e.preventDefault(); App.show(VIEWS[+k - 1]); return; }
  if (k === "enter" && view === "view-humanizer") { e.preventDefault(); $("#h-go").click(); return; }
  if (k === "o") {
    e.preventDefault();
    if (view === "view-humanizer") $("#h-open").click(); else if (view === "view-writer") $("#btn-open").click();
    return;
  }
  if (k === "s" && view === "view-humanizer") { e.preventDefault(); saveOutput(); return; }
  if (k === "p" && view === "view-writer") { e.preventDefault(); $("#btn-preview").click(); return; }
  if (k === "h" && view === "view-humanizer") { e.preventDefault(); showHistory(); }
});

window.Extras = { restoreDrafts, readability };
// Browser review hook: index.html#preview opens the typing preview demo.
if (!(window.pywebview && window.pywebview.api) && /preview/.test(location.hash)) setTimeout(() => $("#btn-preview").click(), 300);
})();

/* Typing preview: plays the Writer's exact keystroke plan inside Cadence. */
(() => {
"use strict";
const { $, api, icon, esc, toast, fmtClock } = C;
const SPEEDS = [1, 2, 5, 20];
const STATUS = { t: ["Typing", ""], y: ["Typo", "warn"], f: ["Fixing a typo", "warn"], n: ["Moving the cursor", "info"],
                 r: ["Revising earlier text", "info"], k: ["Rethinking a word", "info"], g: ["Rough draft wording", "info"] };

async function open(text) {
  if (!text.trim()) return toast("Add some text to preview first.", "warn");
  const a = api();
  let plan;
  if (a) plan = await a.preview_plan(text);
  else plan = demoPlan(text);
  if (!plan || plan.error) return toast(plan && plan.error ? plan.error : "Couldn't build a preview.", "warn");

  const notes = [];
  if (plan.truncated) notes.push(`Showing the first ${plan.text.length.toLocaleString()} characters.`);
  if (plan.duration_mode) notes.push("Paced by words per minute (target-duration pacing applies to the real run).");
  const m = C.modal({
    title: "Typing preview",
    body: `<p class="muted pv-sub">Exactly what the Writer will type: speed, pauses, typos and fixes. Nothing is typed anywhere else.</p>
      <div class="pv-doc" id="pv-doc"><span id="pv-before"></span><span class="pv-caret" id="pv-caret"></span><span id="pv-after"></span></div>
      <div class="pv-status"><span class="pv-dot" id="pv-dot"></span><span id="pv-state">Ready</span>
        <span class="pv-counts muted num" id="pv-counts"></span></div>
      <div class="pv-bar"><i id="pv-bar"></i></div>
      <div class="pv-controls">
        <button class="pill primary" id="pv-play">${icon("play", "sm")}<span>Play</span></button>
        <button class="pill icon" id="pv-restart" aria-label="Restart" title="Restart">${icon("skip-back", "sm")}</button>
        ${C.segHTML("pv-speed", SPEEDS.map(s => [String(s), `${s}×`]), 'id="pv-speed"')}
        <span class="muted num pv-time" id="pv-time"></span>
      </div>
      ${notes.length ? `<p class="muted pv-note">${esc(notes.join(" "))}</p>` : ""}`,
    actions: [{ label: "Close" }],
  });
  m.el.querySelector(".modal").classList.add("pv-modal");
  const player = new Player(plan, m.el);
  m.el.addEventListener("click", e => {
    if (e.target.closest("#pv-play")) player.toggle();
    if (e.target.closest("#pv-restart")) player.restart();
    const s = e.target.closest("#pv-speed button");
    if (s) player.setSpeed(+s.dataset.v);
  });
  const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { player.stop(); obs.disconnect(); } });
  obs.observe(document.body, { childList: true });
  requestAnimationFrame(() => { C.setSeg(m.el.querySelector("#pv-speed"), "1"); player.play(); });
}

class Player {
  constructor(plan, root) {
    this.acts = plan.actions; this.root = root; this.speed = 1;
    this.due = []; let t = 0;
    for (const a of this.acts) { t += a[2]; this.due.push(t); }
    this.total = t;
    this.el = id => root.querySelector(id);
    this.reset();
  }
  reset() {
    this.ed = new PreviewModel.PreviewEditor();
    this.i = 0; this.clock = 0; this.counts = { y: 0, f: 0, r: 0 }; this.lastNote = "t"; this.dirty = true;
    this.render(true);
  }
  play() {
    if (this.i >= this.acts.length) this.reset();
    this.playing = true; this.last = performance.now();
    this.setButton();
    cancelAnimationFrame(this.raf);
    this.raf = requestAnimationFrame(t => this.tick(t));
  }
  pause() { this.playing = false; cancelAnimationFrame(this.raf); this.setButton(); this.render(true); }
  stop() { this.playing = false; cancelAnimationFrame(this.raf); }
  toggle() { this.playing ? this.pause() : this.play(); }
  restart() { this.reset(); this.play(); }
  setSpeed(s) { this.speed = s; C.setSeg(this.el("#pv-speed"), String(s)); this.render(true); }
  setButton() {
    this.el("#pv-play").innerHTML = this.playing ? `${icon("pause", "sm")}<span>Pause</span>` :
      `${icon("play", "sm")}<span>${this.i >= this.acts.length ? "Replay" : "Play"}</span>`;
  }
  tick(now) {
    if (!this.playing) return;
    const dt = Math.min(100, now - this.last); this.last = now;
    this.clock += dt * this.speed;
    let n = 0;
    while (this.i < this.acts.length && this.due[this.i] <= this.clock && n < 600) {
      const a = this.acts[this.i++];
      this.ed.apply(a);
      if (a[4] !== this.lastNote) {
        if (a[4] === "y") this.counts.y++;
        if (a[4] === "f") this.counts.f++;
        if (a[4] === "r") this.counts.r++;
      }
      this.lastNote = a[4]; this.dirty = true; n++;
    }
    this.render();
    if (this.i >= this.acts.length) { this.playing = false; this.setButton(); this.status("Done", ""); return; }
    this.raf = requestAnimationFrame(t => this.tick(t));
  }
  status(label, kind) {
    const s = this.el("#pv-state");
    if (s.textContent !== label) { C.bump(s, label); }
    this.el("#pv-dot").className = `pv-dot ${kind}`;
  }
  render(force) {
    if (!this.dirty && !force) return;
    this.dirty = false;
    const buf = this.ed.buf, c = this.ed.cursor;
    this.el("#pv-before").textContent = buf.slice(0, c).join("");
    this.el("#pv-after").textContent = buf.slice(c).join("");
    const caret = this.el("#pv-caret");
    caret.classList.toggle("warn", this.lastNote === "y" || this.lastNote === "f");
    caret.classList.remove("blink"); void caret.offsetWidth; caret.classList.add("blink");
    const doc = this.el("#pv-doc"), top = caret.offsetTop;
    if (top < doc.scrollTop + 20 || top > doc.scrollTop + doc.clientHeight - 40) doc.scrollTop = top - doc.clientHeight / 2;
    const [label, kind] = STATUS[this.lastNote] || STATUS.t;
    if (this.i > 0 && this.i < this.acts.length) this.status(label, kind);
    else if (this.i === 0) this.status("Ready", "");
    this.el("#pv-bar").style.transform = `scaleX(${this.total ? Math.min(1, this.clock / this.total) : 0})`;
    this.el("#pv-time").textContent = `${fmtClock(Math.min(this.clock, this.total) / 1000)} / ${fmtClock(this.total / 1000)} at 1×`;
    this.el("#pv-counts").textContent = `${this.counts.y} typos · ${this.counts.f} fixed · ${this.counts.r} revisions`;
  }
}

function demoPlan(text) {   // browser preview: plain typing, no engine
  text = text.slice(0, 2500);
  return { text, truncated: false, actions: [...text].map(ch => ch === "\n" ? [1, "enter", 160, 0, "t"] : [0, ch, 160, 0, "t"]) };
}

window.Preview = { open };
})();

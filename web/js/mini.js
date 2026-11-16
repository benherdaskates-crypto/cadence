/* Mini panel: shown while typing. Used by mini.html (its own frameless window in
   the app) and embedded in index.html for the browser demo. */
window.MiniPanel = (() => {
"use strict";
const ic = (n, c = "sm") => `<svg class="i ${c}" viewBox="0 0 24 24" aria-hidden="true">${(window.ICONS || {})[n] || ""}</svg>`;
const clock = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`; };
const LABEL = { idle: "Ready", countdown: "Starting", typing: "Typing", paused: "Paused", break: "On a break",
                resuming: "Resuming", done: "Finished", stopped: "Stopped", error: "Error" };
const LIVE = new Set(["countdown", "typing", "paused", "break", "resuming"]);
const R = 26, CIRC = 2 * Math.PI * R, SWEEP = 0.75;
// Same idea as C.glide (the mini window doesn't load common.js): ease toward each new value.
const glides = {};
function glide(key, target, apply, tau = 220) {
  const g = glides[key] || (glides[key] = { v: target, t: target, raf: 0, last: 0 });
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

function mount(host, h) {
  host.innerHTML = `
  <div class="mini" role="region" aria-label="Cadence mini panel">
    <div class="mini-full">
      <div class="mini-top drag-region pywebview-drag-region">
        <span class="grip">${ic("grip-vertical")}</span>
        <img class="mini-logo" src="img/logo.png" alt="" draggable="false">
        <span class="mini-dot"></span><span class="mini-state">Ready</span>
        <span class="mini-spacer"></span>
        <button class="mini-btn" data-act="collapse" aria-label="Minimize panel" title="Minimize">${ic("minus")}</button>
        <button class="mini-btn" data-act="expand" aria-label="Open Cadence" title="Open Cadence">${ic("maximize-2")}</button>
        <button class="mini-btn close" data-act="quit" aria-label="Quit Cadence" title="Quit Cadence">${ic("x")}</button>
      </div>
      <div class="mini-body">
        <div class="mini-gauge">
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="32" cy="32" r="${R}" fill="none" stroke-width="5" stroke-linecap="round" class="mg-track"
              stroke-dasharray="${CIRC * SWEEP} ${CIRC}" transform="rotate(135 32 32)"/>
            <circle cx="32" cy="32" r="${R}" fill="none" stroke-width="5" stroke-linecap="round" class="mg-val"
              stroke-dasharray="0 ${CIRC}" transform="rotate(135 32 32)"/>
          </svg>
          <div class="mg-num num">0</div><div class="mg-unit">WPM</div>
        </div>
        <div class="mini-main">
          <div class="mini-eta num">–:––</div>
          <div class="mini-sub num">left</div>
          <div class="mini-prog"><i></i></div>
        </div>
      </div>
      <div class="mini-actions">
        <button class="pill sm" data-act="toggle">${ic("pause")}<span>Pause</span></button>
        <button class="pill sm" data-act="stop">${ic("square")}<span>Stop</span></button>
      </div>
    </div>
    <div class="mini-pill drag-region pywebview-drag-region">
      <span class="grip">${ic("grip-vertical")}</span>
      <span class="mini-dot"></span>
      <span class="mp-text num">Ready</span>
      <span class="mp-ring"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.5" class="mg-track" fill="none" stroke-width="2.5"/>
        <circle cx="10" cy="10" r="7.5" class="mg-val" fill="none" stroke-width="2.5" stroke-linecap="round" transform="rotate(-90 10 10)" stroke-dasharray="0 48"/></svg></span>
      <button class="mini-btn" data-act="toggle" aria-label="Pause or resume" title="Pause / resume">${ic("pause")}</button>
      <button class="mini-btn" data-act="restore" aria-label="Restore panel" title="Restore">${ic("chevron-down")}</button>
    </div>
    <div class="mini-confirm" hidden>
      <div class="mc-text">Stop typing and quit Cadence?</div>
      <div class="mc-actions"><button class="pill sm" data-act="cancel">Cancel</button>
        <button class="pill sm danger" data-act="quit-now">${ic("power")}Quit</button></div>
    </div>
  </div>`;
  const root = host.firstElementChild;
  const q = s => root.querySelector(s);
  let state = "idle";

  root.addEventListener("click", e => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "collapse") { root.classList.add("collapsed"); h.collapse && h.collapse(true); }
    else if (act === "restore") { root.classList.remove("collapsed"); h.collapse && h.collapse(false); }
    else if (act === "quit") {
      if (!LIVE.has(state)) return h.quit();
      root.classList.remove("collapsed");           // ask in the full panel, not the tiny pill
      h.collapse && h.collapse(false);
      q(".mini-confirm").hidden = false;
    }
    else if (act === "cancel") q(".mini-confirm").hidden = true;
    else if (act === "quit-now") h.quit();
    else if (h[act]) h[act]();
  });

  function update(st) {
    state = st.state;
    root.dataset.state = st.state;
    let lbl = LABEL[st.state] || st.state;
    if ((st.state === "countdown" || st.state === "resuming") && st.countdown > 0) lbl += ` · ${Math.ceil(st.countdown)}`;
    q(".mini-state").textContent = lbl;
    const wpm = st.state === "typing" ? st.wpm : 0;
    glide("wpm", wpm, w => {
      q(".mg-num").textContent = Math.round(w);
      const f = Math.min(1, w / 150);
      q(".mini-full .mg-val").setAttribute("stroke-dasharray", `${Math.max(0.001, CIRC * SWEEP * f)} ${CIRC}`);
      q(".mini-full .mg-val").style.opacity = f > 0.002 ? 1 : 0;
    }, 260);
    const eta = LIVE.has(st.state) ? clock(st.remaining) : (st.state === "done" ? "0:00" : "–:––");
    q(".mini-eta").textContent = eta;
    q(".mini-sub").textContent = st.state === "paused" ? (st.message || "Paused") :
      `left · ${Math.round(st.progress * 100)}% · ${st.typed_chars.toLocaleString()}/${st.total_chars.toLocaleString()} chars`;
    glide("prog", st.progress, p => {
      q(".mini-prog i").style.transform = `scaleX(${p})`;
      q(".mp-ring .mg-val").setAttribute("stroke-dasharray", `${47.1 * p} 48`);
    });
    q(".mp-text").textContent = st.state === "typing" ? `${eta} left` : (LIVE.has(st.state) && st.state !== "countdown" && st.state !== "resuming" ? `${lbl} · ${eta}` : lbl);
    const paused = st.state === "paused";
    root.querySelectorAll('[data-act="toggle"]').forEach(b => {
      b.innerHTML = b.classList.contains("pill") ? `${ic(paused ? "play" : "pause")}<span>${paused ? "Resume" : "Pause"}</span>` : ic(paused ? "play" : "pause");
      b.disabled = !LIVE.has(st.state);
    });
    q('[data-act="stop"]').disabled = !LIVE.has(st.state);
  }
  return { root, update };
}

/* Manual drag for the in-page demo (the real window uses pywebview's drag region). */
function makeDraggable(host) {
  let sx, sy, ox, oy, dragging = false;
  host.addEventListener("pointerdown", e => {
    if (!e.target.closest(".drag-region") || e.target.closest("button")) return;
    dragging = true; host.setPointerCapture(e.pointerId);
    const r = host.getBoundingClientRect(); sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top;
    host.style.right = "auto"; host.style.left = `${ox}px`; host.style.top = `${oy}px`;
  });
  host.addEventListener("pointermove", e => {
    if (!dragging) return;
    host.style.left = `${ox + e.clientX - sx}px`; host.style.top = `${oy + e.clientY - sy}px`;
  });
  host.addEventListener("pointerup", () => { dragging = false; });
}
return { mount, makeDraggable };
})();

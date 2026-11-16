/* Install on this PC, shortcuts, uninstall, and updates. */
(() => {
"use strict";
const { $, api, icon, esc, toast } = C;
let inst = null, upd = { configured: false }, version = "", pending = null;

function cardHTML() {
  if (!inst) return "";
  let body;
  if (!inst.frozen) {
    body = `<div class="row"><div class="row-desc">Running from source. Install, shortcuts and updates work in the .exe (build it with <code>build.bat</code>).</div></div>`;
  } else {
    const where = inst.running_installed ? `Installed in <span class="path">${esc(inst.install_dir)}</span>`
                                         : `Running from <span class="path">${esc(inst.running_from)}</span>`;
    body = `<div class="row"><div class="row-label">This copy</div><div class="row-desc">${where}</div></div>
      <div class="row"><div class="presets">
        ${inst.running_installed ? "" : `<button class="chip" id="d-install">${icon("download", "sm")}Install on this PC</button>`}
        ${inst.desktop_shortcut ? `<span class="chip static">${icon("check", "sm")}Desktop shortcut</span>`
                                : `<button class="chip" id="d-shortcut">${icon("plus", "sm")}Desktop shortcut</button>`}
        ${inst.running_installed ? `<button class="chip" id="d-uninstall">${icon("trash-2", "sm")}Uninstall</button>` : ""}
      </div></div>`;
  }
  const updRow = !upd.configured
    ? `<div class="row"><div class="row-label">Updates</div><div class="row-desc">Not connected yet. Updates come from a GitHub Releases page; see "Sharing &amp; updates" in the README.</div></div>`
    : `<div class="row"><div class="row-head"><div><div class="row-label">Updates</div>
          <div class="row-desc" id="d-upd-msg">From github.com/${esc(upd.repo)}</div></div>
          <button class="chip" id="d-check">${icon("refresh-cw", "sm")}Check now</button></div>
        <div class="upd-progress" id="d-upd-prog" hidden><span class="bar"><i></i></span><span class="muted num" id="d-upd-pct"></span></div></div>
       <div class="row"><div class="row-head"><div><div class="row-label">Check automatically</div><div class="row-desc">About once a day, in the background.</div></div>
          <label class="switch"><input type="checkbox" id="d-auto" ${window.__uiAutoUpdate !== false ? "checked" : ""} aria-label="Check for updates automatically"><span class="track"></span><span class="knob"></span></label></div></div>`;
  return `<div class="card set-card" id="dist-card">
    <div class="card-title"><h3>Install &amp; updates</h3><span class="muted num">v${esc(version)}</span></div>
    ${body}${updRow}</div>`;
}

function render() {
  const grid = $("#settings-grid");
  if (!grid) return;
  const old = $("#dist-card");
  const html = cardHTML();
  if (!html) return;
  if (old) old.outerHTML = html; else grid.insertAdjacentHTML("beforeend", html);
}
// Settings re-renders its grid; put our card back each time.
new MutationObserver(() => { if (!$("#dist-card") && inst) render(); }).observe($("#settings-grid"), { childList: true });

$("#settings-grid").addEventListener("click", async e => {
  const a = api(); if (!a) return;
  if (e.target.closest("#d-install")) return promptInstall(true);
  if (e.target.closest("#d-shortcut")) {
    const r = await a.add_desktop_shortcut();
    if (!r.ok) return toast(r.error, "warn");
    inst = r.status; render(); toast("Desktop shortcut added");
  }
  if (e.target.closest("#d-uninstall")) {
    C.modal({ title: "Uninstall Cadence?",
      body: `<p class="muted">Removes the app and its shortcuts from this PC. Your settings, styles and history stay in %APPDATA%\\CadenceFree in case you reinstall.</p>`,
      actions: [{ label: "Cancel" }, { label: "Uninstall", primary: true, onClick: async () => { const r = await a.uninstall_app(); if (!r.ok) toast(r.error, "warn"); } }] });
  }
  if (e.target.closest("#d-check")) checkNow();
});
$("#settings-grid").addEventListener("change", e => {
  if (e.target.id === "d-auto") { window.__uiAutoUpdate = e.target.checked; const a = api(); if (a) a.set_ui("auto_update", e.target.checked); }
});

async function checkNow() {
  const a = api(); const btn = $("#d-check"); if (btn) btn.disabled = true;
  const r = await a.check_updates();
  if (btn) btn.disabled = false;
  const msg = $("#d-upd-msg");
  if (!r.ok) { if (msg) msg.textContent = r.error; return toast(r.error, "warn"); }
  if (r.available) offerUpdate(r);
  else { if (msg) msg.textContent = `You're on the latest version (v${r.current}).`; toast("You're up to date"); }
}

function offerUpdate(info) {
  pending = info;
  C.modal({ title: `Update to v${esc(info.latest)}?`,
    body: `<p class="muted">You have v${esc(info.current)}. The new version downloads from GitHub, is checked, and Cadence restarts with it.</p>
      ${info.notes ? `<div class="upd-notes">${esc(info.notes).replace(/\n/g, "<br>")}</div>` : ""}
      ${info.sha256 ? `<p class="muted upd-safe">${icon("shield", "sm")} The download is verified against the release's checksum.</p>` : ""}`,
    actions: [{ label: "Later" }, { label: "Update now", primary: true, onClick: () => { startUpdate(info); } }] });
}

async function startUpdate(info) {
  const a = api();
  const r = await a.install_update(info);
  if (!r.ok) return toast(r.error, "warn");
  toast("Downloading the update…");
  App.show("settings");
  requestAnimationFrame(() => { const p = $("#d-upd-prog"); if (p) p.hidden = false; });
}

Object.assign(window.cadence, {
  updateAvailable(info) {
    upd.configured = true;
    const el = document.createElement("div");
    el.className = "upd-banner";
    el.innerHTML = `${icon("download", "sm")}<span>Cadence v${esc(info.latest)} is available</span>
      <button class="chip" data-act="view">Update</button><button class="mini-btn" data-act="close" aria-label="Dismiss">${icon("x", "sm")}</button>`;
    document.body.appendChild(el);
    el.addEventListener("click", ev => {
      const b = ev.target.closest("[data-act]"); if (!b) return;
      el.classList.add("gone"); setTimeout(() => el.remove(), 250);
      if (b.dataset.act === "view") offerUpdate(info);
    });
  },
  updProgress(got, total) {
    const p = $("#d-upd-prog"); if (!p) return;
    p.hidden = false;
    $("i", p).style.transform = `scaleX(${total ? got / total : 0})`;
    $("#d-upd-pct").textContent = total ? `${Math.round(got / total * 100)}% of ${(total / 1e6).toFixed(1)} MB` : `${(got / 1e6).toFixed(1)} MB`;
  },
  updReady() { toast("Update downloaded. Restarting…"); },
  updError(msg) { const p = $("#d-upd-prog"); if (p) p.hidden = true; toast(msg, "warn"); },
});

// First run from Downloads (or anywhere else): offer to install properly.
function promptInstall(force = false) {
  const a = api(); if (!a || !inst || !inst.frozen || inst.running_installed) return;
  C.modal({ title: "Install Cadence?",
    body: `<p class="muted">Puts Cadence in your user folder with a Start menu entry, so you can find it easily and it can update itself. No admin rights needed.</p>
      <label class="check-row"><input type="checkbox" id="inst-desk" checked> Add a desktop shortcut</label>
      ${force ? "" : `<label class="check-row"><input type="checkbox" id="inst-never"> Don't ask again</label>`}`,
    actions: [{ label: "Just run it", onClick: w => { const n = $("#inst-never", w); if (n && n.checked) a.set_ui("install_prompt", false); } },
              { label: "Install", primary: true, onClick: async w => {
                  const r = await a.install_app($("#inst-desk", w).checked, true);
                  if (!r.ok) return toast(r.error, "warn");
                  toast(r.relaunch ? "Installed. Opening the installed copy…" : "Installed");
                } }] });
}

window.Distribution = {
  init(state) {
    inst = state.install || null; version = state.version || "";
    upd = state.updates || upd;
    window.__uiAutoUpdate = state.ui ? state.ui.auto_update !== false : true;
    render();
    if (state.ui && state.ui.install_prompt !== false && inst && inst.frozen && !inst.running_installed && !inst.installed) {
      setTimeout(() => promptInstall(false), 900);
    }
  },
};
})();

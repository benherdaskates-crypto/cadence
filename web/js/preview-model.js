/* Plain-text editor model used by the typing preview. Mirrors engine/actions.py
   (VirtualEditor) exactly, including Windows-style Ctrl+Left/Right, so the
   preview shows the same thing the real typer produces. Also loadable in Node
   for tests. */
(function (root) {
"use strict";
const isWord = c => /^[A-Za-z0-9]$/.test(c);

function ctrlLeft(buf, p) {
  let q = p;
  while (q > 0 && buf[q - 1] === " ") q--;
  while (q > 0 && isWord(buf[q - 1])) q--;
  if (q === p && p > 0) q = p - 1;
  return q;
}
function ctrlRight(buf, p) {
  const n = buf.length;
  let q = p;
  while (q < n && isWord(buf[q])) q++;
  while (q < n && buf[q] === " ") q++;
  if (q === p && p < n) q = p + 1;
  return q;
}

class PreviewEditor {
  constructor() { this.buf = []; this.cursor = 0; }
  get text() { return this.buf.join(""); }
  // action: [kind(0 char / 1 key), value, delayMs, ctrl, note]
  apply(a) {
    const [kind, v, , ctrl] = a, b = this.buf, c = this.cursor;
    if (kind === 0) { b.splice(c, 0, v); this.cursor = c + 1; return; }
    switch (v) {
      case "backspace": if (c > 0) { b.splice(c - 1, 1); this.cursor = c - 1; } break;
      case "enter": b.splice(c, 0, "\n"); this.cursor = c + 1; break;
      case "tab": b.splice(c, 0, "\t"); this.cursor = c + 1; break;
      case "left": this.cursor = ctrl ? ctrlLeft(b, c) : Math.max(0, c - 1); break;
      case "right": this.cursor = ctrl ? ctrlRight(b, c) : Math.min(b.length, c + 1); break;
      case "home":
        if (ctrl) this.cursor = 0; else { while (this.cursor > 0 && b[this.cursor - 1] !== "\n") this.cursor--; }
        break;
      case "end":
        if (ctrl) this.cursor = b.length; else { while (this.cursor < b.length && b[this.cursor] !== "\n") this.cursor++; }
        break;
    }
  }
}
const api = { PreviewEditor, ctrlLeft, ctrlRight };
if (typeof module !== "undefined" && module.exports) module.exports = api;
else root.PreviewModel = api;
})(typeof window !== "undefined" ? window : globalThis);

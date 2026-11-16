# Cadence

A free, fully offline Windows app. It doesn't need an API key, an account, or the internet.

- **Humanizer**: rewrites stiff, machine-sounding text so it reads like a person wrote it, keeping the same meaning, facts, names, numbers and dates. It has two engines:
  - **Local AI (Ollama)**: a language model running on your own PC, used automatically when it's installed.
  - **Rule-based (instant)**: pure Python with nothing to install. It always works.
- **Writer**: types text into whatever window has focus, keystroke by keystroke, like a person would. It types at an uneven speed with pauses, makes typos and fixes them, and can go back with the arrow keys to revise earlier text.

## Run it

Double-click `Cadence.exe`, or run from source (Windows 10/11, Python 3.11+):

```bash
pip install -r requirements.txt
```

```bash
python main.py
```

## Setting up Local AI (optional)

1. Install Ollama from [ollama.com](https://ollama.com/download).
2. Open a terminal and download a model:
   ```bash
   ollama pull llama3.2
   ```
   On a stronger PC (16 GB RAM or a graphics card), this one gives better rewrites:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Keep Ollama running, then click **Check again** in the Humanizer.

Cadence talks to Ollama at `http://localhost:11434`. The model is told to avoid em dashes, heavy comma use and stiff wording, and every paragraph it writes is cleaned by the rule engine afterwards. Text is rewritten one paragraph at a time and appears as it's written. After each paragraph, Cadence checks that every number, quote and name is still there. If the model changed one, it retries once and then falls back to the rule-based engine for that paragraph.

## How the rule-based engine works

Before any rule runs, numbers, dates, names, anything in quotation marks, URLs and emails are locked, so the rules can't touch them. The engine then:

- replaces stock AI phrases from a curated list in [`humanizer/phrases.json`](humanizer/phrases.json), which you can edit to add more;
- swaps stiff, formal words for plain ones ("approximately" → "about", "individuals" → "people");
- replaces em dashes with a period, a comma or parentheses, depending on what follows;
- drops optional commas (after short openers like "Today", the serial comma, short compound sentences);
- adds contractions, except in Formal tone and never at the end of a clause;
- splits long sentences when sentence lengths are too even;
- varies paragraphs that open with the same transition;
- drops a closing sentence that just repeats the opening one, but only if no fact would be lost.

It never swaps words for random synonyms. Reading level and voice matching need Local AI.

## My style

On the **My style** page, paste a few paragraphs you wrote yourself (at least 60 words, ideally 200+) and save them as a style. Cadence measures your habits and shows them while you type: typical sentence length, how often you use contractions, how many commas, whether you start sentences with And/But/So, first person, and how plain your vocabulary is. You can keep several styles, such as essays and emails.

Pick a style under **Your style** in the Humanizer (it works with both engines):
- **Rule-based:** contractions, comma trimming and sentence splitting follow your measured habits. Formal tone still wins over contractions.
- **Local AI:** the model gets your measured habits plus one or two excerpts of your writing as examples to imitate, never to copy.

Styles are saved in `%APPDATA%\CadenceFree\styles.json`.

## Writer basics

| Key | Action |
|---|---|
| F8 | Start, or resume after a pause |
| F9 | Pause |
| F10 | Emergency stop (instant) |

- **Mini mode:** when typing starts, Cadence shrinks into a small always-on-top panel. You can drag it, minimize it to a pill with **–**, reopen the full window with **⤢**, or quit with **✕**. Clicking the panel never takes focus away from the window you're typing into.
- **Focus lock:** typing pauses if the active window changes. Get back with **Alt+Tab** (clicking inside the text would move the cursor), then press F8.
- **Autocorrect:** turn off Word's and Google Docs' autocorrect before typing into them, so they don't "fix" typos before Cadence does.

## Appearance

Cadence opens at a **Compact** size by default. In **Settings → Appearance** you can:

- pick Compact, Comfortable, Large or Extra large;
- turn animations off;
- hide the stat pills;
- choose which page it opens on.

The Writer's advanced settings (Revise later, Pauses & rhythm, Sessions, Safety) start folded. Click a section header to open it; Cadence remembers which ones you left open. It also remembers the window's size and position.

Only one copy of Cadence runs at a time (two would both grab F8–F10). Opening it again brings the existing window to the front.

## Handy extras

- **Typing preview** (Writer → Preview, or Ctrl+P): plays exactly what the Writer will type, inside Cadence, at 1×–20× speed. It shows the typos, the fixes and the arrow-key revisions, and nothing is typed into other apps. Long texts preview their first 2,500 characters.
- **Auto-save:** the Writer text and both Humanizer boxes come back after a restart.
- **History** (Humanizer → History, or Ctrl+H): your last 30 rewrites. Click one to restore it.
- **Files:** open .txt, .md or .docx with **Open** (Ctrl+O) or by dragging the file onto a text box. Save the humanized text as .txt with **Save** (Ctrl+S).
- **Readability:** each Humanizer box shows a reading grade (Flesch-Kincaid), such as "Grade 8 · plain English".
- **Shortcuts:** Ctrl+1–5 switch pages and Ctrl+Enter humanizes. The full list is in Settings.

## Sharing & updates

### Send it to a friend
Run `python release.py <version>` (or `build.bat`) and send the `.exe` it makes. It's about 9 MB, so it fits under Discord's 10 MB upload limit. It's one file and needs no installer.

When they open it, Cadence offers to **install itself**. It goes into their user folder (`%LOCALAPPDATA%\Programs\Cadence`) with a Start menu entry and an optional desktop shortcut. It needs no admin rights and makes no registry changes. **Settings → Install & updates** also has an Uninstall button.

Two warnings they may see, because the exe isn't code-signed (signing costs money):
- **"Windows protected your PC"** (SmartScreen): click **More info → Run anyway**.
- **Antivirus:** some antivirus tools flag apps that simulate keystrokes and use global hotkeys, which is what the Writer does. That's a false positive, but they may need to allow it.

### Turn on updates (one-time setup, about 5 minutes)
Updates come from a GitHub **Releases** page. The repository can be empty; only the releases matter.
1. Make a free account at github.com, then create a new **public** repository, e.g. `cadence`.
2. Build a release that knows where to look:
   ```bash
   python release.py 1.1.0 --repo yourname/cadence
   ```
3. On GitHub, open the repository → **Releases → Draft a new release**. Set the tag to `v1.1.0`, paste the text from `release/v1.1.0-notes.md` (keep the `sha256:` line), attach `release/Cadence-v1.1.0.exe`, and publish.
4. Share that release's download link. Every copy made from this build now checks for updates.

### Publish an update later
```bash
python release.py 1.2.0
```
Then make a new release with tag `v1.2.0` in the same way. Everyone's Cadence offers the update within about a day, or right away with **Settings → Check now**. The app downloads it only from your repo's releases, checks that it's a real Windows program of the right size and matches the `sha256` in the notes, then swaps it in and restarts.

## Build the .exe

```bash
build.bat
```

This produces `dist\Cadence.exe`, a single file with the web UI, Inter font, Lucide icons and phrase dictionary inside.

## Tests

```bash
python -m pytest -q tests
```

The suite covers:

- the typing engine and cursor tracking;
- the rule-based humanizer, including checks that facts survive every strength, tone and many random seeds;
- the Ollama engine, against a fake local server.

## Layout

```
main.py / app.py        pywebview windows + the Python API the page calls
web/                    index.html (main UI), mini.html (mini panel), css/, js/, fonts/
humanizer/              rules.py, phrases.json, ollama.py, diff.py
engine/                 typing engine (planner, typer, typos, revisions, timing)
config/                 settings and presets (saved in %APPDATA%\CadenceFree)
hotkeys.py              global F8/F9/F10
```

Inter is under the SIL Open Font License; Lucide icons are under the ISC License. Both license files are in `web/`.

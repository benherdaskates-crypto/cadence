"""Local AI humanizer through Ollama (https://ollama.com): free, runs on this PC,
no API key. Talks to Ollama's HTTP API at http://localhost:11434.

Text is rewritten one paragraph at a time so small models stay accurate, and
each paragraph is streamed back as it's generated. After each paragraph the
numbers, quotes and names are checked; if the model changed or dropped one,
that paragraph is retried once and otherwise falls back to the rule-based
engine, so facts are never silently altered.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from . import rules
from . import style as style_mod

DEFAULT_HOST = "http://localhost:11434"
PREFERRED = ("qwen2.5:7b", "qwen2.5", "llama3.1:8b", "llama3.2", "llama3.1", "mistral", "gemma2", "phi3")

TONE_GUIDE = {
    "Casual": "relaxed and conversational, like explaining something to a friend; contractions welcome",
    "Neutral": "clear, plain and natural, like a thoughtful person writing an email or blog post",
    "Formal": "polished and professional but still human; fewer contractions, no stiffness",
    "Student essay": "a thoughtful student writing an essay: keep the argument, natural transitions, "
                     "vocabulary a strong student would actually use",
}
STRENGTH_GUIDE = [
    "LIGHT TOUCH: keep the structure and most wording. Only fix what sounds robotic: stock phrases, "
    "formulaic transitions, missing contractions, sentences that are all the same length.",
    "MODERATE: rework sentences freely for flow. Vary sentence length and openings, merge or split "
    "sentences where it reads better.",
    "HEAVY: rewrite in fresh words. You may reorder and restructure sentences within the paragraph, "
    "as long as every point and fact survives.",
]
LEVEL_GUIDE = {
    "Middle school": "short sentences and everyday words a 12-year-old knows",
    "High school": "clear everyday vocabulary with some variety",
    "College": "a fuller vocabulary and some longer sentences, still plain-spoken",
    "Professional": "precise, mature vocabulary without jargon for its own sake",
}

SYSTEM_PROMPT = """You are a humanizer. You rewrite text that sounds stiff, robotic or machine-written so it reads like a real person wrote it, while keeping exactly the same meaning.

Machine-written text has recognizable habits:
- Every sentence is about the same length and shape, giving a flat, even rhythm.
- Overused words and phrases: "delve", "crucial", "furthermore", "moreover", "additionally", "in today's world", "it is important to note", "plays a vital role", "a testament to", "navigate", "landscape", "tapestry", "in conclusion", "overall".
- Overly formal; avoids contractions ("it is", "do not").
- Loves lists of three and perfectly balanced sentences.
- Paragraphs open with a topic sentence and close with a neat summary that restates it.
- Hedges constantly; polished and neutral with no personality.
- A mechanical transition at the start of nearly every paragraph.

Human writing, by contrast:
- Mixes short punchy sentences with longer ones. Occasionally a fragment.
- Uses contractions and plainer, everyday words.
- Varies how sentences and paragraphs begin.
- Uses fewer formal transitions; ideas connect through the content itself.
- Has a little personality and natural rhythm, while staying correct.
- Doesn't summarize itself at the end of every paragraph.

Rules you must follow:
- Keep the exact meaning. Keep every fact, name, number, date and quotation exactly as written. Do not add facts, examples or opinions, and do not remove any.
- Text inside quotation marks must stay word-for-word.
- Never use em dashes (—) or en dashes (–). Use a period, a comma or parentheses instead.
- Go easy on commas. Two short sentences beat one long sentence strung together with commas.
- Unless the tone is Formal, sound relaxed and plain, not corporate or academic. Skip stiff words like "utilize", "individuals", "approximately", "demonstrate", "ensure" and "furthermore".
- No spelling or grammar mistakes.
- Output ONLY the rewritten paragraph. No preamble ("Here is..."), no notes, no quotation marks around it, no headings."""

_PREAMBLE = re.compile(
    r"^\s*(?:(?:sure|certainly|okay|ok|of course)[,!.]?\s*)?"
    r"(?:here(?:'s| is| are)\b[^\n:]*:|(?:the )?rewritten (?:text|paragraph|version)[^\n:]*:|(?:revised|humanized) (?:text|version|paragraph)[^\n:]*:)\s*",
    re.IGNORECASE)
_TRAILER = re.compile(r"\n\s*(?:note|notes|i (?:have|made|kept|changed))\b.*$", re.IGNORECASE | re.DOTALL)


class OllamaError(Exception):
    pass


@dataclass
class Status:
    running: bool
    models: list[str] = field(default_factory=list)
    version: str = ""

    @property
    def default_model(self) -> str | None:
        for pref in PREFERRED:
            for m in self.models:
                if m == pref or m.startswith(pref + ":") or m.split(":")[0] == pref:
                    return m
        return self.models[0] if self.models else None


def host() -> str:
    return os.environ.get("CADENCE_OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def detect(timeout: float = 1.5) -> Status:
    try:
        with urllib.request.urlopen(f"{host()}/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return Status(running=False)
    models = sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))
    version = ""
    try:
        with urllib.request.urlopen(f"{host()}/api/version", timeout=timeout) as r:
            version = json.loads(r.read().decode("utf-8")).get("version", "")
    except (OSError, ValueError):
        pass
    return Status(running=True, models=models, version=version)


def clean_output(text: str) -> str:
    """Strip preambles/notes a model may add despite instructions."""
    t = text.strip()
    t = re.sub(r"^```\w*\n?|```$", "", t).strip()
    t = _PREAMBLE.sub("", t, count=1)
    t = _TRAILER.sub("", t).strip()
    if len(t) > 2 and t[0] in "\"“" and t[-1] in "\"”" and t.count('"') + t.count("“") + t.count("”") == 2:
        t = t[1:-1].strip()
    return t


def must_keep(paragraph: str) -> set[str]:
    """Numbers, quotes and names the rewrite has to contain."""
    out = set(re.findall(r"\d[\d,]*(?:\.\d+)?", paragraph))
    out |= {q for q in re.findall(r'"[^"\n]{1,300}"|“[^”\n]{1,300}”', paragraph)}
    for m in re.finditer(r"\b[A-Z][a-zA-Z'’-]+", paragraph):
        before = paragraph[: m.start()].rstrip(' "“(')
        if before and before[-1] not in ".!?:":
            out.add(m.group())
    return out


def build_user_prompt(paragraph: str, tone: str, strength: int, reading_level: str,
                      voice_sample: str, previous: str | None) -> str:
    parts = [f"Tone: {tone} ({TONE_GUIDE.get(tone, TONE_GUIDE['Neutral'])}).",
             f"Reading level: {reading_level} ({LEVEL_GUIDE.get(reading_level, LEVEL_GUIDE['High school'])}).",
             f"Strength: {STRENGTH_GUIDE[max(0, min(2, strength))]}"]
    if voice_sample.strip():
        parts.append(style_mod.prompt_block(style_mod.analyze(voice_sample), voice_sample))
    if previous:
        parts.append(f"For flow only (already rewritten, do NOT output it):\n<previous>\n{previous}\n</previous>")
    parts.append(f"Rewrite this paragraph:\n<paragraph>\n{paragraph}\n</paragraph>")
    return "\n\n".join(parts)


def _chat_stream(model: str, system: str, user: str, temperature: float, cancel: threading.Event | None,
                 on_delta: Callable[[str], None] | None, timeout: float = 120) -> str:
    body = json.dumps({
        "model": model, "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_ctx": 4096},
    }).encode("utf-8")
    req = urllib.request.Request(f"{host()}/api/chat", data=body, headers={"Content-Type": "application/json"})
    out = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                if cancel is not None and cancel.is_set():
                    raise OllamaError("Cancelled.")
                line = raw.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise OllamaError(msg["error"])
                delta = msg.get("message", {}).get("content", "")
                if delta:
                    out.append(delta)
                    if on_delta:
                        on_delta(delta)
                if msg.get("done"):
                    break
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404:
            raise OllamaError(f"Model “{model}” isn't installed. Run: ollama pull {model}")
        raise OllamaError(f"Ollama error {e.code}: {detail[:200]}")
    except urllib.error.URLError:
        raise OllamaError("Can't reach Ollama. Make sure it's running (open the Ollama app).")
    except TimeoutError:
        raise OllamaError("Ollama took too long to answer.")
    return "".join(out)


def humanize(text: str, model: str, tone: str = "Neutral", strength: int = 1, reading_level: str = "High school",
             voice_sample: str = "", cancel: threading.Event | None = None,
             on_progress: Callable[[int, int], None] | None = None,
             on_delta: Callable[[int, str], None] | None = None,
             on_paragraph: Callable[[int, str], None] | None = None) -> dict:
    """Rewrite `text` paragraph by paragraph.

    on_progress(done, total)       after each paragraph
    on_delta(index, chunk)         streamed tokens of the paragraph being written
    on_paragraph(index, final)     cleaned text of each finished paragraph
    Returns {"text": ..., "fallbacks": n} where fallbacks counts paragraphs that
    were handled by the rule engine because the model changed a fact.
    """
    if not model:
        raise OllamaError("No local model selected.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = text.split("\n")
    work = [i for i, p in enumerate(paras) if p.strip()]
    out = list(paras)
    temperature = (0.5, 0.7, 0.85)[max(0, min(2, strength))]
    profile = style_mod.analyze(voice_sample) if voice_sample.strip() else None
    previous = None
    fallbacks = 0
    for n, i in enumerate(work):
        if cancel is not None and cancel.is_set():
            raise OllamaError("Cancelled.")
        original = paras[i].strip()
        indent = paras[i][: len(paras[i]) - len(paras[i].lstrip())]
        keep = must_keep(original)
        result = None
        missing: set[str] = set()
        for attempt in range(2):
            user = build_user_prompt(original, tone, strength, reading_level, voice_sample, previous)
            if attempt:
                user += ("\n\nYour previous attempt changed or dropped these exact items: "
                         + ", ".join(sorted(missing)) + ". Keep every one of them exactly as written.")
            raw = _chat_stream(model, SYSTEM_PROMPT, user, temperature, cancel,
                               (lambda d, i=i: on_delta(i, d)) if on_delta else None)
            cand = clean_output(raw)
            missing = {k for k in keep if k not in cand}
            if cand and not missing:
                result = cand
                break
        if result is None:   # model kept changing facts: use the safe engine for this paragraph
            result = rules.humanize(original, strength, tone, style=profile).text
            fallbacks += 1
        else:                # safety net: strip dashes/stock phrases/extra commas the model left in
            result = rules.polish(result, strength, tone, style=profile).text
        out[i] = indent + result
        previous = result
        if on_paragraph:
            on_paragraph(i, out[i])
        if on_progress:
            on_progress(n + 1, len(work))
    return {"text": "\n".join(out), "fallbacks": fallbacks}

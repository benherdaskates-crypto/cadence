"""Ollama engine tests against a local fake of Ollama's HTTP API."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from humanizer import ollama
from humanizer.diff import change_ratio, word_diff


class FakeOllama(BaseHTTPRequestHandler):
    models = ["llama3.2:latest", "qwen2.5:7b", "mistral:latest"]
    mode = "good"           # good | preamble | drop_numbers | error404
    requests = []

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": m} for m in self.models]})
        elif self.path == "/api/version":
            self._json({"version": "0.9.0"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        if self.mode == "error404":
            return self._json({"error": f"model '{body['model']}' not found"}, 404)
        user = body["messages"][1]["content"]
        para = re.search(r"<paragraph>\n(.*)\n</paragraph>", user, re.S).group(1)
        reply = para.replace("Furthermore, it", "It").replace("utilize", "use")
        if self.mode == "preamble":
            reply = "Here is the rewritten paragraph:\n\n" + reply + "\n\nNote: I kept all facts."
        if self.mode == "drop_numbers":
            reply = re.sub(r"\d", "", reply)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for k in range(0, len(reply), 7):
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": reply[k:k + 7]}, "done": False}) + "\n").encode())
            self.wfile.flush()
        self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n").encode())


@pytest.fixture
def fake(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CADENCE_OLLAMA_HOST", f"http://127.0.0.1:{srv.server_port}")
    FakeOllama.mode, FakeOllama.requests = "good", []
    yield FakeOllama
    srv.shutdown()


TEXT = ("Furthermore, it is clear that students utilize 3 tools.\n\n"
        "Lincoln High School saw a 23% rise in 2024.\n"
        "Dr. Chen said \"we must utilize what we have.\"")


def test_detect_not_running(monkeypatch):
    monkeypatch.setenv("CADENCE_OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens here
    st = ollama.detect(timeout=0.5)
    assert not st.running and st.models == [] and st.default_model is None


def test_detect_running_and_prefers_better_model(fake):
    st = ollama.detect()
    assert st.running and st.version == "0.9.0"
    assert "llama3.2:latest" in st.models
    assert st.default_model == "qwen2.5:7b"
    fake.models = ["llama3.2:latest", "phi3:mini"]
    assert ollama.detect().default_model == "llama3.2:latest"
    fake.models = ["someothermodel:1b"]
    assert ollama.detect().default_model == "someothermodel:1b"


def test_paragraph_by_paragraph_streaming(fake):
    progress, deltas, done = [], [], []
    res = ollama.humanize(TEXT, "qwen2.5:7b", "Casual", 2, "College", voice_sample="i write short.",
                          on_progress=lambda a, b: progress.append((a, b)),
                          on_delta=lambda i, d: deltas.append(i),
                          on_paragraph=lambda i, t: done.append(i))
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert done == [0, 2, 3] and sorted(set(deltas)) == [0, 2, 3]
    out = res["text"]
    assert out.split("\n")[1] == ""                      # blank line kept
    assert "tudents use 3 tools." in out and "It is clear that" not in out   # polished after the model
    assert '"we must utilize what we have."' in out      # quote untouched
    # The fake model also edits inside the quote, so that paragraph is caught by
    # the fact check and handled by the rule engine instead.
    assert res["fallbacks"] == 1
    req = fake.requests[0]
    assert req["model"] == "qwen2.5:7b" and req["stream"] is True
    assert "humanizer" in req["messages"][0]["content"] and "Output ONLY" in req["messages"][0]["content"]
    user = req["messages"][1]["content"]
    assert "Tone: Casual" in user and "College" in user and "HEAVY" in user and "<example>" in user and "Match the writer" in user
    assert "<previous>" in fake.requests[1]["messages"][1]["content"]


def test_preamble_and_notes_are_stripped(fake):
    fake.mode = "preamble"
    out = ollama.humanize("Furthermore, it is fine.", "llama3.2")["text"]
    assert out in ("It is fine.", "It's fine.")   # preamble/notes gone; polish may contract


@pytest.mark.parametrize("raw,clean", [
    ("Sure! Here's the rewritten text:\nHello there.", "Hello there."),
    ("Here is a more natural version of the paragraph:\n\nHello.", "Hello."),
    ("Rewritten paragraph: Hello.", "Hello."),
    ('"Hello there."', "Hello there."),
    ("```\nHello.\n```", "Hello."),
    ("Hello.\n\nNote: I changed the tone.", "Hello."),
    ('He said "hi" and "bye".', 'He said "hi" and "bye".'),
])
def test_clean_output(raw, clean):
    assert ollama.clean_output(raw) == clean


def test_changed_facts_retry_then_fall_back_to_rules(fake):
    fake.mode = "drop_numbers"
    res = ollama.humanize("Sales grew 45% to $3,200 in 2023. Furthermore, costs fell.", "llama3.2", strength=2)
    assert res["fallbacks"] == 1
    assert len(fake.requests) == 2                      # one retry
    assert "dropped these exact items" in fake.requests[1]["messages"][1]["content"]
    for f in ("45%", "$3,200", "2023"):
        assert f in res["text"]


def test_cancel(fake):
    ev = threading.Event()
    ev.set()
    with pytest.raises(ollama.OllamaError, match="Cancelled"):
        ollama.humanize(TEXT, "llama3.2", cancel=ev)


def test_missing_model_message(fake):
    fake.mode = "error404"
    with pytest.raises(ollama.OllamaError, match="ollama pull qwen2.5:7b"):
        ollama.humanize("Hello there.", "qwen2.5:7b")


def test_unreachable(monkeypatch):
    monkeypatch.setenv("CADENCE_OLLAMA_HOST", "http://127.0.0.1:9")
    with pytest.raises(ollama.OllamaError, match="running"):
        ollama.humanize("Hello there.", "llama3.2")


def test_word_diff_roundtrip():
    a = "Furthermore, we utilize tools daily."
    b = "We use tools every day."
    segs = word_diff(a, b)
    assert "".join(t for op, t in segs if op != "ins") == a
    assert "".join(t for op, t in segs if op != "del") == b
    assert {op for op, _ in segs} == {"eq", "del", "ins"}
    assert change_ratio(a, a) == 0 and change_ratio(a, b) > 0.3


def test_model_output_is_polished(fake):
    fake.mode = "good"
    out = ollama.humanize("The plan worked — mostly. Furthermore, it is cheap.", "llama3.2", strength=1)["text"]
    assert "—" not in out and "Furthermore" not in out
    sysmsg = fake.requests[0]["messages"][0]["content"]
    assert "em dashes" in sysmsg and "commas" in sysmsg

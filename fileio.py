"""Reading .txt/.md/.docx files and writing .txt, with no extra dependencies."""
from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_BYTES = 25 * 1024 * 1024


def read_text_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text.replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def docx_to_text(data: bytes) -> str:
    """Paragraph text from a .docx (body only; tabs and line breaks kept)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(f"{W}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        paras.append("".join(parts))
    text = "\n".join(paras)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def read_any(name: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError("That file is too large (over 25 MB).")
    ext = Path(name).suffix.lower()
    if ext == ".docx":
        try:
            return docx_to_text(data)
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            raise ValueError("Couldn't read that Word file. Try saving it again as .docx or .txt.")
    if ext in (".txt", ".md", ".markdown", ".text", ".csv", ".log", ""):
        return read_text_bytes(data)
    raise ValueError("Cadence can open .txt, .md and .docx files.")


def read_path(path: str) -> str:
    p = Path(path)
    return read_any(p.name, p.read_bytes())


def read_b64(name: str, b64: str) -> str:
    return read_any(name, base64.b64decode(b64))


def write_text(path: str, text: str) -> None:
    """Windows line endings, UTF-8 (opens cleanly in Notepad and Word)."""
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text.replace("\r\n", "\n"))

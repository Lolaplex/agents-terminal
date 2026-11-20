"""Stdlib text extraction from PDF and DOCX payloads.

Deliberately minimal: DOCX paragraphs come from ``word/document.xml`` runs;
PDF text comes from uncompressed/zlib streams' ``Tj``/``TJ`` show operators.
Encrypted, object-stream-only, or image-only PDFs yield whatever parses —
callers get plain text lines, never a crash.
"""

from __future__ import annotations

import re
import zlib
import zipfile
from io import BytesIO


def doc_kind(head: bytes, name: str) -> str | None:
    """``pdf``/``docx`` when head bytes + filename look like that document."""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") and name.lower().endswith(".docx"):
        return "docx"
    return None


class DocumentError(Exception):
    """The payload looked like a document but could not be parsed."""


def extract_text(kind: str, data: bytes) -> str:
    try:
        if kind == "docx":
            return _docx_text(data)
        return _pdf_text(data)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise DocumentError("unreadable document") from exc


def _decode_xml(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def _docx_text(data: bytes) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(BytesIO(data)) as zf:
        with zf.open("word/document.xml") as fh:
            xml = fh.read().decode("utf-8", errors="replace")
    for para in xml.split("</w:p>"):
        line = _decode_xml("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", para)))
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


_HEX_GAP = re.compile(rb"\s+")
_SHOW_OPS = (b"Tj", b"TJ", b"'", b'"')


def _pdf_text(data: bytes) -> str:
    lines: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = match.group(1).rstrip(b"\r\n")
        try:
            body = zlib.decompress(raw)
        except zlib.error:
            body = raw if b"BT" in raw[:4096] else b""
        if not body:
            continue
        lines.extend(_block_text(body))
    return "\n".join(lines)


def _block_text(body: bytes) -> list[str]:
    """Extract shown strings from BT..ET blocks, one line per show op."""
    lines: list[str] = []
    for block in re.finditer(rb"BT(.*?)ET", body, re.S):
        cur: list[str] = []
        buf = block.group(1)
        i = 0
        while i < len(buf):
            c = buf[i]
            if c == 0x28:  # ( literal string
                s, i = _literal(buf, i)
                cur.append(_dec(s))
            elif c == 0x3C and buf[i : i + 2] != b"<<":  # < hex string
                s, i = _hexstr(buf, i)
                cur.append(_dec(s))
            elif buf[i : i + 2] in (b"Tj", b"TJ") or c in (0x27, 0x22):
                if cur:
                    lines.append("".join(cur))
                    cur = []
                i += 2 if buf[i : i + 2] in (b"Tj", b"TJ") else 1
            else:
                i += 1
        if cur:
            lines.append("".join(cur))
    return [ln for ln in lines if ln.strip()]


def _literal(buf: bytes, i: int) -> tuple[bytes, int]:
    """Parse ``(...)`` starting at the open paren; handle escapes + nesting."""
    out = bytearray()
    depth = 0
    i += 1
    while i < len(buf):
        c = buf[i]
        if c == 0x5C and i + 1 < len(buf):
            n = buf[i + 1]
            if n in b"nrtbf":
                out.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[n])
                i += 2
            elif n in (10, 13):
                i += 3 if buf[i + 1 : i + 3] == b"\r\n" else 2
            elif 48 <= n <= 55:
                j = i + 1
                oct_digits = bytearray()
                while j < len(buf) and len(oct_digits) < 3 and 48 <= buf[j] <= 55:
                    oct_digits.append(buf[j])
                    j += 1
                out.append(int(oct_digits, 8) & 0xFF)
                i = j
            else:
                out.append(n)
                i += 2
        elif c == 0x28:
            depth += 1
            out.append(c)
            i += 1
        elif c == 0x29:
            if depth == 0:
                return bytes(out), i + 1
            depth -= 1
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return bytes(out), i


def _hexstr(buf: bytes, i: int) -> tuple[bytes, int]:
    end = buf.find(b">", i + 1)
    if end < 0:
        return b"", len(buf)
    raw = _HEX_GAP.sub(b"", buf[i + 1 : end])
    if len(raw) % 2:
        raw += b"0"
    try:
        data = bytes.fromhex(raw.decode("ascii"))
    except ValueError:
        data = b""
    return data, end + 1


def _dec(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")

"""Document extraction (PDF/DOCX -> text) on read."""

import tempfile
import unittest
import zlib
import zipfile
from pathlib import Path

from agents_terminal.readonly import ReadonlyError, read_file


def _pdf(body_stream: bytes) -> bytes:
    return b"%PDF-1.4\n1 0 obj\nstream\n" + zlib.compress(body_stream) + b"\nendstream\nendobj\n%%EOF\n"


class TestDocRead(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_pdf_tj(self) -> None:
        stream = b"BT /F1 12 Tf 10 10 Td (Hello PDF) Tj (second) Tj ET"
        (self.root / "doc.pdf").write_bytes(_pdf(stream))
        hit = read_file(self.root, "doc.pdf")
        self.assertEqual(hit["encoding"], "pdf")
        self.assertIn("Hello PDF", hit["content"])
        self.assertIn("second", hit["content"])

    def test_pdf_tj_array_and_escapes(self) -> None:
        stream = b"BT (a\\)b) Tj [(x) 20 (y)] TJ ET"
        (self.root / "d2.pdf").write_bytes(_pdf(stream))
        hit = read_file(self.root, "d2.pdf")
        self.assertIn("a)b", hit["content"])
        self.assertIn("xy", hit["content"])

    def test_docx(self) -> None:
        path = self.root / "paper.docx"
        xml = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Second &amp; third</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("word/document.xml", xml)
        hit = read_file(self.root, "paper.docx")
        self.assertEqual(hit["encoding"], "docx")
        self.assertIn("Hello DOCX", hit["content"])
        self.assertIn("Second & third", hit["content"])

    def test_broken_docx_refused(self) -> None:
        (self.root / "bad.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        with self.assertRaises(ReadonlyError):
            read_file(self.root, "bad.docx")


if __name__ == "__main__":
    unittest.main()

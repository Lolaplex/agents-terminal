"""UTF-16 transcode on read."""

import tempfile
import unittest
from pathlib import Path

from agents_terminal.readonly import ReadonlyError, read_file


class TestUtf16Read(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_bom_le(self) -> None:
        (self.root / "u16.txt").write_bytes("one\ntwo\nthree\n".encode("utf-16"))
        hit = read_file(self.root, "u16.txt")
        self.assertEqual(hit["encoding"], "utf-16-le")
        self.assertEqual(hit["content"].splitlines(), ["one", "two", "three"])

    def test_bom_be(self) -> None:
        (self.root / "u16be.txt").write_bytes("alpha\nbeta\n".encode("utf-16-be"))
        data = (self.root / "u16be.txt").read_bytes()
        (self.root / "u16be.txt").write_bytes(b"\xfe\xff" + data)
        hit = read_file(self.root, "u16be.txt")
        self.assertEqual(hit["encoding"], "utf-16-be")
        self.assertIn("beta", hit["content"])

    def test_heuristic_no_bom(self) -> None:
        text = "first line\nsecond line\nthird line\n"
        (self.root / "nobom.txt").write_bytes(text.encode("utf-16-le"))
        hit = read_file(self.root, "nobom.txt")
        self.assertEqual(hit["encoding"], "utf-16-le")
        self.assertIn("second line", hit["content"])

    def test_offset_limit_on_transcoded(self) -> None:
        (self.root / "u16.txt").write_bytes("l1\nl2\nl3\n".encode("utf-16"))
        hit = read_file(self.root, "u16.txt", offset=2, limit=1)
        self.assertEqual(hit["content"].strip(), "l2")

    def test_short_binary_still_rejected(self) -> None:
        (self.root / "bin.dat").write_bytes(b"hello\x00")
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "bin.dat")
        self.assertEqual(ctx.exception.message, "binary file")

    def test_utf8_unchanged(self) -> None:
        (self.root / "plain.txt").write_text("a\nb\n", encoding="utf-8")
        hit = read_file(self.root, "plain.txt")
        self.assertEqual(hit["encoding"], "utf-8")


if __name__ == "__main__":
    unittest.main()

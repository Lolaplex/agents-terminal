"""Mutating write and edit commands and their side-effect metadata."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase, mock, skipUnless

from agents_terminal.__main__ import main
from agents_terminal.manifest import help_json
from agents_terminal.mutate import edit_file, format_edit, format_write, write_file
from agents_terminal.readonly import ReadonlyError


def _can_symlink() -> bool:
    if getattr(os, "symlink", None) is None:
        return False
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        try:
            os.symlink(tmp / "a", tmp / "b")
        except (OSError, NotImplementedError):
            return False
    return True


_SYMLINK_OK = _can_symlink()
_SYMLINK_SKIP = "os.symlink unavailable (Windows needs Developer Mode or admin; WinError 1314)"


class TestWrite(TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "ws"
        self.root.mkdir()
        self.outside = Path(self._td.name) / "outside"
        self.outside.mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_new_file(self) -> None:
        result = write_file(self.root, "a.txt", "hello\nworld\n")
        self.assertTrue(result["created"])
        self.assertEqual(result["path"], "a.txt")
        self.assertEqual(result["lines"], 2)
        self.assertEqual(result["bytes"], len(b"hello\nworld\n"))
        self.assertEqual((self.root / "a.txt").read_bytes(), b"hello\nworld\n")
        self.assertEqual(format_write(result), "wrote a.txt (2 lines, 12 bytes)\n")

    def test_overwrite(self) -> None:
        write_file(self.root, "a.txt", "one\n")
        result = write_file(self.root, "a.txt", "two\nthree\n")
        self.assertFalse(result["created"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"two\nthree\n")

    def test_create_only_existing(self) -> None:
        (self.root / "a.txt").write_bytes(b"keep\n")
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "a.txt", "new\n", create_only=True)
        self.assertEqual(ctx.exception.message, "exists")
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"keep\n")

    def test_create_only_missing(self) -> None:
        result = write_file(self.root, "a.txt", "new\n", create_only=True)
        self.assertTrue(result["created"])

    def test_parent_dirs_created(self) -> None:
        result = write_file(self.root, "sub/deep/a.txt", "x\n")
        self.assertEqual(result["path"], "sub/deep/a.txt")
        self.assertEqual((self.root / "sub" / "deep" / "a.txt").read_bytes(), b"x\n")

    def test_dotdot_escape_rejected(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "../escape.txt", "x")
        self.assertEqual(ctx.exception.message, "path escapes workspace root")
        self.assertFalse((Path(self._td.name) / "escape.txt").exists())

    def test_absolute_outside_rejected(self) -> None:
        target = self.outside / "escape.txt"
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, str(target), "x")
        self.assertEqual(ctx.exception.message, "path escapes workspace root")
        self.assertFalse(target.exists())

    def test_crlf_preserved(self) -> None:
        (self.root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        write_file(self.root, "a.txt", "x\ny\n")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"x\r\ny\r\n")

    def test_new_file_uses_lf(self) -> None:
        write_file(self.root, "a.txt", "x\r\ny\r\n")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"x\ny\n")

    def test_directory_target_rejected(self) -> None:
        (self.root / "sub").mkdir()
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "sub", "x")
        self.assertEqual(ctx.exception.message, "not a file")
        self.assertTrue((self.root / "sub").is_dir())

    def test_binary_target_rejected(self) -> None:
        (self.root / "bin.dat").write_bytes(b"a\x00b")
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "bin.dat", "x")
        self.assertEqual(ctx.exception.message, "binary file")
        self.assertEqual((self.root / "bin.dat").read_bytes(), b"a\x00b")

    @skipUnless(_SYMLINK_OK, _SYMLINK_SKIP)
    def test_symlink_target_rejected(self) -> None:
        (self.outside / "secret.txt").write_bytes(b"secret\n")
        os.symlink(self.outside / "secret.txt", self.root / "link")
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "link", "x")
        self.assertEqual(ctx.exception.message, "path escapes workspace root")
        self.assertEqual((self.outside / "secret.txt").read_bytes(), b"secret\n")

    @skipUnless(_SYMLINK_OK, _SYMLINK_SKIP)
    def test_symlinked_parent_outside_rejected(self) -> None:
        os.symlink(self.outside, self.root / "linkdir")
        with self.assertRaises(ReadonlyError) as ctx:
            write_file(self.root, "linkdir/a.txt", "x")
        self.assertEqual(ctx.exception.message, "path escapes workspace root")
        self.assertFalse((self.outside / "a.txt").exists())


class TestEdit(TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "ws"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_single_hit(self) -> None:
        (self.root / "a.txt").write_bytes(b"hello\nworld\n")
        result = edit_file(self.root, "a.txt", old="world", new="klanker")
        self.assertEqual(result["replacements"], 1)
        self.assertEqual(result["first_line"], 2)
        self.assertEqual(result["last_line"], 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"hello\nklanker\n")
        self.assertIn("+klanker", result["diff"])
        self.assertIn("edited a.txt: 1 replacement(s), lines 2-2", format_edit(result))

    def test_zero_hits(self) -> None:
        (self.root / "a.txt").write_bytes(b"hello\n")
        with self.assertRaises(ReadonlyError) as ctx:
            edit_file(self.root, "a.txt", old="missing", new="x")
        self.assertEqual(ctx.exception.message, "old text not found")
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"hello\n")

    def test_multiple_hits_without_replace_all(self) -> None:
        (self.root / "a.txt").write_bytes(b"x\nx\n")
        with self.assertRaises(ReadonlyError) as ctx:
            edit_file(self.root, "a.txt", old="x", new="y")
        self.assertEqual(ctx.exception.message, "old text matches 2 times; add context or pass --replace-all")
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"x\nx\n")

    def test_multiple_hits_with_replace_all(self) -> None:
        (self.root / "a.txt").write_bytes(b"x\nx\n")
        result = edit_file(self.root, "a.txt", old="x", new="y", replace_all=True)
        self.assertEqual(result["replacements"], 2)
        self.assertEqual(result["first_line"], 1)
        self.assertEqual(result["last_line"], 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"y\ny\n")

    def test_crlf_file_with_lf_old(self) -> None:
        (self.root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        result = edit_file(self.root, "a.txt", old="two", new="three")
        self.assertEqual(result["first_line"], 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"one\r\nthree\r\n")

    def test_mixed_line_endings_are_preserved(self) -> None:
        (self.root / "a.txt").write_bytes(b"one\r\ntwo\nthree\r\n")
        edit_file(self.root, "a.txt", old="two", new="TWO")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"one\r\nTWO\nthree\r\n")

    def test_exact_match_wins_over_normalized(self) -> None:
        # The LF form appears once literally and twice after normalization.
        (self.root / "a.txt").write_bytes(b"a\r\nb\r\na\nb\n")
        result = edit_file(self.root, "a.txt", old="a\nb", new="A\nB")
        self.assertEqual(result["replacements"], 1)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"a\r\nb\r\nA\nB\n")

    def test_crlf_old_against_lf_file(self) -> None:
        (self.root / "a.txt").write_bytes(b"one\ntwo\n")
        edit_file(self.root, "a.txt", old="one\r\ntwo", new="ONE\r\nTWO")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"ONE\nTWO\n")

    def test_replace_all_keeps_mixed_endings(self) -> None:
        (self.root / "a.txt").write_bytes(b"x\r\nx\n")
        result = edit_file(self.root, "a.txt", old="x", new="y", replace_all=True)
        self.assertEqual(result["replacements"], 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"y\r\ny\n")

    def test_multiline_edit(self) -> None:
        (self.root / "a.txt").write_bytes(b"a\nb\nc\n")
        result = edit_file(self.root, "a.txt", old="a\nb", new="a\nB\nb")
        self.assertEqual(result["first_line"], 1)
        self.assertEqual(result["last_line"], 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"a\nB\nb\nc\n")

    def test_empty_old_is_usage_error(self) -> None:
        (self.root / "a.txt").write_bytes(b"a\n")
        with self.assertRaises(ReadonlyError) as ctx:
            edit_file(self.root, "a.txt", old="", new="x")
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"a\n")

    def test_binary_file_rejected(self) -> None:
        (self.root / "bin.dat").write_bytes(b"a\x00b")
        with self.assertRaises(ReadonlyError) as ctx:
            edit_file(self.root, "bin.dat", old="a", new="x")
        self.assertEqual(ctx.exception.message, "binary file")
        self.assertEqual((self.root / "bin.dat").read_bytes(), b"a\x00b")

    def test_missing_file(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            edit_file(self.root, "missing.txt", old="a", new="b")
        self.assertEqual(ctx.exception.message, "not found")


class TestManifestMutate(TestCase):
    def test_write_and_edit_are_mutating(self) -> None:
        commands = help_json()["commands"]
        for name in ("write", "edit"):
            spec = commands[name]
            self.assertEqual(spec["side_effects"], "mutating")
            self.assertTrue(spec["mutates"])
            self.assertFalse(spec["annotations"]["readOnlyHint"])
            self.assertTrue(spec["annotations"]["destructiveHint"])
            self.assertFalse(spec["annotations"]["idempotentHint"])
            self.assertFalse(spec["annotations"]["openWorldHint"])
            self.assertIn("path", spec["parameters"]["required"])
        for name in ("list", "read", "grep", "stat"):
            self.assertEqual(commands[name]["side_effects"], "read-only")


class TestCliMutate(TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "ws"
        self.root.mkdir()
        self.env = {
            "AGENTS_WORKSPACE_DIR": str(self.root),
            "AGENTS_TERMINAL_POLICY": "",
            "AGENTS_TERMINAL_DRIVER": "subprocess",
            "AGENTS_NO_UPDATE_CHECK": "1",
        }

    def tearDown(self) -> None:
        self._td.cleanup()

    def _run(self, argv: list[str], stdin: str = "") -> tuple[int, str, str]:
        out = StringIO()
        err = StringIO()
        with mock.patch.dict(os.environ, self.env, clear=False):
            with mock.patch("sys.stdin", StringIO(stdin)):
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_write_then_edit_then_read(self) -> None:
        code, out, err = self._run(["write", "a.txt", "--content", "hello\nworld\n"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, "wrote a.txt (2 lines, 12 bytes)\n")
        code, out, err = self._run(["edit", "a.txt", "--old", "world", "--new", "klanker"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("+klanker", out)
        self.assertIn("edited a.txt: 1 replacement(s), lines 2-2", out)
        code, out, _err = self._run(["read", "a.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "hello\nklanker\n")

    def test_write_from_stdin_and_json(self) -> None:
        code, out, _err = self._run(["write", "a.txt", "--stdin", "--json"], stdin="x\ny\n")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload, {"path": "a.txt", "created": True, "lines": 2, "bytes": 4})

    def test_write_requires_exactly_one_source(self) -> None:
        code, out, err = self._run(["write", "a.txt"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("exactly one", err)
        code, _out, err = self._run(["write", "a.txt", "--content", "x", "--stdin"], stdin="y")
        self.assertEqual(code, 2)
        self.assertIn("exactly one", err)
        self.assertFalse((self.root / "a.txt").exists())

    def test_edit_stdin_json_multiline(self) -> None:
        self._run(["write", "a.txt", "--content", "a\nb\nc\n"])
        code, out, err = self._run(
            ["edit", "a.txt", "--stdin-json", "--json"],
            stdin=json.dumps({"old": "a\nb", "new": "a\nB\nb"}),
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["replacements"], 1)
        self.assertEqual(payload["first_line"], 1)
        self.assertEqual(payload["last_line"], 2)
        self.assertIn("+B", payload["diff"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"a\nB\nb\nc\n")

    def test_edit_rejects_both_sources(self) -> None:
        self._run(["write", "a.txt", "--content", "a\n"])
        code, _out, err = self._run(
            ["edit", "a.txt", "--old", "a", "--new", "b", "--stdin-json"],
            stdin=json.dumps({"old": "a", "new": "b"}),
        )
        self.assertEqual(code, 2)
        self.assertIn("not both", err)
        self.assertEqual((self.root / "a.txt").read_bytes(), b"a\n")

    def test_edit_requires_arguments(self) -> None:
        self._run(["write", "a.txt", "--content", "a\n"])
        code, _out, err = self._run(["edit", "a.txt"])
        self.assertEqual(code, 2)
        self.assertIn("--old", err)

    def test_escape_is_exit_one_and_writes_nothing(self) -> None:
        code, out, err = self._run(["write", "../escape.txt", "--content", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "path escapes workspace root\n")
        self.assertFalse((Path(self._td.name) / "escape.txt").exists())

    def test_edit_failure_leaves_file_unchanged(self) -> None:
        self._run(["write", "a.txt", "--content", "x\nx\n"])
        code, out, err = self._run(["edit", "a.txt", "--old", "x", "--new", "y"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "old text matches 2 times; add context or pass --replace-all\n")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"x\nx\n")

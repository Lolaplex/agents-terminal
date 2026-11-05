"""Read-only filesystem commands and their side-effect metadata."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase, mock

from agents_terminal import __version__
from agents_terminal.__main__ import main
from agents_terminal.manifest import CLASSIFICATION, help_json
from agents_terminal.policy import Policy
from agents_terminal.readonly import (
    ReadonlyError,
    _open_regular,
    format_read,
    grep_files,
    list_directory,
    read_file,
    stat_path,
)

_SECRET = "TOP-SECRET-CONTENTS"


def _snapshot(root: Path) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            link = os.readlink(path) if stat.S_ISLNK(st.st_mode) else None
            data = b""
            if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                data = path.read_bytes()
            rows.append((str(path.relative_to(root)), st.st_mode, st.st_size, st.st_mtime_ns, link, data))
    return rows


class TestPathSafety(TestCase):
    def setUp(self) -> None:
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.root = self.tmp / "ws"
        self.evil = self.tmp / "ws-evil"
        self.outside = self.tmp / "outside"
        self.root.mkdir()
        self.evil.mkdir()
        self.outside.mkdir()
        (self.root / "ok.txt").write_text("hello\nworld\n", encoding="utf-8")
        (self.root / "ws-evil").mkdir()
        (self.root / "ws-evil" / "ok.txt").write_text("inside\n", encoding="utf-8")
        (self.evil / "x.txt").write_text(_SECRET, encoding="utf-8")
        (self.outside / "secret.txt").write_text(_SECRET, encoding="utf-8")
        os.symlink(Path("..") / "outside" / "secret.txt", self.root / "leak")
        os.symlink(self.outside, self.root / "leakdir")
        os.symlink(self.root / "ok.txt", self.root / "inside-link")
        self.before = _snapshot(self.root)
        self.evil_before = _snapshot(self.evil)
        self.outside_before = _snapshot(self.outside)

    def tearDown(self) -> None:
        self.assertEqual(_snapshot(self.root), self.before)
        self.assertEqual(_snapshot(self.evil), self.evil_before)
        self.assertEqual(_snapshot(self.outside), self.outside_before)
        self._td.cleanup()

    def test_relative_and_absolute_reads_stay_inside(self) -> None:
        rel = read_file(self.root, "ok.txt", offset=1, limit=1)
        abs_hit = read_file(self.root, str(self.root / "ok.txt"), offset=2, limit=1)
        nested = read_file(self.root, "ws-evil/ok.txt")
        via_link = read_file(self.root, "inside-link")
        self.assertEqual(rel["content"], "hello\n")
        self.assertTrue(rel["truncated"])
        self.assertEqual(abs_hit["content"], "world\n")
        self.assertEqual(abs_hit["path"], "ok.txt")
        self.assertEqual(nested["content"], "inside\n")
        self.assertEqual(via_link["content"], "hello\nworld\n")
        dotted = read_file(self.root, "ws-evil/../ok.txt", offset=1, limit=1)
        self.assertEqual(dotted["content"], "hello\n")

    def test_escape_attempts_are_rejected(self) -> None:
        escapes = [
            "../ws-evil/x.txt",
            str(self.evil / "x.txt"),
            "leak",
            "leakdir",
            "leakdir/secret.txt",
            "nope/../../ws-evil/x.txt",
        ]
        # stat describes a symlink node that lives inside the root.
        stat_escapes = [item for item in escapes if item not in {"leak", "leakdir"}]
        ops = (
            read_file,
            list_directory,
            lambda root, path: grep_files(root, "x", path),
            stat_path,
        )
        for user_path in escapes:
            for op in ops:
                if op is stat_path and user_path not in stat_escapes:
                    continue
                with self.subTest(path=user_path, op=getattr(op, "__name__", "grep")):
                    with self.assertRaises(ReadonlyError) as ctx:
                        op(self.root, user_path)
                    self.assertEqual(ctx.exception.message, "path escapes workspace root")
                    self.assertNotIn(_SECRET, ctx.exception.message)
        for user_path in ("ok.txt\x00", "ok.txt\n"):
            for op in ops:
                with self.subTest(path=repr(user_path), op=getattr(op, "__name__", "grep")):
                    with self.assertRaises(ReadonlyError) as ctx:
                        op(self.root, user_path)
                    self.assertEqual(ctx.exception.message, "invalid path")
                    self.assertEqual(ctx.exception.code, 2)

    def test_stat_describes_symlink_without_reading_target(self) -> None:
        described = stat_path(self.root, "leak")
        blob = json.dumps(described)
        self.assertEqual(described["type"], "symlink")
        self.assertEqual(described["target"], os.readlink(self.root / "leak"))
        self.assertNotIn(_SECRET, blob)

    def test_list_does_not_descend_into_escaped_symlink(self) -> None:
        listed = list_directory(self.root, ".")
        names = [entry["name"] for entry in listed["entries"]]
        self.assertIn("leakdir", names)
        self.assertNotIn("secret.txt", names)
        self.assertNotIn(".", names)
        self.assertNotIn("..", names)
        leak = next(entry for entry in listed["entries"] if entry["name"] == "leak")
        self.assertEqual(leak["type"], "symlink")
        self.assertNotIn(_SECRET, json.dumps(listed))

    def test_grep_skips_symlink_dirs_and_files(self) -> None:
        (self.root / "note.txt").write_text("visible-token\n", encoding="utf-8")
        self.before = _snapshot(self.root)
        found = grep_files(self.root, "TOP-SECRET")
        self.assertEqual(found["matches"], [])
        found_ok = grep_files(self.root, "visible-token")
        self.assertEqual([hit["path"] for hit in found_ok["matches"]], ["note.txt"])

    def test_missing_path_is_not_created(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "missing/nope.txt")
        self.assertEqual(ctx.exception.message, "not found")
        self.assertFalse((self.root / "missing").exists())

    def test_missing_root_is_not_created(self) -> None:
        missing = self.tmp / "absent"
        with self.assertRaises(ReadonlyError) as ctx:
            list_directory(missing, ".")
        self.assertEqual(ctx.exception.message, "not found")
        self.assertFalse(missing.exists())

    def test_symlink_workspace_root_still_confines(self) -> None:
        link = self.tmp / "link-ws"
        os.symlink(self.root, link)
        hit = read_file(link, str(link / "ok.txt"), offset=1, limit=1)
        self.assertEqual(hit["content"], "hello\n")
        self.assertEqual(hit["path"], "ok.txt")
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(link, str(self.outside / "secret.txt"))
        self.assertEqual(ctx.exception.message, "path escapes workspace root")

    def test_component_open_does_not_follow_symlink(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "f.txt").write_text("inside\n", encoding="utf-8")
        os.symlink(nested, self.root / "linksub")
        self.before = _snapshot(self.root)
        followed = read_file(self.root, "linksub/f.txt")
        self.assertEqual(followed["content"], "inside\n")
        self.assertEqual(followed["path"], "nested/f.txt")
        from agents_terminal.readonly import _open_under

        with self.assertRaises(ReadonlyError) as ctx:
            _open_under(self.root.resolve(), self.root / "linksub" / "f.txt", directory=False)
        self.assertEqual(ctx.exception.message, "path escapes workspace root")

    def test_open_does_not_follow_final_symlink(self) -> None:
        self.assertTrue(hasattr(os, "O_NOFOLLOW"))
        with self.assertRaises(ReadonlyError) as ctx:
            with _open_regular(self.root / "leak"):
                pass
        self.assertEqual(ctx.exception.message, "path escapes workspace root")

    def test_fifo_and_directory_are_not_files(self) -> None:
        os.mkfifo(self.root / "pipe")
        self.before = _snapshot(self.root)
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "pipe")
        self.assertEqual(ctx.exception.message, "not a file")
        with self.assertRaises(ReadonlyError) as ctx:
            grep_files(self.root, "x", "pipe")
        self.assertEqual(ctx.exception.message, "not a file")
        self.assertEqual(stat_path(self.root, "pipe")["type"], "other")
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, ".")
        self.assertEqual(ctx.exception.message, "not a file")
        with self.assertRaises(ReadonlyError) as ctx:
            list_directory(self.root, "ok.txt")
        self.assertEqual(ctx.exception.message, "not a directory")

    def test_operations_do_not_write_or_spawn(self) -> None:
        real_open = os.open

        def guard(path: int | str | bytes, flags: int, *args: object, **kwargs: object) -> int:
            write_bits = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
            if flags & write_bits:
                raise AssertionError(f"write open flags={flags:#x}")
            return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

        blocked = [
            "subprocess.Popen",
            "subprocess.run",
            "os.remove",
            "os.unlink",
            "os.rename",
            "os.replace",
            "os.mkdir",
            "os.makedirs",
            "os.chmod",
            "os.truncate",
        ]
        with mock.patch("agents_terminal.readonly.os.open", guard):
            patches = [mock.patch(name, side_effect=AssertionError(name)) for name in blocked]
            for patcher in patches:
                patcher.start()
            try:
                list_directory(self.root, ".")
                read_file(self.root, "ok.txt")
                grep_files(self.root, "hello")
                stat_path(self.root, "ok.txt")
                stat_path(self.root, "leak")
            finally:
                for patcher in patches:
                    patcher.stop()


class TestReadAndSearch(TestCase):
    def setUp(self) -> None:
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "lines.txt").write_bytes(b"a\nb\nc")
        (self.root / "dots.txt").write_text("a\n.\n", encoding="utf-8")
        (self.root / "case.txt").write_text("Hello\n", encoding="utf-8")
        (self.root / "bin.dat").write_bytes(b"hello\x00")
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("token\n", encoding="utf-8")
        (self.root / "note.txt").write_text("token\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_offset_limit_and_eof(self) -> None:
        mid = read_file(self.root, "lines.txt", offset=2, limit=1)
        self.assertEqual(mid["content"], "b\n")
        self.assertEqual(mid["line_count"], 1)
        self.assertTrue(mid["truncated"])
        tail = read_file(self.root, "lines.txt", offset=3, limit=5)
        self.assertEqual(tail["content"], "c")
        self.assertFalse(tail["truncated"])
        past = read_file(self.root, "lines.txt", offset=9, limit=1)
        self.assertEqual(past["content"], "")
        self.assertFalse(past["truncated"])
        self.assertEqual(format_read(mid), "b\n")

    def test_binary_file_is_rejected(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "bin.dat")
        self.assertEqual(ctx.exception.message, "binary file")
        self.assertEqual((self.root / "bin.dat").read_bytes(), b"hello\x00")

    def test_usage_bounds(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "lines.txt", offset=0, limit=1)
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(ReadonlyError) as ctx:
            read_file(self.root, "lines.txt", offset=1, limit=0)
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(ReadonlyError) as ctx:
            grep_files(self.root, "", "lines.txt")
        self.assertEqual(ctx.exception.message, "empty pattern")
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(ReadonlyError) as ctx:
            grep_files(self.root, "[", "lines.txt")
        self.assertEqual(ctx.exception.message, "invalid pattern")
        self.assertEqual(ctx.exception.code, 2)

    def test_grep_literal_glob_case_and_max(self) -> None:
        literal = grep_files(self.root, ".", "dots.txt", literal=True)
        regex = grep_files(self.root, ".", "dots.txt", literal=False)
        self.assertEqual([hit["line"] for hit in literal["matches"]], [2])
        self.assertEqual([hit["line"] for hit in regex["matches"]], [1, 2])
        folded = grep_files(self.root, "hello", "case.txt", ignore_case=True)
        self.assertEqual(folded["matches"][0]["text"], "Hello")
        plain = grep_files(self.root, "hello", "case.txt")
        self.assertEqual(plain["matches"], [])
        globbed = grep_files(self.root, "token", ".", glob="*.py")
        self.assertEqual([hit["path"] for hit in globbed["matches"]], ["sub/c.py"])
        capped = grep_files(self.root, ".", "dots.txt", max_matches=1)
        self.assertEqual(len(capped["matches"]), 1)
        self.assertTrue(capped["truncated"])
        exact = grep_files(self.root, "token", "note.txt", max_matches=1)
        self.assertEqual(len(exact["matches"]), 1)
        self.assertFalse(exact["truncated"])
        walked = grep_files(self.root, "hello", ".")
        self.assertEqual([hit["path"] for hit in walked["matches"]], [])
        skipped = grep_files(self.root, "token", ".")
        self.assertEqual(sorted(hit["path"] for hit in skipped["matches"]), ["note.txt", "sub/c.py"])

    def test_direct_binary_grep_errors(self) -> None:
        with self.assertRaises(ReadonlyError) as ctx:
            grep_files(self.root, "hello", "bin.dat")
        self.assertEqual(ctx.exception.message, "binary file")

    def test_stat_file_and_root(self) -> None:
        described = stat_path(self.root, "lines.txt")
        self.assertEqual(described["type"], "file")
        self.assertEqual(described["size"], len(b"a\nb\nc"))
        self.assertIsNone(described["target"])
        self.assertRegex(described["mode"], r"^[0-7]{4}$")
        self.assertRegex(described["mtime"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        root_stat = stat_path(self.root, ".")
        self.assertEqual(root_stat["path"], ".")
        self.assertEqual(root_stat["type"], "dir")
        abs_root = stat_path(self.root, str(self.root))
        self.assertEqual(abs_root["path"], ".")
        self.assertEqual(abs_root["type"], "dir")


class TestManifest(TestCase):
    def test_side_effects_are_consistent(self) -> None:
        data = help_json()
        self.assertEqual(data["name"], "agents-terminal")
        self.assertEqual(data["version"], __version__)
        self.assertEqual(data["classification"]["field"], "side_effects")
        self.assertEqual(data["classification"]["enum"], ["read-only", "mutating"])
        self.assertEqual(data["classification"]["boolean_field"], "mutates")
        self.assertEqual(data["classification"]["annotation"], "annotations.readOnlyHint")
        self.assertEqual(CLASSIFICATION["enum"], ["read-only", "mutating"])
        commands = data["commands"]
        self.assertEqual(set(commands), {"list", "read", "grep", "stat", "run"})
        for name, spec in commands.items():
            side = spec["side_effects"]
            self.assertIn(side, ("read-only", "mutating"))
            read_only = side == "read-only"
            self.assertEqual(spec["mutates"], not read_only)
            ann = spec["annotations"]
            self.assertEqual(set(ann), {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"})
            self.assertEqual(ann["readOnlyHint"], read_only)
            self.assertEqual(ann["destructiveHint"], not read_only)
            self.assertEqual(ann["idempotentHint"], read_only)
            self.assertIs(spec["parameters"]["additionalProperties"], False)
            json.dumps(spec)
        for name in ("list", "read", "grep", "stat"):
            self.assertEqual(commands[name]["side_effects"], "read-only")
            self.assertFalse(commands[name]["annotations"]["openWorldHint"])
        self.assertEqual(commands["run"]["side_effects"], "mutating")
        self.assertTrue(commands["run"]["mutates"])
        self.assertTrue(commands["run"]["annotations"]["openWorldHint"])
        self.assertEqual(commands["grep"]["aliases"], ["search"])
        self.assertEqual(commands["read"]["parameters"]["properties"]["offset"]["default"], 1)
        self.assertIn("path", commands["read"]["parameters"]["required"])
        self.assertIn("pattern", commands["grep"]["parameters"]["required"])
        self.assertIn("argv", commands["run"]["parameters"]["required"])

    def test_metadata_doc_names_the_field(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "abi" / "METADATA.md").read_text(encoding="utf-8")
        self.assertIn("side_effects", text)
        self.assertIn("read-only", text)
        self.assertIn("mutating", text)
        self.assertIn("annotations.readOnlyHint", text)
        self.assertIn("`mutates`", text)
        self.assertIn("Do not infer the class from the command name.", text)
        self.assertIn("Missing `side_effects` metadata means mutating.", text)

    def test_missing_side_effects_means_mutating(self) -> None:
        from agents_terminal.manifest import effective_side_effects, is_mutating

        unlabeled = (
            None,
            [],
            {},
            {"mutates": False},
            {"annotations": {"readOnlyHint": True}},
            {"mutates": False, "annotations": {"readOnlyHint": True}},
            {"side_effects": "nope"},
            {"side_effects": "mutating"},
            {"side_effects": ""},
        )
        for spec in unlabeled:
            with self.subTest(spec=spec):
                self.assertTrue(is_mutating(spec))
                self.assertEqual(effective_side_effects(spec), "mutating")
        self.assertFalse(is_mutating({"side_effects": "read-only", "mutates": True}))
        self.assertEqual(effective_side_effects({"side_effects": "read-only"}), "read-only")
        data = help_json()
        self.assertEqual(data["classification"]["missing"], "mutating")
        self.assertIn("Missing side_effects metadata means mutating.", data["classification"]["description"])
        for spec in data["commands"].values():
            self.assertIn(spec["side_effects"], ("read-only", "mutating"))
            self.assertEqual(is_mutating(spec), spec["side_effects"] != "read-only")


class TestCli(TestCase):
    def setUp(self) -> None:
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "ws"
        self.root.mkdir()
        (self.root / "ok.txt").write_text("one\ntwo\n", encoding="utf-8")
        self.env = {
            "AGENTS_WORKSPACE_DIR": str(self.root),
            "AGENTS_TERMINAL_POLICY": "",
            "AGENTS_TERMINAL_DRIVER": "subprocess",
            "AGENTS_NO_UPDATE_CHECK": "1",
        }

    def tearDown(self) -> None:
        self._td.cleanup()

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out = StringIO()
        err = StringIO()
        with mock.patch.dict(os.environ, self.env, clear=False):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_read_list_grep_stat_and_search_alias(self) -> None:
        code, out, err = self._run(["read", "ok.txt", "--offset", "1", "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "one\n")
        self.assertEqual(err, "truncated\n")
        code, out, err = self._run(["read", "ok.txt", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["content"], "one\ntwo\n")
        self.assertFalse(payload["truncated"])
        code, out, _err = self._run(["list", "--json"])
        listed = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual([entry["name"] for entry in listed["entries"]], ["ok.txt"])
        code, out, _err = self._run(["grep", "two", "--literal"])
        self.assertEqual(code, 0)
        self.assertIn("ok.txt:2:two", out)
        code, out, _err = self._run(["search", "two"])
        self.assertEqual(code, 0)
        self.assertIn("ok.txt:2:two", out)
        code, out, _err = self._run(["stat", "ok.txt"])
        self.assertEqual(code, 0)
        self.assertIn("type: file", out)
        self.assertIn("path: ok.txt", out)

    def test_escape_and_missing_root_do_not_create_files(self) -> None:
        outside = self.root.parent / "secret.txt"
        outside.write_text(_SECRET, encoding="utf-8")
        os.symlink(outside, self.root / "leak")
        before = _snapshot(self.root)
        code, out, err = self._run(["read", "leak"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "path escapes workspace root\n")
        self.assertEqual(_snapshot(self.root), before)
        self.assertEqual(outside.read_text(encoding="utf-8"), _SECRET)
        missing = self.root.parent / "missing-root"
        self.env["AGENTS_WORKSPACE_DIR"] = str(missing)
        code, out, err = self._run(["list"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "not found\n")
        self.assertFalse(missing.exists())

    def test_read_only_commands_do_not_call_run(self) -> None:
        with mock.patch("agents_terminal.__main__.run_command", side_effect=AssertionError("run")):
            code, out, _err = self._run(["stat", "--json", "ok.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["type"], "file")

    def test_run_still_executes_and_help_json_classifies_it(self) -> None:
        code, out, _err = self._run(["run", "--", "echo", "hi"])
        self.assertEqual(code, 0)
        self.assertIn("hi", out)
        code, out, _err = self._run(["--help-json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["commands"]["run"]["side_effects"], "mutating")
        self.assertEqual(data["commands"]["read"]["side_effects"], "read-only")
        code, _out, err = self._run(["run"])
        self.assertEqual(code, 2)
        self.assertIn("argv", err)

    def test_help_json_subprocess(self) -> None:
        env = os.environ.copy()
        env.update(self.env)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[1] / "src"), env.get("PYTHONPATH", "")]
        )
        proc = subprocess.run(
            [sys.executable, "-m", "agents_terminal", "--help-json"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["commands"]["stat"]["mutates"], False)
        self.assertTrue(data["commands"]["stat"]["annotations"]["readOnlyHint"])


class TestWorkRoot(TestCase):
    def test_cwd_wins_and_nothing_is_created(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            missing = tmp / "proj"
            pol = Policy(cwd=str(missing))
            self.assertEqual(pol.work_root(), missing.resolve())
            self.assertFalse(missing.exists())
            workspace = tmp / "ws"
            workspace.mkdir()
            with mock.patch.dict(
                os.environ,
                {"AGENTS_WORKSPACE_DIR": str(workspace), "AGENTS_TERMINAL_POLICY": ""},
                clear=False,
            ):
                self.assertEqual(Policy.load().work_root(), workspace.resolve())


class _ReparseStat:
    def __init__(self, mode: int, attributes: int) -> None:
        self.st_mode = mode
        self.st_file_attributes = attributes
        self.st_size = 0
        self.st_mtime = 0
        self.st_ino = 0
        self.st_dev = 0


class TestFailClosed(TestCase):
    def setUp(self) -> None:
        import tempfile

        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.root = self.tmp / "ws"
        self.outside = self.tmp / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        (self.root / "ok.txt").write_text("hello\n", encoding="utf-8")
        (self.outside / "secret.txt").write_text(_SECRET, encoding="utf-8")
        os.symlink(self.outside / "secret.txt", self.root / "leak")
        os.symlink(self.outside, self.root / "leakdir")
        os.symlink(self.root / "ok.txt", self.root / "inside-link")

    def tearDown(self) -> None:
        self._td.cleanup()

    def _disabled(self, *, drop_nofollow: bool = True, drop_dir_fd: bool = True):
        kwargs = {}
        if drop_nofollow:
            kwargs["O_NOFOLLOW"] = None
        if drop_dir_fd:
            kwargs["supports_dir_fd"] = frozenset()
            kwargs["supports_fd"] = frozenset()
        return mock.patch.multiple(os, create=True, **kwargs)

    def test_reparse_attribute_and_symlink_bit(self) -> None:
        from agents_terminal.readonly import _REPARSE_ATTRIBUTE, _is_reparse

        self.assertTrue(_is_reparse(_ReparseStat(stat.S_IFDIR | 0o755, _REPARSE_ATTRIBUTE)))
        self.assertTrue(_is_reparse(_ReparseStat(stat.S_IFLNK | 0o777, 0)))
        self.assertFalse(_is_reparse(_ReparseStat(stat.S_IFREG | 0o644, 0)))

    def test_missing_nofollow_or_dir_fd_reads_plain_files_and_rejects_escapes(self) -> None:
        from agents_terminal.readonly import _fd_confinement_supported

        cases = (
            {"drop_nofollow": True, "drop_dir_fd": False},
            {"drop_nofollow": False, "drop_dir_fd": True},
            {"drop_nofollow": True, "drop_dir_fd": True},
        )
        for case in cases:
            with self.subTest(**case):
                dir_fd_calls: list[object] = []
                real_open = os.open

                def guard(path, flags, *args, **kwargs):
                    if "dir_fd" in kwargs:
                        dir_fd_calls.append(kwargs["dir_fd"])
                    return real_open(path, flags, *args, **kwargs)

                with self._disabled(**case), mock.patch.object(os, "open", guard):
                    self.assertFalse(_fd_confinement_supported())
                    listed = list_directory(self.root, ".")
                    self.assertIn("ok.txt", [entry["name"] for entry in listed["entries"]])
                    body = read_file(self.root, "ok.txt")
                    self.assertEqual(body["content"], "hello\n")
                    found = grep_files(self.root, "hello", "ok.txt")
                    self.assertEqual(found["matches"][0]["text"], "hello")
                    described = stat_path(self.root, "ok.txt")
                    self.assertEqual(described["type"], "file")
                    self.assertIsNone(described["target"])
                    link = stat_path(self.root, "leak")
                    self.assertEqual(link["type"], "symlink")
                    self.assertNotIn(_SECRET, json.dumps(link))
                    for user_path in ("leak", "leakdir/secret.txt", "../outside/secret.txt", str(self.outside / "secret.txt")):
                        for op in (
                            lambda p=user_path: read_file(self.root, p),
                            lambda p=user_path: list_directory(self.root, p),
                            lambda p=user_path: grep_files(self.root, "TOP", p),
                            lambda p=user_path: stat_path(self.root, p) if p != "leak" else stat_path(self.root, "leakdir/secret.txt"),
                        ):
                            with self.assertRaises(ReadonlyError) as ctx:
                                op()
                            self.assertEqual(ctx.exception.message, "path escapes workspace root")
                            self.assertNotIn(_SECRET, ctx.exception.message)
                    self.assertEqual(dir_fd_calls, [])

    def test_stat_uses_dir_fd_and_rejects_escapes(self) -> None:
        seen: list[object] = []
        real_stat = os.stat

        def wrap_stat(path, *args, **kwargs):
            if kwargs.get("dir_fd") is not None and kwargs.get("follow_symlinks") is False:
                seen.append(kwargs.get("dir_fd"))
            return real_stat(path, *args, **kwargs)

        # os.stat is what supports_dir_fd advertises. The wrapper must stay in that set
        # or the capability check treats dir_fd as unavailable and uses the fallback.
        advertised = set(os.supports_dir_fd)
        advertised.add(wrap_stat)
        with (
            mock.patch.object(os, "stat", wrap_stat),
            mock.patch.object(os, "supports_dir_fd", advertised),
        ):
            described = stat_path(self.root, "ok.txt")
        self.assertEqual(described["type"], "file")
        self.assertTrue(any(isinstance(fd, int) for fd in seen))
        for user_path in ("../outside/secret.txt", str(self.outside / "secret.txt"), "leakdir/secret.txt"):
            with self.subTest(path=user_path):
                with self.assertRaises(ReadonlyError) as ctx:
                    stat_path(self.root, user_path)
                self.assertEqual(ctx.exception.message, "path escapes workspace root")
                self.assertNotIn(_SECRET, ctx.exception.message)
        link = stat_path(self.root, "leak")
        self.assertEqual(link["type"], "symlink")
        self.assertNotIn(_SECRET, json.dumps(link))

    def test_dir_fd_typeerror_is_readonly_error(self) -> None:
        real_open = os.open

        def boom(path, flags, *args, **kwargs):
            if "dir_fd" in kwargs:
                raise TypeError("dir_fd unsupported")
            return real_open(path, flags, *args, **kwargs)

        advertised = set(os.supports_dir_fd)
        advertised.discard(real_open)
        advertised.add(boom)
        with mock.patch.object(os, "open", boom), mock.patch.object(os, "supports_dir_fd", advertised):
            with self.assertRaises(ReadonlyError) as ctx:
                read_file(self.root, "ok.txt")
            self.assertEqual(ctx.exception.message, "confinement unavailable")
            self.assertIsInstance(ctx.exception.__cause__, TypeError)

    def test_junction_reparse_rejected_before_open(self) -> None:
        import agents_terminal.readonly as ro

        junction = self.root / "junction"
        junction.mkdir()
        secret = junction / "secret.txt"
        secret.write_text(_SECRET, encoding="utf-8")
        inode = junction.lstat().st_ino
        original = ro._is_reparse

        def fake(st: object) -> bool:
            if getattr(st, "st_ino", None) == inode:
                return True
            return original(st)

        opened: list[str] = []
        real_open = os.open

        def guard(path, flags, *args, **kwargs):
            opened.append(os.fspath(path))
            if "dir_fd" in kwargs:
                raise TypeError("dir_fd")
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(ro, "_is_reparse", fake), self._disabled(), mock.patch.object(os, "open", guard):
            with self.assertRaises(ReadonlyError) as ctx:
                read_file(self.root, "junction/secret.txt")
            self.assertEqual(ctx.exception.message, "path escapes workspace root")
            with self.assertRaises(ReadonlyError) as ctx:
                stat_path(self.root, "junction/secret.txt")
            self.assertEqual(ctx.exception.message, "path escapes workspace root")
            with self.assertRaises(ReadonlyError) as ctx:
                list_directory(self.root, "junction")
            self.assertEqual(ctx.exception.message, "path escapes workspace root")
        self.assertFalse(any(path.endswith("secret.txt") for path in opened))
        self.assertEqual(secret.read_text(encoding="utf-8"), _SECRET)


if __name__ == "__main__":
    import unittest

    unittest.main()

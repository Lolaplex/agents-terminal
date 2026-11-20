"""PTY mode: bg --pty runs the child on a pseudo-terminal."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from agents_terminal import proc


class TestPty(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["AGENTS_TERMINAL_PROCS_DIR"] = self._tmp.name
        os.environ["AGENTS_TERMINAL_DRIVER"] = "subprocess"

    def tearDown(self) -> None:
        os.environ.pop("AGENTS_TERMINAL_PROCS_DIR", None)
        os.environ.pop("AGENTS_TERMINAL_DRIVER", None)

    @unittest.skipIf(sys.platform == "win32", "pty is POSIX only")
    def test_child_sees_tty(self) -> None:
        code = "import sys; print('isatty', sys.stdout.isatty()); sys.stdout.flush()"
        spawned = proc.bg_spawn([sys.executable, "-c", code], pty=True)
        pid = spawned["id"]
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["exit_code"], 0)
        self.assertIn("isatty True", proc.proc_log(pid)["stdout"])

    @unittest.skipIf(sys.platform == "win32", "pty is POSIX only")
    def test_pty_stdin_feed(self) -> None:
        code = "import sys; print('got ' + sys.stdin.readline().strip()); sys.stdout.flush()"
        spawned = proc.bg_spawn([sys.executable, "-c", code], pty=True)
        pid = spawned["id"]
        try:
            proc.proc_write(pid, "pty-line")
            done = proc.proc_wait(pid, timeout_sec=30)
        finally:
            proc.proc_kill(pid)
        self.assertEqual(done["exit_code"], 0)
        self.assertIn("got pty-line", proc.proc_log(pid)["stdout"])

    @unittest.skipUnless(sys.platform == "win32", "windows refusal path")
    def test_windows_refuses(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "print(1)"], pty=True)
        pid = spawned["id"]
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["exit_code"], 2)
        self.assertIn("POSIX", done.get("error") or "")
        meta_err = (Path(self._tmp.name) / pid / "exit.json").read_text()
        self.assertIn("posix", meta_err.lower())


if __name__ == "__main__":
    unittest.main()

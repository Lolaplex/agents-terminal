"""Auto-background on a trailing & marker."""

import os
import sys
import tempfile
import unittest

from agents_terminal import proc
from agents_terminal.proc import strip_bg_marker
from agents_terminal.router import run_command


class TestMarker(unittest.TestCase):
    def test_bare_token(self) -> None:
        self.assertEqual(strip_bg_marker(["sleep", "5", "&"]), ["sleep", "5"])

    def test_trailing_suffix(self) -> None:
        self.assertEqual(strip_bg_marker(["sleep", "5&"]), ["sleep", "5"])

    def test_single_string(self) -> None:
        self.assertEqual(strip_bg_marker(["sleep 5 &"]), ["sleep", "5"])

    def test_script_arg_untouched(self) -> None:
        self.assertIsNone(strip_bg_marker(["bash", "-c", "sleep 5 &"]))
        self.assertIsNone(strip_bg_marker(["cmd", "/c", "x &"]))

    def test_flag_arg_untouched(self) -> None:
        self.assertIsNone(strip_bg_marker(["grep", "-e&"]))

    def test_no_marker(self) -> None:
        self.assertIsNone(strip_bg_marker(["echo", "a && b"]))
        self.assertIsNone(strip_bg_marker([]))


class TestAutoBg(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["AGENTS_TERMINAL_PROCS_DIR"] = self._tmp.name
        os.environ["AGENTS_TERMINAL_DRIVER"] = "subprocess"

    def tearDown(self) -> None:
        os.environ.pop("AGENTS_TERMINAL_PROCS_DIR", None)
        os.environ.pop("AGENTS_TERMINAL_DRIVER", None)

    def test_trailing_amp_backgrounds(self) -> None:
        res = run_command([sys.executable, "-c", "print(42)", "&"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("auto_backgrounded", res.stdout)
        pid = res.stdout.split()[1]
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["exit_code"], 0)
        self.assertIn("42", proc.proc_log(pid)["stdout"])

    def test_normal_argv_untouched(self) -> None:
        res = run_command([sys.executable, "-c", "print(7)"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "7")


if __name__ == "__main__":
    unittest.main()

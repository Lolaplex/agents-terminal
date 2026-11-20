"""Signal-death explanations in run and proc results."""

import os
import sys
import tempfile
import unittest

from agents_terminal.driver import RunResult, format_result
from agents_terminal.exitinfo import explain_exit
from agents_terminal import proc


class TestExplain(unittest.TestCase):
    def test_posix_negative(self) -> None:
        self.assertIn("SIGKILL", explain_exit(-9))
        self.assertIn("OOM", explain_exit(-9))
        self.assertIn("SIGSEGV", explain_exit(-11))
        self.assertIn("SIGTERM", explain_exit(-15))

    def test_shell_128_plus_n(self) -> None:
        self.assertIn("SIGKILL", explain_exit(137))
        self.assertIn("SIGINT", explain_exit(130))

    def test_ntstatus_signed(self) -> None:
        # 0xC0000005 access violation as signed int32
        self.assertIn("ACCESS_VIOLATION", explain_exit(-1073741819))
        self.assertIn("Ctrl+C", explain_exit(-1073741510))  # 0xC000013A

    def test_ordinary_codes_silent(self) -> None:
        for code in (None, 0, 1, 2, 126, 127, 128, 255):
            self.assertIsNone(explain_exit(code), code)

    def test_format_result_notes_signal(self) -> None:
        res = RunResult(argv=["x"], returncode=-11, stdout="", stderr="")
        self.assertIn("SIGSEGV", format_result(res))
        ok = RunResult(argv=["x"], returncode=1, stdout="", stderr="")
        self.assertEqual(format_result(ok), "(exit 1)")


class TestProcNote(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["AGENTS_TERMINAL_PROCS_DIR"] = self._tmp.name
        os.environ["AGENTS_TERMINAL_DRIVER"] = "subprocess"

    def tearDown(self) -> None:
        os.environ.pop("AGENTS_TERMINAL_PROCS_DIR", None)
        os.environ.pop("AGENTS_TERMINAL_DRIVER", None)

    def test_kill_result_explains(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "import time; time.sleep(30)"])
        pid = spawned["id"]
        proc.proc_kill(pid)
        state = proc.proc_poll(pid)
        self.assertEqual(state["exit_code"], -9)
        self.assertIn("SIGKILL", state["exit_note"] or "")
        text = proc.format_proc(state)
        self.assertIn("SIGKILL", text)


if __name__ == "__main__":
    unittest.main()

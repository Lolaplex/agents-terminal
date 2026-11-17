"""Background process lifecycle on the subprocess driver."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from agents_terminal import proc


class TestProc(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["AGENTS_TERMINAL_PROCS_DIR"] = self._tmp.name
        os.environ["AGENTS_TERMINAL_DRIVER"] = "subprocess"

    def tearDown(self) -> None:
        os.environ.pop("AGENTS_TERMINAL_PROCS_DIR", None)
        os.environ.pop("AGENTS_TERMINAL_DRIVER", None)

    def test_spawn_wait_log(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "print('hi')"])
        pid = spawned["id"]
        self.assertTrue((Path(self._tmp.name) / pid / "meta.json").is_file())
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["state"], "exited")
        self.assertEqual(done["exit_code"], 0)
        log = proc.proc_log(pid)
        self.assertIn("hi", log["stdout"])

    def test_list_and_poll(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "import time; time.sleep(20)"])
        pid = spawned["id"]
        try:
            self.assertEqual(proc.proc_poll(pid)["state"], "running")
            ids = [r["id"] for r in proc.proc_list()["processes"]]
            self.assertIn(pid, ids)
        finally:
            proc.proc_kill(pid)
        self.assertEqual(proc.proc_poll(pid)["state"], "exited")

    def test_kill_writes_exit(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "import time; time.sleep(20)"])
        pid = spawned["id"]
        out = proc.proc_kill(pid)
        self.assertEqual(out["state"], "exited")
        self.assertIsNotNone(proc.proc_poll(pid)["exit_code"])

    def test_unknown_id(self) -> None:
        with self.assertRaises(proc.ProcError):
            proc.proc_poll("proc_missing")

    def test_write_refused_without_feeder(self) -> None:
        if sys.platform != "win32":
            self.skipTest("posix spawns a fifo feeder")
        spawned = proc.bg_spawn([sys.executable, "-c", "import time; time.sleep(5)"])
        pid = spawned["id"]
        try:
            with self.assertRaises(proc.ProcError):
                proc.proc_write(pid, "x")
        finally:
            proc.proc_kill(pid)


if __name__ == "__main__":
    unittest.main()

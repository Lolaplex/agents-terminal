"""Background process lifecycle on the subprocess driver."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from agents_terminal import proc
from agents_terminal.policy import Policy


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

    def test_write_feeds_stdin(self) -> None:
        code = "import sys; print(sys.stdin.readline().strip()); sys.stdout.flush()"
        spawned = proc.bg_spawn([sys.executable, "-c", code])
        pid = spawned["id"]
        try:
            proc.proc_write(pid, "hello-stdin")
            done = proc.proc_wait(pid, timeout_sec=30)
        finally:
            proc.proc_kill(pid)
        self.assertEqual(done["exit_code"], 0)
        self.assertIn("hello-stdin", proc.proc_log(pid)["stdout"])

    def test_shell_metachars_stay_arguments(self) -> None:
        """argv elements with cmd/sh metachars must never form a second command."""
        pwned = Path(self._tmp.name) / "PWNED"
        arg = f"x & echo PWNED > {pwned} & exit 1" if sys.platform == "win32" else f"x; echo PWNED > {pwned}"
        spawned = proc.bg_spawn([sys.executable, "-c", "import sys; sys.exit(0)", arg])
        pid = spawned["id"]
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["exit_code"], 0)
        self.assertFalse(pwned.exists())

    def test_openshell_driver_refused(self) -> None:
        pol = Policy(driver="openshell")
        with self.assertRaises(proc.ProcError):
            proc.bg_spawn([sys.executable, "-c", "print(1)"], policy=pol)

    def test_default_procs_dir_uses_ws_run_procs_and_legacy_fallback(self) -> None:
        import json
        from unittest.mock import patch

        from agents_workspace import Host

        from agents_terminal import procsup

        with tempfile.TemporaryDirectory() as tmp:
            host = Host(dir=Path(tmp) / "host")
            ws = host.create("demo")
            # Lazy init: neither run/ nor procs/ exists yet.
            self.assertFalse(ws.run.exists())
            self.assertFalse((ws.dir / "procs").exists())

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("AGENTS_TERMINAL_PROCS_DIR", "AGENTS_TERMINAL_POLICY", "AGENTS_WORKSPACE_ROOT")
            }
            env["AGENTS_HOST_DIR"] = str(host.dir)
            env["AGENTS_WORKSPACE"] = "demo"
            env["AGENTS_TERMINAL_DRIVER"] = "subprocess"
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(proc._procs_root(), ws.procs)
                self.assertEqual(procsup._procs_root(), ws.procs)

                # New spawns land in ws.procs (<ws>/run/procs).
                spawned = proc.bg_spawn([sys.executable, "-c", "print('run-procs-ok')"])
                pid = spawned["id"]
                self.assertEqual(Path(spawned["dir"]).parent, ws.procs)
                self.assertFalse((ws.dir / "procs").exists())
                done = proc.proc_wait(pid, timeout_sec=30)
                self.assertEqual(done["exit_code"], 0)
                self.assertIn("run-procs-ok", done["stdout"])

                # Legacy <ws>/procs entries stay readable for one release.
                legacy_id = "proc_legacy01"
                legacy_dir = ws.dir / "procs" / legacy_id
                legacy_dir.mkdir(parents=True, exist_ok=True)
                (legacy_dir / "meta.json").write_text(
                    json.dumps({"id": legacy_id, "argv": [sys.executable, "-c", "print('legacy-ok')"], "cwd": str(ws.workdir)}),
                    encoding="utf-8",
                )
                (legacy_dir / "out.log").write_text("legacy output\n", encoding="utf-8")
                (legacy_dir / "err.log").write_text("", encoding="utf-8")
                (legacy_dir / "exit.json").write_text(
                    json.dumps({"code": 0, "finished": "2026-11-21T00:00:00+00:00"}),
                    encoding="utf-8",
                )

                polled = proc.proc_poll(legacy_id)
                self.assertEqual(polled["state"], "exited")
                self.assertEqual(polled["exit_code"], 0)
                self.assertIn("legacy output", proc.proc_log(legacy_id)["stdout"])
                listed = {row["id"] for row in proc.proc_list()["processes"]}
                self.assertIn(pid, listed)
                self.assertIn(legacy_id, listed)

                # procsup also resolves the legacy entry when no override is set.
                legacy_sup = "proc_legacysup1"
                legacy_sup_dir = ws.dir / "procs" / legacy_sup
                legacy_sup_dir.mkdir(parents=True, exist_ok=True)
                (legacy_sup_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "id": legacy_sup,
                            "argv": [sys.executable, "-c", "print('sup-legacy')"],
                            "cwd": str(ws.dir),
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(procsup.supervise(legacy_sup), 0)
                self.assertIn("sup-legacy", proc.proc_log(legacy_sup)["stdout"])

            # Explicit AGENTS_TERMINAL_PROCS_DIR override disables legacy fallback.
            with patch.dict(
                os.environ,
                {**env, "AGENTS_TERMINAL_PROCS_DIR": str(Path(tmp) / "custom-procs")},
                clear=True,
            ):
                with self.assertRaises(proc.ProcError):
                    proc.proc_poll(legacy_id)
                self.assertEqual(proc.proc_list()["processes"], [])

    def test_standalone_fallback_without_agents_workspace(self) -> None:
        from unittest.mock import patch

        from agents_terminal import procsup

        with tempfile.TemporaryDirectory() as tmp:
            host_dir = Path(tmp) / "host"
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("AGENTS_TERMINAL_PROCS_DIR", "AGENTS_TERMINAL_POLICY", "AGENTS_WORKSPACE_ROOT")
            }
            env["AGENTS_HOST_DIR"] = str(host_dir)
            env["AGENTS_WORKSPACE"] = "alpha"
            expected = (host_dir / "workspaces" / "alpha" / "run" / "procs").resolve()
            expected_legacy = (host_dir / "workspaces" / "alpha" / "procs").resolve()
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(sys.modules, {"agents_workspace": None}):
                    self.assertEqual(proc._procs_roots(), (expected, expected_legacy))
                    self.assertEqual(proc._procs_root(), expected)
                    self.assertEqual(procsup._procs_root(), expected)


if __name__ == "__main__":
    unittest.main()

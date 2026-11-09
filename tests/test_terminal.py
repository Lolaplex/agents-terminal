"""Tests for agents-terminal policy and driver."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agents_terminal.__main__ import main
from agents_terminal.driver import run_argv
from agents_terminal.policy import Policy


class TestPolicy(unittest.TestCase):
    def test_check_request_denies_net(self):
        pol = Policy(net=False)
        self.assertEqual(pol.check_request(read=False, write=False, net=True), "net denied (no driver)")

    def test_filtered_env_includes_github_token(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret", "RANDOM_VAR": "hidden"}, clear=True):
            pol = Policy.load()
            env = pol.filtered_env()
            self.assertEqual(env.get("GITHUB_TOKEN"), "ghp_secret")
            self.assertNotIn("RANDOM_VAR", env)

    def test_filtered_env_extra_env(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"AGENTS_TERMINAL_EXTRA_ENV": "MY_CUSTOM_VAR,ANOTHER_VAR", "MY_CUSTOM_VAR": "val1"}, clear=True):
            pol = Policy.load()
            env = pol.filtered_env()
            self.assertEqual(env.get("MY_CUSTOM_VAR"), "val1")

    def test_filtered_env_passthrough(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"AGENTS_TERMINAL_ENV_PASSTHROUGH": "1", "ANY_SECRET": "hello"}, clear=True):
            pol = Policy.load()
            env = pol.filtered_env()
            self.assertEqual(env.get("ANY_SECRET"), "hello")

    def test_workspace_dir_resolution(self):
        import os
        from pathlib import Path
        from unittest.mock import patch
        with patch.dict(os.environ, {"AGENTS_WORKSPACE_DIR": "/custom/workspace"}, clear=True):
            pol = Policy.load()
            self.assertEqual(pol.workspace_dir(), Path("/custom/workspace").resolve())



class TestDriver(unittest.TestCase):
    def test_run_argv_echo(self):
        if sys.platform == "win32":
            argv = ["cmd", "/c", "echo", "hi"]
        else:
            argv = ["echo", "hi"]
        pol = Policy(home=True, read=True, write=True, net=False)
        result = run_argv(argv, policy=pol)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hi", result.stdout)


class TestHelpJson(unittest.TestCase):
    def test_help_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "agents_terminal", "--help-json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data.get("name"), "agents-terminal")


class TestWorkspaceLock(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.root = self.tmp / "ws"
        self.outside = self.tmp / "out"
        self.root.mkdir()
        self.outside.mkdir()
        (self.root / "sub").mkdir()
        self.inside = self.root / "ok.txt"
        self.inside.write_text("inside", encoding="utf-8")
        self.secret = self.outside / "secret.txt"
        self.secret.write_text("TOPSECRET", encoding="utf-8")
        self.leakdir = self.root / "leakdir"
        self.indir = self.root / "indir"
        self.cwd_link = self.root / "out-link"
        self._reparse(self.outside, self.leakdir)
        self._reparse(self.root, self.indir)
        self._reparse(self.outside, self.cwd_link)

    def tearDown(self) -> None:
        for path in (self.leakdir, self.indir, self.cwd_link):
            if path.is_symlink() or path.exists():
                path.unlink()
        self._td.cleanup()

    def _reparse(self, src: Path, dst: Path) -> None:
        try:
            os.symlink(src, dst, target_is_directory=True)
        except OSError:
            subprocess.check_call(
                ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _env(self, locked: bool, **extra: str):
        env = os.environ.copy()
        for key in (
            "AGENTS_WORKSPACE_DIR",
            "AGENTS_WORKSPACE_LOCK",
            "AGENTS_WORKSPACE_ALLOW",
            "AGENTS_HOME",
            "AGENTS_SKILLS_DIR",
            "AGENTS_SKILLS_EXTRA",
            "AGENTS_MODULES_DIR",
            "AGENTS_MEMORY_PATH",
            "AGENTS_TRACES_DIR",
            "AGENTS_SCHEDULES_DIR",
            "AGENTS_ROUTINE_RUNS_DIR",
        ):
            env.pop(key, None)
        if locked:
            env["AGENTS_WORKSPACE_DIR"] = str(self.root)
            env["AGENTS_WORKSPACE_LOCK"] = "1"
        env["AGENTS_TERMINAL_POLICY"] = ""
        env["AGENTS_TERMINAL_DRIVER"] = "subprocess"
        env["AGENTS_NO_UPDATE_CHECK"] = "1"
        env.update(extra)
        return patch.dict(os.environ, env, clear=True)

    def _read(self, path: str) -> list[str]:
        code = "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'), end='')"
        return [sys.executable, "-c", code, path]

    def test_inside_allowed(self) -> None:
        pol = Policy(cwd=str(self.root))
        with self._env(True):
            direct = run_argv(self._read(str(self.inside)), policy=pol)
            via_link = run_argv(self._read("indir/ok.txt"), policy=pol)
            dotted = run_argv(self._read("sub/../ok.txt"), policy=pol)
        self.assertIsNone(direct.denied)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(direct.stdout, "inside")
        self.assertEqual(via_link.returncode, 0, via_link.stderr)
        self.assertEqual(via_link.stdout, "inside")
        self.assertEqual(dotted.returncode, 0, dotted.stderr)
        self.assertEqual(dotted.stdout, "inside")

    def test_outside_path_refused(self) -> None:
        pol = Policy(cwd=str(self.root))
        with self._env(True):
            absolute = run_argv(self._read(str(self.secret)), policy=pol)
            parent = run_argv(self._read("../out/secret.txt"), policy=pol)
        for result in (absolute, parent):
            self.assertEqual(result.denied, "path escapes workspace root")
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("TOPSECRET", result.stdout)
            self.assertNotIn("TOPSECRET", result.stderr)

    def test_symlink_outside_refused(self) -> None:
        pol = Policy(cwd=str(self.root))
        with self._env(True):
            result = run_argv(self._read("leakdir/secret.txt"), policy=pol)
        self.assertEqual(result.denied, "path escapes workspace root")
        self.assertNotIn("TOPSECRET", result.stdout + result.stderr)
        self.assertEqual(self.secret.read_text(encoding="utf-8"), "TOPSECRET")

    def test_outside_cwd_refused(self) -> None:
        missing = self.tmp / "missing-cwd"
        canary = self.outside / "canary.txt"
        code = "open('canary.txt','w',encoding='utf-8').write('x')"
        with self._env(True):
            missing_result = run_argv([sys.executable, "-c", code], policy=Policy(cwd=str(missing)))
            link_result = run_argv([sys.executable, "-c", code], policy=Policy(cwd=str(self.cwd_link)))
        self.assertEqual(missing_result.denied, "path escapes workspace root")
        self.assertFalse(missing.exists())
        self.assertEqual(link_result.denied, "path escapes workspace root")
        self.assertFalse(canary.exists())

    def test_internal_dirs_stay_open(self) -> None:
        home = self.tmp / "instance"
        named = {
            "AGENTS_SKILLS_DIR": self.tmp / "skills",
            "AGENTS_MODULES_DIR": self.tmp / "modules",
            "AGENTS_MEMORY_PATH": self.tmp / "memory",
            "AGENTS_TRACES_DIR": self.tmp / "traces",
            "AGENTS_SCHEDULES_DIR": self.tmp / "schedules",
        }
        home.mkdir()
        (home / "note.txt").write_text("home", encoding="utf-8")
        for folder in named.values():
            folder.mkdir()
            (folder / "note.txt").write_text("keep", encoding="utf-8")
        dot_skill = Path.home() / ".agents" / "skills" / "note.md"
        dot_key = Path.home() / ".agents" / "keys" / "secret.ed25519"
        pol = Policy(cwd=str(self.root))
        with self._env(True, AGENTS_HOME=str(home), **{key: str(path) for key, path in named.items()}):
            home_file = run_argv(self._read(str(home / "note.txt")), policy=pol)
            self.assertIsNone(home_file.denied, home_file.stderr)
            self.assertEqual(home_file.stdout, "home")
            for folder in named.values():
                result = run_argv(self._read(str(folder / "note.txt")), policy=pol)
                self.assertIsNone(result.denied, result.stderr)
                self.assertEqual(result.stdout, "keep")
            home_cwd = run_argv([sys.executable, "-c", "print('ok')"], policy=Policy(cwd=str(home)))
            self.assertIsNone(home_cwd.denied, home_cwd.stderr)
            from agents_terminal.policy import refuse_workspace

            self.assertIsNone(refuse_workspace(str(self.root), ["python", str(dot_skill)]))
            self.assertEqual(refuse_workspace(str(self.root), ["python", str(dot_key)]), "path escapes workspace root")
            leaked = run_argv(self._read(str(self.secret)), policy=pol)
            self.assertEqual(leaked.denied, "path escapes workspace root")

    def test_blank_unlocked(self) -> None:
        pol = Policy(cwd=str(self.root))
        with self._env(False, AGENTS_WORKSPACE_DIR="   "):
            result = run_argv(self._read(str(self.secret)), policy=pol)
        self.assertIsNone(result.denied)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "TOPSECRET")

    def test_dir_alone_does_not_lock(self) -> None:
        pol = Policy(cwd=str(self.root))
        with self._env(False, AGENTS_WORKSPACE_DIR=str(self.root)):
            result = run_argv(self._read(str(self.secret)), policy=pol)
        self.assertIsNone(result.denied)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "TOPSECRET")

    def test_allow_list_opens_extra_root(self) -> None:
        pol = Policy(cwd=str(self.outside))
        with self._env(True, AGENTS_WORKSPACE_ALLOW=str(self.outside)):
            result = run_argv(self._read(str(self.secret)), policy=pol)
        self.assertIsNone(result.denied)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "TOPSECRET")

    def test_unset_unchanged(self) -> None:
        canary = self.outside / "canary.txt"
        code = "open('canary.txt','w',encoding='utf-8').write('x')"
        with self._env(False):
            cwd_result = run_argv([sys.executable, "-c", code], policy=Policy(cwd=str(self.outside)))
            path_result = run_argv(self._read(str(self.secret)), policy=Policy(cwd=str(self.root)))
        self.assertIsNone(cwd_result.denied)
        self.assertEqual(cwd_result.returncode, 0, cwd_result.stderr)
        self.assertEqual(canary.read_text(encoding="utf-8"), "x")
        self.assertIsNone(path_result.denied)
        self.assertEqual(path_result.returncode, 0, path_result.stderr)
        self.assertEqual(path_result.stdout, "TOPSECRET")

    def test_cli_stderr_and_policy_root(self) -> None:
        policy = self.tmp / "policy.json"
        policy.write_text(json.dumps({"cwd": str(self.outside)}), encoding="utf-8")
        out, err = StringIO(), StringIO()
        with self._env(True):
            os.environ["AGENTS_TERMINAL_POLICY"] = str(policy)
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["read", "secret.txt"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("path escapes workspace root", err.getvalue())
        self.assertNotIn("TOPSECRET", out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()

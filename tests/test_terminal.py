"""Tests for agents-terminal policy and driver."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()

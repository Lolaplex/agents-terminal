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

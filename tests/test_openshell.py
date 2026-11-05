"""Tests for OpenShell policy mapping and driver routing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_terminal.openshell_policy import policy_to_openshell_yaml
from agents_terminal.policy import Policy
from agents_terminal.router import run_command


def _resolved_posix(path: str | Path) -> str:
    return Path(path).resolve().as_posix()


class TestOpenShellPolicy(unittest.TestCase):
    def test_yaml_includes_version_and_filesystem(self):
        pol = Policy(read=True, write=True, net=False)
        workspace = "/workspace"
        text = policy_to_openshell_yaml(pol, workspace=workspace)
        self.assertIn("version: 1", text)
        self.assertIn("filesystem_policy:", text)
        self.assertIn(_resolved_posix(workspace), text)
        self.assertIn("network_policies: {}", text)

    def test_yaml_workspace_path_is_resolved(self):
        pol = Policy(read=True, write=True, net=False)
        with tempfile.TemporaryDirectory() as raw:
            real = Path(raw) / "real"
            real.mkdir()
            link = Path(raw) / "link"
            try:
                os.symlink(real, link, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks are not available")
            text = policy_to_openshell_yaml(pol, workspace=link)
            resolved = _resolved_posix(link)
            self.assertNotEqual(link.as_posix(), resolved)
            self.assertIn(resolved, text)
            self.assertNotIn(link.as_posix(), text)


class TestRouter(unittest.TestCase):
    def test_subprocess_when_driver_forced(self):
        pol = Policy(driver="subprocess", home=True, read=True, write=True)
        if __import__("sys").platform == "win32":
            argv = ["cmd", "/c", "echo", "ok"]
        else:
            argv = ["echo", "ok"]
        result = run_command(argv, policy=pol)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ok", result.stdout)

    @patch("agents_terminal.router.openshell_available", return_value=False)
    def test_openshell_missing_denied(self, _avail):
        pol = Policy(driver="openshell")
        result = run_command(["echo", "x"], policy=pol)
        self.assertIsNotNone(result.denied)


if __name__ == "__main__":
    unittest.main()

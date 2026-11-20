"""SSH driver config and remote line construction."""

import os
import unittest

from agents_terminal.policy import Policy
from agents_terminal.router import run_command
from agents_terminal.ssh_driver import _remote_line, run_ssh, ssh_target

_ENV_KEYS = (
    "AGENTS_TERMINAL_SSH_HOST",
    "AGENTS_TERMINAL_SSH_USER",
    "AGENTS_TERMINAL_SSH_KEY",
    "AGENTS_TERMINAL_SSH_PORT",
    "AGENTS_TERMINAL_SSH_DIR",
    "AGENTS_TERMINAL_DRIVER",
)


class TestSshConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, val in self._saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_target(self) -> None:
        self.assertEqual(ssh_target(), "")
        os.environ["AGENTS_TERMINAL_SSH_HOST"] = "vps.example"
        self.assertEqual(ssh_target(), "vps.example")
        os.environ["AGENTS_TERMINAL_SSH_USER"] = "felix"
        self.assertEqual(ssh_target(), "felix@vps.example")

    def test_remote_line_quotes_each_arg(self) -> None:
        line = _remote_line(["echo", "hi; rm -rf /"])
        self.assertEqual(line, "echo 'hi; rm -rf /'")

    def test_remote_line_cd(self) -> None:
        os.environ["AGENTS_TERMINAL_SSH_DIR"] = "/srv/work"
        line = _remote_line(["ls", "-la"])
        self.assertEqual(line, "cd /srv/work && ls -la")

    def test_no_host_denies(self) -> None:
        res = run_ssh(["echo", "hi"], policy=Policy())
        self.assertEqual(res.returncode, 127)
        self.assertIn("SSH_HOST", res.denied)

    def test_router_ssh_driver(self) -> None:
        res = run_command(["echo", "hi"], policy=Policy(driver="ssh"))
        self.assertEqual(res.returncode, 127)
        self.assertIn("SSH_HOST", res.denied or "")


if __name__ == "__main__":
    unittest.main()

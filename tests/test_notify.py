"""Notify-on-complete: procsup POSTs exit + tail to AGENTS_TERMINAL_NOTIFY_URL."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from agents_terminal import proc


class _Sink(BaseHTTPRequestHandler):
    posts: list = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        _Sink.posts.append(
            {
                "path": self.path,
                "secret": self.headers.get("X-Relay-Secret") or "",
                "body": json.loads(self.rfile.read(length) or b"{}"),
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_args) -> None:
        pass


class TestNotify(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["AGENTS_TERMINAL_PROCS_DIR"] = self._tmp.name
        os.environ["AGENTS_TERMINAL_DRIVER"] = "subprocess"
        _Sink.posts = []
        self._http = HTTPServer(("127.0.0.1", 0), _Sink)
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._http.server_port}/v1/alert"
        os.environ["AGENTS_TERMINAL_NOTIFY_URL"] = self.url
        os.environ["AGENTS_TERMINAL_NOTIFY_SECRET"] = "s3cr3t"

    def tearDown(self) -> None:
        self._http.shutdown()
        self._http.server_close()
        for key in (
            "AGENTS_TERMINAL_PROCS_DIR",
            "AGENTS_TERMINAL_DRIVER",
            "AGENTS_TERMINAL_NOTIFY_URL",
            "AGENTS_TERMINAL_NOTIFY_SECRET",
        ):
            os.environ.pop(key, None)

    def test_exit_posts_notification(self) -> None:
        spawned = proc.bg_spawn([sys.executable, "-c", "print('body-line')"])
        pid = spawned["id"]
        done = proc.proc_wait(pid, timeout_sec=30)
        self.assertEqual(done["exit_code"], 0)
        deadline_posts = 30
        while not _Sink.posts and deadline_posts:
            import time

            time.sleep(0.2)
            deadline_posts -= 1
        self.assertTrue(_Sink.posts)
        post = _Sink.posts[0]
        self.assertEqual(post["secret"], "s3cr3t")
        body = post["body"]
        self.assertEqual(body["proc"], pid)
        self.assertEqual(body["code"], 0)
        self.assertIn("body-line", body["stdout_tail"])
        self.assertIn("exited", body["text"])
        state = proc.proc_poll(pid)
        self.assertTrue(state.get("notified"))


if __name__ == "__main__":
    unittest.main()

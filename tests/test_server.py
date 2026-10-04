import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib import request, error
import zipfile

from gpt64.runner import Controller
from gpt64.server import make_server


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.controller = Controller(root / "bridge", root / "runs", demo=True)
        self.server = make_server(self.controller, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.controller.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def send(self, path, data=None, headers=None):
        req = request.Request(self.url + path, data=None if data is None else json.dumps(data).encode(), headers=headers or {})
        return request.urlopen(req, timeout=3)

    def test_controls_require_local_token_and_reject_foreign_origin(self):
        with self.assertRaises(error.HTTPError) as error1:
            self.send("/api/start", {})
        self.assertEqual(error1.exception.code, 403)
        state = json.load(self.send("/api/state"))
        with self.assertRaises(error.HTTPError) as error2:
            self.send("/api/start", {}, {"X-Gpt64-Control": state["control_token"], "Origin": "https://example.com"})
        self.assertEqual(error2.exception.code, 403)

    def test_demo_run_archive_image_and_export(self):
        state = json.load(self.send("/api/state"))
        self.send("/api/start", {"goal": "Demo platform", "max_steps": 1, "budget_usd": 1}, {"X-Gpt64-Control": state["control_token"]}).close()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = json.load(self.send("/api/state"))
            if state["status"] == "limit_reached":
                break
            time.sleep(0.02)
        self.assertEqual(state["status"], "limit_reached")
        self.assertTrue(state["demo"])
        self.assertEqual(state["usage"]["total_tokens"], 0)
        self.assertTrue(self.send(state["image_url"]).read().startswith(b"\x89PNG"))
        self.assertEqual(len(json.load(self.send("/api/runs"))), 1)
        data = self.send(f"/api/runs/{state['run_id']}/export").read()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("events.jsonl", archive.namelist())
            self.assertIn("state.json", archive.namelist())
            self.assertTrue(any(name.startswith("screens/") for name in archive.namelist()))
            self.assertNotIn("OPENAI_API_KEY", archive.read("state.json").decode())

    def test_assets_and_no_arbitrary_file_reads(self):
        self.assertIn(b"Agent commentary", self.send("/").read())
        with self.assertRaises(error.HTTPError) as failure:
            self.send("/api/runs/../../.env")
        self.assertEqual(failure.exception.code, 404)

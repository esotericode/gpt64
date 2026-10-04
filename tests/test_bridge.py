import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from gpt64 import Bridge, BridgeError, Segment
from gpt64.bridge import atomic_json
from gpt64.cli import initialize
from lua_host import LUA_LIBRARY, LuaHost


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        initialize(self.root)
        atomic_json(self.root / "ready.json", {"version": 1, "system": "N64", "session": "test", "buttons": ["A"]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_timeout_is_not_retried_and_blocks_new_actions(self):
        with Bridge(self.root, timeout=0.04) as bridge:
            with self.assertRaisesRegex(BridgeError, "Timed out"):
                bridge.step([Segment(1)])
            request = (self.root / "request.txt").read_text()
            with self.assertRaisesRegex(BridgeError, "unconfirmed"):
                bridge.step([Segment(1)])
            self.assertEqual(request, (self.root / "request.txt").read_text())
        with self.assertRaisesRegex(BridgeError, "unconfirmed"):
            with Bridge(self.root):
                pass

    def test_exclusive_client(self):
        with Bridge(self.root):
            with self.assertRaisesRegex(BridgeError, "Another client"):
                with Bridge(self.root):
                    pass

    def test_reset_preserves_images_and_logs(self):
        (self.root / "pending.json").write_text("{}")
        image = self.root / "images" / "keep.png"
        image.write_bytes(b"keep")
        initialize(self.root, reset=True)
        self.assertFalse((self.root / "pending.json").exists())
        self.assertEqual(image.read_bytes(), b"keep")

    def test_bad_frame_reply_retains_pending(self):
        def server():
            deadline = time.monotonic() + 1
            while not (self.root / "request.txt").exists() and time.monotonic() < deadline:
                time.sleep(0.001)
            lines = (self.root / "request.txt").read_text().splitlines()
            atomic_json(self.root / "responses" / f"{lines[2]}.json", {"id": lines[2], "session": lines[1], "ok": True,
                        "frame_before": 1, "frame_after": 20, "advanced": 1, "paused": True})
        thread = threading.Thread(target=server)
        thread.start()
        try:
            with Bridge(self.root, timeout=1) as bridge:
                with self.assertRaisesRegex(BridgeError, "invariant"):
                    bridge.step([Segment(1)])
        finally:
            thread.join(timeout=2)
        self.assertTrue((self.root / "pending.json").exists())


@unittest.skipUnless(LUA_LIBRARY, "liblua5.4 required for real Lua contract tests")
class LuaIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        initialize(self.root)
        self.host = LuaHost(self.root)
        deadline = time.monotonic() + 2
        while not (self.root / "ready.json").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        if not (self.root / "ready.json").exists():
            self.fail((self.root / "console.log").read_text())

    def tearDown(self):
        self.host.close()
        self.tmp.cleanup()

    def test_observe_step_release_and_frozen_idle(self):
        with Bridge(self.root, timeout=2) as bridge:
            first = bridge.observe()
            time.sleep(0.03)
            second = bridge.observe()
            self.assertEqual(first.frame_after, second.frame_before)
            action = bridge.step([Segment(3, 0.5, -1, ("A", "Z")), Segment(2, 0.5, -1)])
            self.assertEqual(action.advanced, 5)
            self.assertEqual(action.frame_after, 105)
            time.sleep(0.03)
            last = bridge.observe()
            self.assertEqual(last.frame_after, 105)
        lines = (self.root / "inputs.log").read_text().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(line.endswith("40 -80 true true") for line in lines[:3]))
        self.assertTrue(all(line.endswith("40 -80 false false") for line in lines[3:]))
        self.assertEqual(len((self.root / "actions.jsonl").read_text().splitlines()), 4)

    def test_duplicate_packet_does_not_repeat_action(self):
        with Bridge(self.root, timeout=2) as bridge:
            action = bridge.step([Segment(2)])
            wire = f"GPT64 1\n{bridge.ready['session']}\n{action.request_id}\n1\n2 0 0 0\n"
            packet = self.root / "request.tmp"
            packet.write_text(wire)
            packet.replace(self.root / "request.txt")
            time.sleep(0.03)
            self.assertEqual(bridge.observe().frame_after, 102)
        self.assertEqual(len((self.root / "inputs.log").read_text().splitlines()), 2)

    def test_stale_session_never_executes(self):
        packet = self.root / "request.tmp"
        packet.write_text("GPT64 1\nold-session\n" + "a" * 32 + "\n1\n30 0 0 1\n")
        packet.replace(self.root / "request.txt")
        deadline = time.monotonic() + 1
        while (self.root / "ready.json").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse((self.root / "ready.json").exists())
        self.assertFalse((self.root / "inputs.log").exists())
        self.assertIn("Stale session", (self.root / "console.log").read_text())

    def test_lua_rejects_out_of_bounds_wire_action(self):
        session = json.loads((self.root / "ready.json").read_text())["session"]
        packet = self.root / "request.tmp"
        packet.write_text(f"GPT64 1\n{session}\n" + "b" * 32 + "\n1\n121 0 0 1\n")
        packet.replace(self.root / "request.txt")
        deadline = time.monotonic() + 1
        while (self.root / "ready.json").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse((self.root / "inputs.log").exists())
        self.assertIn("Invalid action number", (self.root / "console.log").read_text())


if os.environ.get("GPT64_REQUIRE_LUA") and not LUA_LIBRARY:
    raise RuntimeError("CI requires Lua 5.4 contract tests; liblua5.4 not found")

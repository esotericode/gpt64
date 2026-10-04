import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from gpt64.bridge import Observation
from gpt64.model import MODEL, ModelError, Decision, payload, parse_response, usage_summary
from gpt64.runner import Controller

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=')


def answer(done=False):
    return {"commentary": "The path looks clear, so I will move a little. Then I can check the landing. Extra sentence.",
            "memory": "Visible path ahead.", "done": done,
            "segments": [] if done else [{"frames": 4, "x": 0, "y": 0.5, "buttons": ["A"]}]}


def response(value=None, status="completed"):
    return {"id": "response-test", "_request_id": "request-test", "model": MODEL, "status": status,
            "service_tier": "default", "usage": {"input_tokens": 1000, "output_tokens": 100,
             "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 200},
             "output_tokens_details": {"reasoning_tokens": 60}},
            "output": [{"type": "reasoning", "content": "PRIVATE_REASONING_MUST_NOT_BE_LOGGED"},
                       {"type": "message", "content": [{"type": "output_text", "text": json.dumps(value or answer())}]}]}


class FakeClient:
    def __init__(self, reply=None, block=False, fail=False):
        self.reply = reply or response()
        self.sent, self.release = threading.Event(), threading.Event()
        self.counts, self.generations, self.fail = 0, 0, fail
        if not block:
            self.release.set()

    def count(self, body):
        self.counts += 1
        self.body = body
        return 1000

    def generate(self, body):
        self.generations += 1
        self.sent.set()
        if not self.release.wait(3):
            raise RuntimeError("test release timed out")
        if self.fail:
            raise ModelError("Request failed; charge unknown")
        return self.reply


class FakeBridge:
    def __init__(self, root):
        self.root = root
        self.frames, self.actions = 10, []
        self.source = root / "source.png"
        self.source.write_bytes(PNG)
        self.counter = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def observe(self):
        self.counter += 1
        return Observation(self.source, self.frames, self.frames, 0, f"{self.counter:032x}")

    def step(self, segments):
        self.actions.append(segments)
        before = self.frames
        self.frames += sum(x.frames for x in segments)
        self.counter += 1
        return Observation(self.source, before, self.frames, self.frames - before, f"{self.counter:032x}")


class ModelTest(unittest.TestCase):
    def test_public_commentary_is_two_sentences_and_bounded(self):
        decision = Decision.parse(answer())
        self.assertNotIn("Extra", decision.commentary)
        value = answer(); value["commentary"] = "a " * 300
        self.assertLessEqual(len(Decision.parse(value).commentary), 280)

    def test_usage_includes_cache_writes_and_counts_reasoning_once(self):
        usage = usage_summary(response())
        self.assertEqual(usage["total_tokens"], 1100)
        self.assertEqual(usage["reasoning_tokens"], 60)
        self.assertAlmostEqual(usage["estimated_usd"], (700*2 + 100*0.1 + 200*2.5 + 100*10)/1e6)

    def test_rejects_unsafe_action_and_other_models(self):
        value = answer(); value["segments"][0]["frames"] = 999
        with self.assertRaises(ModelError):
            parse_response(response(value))
        value = response(); value["model"] = "different-model"
        with self.assertRaises(ModelError):
            parse_response(value)

    def test_input_is_only_images_goal_memory_and_executed_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "frame.png"; image.write_bytes(PNG)
            value = payload("Reach painting", [image] * 6, ["action"] * 12, "visible notes")
        self.assertEqual(value["model"], MODEL)
        self.assertFalse(value["store"])
        self.assertEqual(value["service_tier"], "default")
        content = value["input"][0]["content"]
        self.assertEqual(len(content), 5)
        context = json.loads(content[0]["text"])
        self.assertEqual(set(context), {"goal", "memory", "executed_actions"})
        self.assertEqual(len(context["executed_actions"]), 8)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = FakeBridge(self.root)
        self.controllers = []

    def tearDown(self):
        for c in self.controllers:
            c.close()
        self.tmp.cleanup()

    def controller(self, client):
        c = Controller(self.root / "bridge", self.root / "runs", bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(c)
        return c

    def until(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.005)
        self.fail("Worker did not reach expected state")

    def test_one_decision_records_commentary_inputs_and_usage(self):
        client = FakeClient(); c = self.controller(client)
        c.start("Reach the painting", continuous=False)
        self.until(lambda: c.snapshot()["status"] == "paused" and c.snapshot()["steps"] == 1)
        state = c.snapshot()
        self.assertEqual(state["usage"]["total_tokens"], 1100)
        self.assertEqual(len(self.bridge.actions), 1)
        self.assertEqual(client.generations, 1)
        records = ''.join(p.read_text() for p in c.log.directory.rglob("*.json*"))
        self.assertIn("action_finished", records)
        self.assertNotIn("PRIVATE_REASONING", records)
        self.assertNotIn("data:image", records)

    def test_budget_stops_before_generation_and_inputs(self):
        client = FakeClient(); c = self.controller(client)
        c.start("Reach painting", budget_usd=0.001)
        self.until(lambda: c.snapshot()["status"] == "budget_reached")
        self.assertEqual(client.generations, 0)
        self.assertEqual(self.bridge.actions, [])

    def test_pause_during_generation_holds_action_and_resume_does_not_rebill(self):
        client = FakeClient(block=True); c = self.controller(client)
        c.start("Reach painting")
        self.assertTrue(client.sent.wait(2))
        c.pause(); client.release.set()
        self.until(lambda: c.snapshot()["status"] == "paused" and c.snapshot()["pending_decision"])
        self.assertEqual(self.bridge.actions, [])
        c.start("Reach painting", continuous=False)
        self.until(lambda: len(self.bridge.actions) == 1 and c.snapshot()["status"] == "paused")
        self.assertEqual(client.generations, 1)

    def test_stop_during_generation_accounts_usage_without_executing(self):
        client = FakeClient(block=True); c = self.controller(client)
        c.start("Reach painting")
        self.assertTrue(client.sent.wait(2))
        c.stop(); client.release.set()
        self.until(lambda: c.snapshot()["status"] == "stopped")
        self.assertEqual(self.bridge.actions, [])
        self.assertEqual(c.snapshot()["usage"]["total_tokens"], 1100)

    def test_incomplete_response_counts_usage_and_stops(self):
        c = self.controller(FakeClient(response(status="incomplete")))
        c.start("Reach painting")
        self.until(lambda: c.snapshot()["status"] == "error")
        self.assertEqual(c.snapshot()["usage"]["output_tokens"], 100)
        self.assertEqual(self.bridge.actions, [])

    def test_unknown_network_outcome_preserves_reservation(self):
        client = FakeClient(fail=True); c = self.controller(client)
        c.start("Reach painting")
        self.until(lambda: c.snapshot()["status"] == "error")
        state = c.snapshot()
        self.assertTrue(state["usage_unknown"])
        self.assertGreater(state["reserved_usd"], 0)
        self.assertEqual(client.generations, 1)
        self.assertEqual(self.bridge.actions, [])

    def test_goal_completion_executes_no_inputs(self):
        c = self.controller(FakeClient(response(answer(done=True))))
        c.start("Reach painting")
        self.until(lambda: c.snapshot()["status"] == "completed")
        self.assertEqual(self.bridge.actions, [])

    def test_limit_stops_an_autonomous_run(self):
        c = self.controller(FakeClient())
        c.start("Reach painting", max_steps=1)
        self.until(lambda: c.snapshot()["status"] == "limit_reached")
        self.assertEqual(len(self.bridge.actions), 1)

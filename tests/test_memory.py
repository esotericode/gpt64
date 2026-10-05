import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from gpt64.model import Decision, ModelError
from gpt64.runner import Controller
from gpt64.scratchpad import Scratchpad
from test_agent import FakeBridge, FakeClient, answer, response


class ScratchpadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pad = Scratchpad(self.root / "scratchpad")

    def tearDown(self):
        self.tmp.cleanup()

    def test_notes_and_corrections_survive_reopening_without_erasing_history(self):
        old = self.pad.append("Hypothesis: jump needs a longer A press.")
        self.pad.append("Correction after visible landing: release A between jump presses.")
        other = Scratchpad(self.pad.directory)
        self.assertEqual(other.context()["total_notes"], 2)
        self.assertIn(old["text"], [e["text"] for e in other.context("jump")["entries"]])
        self.assertEqual(len(other.export().splitlines()), 2)

    def test_bounded_context_recalls_old_notes_and_pages_through_all_notes(self):
        entries = [self.pad.append(f"note-{i} " + "x" * 1980) for i in range(23)]
        recalled = self.pad.context("note-0")
        self.assertIn(entries[0]["id"], [e["id"] for e in recalled["entries"]])
        seen, offset = set(), 0
        while True:
            page = self.pad.context("", offset)
            self.assertLessEqual(sum(len(e["text"]) for e in page["entries"]), 12000)
            seen.update(e["id"] for e in page["entries"])
            if page["next_offset"] is None:
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual(seen, {e["id"] for e in entries})
        self.assertEqual(len(self.pad.export().splitlines()), 23)

    def test_duplicate_writes_are_idempotent_and_conflicting_keys_preserve_notes(self):
        first = self.pad.append("Useful route.", key="run:1")
        self.assertEqual(first, self.pad.append("Useful route.", key="run:1"))
        before = self.pad.export()
        with self.assertRaises(ValueError):
            self.pad.append("Different route.", key="run:1")
        self.assertEqual(before, self.pad.export())

    def test_concurrent_writes_keep_all_records(self):
        errors = []
        def write(i):
            try:
                Scratchpad(self.pad.directory).append(f"lesson-{i}")
            except Exception as exc:
                errors.append(exc)
        workers = [threading.Thread(target=write, args=(i,)) for i in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        self.assertFalse(errors)
        self.assertEqual(self.pad.context()["total_notes"], 12)

    def test_invalid_or_damaged_records_do_not_erase_existing_notes(self):
        self.pad.append("Preserve this.")
        before = self.pad.export()
        for value in ("", "x" * 2001, None):
            with self.assertRaises(ValueError):
                self.pad.append(value)
        for query, offset in (("x" * 201, 0), ("", True), ("", -1)):
            with self.assertRaises(ValueError):
                self.pad.context(query, offset)
        self.assertEqual(before, self.pad.export())
        with self.pad.path.open("a") as target:
            target.write('{"broken":')
        damaged = self.pad.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "damaged record"):
            self.pad.append("New note.")
        self.assertEqual(damaged, self.pad.path.read_bytes())


class TimingDecisionTest(unittest.TestCase):
    def test_model_controls_longer_holds_releases_and_zero_extra_wait(self):
        value = {**answer(), "pause_seconds": 0, "scratchpad_note": "Release A between jumps.",
                 "scratchpad_query": "jump", "scratchpad_offset": 5,
                 "segments": [{"frames": 600, "x": 0, "y": .5, "buttons": ["A"]},
                              {"frames": 600, "x": 0, "y": .5, "buttons": []},
                              {"frames": 600, "x": 0, "y": 0, "buttons": []}]}
        decision = Decision.parse(value)
        self.assertEqual(sum(s.frames for s in decision.segments), 1800)
        self.assertEqual(decision.segments[1].buttons, ())
        self.assertEqual(decision.pause_seconds, 0)
        self.assertEqual(decision.scratchpad_offset, 5)

    def test_invalid_pause_or_notes_cannot_become_inputs(self):
        for changes in ({"pause_seconds": -1}, {"pause_seconds": 31}, {"pause_seconds": True},
                        {"pause_seconds": float("nan")}, {"scratchpad_note": "x" * 2001},
                        {"scratchpad_query": "x" * 201}, {"scratchpad_offset": -1}):
            with self.subTest(changes=changes), self.assertRaises(ModelError):
                Decision.parse({**answer(), **changes})
        with self.assertRaises(ModelError):
            Decision.parse({**answer(), "segments": [], "pause_seconds": 0})
        note_only = Decision.parse({**answer(), "segments": [], "pause_seconds": 0, "scratchpad_query": "camera"})
        self.assertEqual(note_only.segments, ())


class MemoryRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = FakeBridge(self.root)
        self.controllers = []

    def tearDown(self):
        for controller in self.controllers:
            controller.close()
        self.tmp.cleanup()

    def controller(self, client):
        controller = Controller(self.root / "bridge", self.root / "runs",
            bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(controller)
        return controller

    def until(self, condition):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.005)
        self.fail("Worker did not reach expected state")

    def test_frozen_wait_is_interruptible_and_notes_survive_an_unexecuted_plan(self):
        client = FakeClient(response({**answer(), "pause_seconds": 30, "scratchpad_note": "The last jump fell short; try releasing A."}))
        controller = self.controller(client)
        controller.start("Reach painting")
        self.until(lambda: controller.snapshot()["status"] == "waiting")
        self.assertEqual(self.bridge.actions, [])
        controller.stop()
        self.until(lambda: controller.snapshot()["status"] == "stopped")
        self.assertEqual(self.bridge.actions, [])
        self.assertEqual(client.generations, 1)
        reopened = self.controller(FakeClient())
        self.assertEqual(reopened.snapshot()["scratchpad"]["total_notes"], 1)

    def test_user_pause_suspends_the_ai_wait_and_resume_does_not_rebill(self):
        client = FakeClient(response({**answer(), "pause_seconds": .4}))
        controller = self.controller(client)
        controller.start("Reach painting", continuous=False)
        self.until(lambda: controller.snapshot()["status"] == "waiting")
        controller.pause()
        self.until(lambda: controller.snapshot()["status"] == "paused")
        left = controller.snapshot()["pause_remaining_seconds"]
        time.sleep(.1)
        self.assertEqual(left, controller.snapshot()["pause_remaining_seconds"])
        self.assertEqual(self.bridge.actions, [])
        controller.start("Reach painting", continuous=False)
        self.until(lambda: controller.snapshot()["status"] == "paused" and controller.snapshot()["steps"] == 1)
        self.assertEqual(client.generations, 1)

    def test_new_run_and_new_model_receive_previously_saved_lessons(self):
        first = self.controller(FakeClient(response({**answer(), "pause_seconds": 0,
            "scratchpad_note": "Previous failed jump: release A, then try a shorter forward hold."})))
        first.start("Reach painting", max_steps=1)
        self.until(lambda: first.snapshot()["status"] == "limit_reached")
        reply = response({**answer(), "pause_seconds": 0}); reply["model"] = "gpt-6-luna"
        client = FakeClient(reply); second = self.controller(client)
        second.start("Try another route", max_steps=1, model="gpt-6-luna")
        self.until(lambda: second.snapshot()["status"] == "limit_reached")
        context = json.loads(client.body["input"][0]["content"][0]["text"])
        self.assertEqual(context["memory"], "")
        self.assertEqual(context["executed_actions"], [])
        self.assertIn("Previous failed jump", context["scratchpad"]["entries"][0]["text"])
        self.assertEqual(context["scratchpad"]["total_notes"], 1)

    def test_recall_only_turn_moves_zero_frames_and_supplies_notes_to_next_turn(self):
        replies = [response({**answer(), "segments": [], "pause_seconds": 0, "scratchpad_query": "painting",
                    "scratchpad_note": "The previous forward jump missed the painting; adjust the camera first."}),
                   response({**answer(), "pause_seconds": 0})]
        class SequenceClient(FakeClient):
            def __init__(self):
                super().__init__(); self.contexts = []
            def generate(self, body):
                self.contexts.append(json.loads(body["input"][0]["content"][0]["text"]))
                self.generations += 1
                return replies[self.generations - 1]
        client = SequenceClient(); controller = self.controller(client)
        controller.start("Reach painting", max_steps=2)
        self.until(lambda: controller.snapshot()["status"] == "limit_reached")
        self.assertEqual(len(self.bridge.actions), 1)
        self.assertEqual(self.bridge.frames, 14)
        self.assertEqual(controller.snapshot()["steps"], 1)
        self.assertEqual(controller.snapshot()["decisions"], 2)
        self.assertEqual(client.contexts[1]["executed_actions"], [])
        self.assertIn("missed the painting", client.contexts[1]["scratchpad"]["entries"][0]["text"])
        record = json.loads((controller.log.directory / "api/0002.json").read_text())
        self.assertEqual(record["scratchpad_context"]["query"], "painting")

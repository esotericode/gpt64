import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from gpt64.bridge import Observation
from gpt64.model import (MODEL, ModelError, Decision, payload, parse_response, usage_summary,
                         model_catalog, reserve_cost, response_diagnostics, read_stream)
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
    def test_final_answer_is_not_joined_with_intermediate_commentary(self):
        value = response()
        value["output"][-1].update(phase="final_answer", role="assistant", status="completed")
        commentary = {"type": "message", "role": "assistant", "phase": "commentary",
                      "content": [{"type": "output_text", "text": "I will inspect the scene before choosing an input."}]}
        for text in ("I will inspect the scene.", json.dumps(answer(done=True))):
            commentary["content"][0]["text"] = text
            value["output"].insert(1, commentary)
            decision = parse_response(value)
            self.assertFalse(decision.done)
            self.assertEqual(decision.segments[0].frames, 4)
            value["output"].pop(1)

    def test_only_one_eligible_final_message_can_be_executed(self):
        for phase in (None, "commentary", "future_phase"):
            value = response()
            final = value["output"].pop()
            final["phase"] = phase
            value["output"].append(final)
            if phase is None:
                self.assertEqual(parse_response(value).segments[0].frames, 4)
            else:
                with self.assertRaisesRegex(ModelError, "no final answer"):
                    parse_response(value)
        value = response(); value["output"].append(dict(value["output"][-1]))
        with self.assertRaisesRegex(ModelError, "multiple possible final answers"):
            parse_response(value)
        value["output"][-1]["phase"] = "final_answer"
        with self.assertRaises(ModelError):
            parse_response(value)

    def test_malformed_response_shapes_have_specific_errors(self):
        for output, code in ((None, "invalid_output"), ([None], "invalid_output"),
                             ([], "missing_answer"), ([{"type": "message", "content": None}], "invalid_content"),
                             ([{"type": "message", "content": [None]}], "invalid_content"),
                             ([{"type": "message", "status": "incomplete", "content": []}], "incomplete_message"),
                             ([{"type": "message", "content": [{"type": "output_text", "text": None}]}], "invalid_text")):
            value = response(); value["output"] = output
            with self.subTest(code=code), self.assertRaises(ModelError) as failure:
                parse_response(value)
            self.assertEqual(failure.exception.code, code)

    def test_json_errors_distinguish_empty_fenced_and_malformed_answers(self):
        for text, code, phrase in ((" \n", "empty_answer", "empty final answer"),
                                   ("```json\n" + json.dumps(answer()) + "\n```", "invalid_json", "Markdown-fenced"),
                                   ("I will move forward.", "invalid_json", "line 1, column 1"),
                                   ('{\n"commentary":', "invalid_json", "line 2")):
            value = response(); value["output"][-1]["content"][0]["text"] = text
            with self.subTest(phrase=phrase), self.assertRaisesRegex(ModelError, phrase) as failure:
                parse_response(value)
            self.assertEqual(failure.exception.code, code)

    def test_refusal_and_invalid_decisions_do_not_become_inputs(self):
        value = response(); value["output"][-1]["content"] = [{"type": "refusal", "refusal": "PRIVATE_REFUSAL_BODY"}]
        with self.assertRaises(ModelError) as failure:
            parse_response(value)
        self.assertEqual(failure.exception.code, "refusal")
        self.assertNotIn("PRIVATE_REFUSAL", json.dumps(response_diagnostics(value)))
        for decision in ({}, [], {**answer(), "segments": [{"frames": 999, "x": 0, "y": 0, "buttons": []}]}):
            value = response(); value["output"][-1]["content"][0]["text"] = json.dumps(decision)
            with self.subTest(decision=decision), self.assertRaises(ModelError) as failure:
                parse_response(value)
            self.assertEqual(failure.exception.code, "invalid_decision")

    def test_diagnostics_are_bounded_and_exclude_reasoning_and_echoed_inputs(self):
        value = response()
        value.update(input="IMAGE_BASE64_PRIVATE", instructions="PRIVATE_INSTRUCTIONS", encrypted_content="PRIVATE_ENCRYPTED")
        value["output"].insert(0, {"type": "message", "phase": "commentary", "content": [
            {"type": "output_text", "text": "INTERMEDIATE_TEXT_MUST_NOT_BE_LOGGED"}]})
        value["output"][-1]["content"][0]["text"] = "X" * 20000
        value["text"] = {"format": {"type": "json_schema", "schema": {"PRIVATE_SCHEMA": True}}}
        details = response_diagnostics(value)
        self.assertEqual(details["returned_format"], "json_schema")
        self.assertEqual(len(details["answer_text"]), 16384)
        self.assertTrue(details["answer_truncated"])
        self.assertEqual(details["answer_characters"], 20000)
        for secret in ("PRIVATE_REASONING", "IMAGE_BASE64_PRIVATE", "PRIVATE_INSTRUCTIONS", "PRIVATE_ENCRYPTED", "INTERMEDIATE_TEXT", "PRIVATE_SCHEMA"):
            self.assertNotIn(secret, json.dumps(details))

    def test_catalog_accepts_plan_and_api_shapes_without_leaking_metadata(self):
        models = model_catalog({"models": [
            {"slug": "gpt-6-sol", "display_name": "GPT-6 Sol", "visibility": "list", "internal": "PRIVATE"},
            {"slug": "hidden", "visibility": "hide"},
            {"slug": "gpt-6-luna"}, {"slug": "gpt-6-sol"}]})
        self.assertEqual([m["id"] for m in models], ["gpt-6-sol", "gpt-6-luna"])
        self.assertNotIn("PRIVATE", json.dumps(models))
        self.assertEqual(model_catalog({"data": [{"id": "gpt-6-sol"}]}), model_catalog({"models": [{"slug": "gpt-6-sol"}]}))
        for value in ({}, {"models": None}, {"models": [None]}, {"models": [{"slug": "../bad"}]}):
            with self.subTest(value=value), self.assertRaises(ModelError):
                model_catalog(value)

    def test_selected_model_payload_snapshot_and_profile_specific_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "frame.png"; image.write_bytes(PNG)
            body = payload("Reach painting", [image], [], "", model="gpt-6-luna")
            experimental = payload("Reach painting", [image], [], "", model="account-vision-model")
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["reasoning"], {"effort": "medium"})
        self.assertNotIn("reasoning", experimental)
        value = response(); value["model"] = "gpt-6-luna-2026-09-01"
        parse_response(value, "gpt-6-luna")
        with self.assertRaises(ModelError):
            parse_response(value, "gpt-6-sol")
        self.assertAlmostEqual(usage_summary(value, "gpt-6-luna")["estimated_usd"], (700*.1 + 100*.01 + 200*.125 + 100*.5)/1e6)
        self.assertAlmostEqual(reserve_cost(1000, "gpt-6-luna"), (1000*.125 + 4096*.5)/1e6)
        self.assertEqual(usage_summary(value, "account-vision-model", api_pricing=False)["estimated_usd"], 0)
        with self.assertRaises(ModelError):
            reserve_cost(1000, "unpriced-model")

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

    def test_rejected_answer_logs_public_text_and_error_without_retrying(self):
        reply = response(); reply["output"][-1]["content"][0]["text"] = "I will press A."
        client = FakeClient(reply); c = self.controller(client)
        c.start("Reach painting")
        self.until(lambda: c.snapshot()["status"] == "error")
        self.assertEqual(client.generations, 1)
        self.assertEqual(c.snapshot()["usage"]["total_tokens"], 1100)
        self.assertFalse(c.snapshot()["usage_unknown"])
        self.assertEqual(self.bridge.actions, [])
        record = json.loads((c.log.directory / "api" / "0001.json").read_text())
        self.assertEqual(record["parse_error"]["code"], "invalid_json")
        self.assertEqual(record["diagnostics"]["answer_text"], "I will press A.")
        self.assertNotIn("PRIVATE_REASONING", json.dumps(record))
        self.assertIn("Download run ZIP", c.snapshot()["error"])

    def test_commentary_then_final_answer_executes_once_and_logs_final_text(self):
        reply = response(); reply["output"][-1]["phase"] = "final_answer"
        reply["output"].insert(1, {"type": "message", "phase": "commentary", "content": [
            {"type": "output_text", "text": "PREAMBLE_DO_NOT_PARSE_OR_LOG"}]})
        client = FakeClient(reply); c = self.controller(client)
        c.start("Reach painting", max_steps=1)
        self.until(lambda: c.snapshot()["status"] == "limit_reached")
        self.assertEqual(client.generations, 1)
        self.assertEqual(len(self.bridge.actions), 1)
        record = json.loads((c.log.directory / "api" / "0001.json").read_text())
        self.assertTrue(record["decision_valid"])
        self.assertEqual(json.loads(record["diagnostics"]["answer_text"]), answer())
        self.assertNotIn("PREAMBLE", json.dumps(record))

    def test_empty_plan_terminal_recovers_completed_message_and_accounts_once(self):
        message = {"id": "msg-test", "type": "message", "role": "assistant", "phase": "final_answer", "status": "completed",
                   "content": [{"type": "output_text", "text": json.dumps(answer())}]}
        terminal = response(); terminal.update(model="gpt-6-astra", output=[],
            usage={"input_tokens": 634, "output_tokens": 66, "output_tokens_details": {"reasoning_tokens": 0}})
        events = [{"type": "response.output_item.done", "output_index": 0, "item": message},
                  {"type": "response.completed", "response": terminal}]
        class StreamClient(FakeClient):
            def check(self):
                return "gpt-6-astra"
            def generate(self, body):
                self.generations += 1
                stream = io.BytesIO(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events))
                return read_stream(stream)
        client = StreamClient()
        c = Controller(self.root / "bridge", self.root / "runs", billing="chatgpt", model="gpt-6-astra",
                       bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(c)
        c.start("Enter Bob-omb Battlefield through its painting.", max_steps=1)
        self.until(lambda: c.snapshot()["status"] == "limit_reached")
        self.assertEqual(len(self.bridge.actions), 1)
        self.assertEqual(client.generations, 1)
        self.assertEqual(client.counts, 0)
        self.assertEqual(c.snapshot()["usage"]["total_tokens"], 700)
        self.assertEqual(c.snapshot()["usage"]["estimated_usd"], 0)
        record = json.loads((c.log.directory / "api" / "0001.json").read_text())
        self.assertTrue(record["decision_valid"])
        self.assertEqual(record["diagnostics"]["stream"]["terminal_output_count"], 0)
        self.assertEqual(record["diagnostics"]["stream"]["output_source"], "completed_events")

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

    def test_chatgpt_plan_does_not_count_or_price_as_paid_api(self):
        client = FakeClient()
        client.check = lambda: MODEL
        c = Controller(self.root / "bridge", self.root / "runs", billing="chatgpt",
                       bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(c)
        c.start("Reach painting", max_steps=1, budget_usd=0.001)
        self.until(lambda: c.snapshot()["status"] == "limit_reached")
        self.assertEqual(client.counts, 0)
        self.assertEqual(client.generations, 1)
        self.assertEqual(c.snapshot()["usage"]["estimated_usd"], 0)
        self.assertEqual(c.snapshot()["usage"]["total_tokens"], 1100)
        self.assertEqual(c.snapshot()["billing_mode"], "chatgpt")

    def test_chatgpt_usage_limit_records_usage_and_never_falls_back(self):
        reply = response(status="failed")
        reply["error"] = {"code": "subscription_sharing_usage_limit_exceeded"}
        client = FakeClient(reply)
        client.check = lambda: MODEL
        c = Controller(self.root / "bridge", self.root / "runs", billing="chatgpt",
                       bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(c)
        c.start("Reach painting")
        self.until(lambda: c.snapshot()["status"] == "error")
        self.assertEqual(client.generations, 1)
        self.assertEqual(c.snapshot()["usage"]["total_tokens"], 1100)
        self.assertIn("subscription_sharing_usage_limit_exceeded", c.snapshot()["error"])
        self.assertEqual(self.bridge.actions, [])

    def test_explicit_replacement_model_executes_and_cannot_change_on_resume(self):
        reply = response(); reply["model"] = "gpt-6-luna"
        client = FakeClient(reply); c = self.controller(client)
        c.start("Reach painting", continuous=False, model="gpt-6-luna")
        self.until(lambda: c.snapshot()["status"] == "paused" and c.snapshot()["steps"] == 1)
        self.assertEqual(client.body["model"], "gpt-6-luna")
        self.assertEqual(c.snapshot()["model"], "gpt-6-luna")
        self.assertEqual(c.snapshot()["actual_model"], "gpt-6-luna")
        with self.assertRaisesRegex(ValueError, "Stop this run"):
            c.start("Reach painting", model=MODEL)
        self.assertEqual(client.generations, 1)

    def test_missing_plan_model_stops_before_observing_or_generating(self):
        client = FakeClient()
        def check():
            raise ModelError("Selected model not listed; choose another")
        client.check = check
        c = Controller(self.root / "bridge", self.root / "runs", billing="chatgpt",
                       bridge_factory=lambda: self.bridge, client_factory=lambda: client)
        self.controllers.append(c)
        c.start("Reach painting", model="gpt-6-sol")
        self.until(lambda: c.snapshot()["status"] == "error")
        self.assertEqual(client.generations, 0)
        self.assertEqual(self.bridge.counter, 0)

    def test_unpriced_api_selection_is_rejected_before_requests(self):
        client = FakeClient(); c = self.controller(client)
        with self.assertRaisesRegex(ModelError, "verified pricing"):
            c.start("Reach painting", model="account-vision-model")
        self.assertEqual(client.counts, 0)
        self.assertEqual(client.generations, 0)
        self.assertIsNone(c.log)

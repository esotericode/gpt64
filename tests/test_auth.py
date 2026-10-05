import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import request
from urllib.parse import parse_qs, urlsplit, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from gpt64.auth import AuthStore, DIRECT, ISSUER, RESOURCE, validate_identity
from gpt64.model import MODEL, ModelError, PlanClient, read_stream, parse_response


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid="test-key", alg="RS256", use="sig")
        cls.jwks = {"keys": [cls.jwk]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.tmp.name) / "auth")

    def tearDown(self):
        self.tmp.cleanup()

    def identity(self, nonce="nonce", **changes):
        claims = {"iss": ISSUER, "aud": "oaiapp_test", "sub": "test-sub", "email": "same@example.test",
                  "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": nonce, **changes}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test-key"})

    def seed(self, scope=DIRECT, expires=300):
        with self.store.locked():
            self.store.save({"host_id": "urn:uuid:stable", "active": "oaiapp_test", "accounts": {
                "oaiapp_test": {"client_id": "oaiapp_test", "subject": "test-sub", "email": "same@example.test",
                "scopes": [scope], "access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET",
                "expires_at": time.time() + expires}}})

    def test_identity_requires_valid_signature_issuer_audience_expiry_and_nonce(self):
        self.assertEqual(validate_identity(self.identity(), "oaiapp_test", "nonce", self.jwks)["sub"], "test-sub")
        for changes in ({"iss": "https://evil.test"}, {"aud": "other-client"}, {"exp": 0}, {"nonce": "wrong"}, {"sub": ""}):
            with self.subTest(changes=changes), self.assertRaises(ModelError):
                validate_identity(self.identity(**changes), "oaiapp_test", "nonce", self.jwks)
        bad = self.identity().rsplit('.', 1)[0] + '.' + base64.urlsafe_b64encode(b'bad-signature').decode().rstrip('=')
        with self.assertRaises(ModelError):
            validate_identity(bad, "oaiapp_test", "nonce", self.jwks)

    def test_store_public_excludes_tokens_and_os_protects_file(self):
        self.seed()
        self.assertNotIn("SECRET", json.dumps(self.store.public()))
        self.assertTrue(self.store.public()["ready"])
        if os.name == "nt":
            self.assertNotIn(b"ACCESS_SECRET", self.store.path.read_bytes())
        else:
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_missing_plan_permission_never_authorizes_inference(self):
        self.seed(scope="openid")
        self.assertFalse(self.store.public()["ready"])
        with self.assertRaisesRegex(ModelError, "not enabled"):
            self.store.access_token()

    def test_refresh_uses_saved_client_and_rotates_token_atomically(self):
        self.seed(expires=-1)
        tokens = {"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH", "token_type": "Bearer",
                  "expires_in": 3600, "scope": DIRECT}
        with patch("gpt64.auth.auth_request", return_value=tokens) as send:
            self.assertEqual(self.store.access_token(), ("oaiapp_test", "NEW_ACCESS"))
        form = send.call_args.args[1]
        self.assertEqual(form["client_id"], "oaiapp_test")
        self.assertEqual(form["resource"], RESOURCE)
        self.assertNotIn("scope", form)
        self.assertEqual(self.store.load()["accounts"]["oaiapp_test"]["refresh_token"], "NEW_REFRESH")

    def test_process_lock_blocks_competing_credential_mutation(self):
        with self.store.locked():
            with self.assertRaises(ModelError):
                with AuthStore(self.store.directory).locked():
                    pass

    def test_login_verifies_pkce_state_identity_and_reuses_host_and_client(self):
        opened, exchanges, threads = [], [], []
        def browser(url):
            params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
            opened.append(params)
            def callback():
                # A mismatched callback must not redeem its code.
                wrong = params["redirect_uri"] + "?" + urlencode({"state": "wrong", "code": "BAD"})
                try:
                    request.urlopen(wrong, timeout=2).close()
                except Exception:
                    pass
                good = params["redirect_uri"] + "?" + urlencode({"state": params["state"], "code": "GOOD", "client_id": "oaiapp_test"})
                request.urlopen(good, timeout=2).close()
            thread = threading.Thread(target=callback); threads.append(thread); thread.start()
            return True
        def auth(url, form=None):
            if url.endswith("openid-configuration"):
                return {"issuer": ISSUER, "jwks_uri": ISSUER + "/.well-known/jwks.json"}
            if url.endswith("jwks.json"):
                return self.jwks
            exchanges.append(form)
            return {"access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET", "token_type": "Bearer",
                    "expires_in": 3600, "scope": DIRECT, "id_token": self.identity(opened[-1]["nonce"])}
        with patch("gpt64.auth.auth_request", side_effect=auth):
            self.assertTrue(self.store.login(browser_open=browser, timeout=3)["ready"])
            self.store.login(browser_open=browser, timeout=3)
        for thread in threads:
            thread.join(2)
        self.assertEqual(opened[0]["client_id"], "dynamic_agent_client")
        self.assertEqual(opened[1]["client_id"], "oaiapp_test")
        self.assertEqual(opened[0]["ext_agent_host_id"], opened[1]["ext_agent_host_id"])
        self.assertNotIn("agent_name_hint", opened[1])
        for params, form in zip(opened, exchanges):
            self.assertEqual(form["code"], "GOOD")
            self.assertEqual(form["redirect_uri"], params["redirect_uri"])
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
            self.assertEqual(challenge, params["code_challenge"])

    def test_logout_preserves_registration_and_clears_tokens_when_revocation_fails(self):
        self.seed()
        with patch("gpt64.auth.auth_request", side_effect=ModelError("offline")):
            self.assertFalse(self.store.logout())
        saved = self.store.load()
        self.assertEqual(saved["active"], "oaiapp_test")
        self.assertNotIn("access_token", saved["accounts"]["oaiapp_test"])
        self.assertEqual(saved["host_id"], "urn:uuid:stable")


class StreamTest(unittest.TestCase):
    def stream(self, *events):
        return io.BytesIO(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events))

    def test_only_terminal_response_is_used(self):
        final = {"status": "completed", "model": MODEL, "output": [], "usage": {}}
        result = read_stream(self.stream({"type": "response.output_text.delta", "delta": "partial"},
                                        {"type": "response.completed", "response": final}))
        self.assertEqual(result["output"], [])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["_stream_diagnostics"]["output_source"], "none")
        self.assertEqual(result["_stream_diagnostics"]["event_counts"]["response.output_text.delta"], 1)

    def message(self, phase="final_answer"):
        decision = {"commentary": "Mario is at the menu, so I will press Start.", "memory": "Menu.", "done": False,
                    "segments": [{"frames": 4, "x": 0, "y": 0, "buttons": ["Start"]}]}
        return {"id": "msg-test", "type": "message", "role": "assistant", "status": "completed", "phase": phase,
                "content": [{"type": "output_text", "text": json.dumps(decision)}]}

    def envelope(self, status="completed"):
        # Shape and counts from the user's GPT-6 Astra failure: completed,
        # json_schema, nonzero usage, but no output in the terminal event.
        return {"model": "gpt-6-astra", "status": status, "output": [], "text": {"format": {"type": "json_schema"}},
                "usage": {"input_tokens": 634, "output_tokens": 66, "output_tokens_details": {"reasoning_tokens": 0}}}

    def test_finalized_items_recover_missing_null_or_empty_terminal_output(self):
        for output in ("missing", None, []):
            final = self.envelope()
            if output == "missing":
                final.pop("output")
            else:
                final["output"] = output
            message = self.message()
            message["content"][0]["logprobs"] = "PRIVATE_LOGPROBS"
            message["content"][0]["annotations"] = "PRIVATE_ANNOTATIONS"
            message["encrypted_content"] = "PRIVATE_ENCRYPTED"
            result = read_stream(self.stream(
                {"type": "response.output_item.done", "output_index": 0, "item": {"type": "reasoning", "content": "PRIVATE_REASONING"}},
                {"type": "response.output_item.done", "output_index": 1, "item": message},
                {"type": "response.completed", "response": final}))
            with self.subTest(output=output):
                self.assertEqual(parse_response(result, "gpt-6-astra").segments[0].buttons, ("Start",))
                self.assertEqual(result["usage"], final["usage"])
                self.assertEqual(result["_stream_diagnostics"]["output_source"], "completed_events")
                self.assertEqual(result["_stream_diagnostics"]["completed_message_count"], 1)
                self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_finalized_items_keep_phase_refusal_and_index_order(self):
        commentary = self.message("commentary")
        commentary["content"][0]["text"] = "I will inspect the scene."
        result = read_stream(self.stream(
            {"type": "response.output_item.done", "output_index": 3, "item": self.message()},
            {"type": "response.output_item.done", "output_index": 1, "item": commentary},
            {"type": "response.completed", "response": self.envelope()}))
        self.assertEqual([m["phase"] for m in result["output"]], ["commentary", "final_answer"])
        self.assertEqual(parse_response(result, "gpt-6-astra").segments[0].frames, 4)
        refusal = self.message(); refusal["content"] = [{"type": "refusal", "refusal": "declined"}]
        result = read_stream(self.stream({"type": "response.output_item.done", "output_index": 0, "item": refusal},
                                        {"type": "response.completed", "response": self.envelope()}))
        with self.assertRaisesRegex(ModelError, "declined"):
            parse_response(result, "gpt-6-astra")

    def test_terminal_output_is_authoritative_and_items_are_not_appended_twice(self):
        final = self.envelope(); final["output"] = [self.message()]
        result = read_stream(self.stream(
            {"type": "response.output_item.done", "output_index": 0, "item": self.message()},
            {"type": "response.output_item.done", "output_index": 0, "item": self.message()},
            {"type": "response.completed", "response": final}))
        self.assertEqual(len(result["output"]), 1)
        self.assertEqual(result["_stream_diagnostics"]["output_source"], "terminal")
        self.assertEqual(parse_response(result, "gpt-6-astra").segments[0].frames, 4)

    def test_deltas_or_text_done_without_a_finalized_message_cannot_execute(self):
        text = self.message()["content"][0]["text"]
        result = read_stream(self.stream(
            {"type": "response.output_text.delta", "delta": text},
            {"type": "response.output_text.done", "text": text},
            {"type": "response.completed", "response": self.envelope()}))
        with self.assertRaisesRegex(ModelError, "no final answer"):
            parse_response(result, "gpt-6-astra")
        with self.assertRaisesRegex(ModelError, "terminal response"):
            read_stream(self.stream({"type": "response.output_item.done", "output_index": 0, "item": self.message()}))

    def test_conflicting_or_incomplete_done_items_stop_after_accounting(self):
        conflicting = self.message(); conflicting["content"][0]["text"] = "different"
        incomplete = self.message(); incomplete["status"] = "in_progress"
        for events, code in (([
                {"type": "response.output_item.done", "output_index": 0, "item": self.message()},
                {"type": "response.output_item.done", "output_index": 0, "item": conflicting}], "conflicting_completed_items"),
                ([{"type": "response.output_item.done", "output_index": 0, "item": incomplete}], "incomplete_completed_item"),
                ([{"type": "response.output_item.done", "output_index": True, "item": self.message()}], "invalid_completed_item")):
            result = read_stream(self.stream(*events, {"type": "response.completed", "response": self.envelope()}))
            self.assertEqual(result["usage"]["output_tokens"], 66)
            self.assertEqual(result["_stream_diagnostics"]["error"], code)
            with self.assertRaises(ModelError) as failure:
                parse_response(result, "gpt-6-astra")
            self.assertEqual(failure.exception.code, "invalid_stream")

    def test_finalized_message_does_not_override_failed_or_incomplete_terminal_status(self):
        for status in ("failed", "incomplete"):
            result = read_stream(self.stream(
                {"type": "response.output_item.done", "output_index": 0, "item": self.message()},
                {"type": "response." + status, "response": self.envelope(status)}))
            self.assertEqual(result["usage"]["output_tokens"], 66)
            with self.assertRaises(ModelError) as failure:
                parse_response(result, "gpt-6-astra")
            self.assertEqual(failure.exception.code, "incomplete_response")

    def test_streamed_commentary_is_separate_from_the_final_decision(self):
        decision = {"commentary": "Mario is at the menu, so I will press Start.", "memory": "Menu.", "done": False,
                    "segments": [{"frames": 4, "x": 0, "y": 0, "buttons": ["Start"]}]}
        final = {"status": "completed", "model": MODEL, "output": [
            {"type": "message", "phase": "commentary", "content": [{"type": "output_text", "text": "I will inspect the menu."}]},
            {"type": "message", "phase": "final_answer", "content": [{"type": "output_text", "text": json.dumps(decision)}]}]}
        result = read_stream(self.stream({"type": "response.output_text.delta", "delta": "ignored partial JSON"},
                                        {"type": "response.completed", "response": final}))
        self.assertEqual(parse_response(result).segments[0].buttons, ("Start",))

    def test_interrupted_stream_cannot_execute_partial_action(self):
        with self.assertRaisesRegex(ModelError, "terminal"):
            read_stream(self.stream({"type": "response.output_text.delta", "delta": "partial"}))

    def test_failed_terminal_keeps_usage_for_accounting(self):
        final = {"status": "failed", "error": {"code": "subscription_sharing_usage_limit_exceeded"}, "usage": {"input_tokens": 100}}
        result = read_stream(self.stream({"type": "response.failed", "response": final}))
        self.assertEqual(result["usage"], final["usage"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], final["error"])

    def test_plan_request_omits_api_only_fields_and_requires_exact_available_model(self):
        store = unittest.mock.Mock()
        store.access_token.return_value = ("oaiapp_test", "PLAN_SECRET")
        client = PlanClient(store)
        with patch.object(client, "_send", return_value={"models": [{"slug": "other", "visibility": "list"}]}):
            with self.assertRaises(ModelError):
                client.check()
        terminal = self.stream({"type": "response.completed", "response": {"status": "completed"}})
        terminal.headers = {"x-request-id": "req-test"}
        with patch.object(client.opener, "open", return_value=terminal) as send:
            client.generate({"model": MODEL, "input": [], "max_output_tokens": 4096, "service_tier": "default", "store": False})
        body = json.loads(send.call_args.args[0].data)
        self.assertTrue(body["stream"])
        self.assertFalse(body["store"])
        self.assertNotIn("max_output_tokens", body)
        self.assertNotIn("service_tier", body)
        self.assertEqual(body["model"], MODEL)

    def test_plan_catalog_can_select_an_alternative_and_error_lists_choices(self):
        store = unittest.mock.Mock()
        store.access_token.return_value = ("oaiapp_test", "PLAN_SECRET")
        client = PlanClient(store, model="gpt-6-sol")
        with patch.object(client, "_send", return_value={"data": [{"id": "gpt-6-sol"}, {"id": "gpt-6-luna"}]}) as send:
            self.assertEqual(client.check(), "gpt-6-sol")
            self.assertEqual(send.call_args.args, ("models",))
        with patch.object(client, "_send", return_value={"models": [{"slug": "gpt-6-luna", "visibility": "list"}]}):
            with self.assertRaisesRegex(ModelError, "Available: gpt-6-luna"):
                client.check()
        with patch.object(client, "_send", return_value={"unexpected": []}):
            with self.assertRaisesRegex(ModelError, "Unrecognized model catalog"):
                client.check()

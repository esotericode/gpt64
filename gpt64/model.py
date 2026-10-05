"""Explicitly selected vision models through the official Responses API."""

import base64
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from urllib import error, request

from .actions import BUTTONS, Segment, validate_sequence

MODEL = "gpt-6.1-sol"
PRICING_DATE = "2026-10-05"
RATES = {"input": 2.0, "cached": 0.1, "cache_write": 2.5, "output": 10.0}
MODEL_RATES = {
    MODEL: RATES,
    "gpt-6-sol": {"input": 2.0, "cached": 0.2, "cache_write": 2.5, "output": 10.0},
    "gpt-6-luna": {"input": 0.1, "cached": 0.01, "cache_write": 0.125, "output": 0.5},
    "gpt-6-astra": {"input": 10.0, "cached": 1.0, "cache_write": 12.5, "output": 50.0},
}
MAX_OUTPUT = 4096

INSTRUCTIONS = """You play Super Mario 64 using only screenshots and your own executed
controller history. Pursue the user's goal. Never claim access to RAM, world
coordinates, or invisible game state. Images are ordered oldest to newest.
The emulator is paused while you decide. Return controller segments as data;
the harness holds each segment for exactly its frames, releases all controls,
pauses again, and gives you the next screenshot. You do not call emulator APIs.
Stick x positive means right, y positive means up, relative to the game's camera.
Use short actions (usually 4–15 emulator frames) near obstacles; 1–120 frames per
segment, at most 16 segments and 240 frames total. Include explicit button release
segments when useful. Re-observe if unsure; do not blindly repeat failed movement.
Allowed buttons: A, B, Z, Start, L, R, C Up, C Down, C Left, C Right.
Stick axes are numbers from -1 to 1. Empty buttons release buttons; zero axes
center the stick. Buttons stay held for the segment, so use a release segment
between distinct jump presses. Frame durations are emulator ticks, not seconds.
Return a concise public commentary of one or two sentences, at most 280 characters,
that explains the visible cue and selected action. Do not provide private internal
reasoning or step-by-step deliberation. Update compact memory from visible evidence
and action outcomes only. Set done only when screenshots support goal completion.
When done return no segments. Otherwise return one or more segments. A neutral
segment can wait for game animation. Your commentary will be shown before execution.
Your final answer must be one JSON object with exactly commentary, memory, done,
and segments. Each segment has frames, x, y, and buttons. Return raw JSON without
Markdown fences or text outside the object. Keep memory at most 1500 characters.
"""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "commentary": {"type": "string"}, "memory": {"type": "string"},
        "done": {"type": "boolean"},
        "segments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"frames": {"type": "integer"}, "x": {"type": "number"},
                           "y": {"type": "number"}, "buttons": {"type": "array", "items": {"type": "string", "enum": list(BUTTONS)}}},
            "required": ["frames", "x", "y", "buttons"]}},
    }, "required": ["commentary", "memory", "done", "segments"]}


class ModelError(RuntimeError):
    pass


class ResponseError(ModelError):
    """A response rejection with a stable, non-secret diagnostic code."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message + "; no action was executed. Download run ZIP for diagnostics.")


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise ValueError("Invalid model ID; use an ID from your account's model list")
    return value


def model_rates(model):
    rates = MODEL_RATES.get(model_id(model))
    if rates is None:
        raise ModelError("Paid API mode requires a model with verified pricing: " + ", ".join(MODEL_RATES))
    return rates


def model_catalog(value):
    """Normalize plan and API catalogs without exposing raw provider metadata."""
    entries = value.get("models", value.get("data"))
    if not isinstance(entries, list):
        raise ModelError("Unrecognized model catalog response. Refresh models or sign in again; no inference was sent.")
    models, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ModelError("Malformed model catalog entry; no inference was sent")
        if entry.get("visibility", "list") != "list":
            continue
        try:
            slug = model_id(entry.get("slug", entry.get("id")))
        except ValueError:
            raise ModelError("Malformed model ID in catalog; no inference was sent") from None
        if slug in seen:
            continue
        seen.add(slug)
        label = entry.get("display_name") or slug
        if not isinstance(label, str):
            label = slug
        models.append({"id": slug, "display_name": label[:160], "profile_known": slug in MODEL_RATES})
    return models


def response_model_matches(actual, selected):
    return isinstance(actual, str) and (actual == selected or
        re.fullmatch(re.escape(selected) + r"-\d{4}-\d{2}-\d{2}", actual) is not None)


def brief_commentary(text):
    if not isinstance(text, str) or not text.strip():
        raise ModelError("The model returned empty commentary")
    text = " ".join(text.split())
    # The UI receives a bounded public summary, never an unbounded text stream.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2])
    if len(text) > 280:
        text = text[:277].rsplit(" ", 1)[0].rstrip(".!?") + "…"
    return text


@dataclass(frozen=True)
class Decision:
    commentary: str
    memory: str
    done: bool
    segments: tuple[Segment, ...]

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != {"commentary", "memory", "done", "segments"}:
            raise ModelError("Invalid structured decision")
        if type(value["done"]) is not bool or not isinstance(value["memory"], str) or len(value["memory"]) > 1500:
            raise ModelError("Invalid completion flag or memory")
        if not isinstance(value["segments"], list) or len(value["segments"]) > 16:
            raise ModelError("Invalid segment array")
        try:
            segments = tuple(Segment(**item) for item in value["segments"])
            if value["done"]:
                if segments:
                    raise ValueError("Completed decisions must have no inputs")
            else:
                segments = validate_sequence(segments)
        except (TypeError, ValueError) as e:
            raise ModelError(f"Rejected unsafe model action: {e}") from e
        return cls(brief_commentary(value["commentary"]), value["memory"], value["done"], segments)

    def public(self):
        return {"commentary": self.commentary, "memory": self.memory, "done": self.done,
                "segments": [asdict(s) for s in self.segments]}


def payload(goal, images, history, memory, effort="medium", model=MODEL):
    model_id(model)
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1500:
        raise ValueError("Goal must be 1–1500 characters")
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ValueError("Unsupported reasoning effort")
    content = [{"type": "input_text", "text": json.dumps({"goal": goal, "memory": memory,
               "executed_actions": history[-8:]}, ensure_ascii=False)}]
    for image in images[-4:]:
        data = Path(image).read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 10_000_000:
            raise ModelError("Expected a PNG screenshot smaller than 10 MB")
        content.append({"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(data).decode(), "detail": "high"})
    if len(content) < 2:
        raise ModelError("At least one screenshot is required")
    body = {"model": model, "instructions": INSTRUCTIONS, "input": [{"role": "user", "content": content}],
            "max_output_tokens": MAX_OUTPUT, "store": False,
            "service_tier": "default", "text": {"format": {
                "type": "json_schema", "name": "mario_decision", "strict": True, "schema": SCHEMA}}}
    if model in MODEL_RATES:
        body["reasoning"] = {"effort": effort}
    return body


def usage_summary(response, model=MODEL, api_pricing=True):
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise ModelError("API returned no usage; charge is unknown, so the run stops")
    def count(obj, key, default=None):
        n = obj.get(key, default)
        if type(n) is not int or n < 0:
            raise ModelError("Invalid API usage; charge is unknown")
        return n
    inp, out = count(usage, "input_tokens"), count(usage, "output_tokens")
    details = usage.get("input_tokens_details") or {}
    cached, writes = count(details, "cached_tokens", 0), count(details, "cache_write_tokens", 0)
    reasoning = count(usage.get("output_tokens_details") or {}, "reasoning_tokens", 0)
    if cached + writes > inp or reasoning > out:
        raise ModelError("Inconsistent API token counts")
    cost = 0
    if api_pricing:
        rates = model_rates(model)
        cost = ((inp - cached - writes) * rates["input"] + cached * rates["cached"] +
                writes * rates["cache_write"] + out * rates["output"]) / 1_000_000
    # output_tokens already includes reasoning tokens. Never add them twice.
    return {"input_tokens": inp, "output_tokens": out, "cached_tokens": cached,
            "cache_write_tokens": writes, "reasoning_tokens": reasoning,
            "total_tokens": inp + out, "estimated_usd": cost}


def reserve_cost(input_tokens, model=MODEL):
    if type(input_tokens) is not int or not 1 <= input_tokens <= 100_000:
        raise ModelError("Input token count is invalid or exceeds the 100,000-token cap")
    rates = model_rates(model)
    return (input_tokens * max(rates["input"], rates["cache_write"]) + MAX_OUTPUT * rates["output"]) / 1_000_000


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class OpenAIClient:
    billing_mode = "api"
    def __init__(self, key=None, timeout=120, model=MODEL):
        self.model = model_id(model)
        self.key = key or os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise ModelError("OPENAI_API_KEY is missing. Set it in the PowerShell window that starts gpt64.")
        self.timeout = timeout
        self.opener = request.build_opener(NoRedirect)

    def _send(self, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = request.Request("https://api.openai.com/v1/" + path, data=body,
                              headers={"Authorization": "Bearer " + self.key,
                                       "Content-Type": "application/json", "User-Agent": "gpt64/0.4.1"})
        try:
            with self.opener.open(req, timeout=self.timeout) as reply:
                result = json.load(reply)
                if not isinstance(result, dict):
                    raise ModelError("Malformed API response")
                result["_request_id"] = reply.headers.get("x-request-id")
                return result
        except error.HTTPError as e:
            hints = {401: "Check your local API key", 403: "Check project/model permissions",
                     404: "The selected model or endpoint is unavailable to this account; refresh the model list",
                     429: "Check API credit, limits, and rate limits"}
            if self.billing_mode == "chatgpt":
                hints.update({401: "Continue with ChatGPT again and grant plan usage", 403: "Check ChatGPT account eligibility, region and model permissions",
                              429: "ChatGPT allowance may be exhausted; open ChatGPT Settings > Usage", 503: "ChatGPT plan routing is unavailable"})
            # Do not echo provider bodies or request headers into logs.
            raise ModelError(f"OpenAI HTTP {e.code}. {hints.get(e.code, 'Check API service status')}. "
                             f"Request ID: {e.headers.get('x-request-id', 'unavailable')}. No automatic retry.") from None
        except (error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ModelError("OpenAI request failed or timed out; no automatic retry. "
                             "A generation request may have incurred usage.") from None

    def check(self):
        model_rates(self.model)
        value = self._send("models/" + self.model)
        if value.get("id") != self.model:
            raise ModelError("Model check did not return the requested model")
        return self.model

    def models(self):
        return model_catalog(self._send("models"))

    def count(self, body):
        # Token counting supports the same input and output schema context.
        value = self._send("responses/input_tokens", {k: body[k] for k in ("model", "instructions", "input", "text", "reasoning") if k in body})
        tokens = value.get("input_tokens")
        reserve_cost(tokens, self.model)
        return tokens

    def generate(self, body):
        return self._send("responses", body)


def read_stream(reply):
    """Read through the terminal SSE event; never expose reasoning deltas."""
    data, size = [], 0
    for raw in reply:
        size += len(raw)
        if len(raw) > 4_000_000 or size > 64_000_000:
            raise ModelError("Response stream exceeded the local size limit; usage is unconfirmed")
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            event = json.loads("\n".join(data)); data = []
            kind = event.get("type")
            if kind in ("response.completed", "response.failed", "response.incomplete"):
                response = event.get("response")
                if not isinstance(response, dict):
                    raise ModelError("Response stream returned no terminal response")
                return response
            if kind == "error":
                code = event.get("code", "unknown_error")
                safe = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", code) else "unknown_error"
                raise ModelError(f"ChatGPT stream error: {safe}. Check ChatGPT Settings > Usage. No automatic retry or API billing fallback.")
    raise ModelError("ChatGPT stream ended before a terminal response; usage is unconfirmed. No retry was sent.")


class PlanClient(OpenAIClient):
    billing_mode = "chatgpt"

    def __init__(self, store=None, timeout=120, model=MODEL):
        self.model = model_id(model)
        from .auth import AuthStore
        self.store = store or AuthStore()
        self.client_id, self.key = self.store.access_token()
        self.timeout = timeout
        self.opener = request.build_opener(NoRedirect)

    def check(self):
        models = self.models()
        if not any(m["id"] == self.model for m in models):
            available = ", ".join(m["id"] for m in models[:30]) or "none"
            raise ModelError(f"This ChatGPT account does not list {self.model}. Available: {available}. "
                             "Choose a listed model in Run controls or use serve --model MODEL_ID. No paid API fallback was selected.")
        return self.model

    def models(self):
        self.client_id, self.key = self.store.access_token(self.client_id)
        return super().models()

    def generate(self, body):
        self.client_id, self.key = self.store.access_token(self.client_id)
        body = {k: v for k, v in body.items() if k not in ("max_output_tokens", "service_tier")}
        body.update(store=False, stream=True)
        req = request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                              headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                                       "Accept": "text/event-stream", "User-Agent": "gpt64/0.4.1"})
        try:
            with self.opener.open(req, timeout=self.timeout) as reply:
                result = read_stream(reply)
                result["_request_id"] = reply.headers.get("x-request-id")
                return result
        except error.HTTPError as exc:
            code, shape = "unknown_error", "unknown"
            try:
                body = json.loads(exc.read(8192))
                shape = "error" if isinstance(body.get("error"), dict) else "detail" if "detail" in body else "other"
                candidate = (body.get("error") or {}).get("code") if shape == "error" else None
                if isinstance(candidate, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", candidate):
                    code = candidate
            except (ValueError, AttributeError):
                pass
            raise ModelError(f"ChatGPT HTTP {exc.code}; {shape} response; code {code}; request ID {exc.headers.get('x-request-id', 'unavailable')}. "
                             "Check ChatGPT Settings > Usage or sign-in permissions. No retry or paid API fallback.") from None
        except (error.URLError, TimeoutError, OSError, ValueError):
            raise ModelError("ChatGPT stream failed or timed out; plan usage may have occurred. No retry or paid API fallback.") from None


def decision_message(response):
    """Select one structured answer, following the SDK's message-phase rule.

    Explicit phases other than final_answer are never structured results. Old
    models may omit phase. Never guess between multiple eligible messages or
    combine commentary with an answer, even if commentary happens to be JSON.
    """
    output = response.get("output")
    if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
        raise ResponseError("invalid_output", "Provider returned a malformed output array")
    messages = [item for item in output if item.get("type") == "message"
                and item.get("role", "assistant") == "assistant"
                and item.get("phase") in (None, "final_answer")]
    if not messages:
        raise ResponseError("missing_answer", "Model returned no final answer (only commentary, reasoning, or empty output)")
    if len(messages) != 1:
        raise ResponseError("multiple_answers", "Model returned multiple possible final answers")
    message = messages[0]
    if message.get("status", "completed") != "completed":
        raise ResponseError("incomplete_message", "Model's final answer message was not completed")
    parts = message.get("content")
    if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
        raise ResponseError("invalid_content", "Provider returned malformed final-answer content")
    return message


def decision_text(message):
    texts = []
    for part in message["content"]:
        if part.get("type") == "refusal":
            raise ResponseError("refusal", "Model declined the request")
        if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
            raise ResponseError("invalid_text", "Provider returned unexpected final-answer content")
        texts.append(part["text"])
    text = "".join(texts)
    if not text.strip():
        raise ResponseError("empty_answer", "Model returned an empty final answer")
    return text


def response_diagnostics(response, model=MODEL):
    """Allowlisted shape metadata plus a bounded public final answer.

    Never serialize whole responses: they can contain private reasoning,
    encrypted content, echoed screenshots/instructions, and provider metadata.
    """
    def label(value):
        return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) else None
    result = {"selected_model": model, "output_items": []}
    output = response.get("output")
    if isinstance(output, list):
        for item in output[:64]:
            info = {"type": label(item.get("type"))} if isinstance(item, dict) else {"type": None}
            if isinstance(item, dict) and item.get("type") == "message":
                info.update(role=label(item.get("role")), phase=label(item.get("phase")), status=label(item.get("status")))
                parts = item.get("content")
                if isinstance(parts, list):
                    info["content_types"] = [label(p.get("type")) if isinstance(p, dict) else None for p in parts[:64]]
                    info["text_characters"] = sum(len(p["text"]) for p in parts if isinstance(p, dict)
                                                  and p.get("type") == "output_text" and isinstance(p.get("text"), str))
            result["output_items"].append(info)
        result["output_item_count"] = len(output)
    for source, key in ((response.get("text"), "format"), (response.get("incomplete_details"), "reason"),
                        (response.get("error"), "code")):
        if isinstance(source, dict):
            value = source.get(key)
            if key == "format":
                value = value.get("type") if isinstance(value, dict) else None
            result[{"format": "returned_format", "reason": "incomplete_reason", "code": "provider_error_code"}[key]] = label(value)
    try:
        text = decision_text(decision_message(response))
        result.update(answer_text=text[:16384], answer_characters=len(text), answer_truncated=len(text) > 16384)
    except ResponseError as exc:
        result["selection_error"] = exc.code
    return result


def parse_response(response, model=MODEL):
    if not isinstance(response, dict):
        raise ResponseError("invalid_response", "Provider returned a malformed response")
    if not response_model_matches(response.get("model"), model):
        raise ResponseError("unexpected_model", "Provider returned an unexpected model")
    if response.get("status") != "completed":
        details = response_diagnostics(response, model)
        code = details.get("provider_error_code") or details.get("incomplete_reason")
        raise ResponseError("incomplete_response", "Model response was incomplete or failed" +
                            (f". Code: {code}. For plan limits, open ChatGPT Settings > Usage" if code else ""))
    text = decision_text(decision_message(response))
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        kind = "Markdown-fenced text instead of raw JSON" if text.lstrip().startswith("```") else "invalid JSON"
        raise ResponseError("invalid_json", f"Model's final answer was {kind} (line {exc.lineno}, column {exc.colno})") from exc
    try:
        return Decision.parse(value)
    except ModelError as exc:
        raise ResponseError("invalid_decision", str(exc)) from exc

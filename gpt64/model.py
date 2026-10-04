"""GPT-6.1 Sol vision decisions through the official Responses API."""

import base64
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from urllib import error, request

from .actions import BUTTONS, Segment, validate_sequence

MODEL = "gpt-6.1-sol"
PRICING_DATE = "2026-10-04"
RATES = {"input": 2.0, "cached": 0.1, "cache_write": 2.5, "output": 10.0}
MAX_OUTPUT = 4096

INSTRUCTIONS = """You play Super Mario 64 using only screenshots and your own executed
controller history. Pursue the user's goal. Never claim access to RAM, world
coordinates, or invisible game state. Images are ordered oldest to newest.
Stick x positive means right, y positive means up, relative to the game's camera.
Use short actions (usually 4–15 emulator frames) near obstacles; 1–120 frames per
segment, at most 16 segments and 240 frames total. Include explicit button release
segments when useful. Re-observe if unsure; do not blindly repeat failed movement.
Return a concise public commentary of one or two sentences, at most 280 characters,
that explains the visible cue and selected action. Do not provide private internal
reasoning or step-by-step deliberation. Update compact memory from visible evidence
and action outcomes only. Set done only when screenshots support goal completion.
When done return no segments. Otherwise return one or more segments. A neutral
segment can wait for game animation. Your commentary will be shown before execution.
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


def payload(goal, images, history, memory, effort="medium"):
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
    return {"model": MODEL, "instructions": INSTRUCTIONS, "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": effort}, "max_output_tokens": MAX_OUTPUT, "store": False,
            "service_tier": "default", "text": {"format": {
                "type": "json_schema", "name": "mario_decision", "strict": True, "schema": SCHEMA}}}


def usage_summary(response):
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
    cost = ((inp - cached - writes) * RATES["input"] + cached * RATES["cached"] +
            writes * RATES["cache_write"] + out * RATES["output"]) / 1_000_000
    # output_tokens already includes reasoning tokens. Never add them twice.
    return {"input_tokens": inp, "output_tokens": out, "cached_tokens": cached,
            "cache_write_tokens": writes, "reasoning_tokens": reasoning,
            "total_tokens": inp + out, "estimated_usd": cost}


def reserve_cost(input_tokens):
    if type(input_tokens) is not int or not 1 <= input_tokens <= 100_000:
        raise ModelError("Input token count is invalid or exceeds the 100,000-token cap")
    return (input_tokens * RATES["cache_write"] + MAX_OUTPUT * RATES["output"]) / 1_000_000


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class OpenAIClient:
    def __init__(self, key=None, timeout=120):
        self.key = key or os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise ModelError("OPENAI_API_KEY is missing. Set it in the PowerShell window that starts gpt64.")
        self.timeout = timeout
        self.opener = request.build_opener(NoRedirect)

    def _send(self, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = request.Request("https://api.openai.com/v1/" + path, data=body,
                              headers={"Authorization": "Bearer " + self.key,
                                       "Content-Type": "application/json", "User-Agent": "gpt64/0.2"})
        try:
            with self.opener.open(req, timeout=self.timeout) as reply:
                result = json.load(reply)
                if not isinstance(result, dict):
                    raise ModelError("Malformed API response")
                result["_request_id"] = reply.headers.get("x-request-id")
                return result
        except error.HTTPError as e:
            hints = {401: "Check your local API key", 403: "Check project/model permissions",
                     404: "The exact gpt-6.1-sol model or endpoint is unavailable to this account",
                     429: "Check API credit, limits, and rate limits"}
            # Do not echo provider bodies or request headers into logs.
            raise ModelError(f"OpenAI HTTP {e.code}. {hints.get(e.code, 'Check API service status')}. "
                             f"Request ID: {e.headers.get('x-request-id', 'unavailable')}. No automatic retry.") from None
        except (error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ModelError("OpenAI request failed or timed out; no automatic retry. "
                             "A generation request may have incurred usage.") from None

    def check(self):
        value = self._send("models/" + MODEL)
        if value.get("id") != MODEL:
            raise ModelError("Model check did not return the requested model")
        return MODEL

    def count(self, body):
        # Token counting supports the same input and output schema context.
        value = self._send("responses/input_tokens", {k: body[k] for k in ("model", "instructions", "input", "text", "reasoning")})
        tokens = value.get("input_tokens")
        reserve_cost(tokens)
        return tokens

    def generate(self, body):
        return self._send("responses", body)


def parse_response(response):
    if response.get("model") != MODEL:
        raise ModelError("API returned an unexpected model; no fallback is allowed")
    if response.get("status") != "completed":
        raise ModelError("Model response was incomplete or failed; no action was executed")
    texts = []
    for item in response.get("output", []):
        # Ignore reasoning items entirely. Only the public structured answer is used.
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise ModelError("Model declined the request; no action was executed")
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
    try:
        return Decision.parse(json.loads("".join(texts)))
    except (ValueError, TypeError) as e:
        raise ModelError("Model response was not a valid structured decision") from e

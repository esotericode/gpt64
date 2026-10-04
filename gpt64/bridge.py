"""Local mailbox transport with one in-flight action and no automatic replay."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import uuid

from .actions import Segment, validate_sequence


class BridgeError(RuntimeError):
    pass


def atomic_json(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class Observation:
    image: Path
    frame_before: int
    frame_after: int
    advanced: int
    request_id: str


class Bridge:
    def __init__(self, root: Path | str, timeout: float = 20):
        self.root = Path(root).resolve()
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("timeout must be positive and finite")
        self.timeout = timeout
        self._locked = False
        self.ready = None

    def __enter__(self):
        if not self.root.is_dir():
            raise BridgeError("Bridge directory missing. Run: py -m gpt64 init")
        try:
            with (self.root / "client.lock").open("x", encoding="utf-8") as f:
                f.write("one client owns this bridge\n")
        except FileExistsError as e:
            raise BridgeError("Another client owns the bridge, or a previous client was interrupted. "
                              "Stop Lua and run init --reset before recovering.") from e
        self._locked = True
        try:
            if (self.root / "pending.json").exists():
                raise BridgeError("An earlier action has an unconfirmed result. "
                                  "Stop Lua and run init --reset; do not replay it blindly.")
            self.ready = self._read_ready()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self._locked:
            (self.root / "client.lock").unlink(missing_ok=True)
            self._locked = False

    def _read_ready(self):
        try:
            ready = json.loads((self.root / "ready.json").read_text(encoding="utf-8"))
            if ready["version"] != 1 or ready["system"] != "N64" or not ready["session"]:
                raise ValueError("unsupported bridge")
            return ready
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise BridgeError("Bridge not ready. Load the generated start.lua in BizHawk with an N64 ROM.") from e

    def observe(self) -> Observation:
        return self._request(())

    def step(self, segments) -> Observation:
        return self._request(validate_sequence(segments))

    def _request(self, segments) -> Observation:
        if not self._locked:
            raise BridgeError("Use Bridge as a context manager")
        pending = self.root / "pending.json"
        if pending.exists():
            raise BridgeError("Previous action unconfirmed; reset before sending another")
        if self._read_ready()["session"] != self.ready["session"]:
            raise BridgeError("Lua bridge restarted; open a new client")
        request_id = uuid.uuid4().hex
        session = self.ready["session"]
        expected = sum(s.frames for s in segments)
        wire = "\n".join(["GPT64 1", session, request_id, str(len(segments)),
                           *(s.wire() for s in segments)]) + "\n"
        record = {"id": request_id, "session": session,
                  "time": datetime.now(timezone.utc).isoformat(),
                  "segments": [asdict(s) for s in segments]}
        atomic_json(pending, record)
        temporary = self.root / "request.tmp"
        temporary.write_text(wire, encoding="ascii")
        temporary.replace(self.root / "request.txt")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                reply = json.loads((self.root / "responses" / f"{request_id}.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if not isinstance(reply, dict):
                raise BridgeError("Malformed emulator response; stop Lua and reset before continuing")
            if reply.get("id") != request_id or reply.get("session") != session:
                time.sleep(0.02)
                continue
            # Only a confirmed, fully validated outcome clears the pending marker.
            if reply.get("ok") is not True:
                raise BridgeError(f"Emulator rejected or failed the request: {reply.get('error')}. "
                                  "Stop Lua and reset before continuing.")
            before, after = reply.get("frame_before"), reply.get("frame_after")
            if (type(before) is not int or type(after) is not int or
                    after - before != expected or reply.get("advanced") != expected or
                    reply.get("paused") is not True):
                raise BridgeError("Frame/pause invariant failed; stop Lua and reset before continuing")
            filename = f"{request_id}.png"
            if reply.get("image") != filename:
                raise BridgeError("Invalid screenshot filename")
            path = self.root / "images" / filename
            try:
                with path.open("rb") as f:
                    if f.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise BridgeError("Screenshot is not a PNG")
            except OSError as e:
                raise BridgeError("Screenshot was not written") from e
            with (self.root / "actions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({**record, "result": reply}) + "\n")
            pending.unlink()
            return Observation(path, before, after, expected, request_id)
        raise BridgeError("Timed out; the action may have executed. No retry was sent. "
                          "Stop Lua and run init --reset before continuing.")

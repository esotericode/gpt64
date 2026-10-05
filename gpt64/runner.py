"""Serialized game/agent worker, public state, and durable experiment records."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
import zlib
import struct

from .actions import Segment
from .bridge import Bridge, BridgeError, Observation, atomic_json
from .model import (MODEL, MODEL_RATES, PRICING_DATE, Decision, ModelError, OpenAIClient, PlanClient,
                    model_id, model_rates, parse_response, payload, reserve_cost, response_model_matches, usage_summary)


def now():
    return datetime.now(timezone.utc).isoformat()


class RunLog:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "screens").mkdir()
        (directory / "api").mkdir()

    def event(self, kind, **data):
        value = {"time": now(), "event": kind, **data}
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return value

    def save(self, state):
        atomic_json(self.directory / "state.json", state)


class Controller:
    def __init__(self, bridge_root, runs_root, demo=False, effort="medium",
                 bridge_factory=None, client_factory=None, billing="api", auth_store=None, model=None, settings=None):
        self.bridge_root = Path(bridge_root).resolve()
        self.runs_root = Path(runs_root).resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.demo, self.effort = demo, effort
        self.settings = settings
        self.preferences = settings.load() if settings else {"model": MODEL, "goal": "", "max_steps": 10, "budget_usd": .25}
        self.model = model_id(model or self.preferences["model"])
        if billing not in ("api", "chatgpt", "claude"):
            raise ValueError("Choose api, chatgpt, or claude billing")
        self.billing = billing
        from .auth import AuthStore
        self.auth_store = auth_store or AuthStore()
        self.auth_worker = None
        self.auth_status, self.auth_error = "idle", None
        self.bridge_factory = bridge_factory or (lambda: DemoBridge(self.runs_root / "preview") if demo else Bridge(self.bridge_root))
        self.client_factory = client_factory or (lambda: PlanClient(self.auth_store, model=self.model) if billing == "chatgpt" else OpenAIClient(model=self.model))
        self.catalog = {"status": "idle", "models": [], "error": None}
        self.condition = threading.Condition(threading.RLock())
        self.worker = None
        self.log = None
        self.stopping = False
        self.continuous = False
        self.permits = 0
        self.images, self.history = [], []
        self.memory = ""
        self.external_proposal = None
        self.state = self.initial_state()

    def initial_state(self):
        return {"run_id": None, "status": "idle", "model": self.model, "actual_model": None, "demo": self.demo,
                "key_present": bool(os.environ.get("OPENAI_API_KEY")), "goal": self.preferences["goal"],
                "steps": 0, "decisions": 0, "max_steps": self.preferences["max_steps"], "budget_usd": self.preferences["budget_usd"],
                "usage": {k: 0 for k in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens", "reasoning_tokens", "total_tokens", "estimated_usd")},
                "reserved_usd": 0, "usage_unknown": False, "commentary": "Ready when you are.",
                "segments": [], "image_url": None, "events": [], "error": None,
                "latency_seconds": None, "updated": now(), "reasoning_effort": self.effort if self.model in MODEL_RATES else "provider default",
                "pricing_date": PRICING_DATE, "rates_per_million": MODEL_RATES.get(self.model), "pending_decision": False,
                "usage_available": self.billing != "claude", "observation_id": None}

    def snapshot(self):
        with self.condition:
            state = json.loads(json.dumps(self.state))
            state["billing_mode"] = "demo" if self.demo else self.billing
            if self.billing == "chatgpt" and not self.demo:
                try:
                    state["auth"] = self.auth_store.public()
                except ModelError as exc:
                    state["auth"] = {"ready": False, "accounts": [], "label": "Credential error", "active": None, "welcome": False}
                    state["auth_error"] = str(exc)
            state["auth_status"] = self.auth_status
            state["auth_error"] = state.get("auth_error") or self.auth_error
            state["model_catalog"] = json.loads(json.dumps(self.catalog))
            state["preferences"] = {k: self.preferences[k] for k in ("model", "goal", "max_steps", "budget_usd")}
            return state

    def save_preferences(self, changes):
        from .paths import Settings
        with self.condition:
            if self.worker and self.worker.is_alive():
                raise ValueError("Stop the run before changing saved preferences")
            if set(changes) - {"model", "goal", "max_steps", "budget_usd"}:
                raise ValueError("Only run preferences can be changed in the dashboard")
            Settings.validate(changes)
            self.preferences.update(changes)
            if self.settings:
                self.settings.save(changes)
            if "model" in changes:
                self.model = changes["model"]
                if not self.state["run_id"]:
                    self._update(model=self.model)

    def refresh_models(self):
        with self.condition:
            if self.demo or self.billing == "claude":
                raise ValueError("Choose Claude models with /model in the official Claude app; demo mode makes no model requests")
            if (self.worker and self.worker.is_alive()) or (self.auth_worker and self.auth_worker.is_alive()) or self.catalog["status"] == "loading":
                raise ValueError("Stop active work and wait for sign-in/model refresh before refreshing models")
            self.catalog = {"status": "loading", "models": [], "error": None}
        try:
            models = self.client_factory().models()
            with self.condition:
                self.catalog = {"status": "ready", "models": models, "error": None}
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ModelError, ValueError)) else "Model catalog request failed locally"
            with self.condition:
                self.catalog = {"status": "error", "models": [], "error": message}
            raise ModelError(message) from None

    def account_action(self, action, account=None, new=False, enable_plan=False):
        with self.condition:
            if self.demo or self.billing != "chatgpt":
                raise ValueError("ChatGPT sign-in is available in ChatGPT plan mode")
            if (self.worker and self.worker.is_alive()) or (self.auth_worker and self.auth_worker.is_alive()) or self.catalog["status"] == "loading":
                raise ValueError("Stop the active work before changing ChatGPT accounts")
            if action != "ack":
                self.catalog = {"status": "idle", "models": [], "error": None}
            if action == "ack":
                self.auth_store.acknowledge()
            elif action == "select":
                self.auth_store.select(account)
            elif action in ("login", "logout"):
                self.auth_status, self.auth_error = "signing_in" if action == "login" else "signing_out", None
                def work():
                    try:
                        if action == "login":
                            self.auth_store.login(new=new, enable_plan=enable_plan)
                        elif not self.auth_store.logout():
                            raise ModelError("Signed out locally; remote revocation was not confirmed. Disconnect gpt64 in ChatGPT Settings.")
                    except Exception as exc:
                        self.auth_error = str(exc) if isinstance(exc, ModelError) else "ChatGPT authentication failed locally"
                    finally:
                        self.auth_status = "idle"
                self.auth_worker = threading.Thread(target=work, daemon=True)
                self.auth_worker.start()
            else:
                raise ValueError("Unknown account action")

    def _update(self, **data):
        with self.condition:
            self.state.update(data, updated=now())
            if self.log:
                self.log.save(self.state)

    def _event(self, kind, **data):
        with self.condition:
            value = self.log.event(kind, **data) if self.log else {"time": now(), "event": kind, **data}
            self.state["events"] = (self.state["events"] + [value])[-100:]
            if self.log:
                self.log.save(self.state)

    def start(self, goal, max_steps=100, budget_usd=1, continuous=True, model=None):
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1500:
            raise ValueError("Enter a goal of 1–1500 characters")
        if type(max_steps) is not int or not 1 <= max_steps <= 10000:
            raise ValueError("Decision limit must be 1–10000")
        if isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)) or not math.isfinite(budget_usd) or not 0 < budget_usd <= 1000:
            raise ValueError("Budget must be between $0 and $1000")
        with self.condition:
            selected = model_id(self.model if model is None else model)
            if self.worker and self.worker.is_alive():
                if selected != self.model:
                    raise ValueError("Stop this run before choosing a different model")
                if self.stopping or self.state["status"] != "paused":
                    raise ValueError("A run is already active")
                self.continuous, self.permits = continuous, 0 if continuous else 1
                self.condition.notify_all()
                return
            if (self.auth_worker and self.auth_worker.is_alive()) or self.catalog["status"] == "loading":
                raise ValueError("Wait for ChatGPT sign-in/model refresh to finish")
            if not self.demo and self.billing == "api":
                model_rates(selected)
            self.save_preferences({"model": selected, "goal": goal.strip(), "max_steps": max_steps, "budget_usd": float(budget_usd)})
            self.model = selected
            # Validate credentials before creating a live run. Never include them in state/logs.
            client = None if self.demo or self.billing == "claude" else self.client_factory()
            self.log = RunLog(self.runs_root / uuid.uuid4().hex)
            self.state = self.initial_state()
            self._update(run_id=self.log.directory.name, goal=goal.strip(), max_steps=max_steps,
                         budget_usd=float(budget_usd), status="starting", billing_mode="demo" if self.demo else self.billing)
            self.images, self.history, self.memory = [], [], ""
            self.external_proposal = None
            self.stopping = False
            self.continuous, self.permits = continuous, 0 if continuous else 1
            self._event("run_started", model="Chosen in Claude Code" if self.billing == "claude" else self.model, demo=self.demo, goal=goal.strip(),
                        max_steps=max_steps, budget_usd=budget_usd, pricing_date=PRICING_DATE, billing_mode=self.state["billing_mode"])
            if self.billing == "claude" and not self.demo:
                self._update(model="Chosen in Claude Code", actual_model=None, reasoning_effort="Chosen in Claude Code", rates_per_million=None)
            self.worker = threading.Thread(target=self._run_external if self.billing == "claude" and not self.demo else self._run, args=() if self.billing == "claude" and not self.demo else (client,), daemon=True)
            self.worker.start()

    def pause(self):
        with self.condition:
            self.continuous, self.permits = False, 0
            self._event("pause_requested")
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.stopping = True
            self._event("stop_requested")
            if self.worker and self.worker.is_alive():
                self._update(status="stopping")
            self.condition.notify_all()

    def close(self):
        self.stop()
        if self.worker:
            self.worker.join(timeout=5)
            if self.worker.is_alive():
                self._event("shutdown_with_inflight_work", reserved_usd=self.state["reserved_usd"])

    def _permission(self):
        with self.condition:
            while not self.stopping and not self.continuous and not self.permits:
                self._update(status="paused")
                self.condition.wait()
            return not self.stopping

    def _capture(self, observation):
        with self.condition:
            if self.log:
                filename = f"{len(self.images):04d}-{observation.request_id}.png"
                target = self.log.directory / "screens" / filename
                url = f"/api/runs/{self.state['run_id']}/screens/{filename}"
            else:
                directory = self.runs_root / "preview"
                directory.mkdir(exist_ok=True)
                filename = observation.request_id + ".png"
                target = directory / filename
                url = "/api/preview/" + filename
            if target != observation.image:
                shutil.copyfile(observation.image, target)
            self.images.append(target)
            self._update(image_url=url, observation_id=observation.request_id)
            self._event("observation", image=filename, advanced=observation.advanced,
                        frame_before=observation.frame_before, frame_after=observation.frame_after)

    def observe(self):
        with self.condition:
            if self.worker and self.worker.is_alive():
                raise ValueError("Pause/stop the active run; its screenshots refresh after actions")
            self.log = None
            self.images = []
            self.state = self.initial_state()
            self._update(status="observing", error=None, run_id=None)
            self.worker = threading.Thread(target=self._observe, daemon=True)
            self.worker.start()

    def _observe(self):
        try:
            with self.bridge_factory() as bridge:
                self._capture(bridge.observe())
            self._update(status="idle")
        except Exception as e:
            self._fail(e)

    def _fail(self, exc):
        # Operational exceptions contain no headers or API key. Unexpected errors
        # expose their type only; keep secrets out of dashboard and event files.
        message = str(exc) if isinstance(exc, (BridgeError, ModelError, ValueError)) else f"{type(exc).__name__}: unexpected local failure"
        self._update(status="error", error=message)
        self._event("error", message=message)

    def external_observation(self):
        import base64
        with self.condition:
            if self.billing != "claude" or self.demo:
                raise ValueError("Game MCP controls require the Claude dashboard mode")
            if not self.images or not self.state["run_id"]:
                raise ValueError("Click Start run or One decision in the dashboard first")
            return {"run_id": self.state["run_id"], "observation_id": self.state["observation_id"],
                    "goal": self.state["goal"], "status": self.state["status"], "pending_decision": self.state["pending_decision"],
                    "decisions": self.state["decisions"], "max_steps": self.state["max_steps"],
                    "memory": self.memory, "executed_actions": self.history[-8:],
                    "image": {"type": "image", "mimeType": "image/png", "data": base64.b64encode(self.images[-1].read_bytes()).decode()}}

    def external_decision(self, observation_id, value):
        decision = Decision.parse(value)
        with self.condition:
            if self.billing != "claude" or self.demo or not self.worker or not self.worker.is_alive() or self.stopping or self.state["status"] not in ("waiting_external", "paused", "observing"):
                raise ValueError("Arm a Claude run in the dashboard before sending inputs")
            if observation_id != self.state["observation_id"] or observation_id is None:
                raise ValueError("Stale screenshot; observe again. No inputs were queued")
            if self.state["pending_decision"] or self.external_proposal is not None:
                raise ValueError("A decision is already pending; do not resubmit it")
            if self.state["decisions"] >= self.state["max_steps"]:
                raise ValueError("Decision limit reached; start a new run deliberately")
            self.external_proposal = decision
            self._update(commentary=decision.commentary, segments=[asdict(s) for s in decision.segments], pending_decision=True,
                         decisions=self.state["decisions"] + 1)
            self._event("decision", turn=self.state["decisions"], **decision.public())
            self.condition.notify_all()
            return {"accepted": True, "status": "queued", "observation_id": observation_id,
                    "message": "Do not resubmit. Observe until the screenshot ID changes. If paused/stopped/limit reached, return control to the user."}

    def _run_external(self):
        """Own the bridge while the user's official Claude client supplies data."""
        try:
            with self.bridge_factory() as bridge:
                self._update(status="observing")
                self._capture(bridge.observe())
                while self._permission():
                    with self.condition:
                        while self.external_proposal is None and not self.stopping and (self.continuous or self.permits):
                            self._update(status="waiting_external")
                            self.condition.wait()
                        if self.stopping:
                            break
                        if self.external_proposal is None:
                            continue
                        decision, self.external_proposal = self.external_proposal, None
                        self.condition.wait(timeout=.35)
                    if not self._permission():
                        break
                    if decision.done:
                        self._update(status="completed", pending_decision=False)
                        self._event("goal_completed", commentary=decision.commentary)
                        return
                    self._update(status="acting")
                    self._event("action_requested", segments=[asdict(s) for s in decision.segments])
                    result = bridge.step(decision.segments)
                    self.history.append([asdict(s) for s in decision.segments])
                    self.memory = decision.memory
                    # Capture first so an old observation cannot be submitted twice.
                    self._capture(result)
                    self._update(steps=self.state["steps"] + 1, pending_decision=False)
                    self._event("action_finished", request_id=result.request_id, advanced=result.advanced,
                                frame_before=result.frame_before, frame_after=result.frame_after)
                    with self.condition:
                        if self.permits:
                            self.permits -= 1
                    if self.state["decisions"] >= self.state["max_steps"]:
                        self._update(status="limit_reached")
                        self._event("decision_limit_reached")
                        return
                self._update(status="stopped", pending_decision=False)
                self._event("run_stopped")
        except Exception as exc:
            self._fail(exc)

    def _run(self, client):
        try:
            plan = not self.demo and self.billing == "chatgpt"
            if plan:
                self._update(status="checking_access")
                client.check()
            with self.bridge_factory() as bridge:
                self._update(status="observing")
                self._capture(bridge.observe())
                while self._permission():
                    if self.state["decisions"] >= self.state["max_steps"]:
                        self._update(status="limit_reached")
                        self._event("decision_limit_reached")
                        return
                    if self.demo:
                        self._update(status="thinking")
                        time.sleep(0.35)
                        decision = Decision("The demo marker is moving toward the next platform, so I’m using a short input burst.",
                                            "Demo scene only; no Mario state or API call.", False,
                                            (Segment(8, 0.5, 0, ("A",) if self.state["decisions"] % 3 == 0 else ()),))
                        self._update(decisions=self.state["decisions"] + 1, latency_seconds=0.35)
                    else:
                        body = payload(self.state["goal"], self.images, self.history, self.memory, self.effort, self.model)
                        tokens, reserve = None, 0
                        if not plan:
                            self._update(status="counting_tokens")
                            tokens = client.count(body)
                            reserve = reserve_cost(tokens, self.model)
                            self._event("input_counted", input_tokens=tokens, maximum_standard_estimate_usd=reserve)
                            if self.state["usage"]["estimated_usd"] + reserve > self.state["budget_usd"]:
                                self._update(status="budget_reached")
                                self._event("budget_reached", next_request_reserve_usd=reserve)
                                return
                        if not self._permission():
                            break
                        # Persist the reservation before the billable request starts.
                        self._update(status="thinking", reserved_usd=reserve, usage_unknown=True)
                        turn = self.state["decisions"] + 1
                        self._event("api_request_started", turn=turn, model=self.model, input_tokens=tokens,
                                    max_output_tokens=None if plan else body["max_output_tokens"], billing_mode=self.billing,
                                    screenshots=[p.name for p in self.images[-4:]])
                        started = time.monotonic()
                        response = client.generate(body)
                        usage = usage_summary(response, self.model, api_pricing=not plan)
                        totals = {k: self.state["usage"][k] + usage[k] for k in usage}
                        latency = time.monotonic() - started
                        self._update(usage=totals, reserved_usd=0, usage_unknown=False, decisions=turn, latency_seconds=latency,
                                     actual_model=response.get("model"))
                        # Persist only usage/IDs/public output. No reasoning items,
                        # image base64, request headers, or credentials are recorded.
                        meta = {"id": response.get("id"), "request_id": response.get("_request_id"),
                                "model": response.get("model"), "status": response.get("status"),
                                "service_tier": response.get("service_tier"), "usage": usage,
                                "latency_seconds": latency, "billing_mode": self.billing}
                        atomic_json(self.log.directory / "api" / f"{turn:04d}.json", meta)
                        self._event("api_request_finished", **meta)
                        if not plan and (response.get("service_tier", "default") != "default" or not response_model_matches(response.get("model"), self.model)):
                            self._update(usage_unknown=True)
                            raise ModelError("API used an unexpected model or service tier; cost estimate needs billing verification")
                        decision = parse_response(response, self.model)
                    self._update(commentary=decision.commentary, segments=[asdict(s) for s in decision.segments], pending_decision=True)
                    self._event("decision", turn=self.state["decisions"], **decision.public())
                    # Give the observer a chance to display commentary before the
                    # action starts. Pause/stop wakes this brief wait immediately.
                    with self.condition:
                        self.condition.wait(timeout=0.35)
                    if not self._permission():
                        break
                    if decision.done:
                        self._update(status="completed", pending_decision=False)
                        self._event("goal_completed", commentary=decision.commentary)
                        return
                    self._update(status="acting")
                    self._event("action_requested", segments=[asdict(s) for s in decision.segments])
                    result = bridge.step(decision.segments)
                    self.history.append([asdict(s) for s in decision.segments])
                    self.memory = decision.memory
                    self._update(steps=self.state["steps"] + 1, pending_decision=False)
                    self._event("action_finished", request_id=result.request_id, advanced=result.advanced,
                                frame_before=result.frame_before, frame_after=result.frame_after)
                    self._capture(result)
                    with self.condition:
                        if self.permits:
                            self.permits -= 1
                    if self.state["decisions"] >= self.state["max_steps"]:
                        self._update(status="limit_reached")
                        self._event("decision_limit_reached")
                        return
                self._update(status="stopped", pending_decision=False)
                self._event("run_stopped")
        except Exception as e:
            self._fail(e)


class DemoBridge:
    """A clearly labelled, dependency-free scene for testing the observer UI."""
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.frame = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def observe(self):
        return self._image(self.frame, self.frame)

    def step(self, segments):
        before = self.frame
        self.frame += sum(s.frames for s in segments)
        time.sleep(0.12)
        return self._image(before, self.frame)

    def _image(self, before, after):
        w, h = 640, 480
        # Simple deterministic PNG; explicitly synthetic, never presented as SM64.
        rows = bytearray()
        cx = 120 + (self.frame * 3) % 380
        for y in range(h):
            rows.append(0)
            for x in range(w):
                color = (41, 83, 110) if y < 360 else (49, 100, 75)
                if 280 < x < 420 and 290 < y < 310:
                    color = (217, 175, 111)
                if abs(x - cx) < 15 and 322 < y < 360:
                    color = (235, 112, 91)
                rows.extend(color)
        def chunk(name, data):
            return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
        id = uuid.uuid4().hex
        path = self.directory / (id + ".png")
        path.write_bytes(png)
        return Observation(path, before, after, after - before, id)

"""Loopback-only observer UI. Credentials never enter browser responses."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit, parse_qs
import zipfile
import os
import threading
import webbrowser

from .runner import Controller
from .bridge import atomic_json

ID = r"[0-9a-f]{32}"


def make_server(controller, port=8765):
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).with_name("web")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, body, mime="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            # Reject DNS rebinding Host headers; accept only this loopback endpoint.
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.local_host():
                return self.reply(403, {"error": "Local requests only"})
            path = urlsplit(self.path).path
            if path in ("/", "/app.js", "/style.css"):
                name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
                return self.reply(200, (assets / name).read_bytes(), {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name])
            if path == "/api/state":
                return self.reply(200, {**controller.snapshot(), "control_token": token})
            if path == "/api/scratchpad":
                args = parse_qs(urlsplit(self.path).query)
                query = args.get("query", [""])[0]
                try:
                    return self.reply(200, controller.scratchpad_read(query, int(args.get("offset", ["0"])[0])))
                except ValueError as exc:
                    return self.reply(400, {"error": str(exc)})
            if path == "/api/scratchpad/export":
                return self.reply(200, controller.scratchpad.export(), "application/x-ndjson",
                                  {"Content-Disposition": 'attachment; filename="gpt64-scratchpad.jsonl"'})
            if path == "/api/runs":
                runs = []
                for p in controller.runs_root.glob("*/state.json"):
                    if re.fullmatch(ID, p.parent.name):
                        try:
                            value = json.loads(p.read_text(encoding="utf-8"))
                            runs.append({k: value.get(k) for k in ("run_id", "goal", "status", "updated", "demo", "steps")})
                        except (OSError, ValueError):
                            continue
                return self.reply(200, sorted(runs, key=lambda x: x.get("updated", ""), reverse=True)[:100])
            match = re.fullmatch(r"/api/runs/(" + ID + r")/(state|export|events\.jsonl|screens/[0-9]{4,}-" + ID + r"\.png)", path)
            if match:
                run_id, resource = match.groups()
                directory = controller.runs_root / run_id
                if not directory.is_dir():
                    return self.reply(404, {"error": "Run not found"})
                if resource == "export":
                    output = io.BytesIO()
                    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                        for p in directory.rglob("*"):
                            if p.is_file() and not p.is_symlink() and p.suffix in (".json", ".jsonl", ".png"):
                                archive.write(p, arcname=p.relative_to(directory))
                    return self.reply(200, output.getvalue(), "application/zip", {"Content-Disposition": f'attachment; filename="gpt64-{run_id}.zip"'})
                file = directory / ("state.json" if resource == "state" else resource)
                if not file.is_file() or file.is_symlink():
                    return self.reply(404, {"error": "Record not found"})
                if resource == "state":
                    return self.reply(200, json.loads(file.read_text(encoding="utf-8")))
                return self.reply(200, file.read_bytes(), "image/png" if file.suffix == ".png" else "application/x-ndjson")
            match = re.fullmatch(r"/api/preview/(" + ID + r"\.png)", path)
            if match:
                file = controller.runs_root / "preview" / match.group(1)
                if file.is_file():
                    return self.reply(200, file.read_bytes(), "image/png")
            return self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.local_host() or not secrets.compare_digest(self.headers.get("X-Gpt64-Control", ""), token):
                return self.reply(403, {"error": "Control token required"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.reply(403, {"error": "Local origin required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    raise ValueError("Request too large")
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                path = urlsplit(self.path).path
                if path in ("/api/start", "/api/step"):
                    controller.start(data.get("goal", ""), data.get("max_steps", 100), data.get("budget_usd", 1), path == "/api/start", data.get("model"))
                elif path == "/api/models":
                    controller.refresh_models()
                elif path == "/api/preferences":
                    controller.save_preferences({k: data[k] for k in ("model", "goal", "max_steps", "budget_usd") if k in data})
                elif path == "/api/external/observe":
                    return self.reply(200, controller.external_observation())
                elif path == "/api/external/decision":
                    return self.reply(200, controller.external_decision(data.get("observation_id"), {k: v for k, v in data.items() if k != "observation_id"}))
                elif path in ("/api/external/scratchpad/read", "/api/external/scratchpad/append"):
                    if controller.billing != "claude" or controller.demo:
                        raise ValueError("Scratchpad MCP writes require the Claude dashboard")
                    if path.endswith("read"):
                        if set(data) - {"query", "offset"}:
                            raise ValueError("Scratchpad read accepts query and offset")
                        return self.reply(200, controller.scratchpad_read(data.get("query", ""), data.get("offset", 0)))
                    if set(data) != {"text"}:
                        raise ValueError("Scratchpad append requires text")
                    return self.reply(200, controller.scratchpad_append(data["text"]))
                elif path == "/api/claude/launch":
                    if controller.billing != "claude" or not controller.settings:
                        raise ValueError("Use start-claude.cmd to open the Claude dashboard")
                    if getattr(controller, "claude_process", None) and controller.claude_process.poll() is None:
                        raise ValueError("Claude Code is already open; return to that window")
                    from .claude import launch
                    controller.claude_process = launch(controller.settings.directory)
                elif path == "/api/pause":
                    controller.pause()
                elif path == "/api/stop":
                    controller.stop()
                elif path == "/api/observe":
                    controller.observe()
                elif path in ("/api/auth/login", "/api/auth/logout", "/api/auth/select", "/api/auth/ack"):
                    controller.account_action(path.rsplit("/", 1)[1], data.get("account"), data.get("new") is True, data.get("enable_plan") is True)
                else:
                    return self.reply(404, {"error": "Not found"})
                return self.reply(200, {"ok": True})
            except (ValueError, RuntimeError) as e:
                return self.reply(400, {"error": str(e)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.control_token = token
    return server


def serve(bridge_root, runs_root, port=8765, demo=False, effort="medium", billing="chatgpt", model=None, settings=None, open_browser=False):
    controller = Controller(bridge_root, runs_root, demo=demo, effort=effort, billing=billing, model=model, settings=settings)
    server = make_server(controller, port)
    url = f"http://127.0.0.1:{server.server_port}"
    descriptor = None
    if settings:
        settings.directory.mkdir(parents=True, exist_ok=True)
        descriptor = settings.directory / "dashboard.json"
        atomic_json(descriptor, {"url": url, "token": server.control_token})
        if os.name != "nt":
            descriptor.chmod(0o600)
    print(f"gpt64 dashboard: http://127.0.0.1:{server.server_port}")
    print("Demo: synthetic scene, no emulator or API calls." if demo else f"Billing: {billing}. Choose a model in the dashboard or official Claude app before starting.")
    if open_browser and not demo:
        controller.observe()
    if open_browser:
        threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping after in-flight work. An API request may finish and incur usage.")
    finally:
        controller.close()
        server.server_close()
        if descriptor:
            try:
                if json.loads(descriptor.read_text())["token"] == server.control_token:
                    descriptor.unlink()
            except (OSError, ValueError, KeyError):
                pass

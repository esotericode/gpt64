"""Loopback-only observer UI. Credentials never enter browser responses."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
import zipfile

from .runner import Controller

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
                if not 0 <= length <= 8192:
                    raise ValueError("Request too large")
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                path = urlsplit(self.path).path
                if path in ("/api/start", "/api/step"):
                    controller.start(data.get("goal", ""), data.get("max_steps", 100), data.get("budget_usd", 1), path == "/api/start")
                elif path == "/api/pause":
                    controller.pause()
                elif path == "/api/stop":
                    controller.stop()
                elif path == "/api/observe":
                    controller.observe()
                else:
                    return self.reply(404, {"error": "Not found"})
                return self.reply(200, {"ok": True})
            except (ValueError, RuntimeError) as e:
                return self.reply(400, {"error": str(e)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(bridge_root, runs_root, port=8765, demo=False, effort="medium"):
    controller = Controller(bridge_root, runs_root, demo=demo, effort=effort)
    server = make_server(controller, port)
    print(f"gpt64 dashboard: http://127.0.0.1:{server.server_port}")
    print("Demo: synthetic scene, no emulator or API calls." if demo else "Model: gpt-6.1-sol. Open the dashboard to observe or start a run.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping after in-flight work. An API request may finish and incur usage.")
    finally:
        controller.close()
        server.server_close()

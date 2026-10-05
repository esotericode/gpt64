"""Official local-app ChatGPT plan OAuth. Tokens never enter the dashboard/logs."""

import base64
from contextlib import contextmanager
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib import error, request
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

from .model import ModelError, NoRedirect

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT = "chatgpt.tokens.use.direct"


def default_directory():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "gpt64"
    return Path.home() / ".config/gpt64"


def secure_bytes(data, decrypt=False):
    """Windows DPAPI binds credentials to this Windows user; Unix uses mode 0600."""
    if os.name != "nt":
        return data
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ModelError("Windows could not protect/read the saved ChatGPT credentials")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def auth_request(url, form=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "auth.openai.com":
        raise ModelError("Rejected an unexpected OpenAI authentication endpoint")
    req = request.Request(url, data=None if form is None else urlencode(form).encode(),
                          headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with request.build_opener(NoRedirect).open(req, timeout=30) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Oversize authentication response")
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise ValueError("Invalid authentication response")
            return value
    except error.HTTPError as exc:
        raise ModelError(f"ChatGPT authentication HTTP {exc.code}. Sign in again or check account permissions. No automatic retry.") from None
    except (error.URLError, OSError, ValueError):
        raise ModelError("ChatGPT authentication could not complete. Credentials were not replaced; try signing in again.") from None


def validate_identity(token, client_id, nonce, jwks, issuer=ISSUER):
    try:
        import jwt
    except ImportError:
        raise ModelError('Install sign-in support first: py -m pip install ".[signin]"') from None
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in ("RS256", "ES256") or not isinstance(header.get("kid"), str):
            raise ValueError("Unsupported signing key")
        keys = [k for k in jwks["keys"] if k.get("kid") == header["kid"] and
                k.get("use", "sig") == "sig" and k.get("alg", alg) == alg]
        if len(keys) != 1:
            raise ValueError("Unknown signing key")
        key = jwt.PyJWK.from_dict(keys[0], algorithm=alg).key
        claims = jwt.decode(token, key, algorithms=[alg], audience=client_id, issuer=issuer,
                            leeway=5, options={"require": ["sub", "exp", "iat", "nonce"]})
        if not isinstance(claims["sub"], str) or not claims["sub"] or claims["nonce"] != nonce:
            raise ValueError("Identity or nonce mismatch")
        if claims.get("azp", client_id) != client_id:
            raise ValueError("Authorized party mismatch")
        return claims
    except Exception:
        raise ModelError("The ChatGPT identity token could not be verified. Saved accounts were not changed.") from None


class AuthStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else default_directory()
        self.path = self.directory / "accounts.dat"

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / "accounts.lock").open("a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0"); lock.flush()
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ModelError("Another gpt64 process is updating ChatGPT credentials. Close it and retry.") from None
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def load(self):
        if not self.path.exists():
            return {"host_id": None, "active": None, "accounts": {}}
        try:
            value = json.loads(secure_bytes(self.path.read_bytes(), decrypt=True))
            if not isinstance(value.get("accounts"), dict):
                raise ValueError("Invalid accounts")
            return value
        except (OSError, ValueError):
            raise ModelError("Saved ChatGPT credentials could not be read. See the setup guide's credential recovery.") from None

    def save(self, value):
        data = secure_bytes(json.dumps(value).encode())
        temp = self.directory / (uuid.uuid4().hex + ".tmp")
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(data); file.flush(); os.fsync(file.fileno())
            # Polling readers can briefly lock a target on Windows.
            for attempt in range(10):
                try:
                    temp.replace(self.path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.02)
        finally:
            temp.unlink(missing_ok=True)

    def public(self):
        value = self.load()
        accounts = [{"id": cid, "label": f"{r.get('email') or 'ChatGPT account'} · {cid[-6:]}",
                     "ready": bool(r.get("access_token") or r.get("refresh_token")) and DIRECT in r.get("scopes", [])}
                    for cid, r in value["accounts"].items()]
        active = next((r for r in accounts if r["id"] == value["active"]), None)
        record = value["accounts"].get(value["active"], {})
        return {"accounts": accounts, "active": value["active"], "ready": bool(active and active["ready"]),
                "label": active["label"] if active else "Not signed in",
                "welcome": bool(active and active["ready"] and not record.get("welcome_seen"))}

    def select(self, client_id):
        with self.locked():
            value = self.load()
            if client_id not in value["accounts"]:
                raise ModelError("Choose a saved ChatGPT account")
            value["active"] = client_id
            self.save(value)

    def acknowledge(self):
        with self.locked():
            value = self.load()
            if value["active"] in value["accounts"]:
                value["accounts"][value["active"]]["welcome_seen"] = True
                self.save(value)

    @staticmethod
    def token_record(tokens, old=None):
        old = old or {}
        if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"] or str(tokens.get("token_type", "")).lower() != "bearer":
            raise ModelError("ChatGPT did not return a valid access token")
        lifetime = tokens.get("expires_in")
        if type(lifetime) is not int or not 0 < lifetime <= 86400:
            raise ModelError("ChatGPT did not return a valid token expiry")
        scopes = tokens.get("scope")
        if not isinstance(scopes, str):
            raise ModelError("ChatGPT did not return granted permissions")
        return {**old, "access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
                "id_token": tokens.get("id_token", old.get("id_token")), "scopes": scopes.split(),
                "expires_at": time.time() + lifetime, "saved_at": time.time()}

    def access_token(self, client_id=None):
        with self.locked():
            value = self.load()
            cid = client_id or value["active"]
            old = value["accounts"].get(cid)
            if not old or DIRECT not in old.get("scopes", []):
                raise ModelError("ChatGPT plan use is not enabled. Choose Continue with ChatGPT and grant plan usage.")
            if old.get("access_token") and old.get("expires_at", 0) > time.time() + 60:
                return cid, old["access_token"]
            if not old.get("refresh_token"):
                raise ModelError("ChatGPT sign-in expired. Continue with ChatGPT again.")
            tokens = auth_request(ISSUER + "/api/accounts/oauth/token", {"grant_type": "refresh_token",
                                  "client_id": cid, "refresh_token": old["refresh_token"], "resource": RESOURCE})
            fresh = self.token_record(tokens, old)
            if not fresh.get("refresh_token"):
                raise ModelError("ChatGPT refresh did not return a replacement token. Sign in again.")
            value["accounts"][cid] = fresh
            self.save(value)
            if DIRECT not in fresh["scopes"]:
                raise ModelError("ChatGPT plan permission is no longer granted. No inference was sent.")
            return cid, fresh["access_token"]

    def logout(self):
        with self.locked():
            value = self.load()
            old = value["accounts"].get(value["active"])
            if not old:
                return True
            revoked = True
            if old.get("refresh_token"):
                try:
                    metadata = auth_request(ISSUER + "/.well-known/openid-configuration")
                    auth_request(metadata["revocation_endpoint"], {"token": old["refresh_token"],
                                 "token_type_hint": "refresh_token", "client_id": value["active"]})
                except (ModelError, KeyError):
                    revoked = False
            for name in ("access_token", "refresh_token", "id_token", "expires_at"):
                old.pop(name, None)
            self.save(value)
            return revoked

    def login(self, new=False, enable_plan=False, browser_open=webbrowser.open, timeout=600):
        try:
            import jwt  # Check optional dependency before opening the browser.
        except ImportError:
            raise ModelError('Install sign-in support first: py -m pip install ".[signin]"') from None
        with self.locked():
            value = self.load()
            if not value["host_id"]:
                value["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self.save(value)
            old = None if new else value["accounts"].get(value["active"])
            client_id = old["client_id"] if old else "dynamic_agent_client"
            state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
            result = {}
            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass  # Callback URLs contain a code; never log them.
                def do_GET(self):
                    parts = urlsplit(self.path)
                    params = parse_qs(parts.query, keep_blank_values=True)
                    returned_state = params.get("state", [""])[0]
                    good = len(self.path) <= 8192 and parts.path == "/auth/callback" and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
                    good = good and all(len(v) == 1 for v in params.values()) and returned_state.isascii() and secrets.compare_digest(returned_state, state)
                    if good and not result:
                        result.update({k: v[0] for k, v in params.items()})
                    self.send_response(200 if good else 400)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    self.wfile.write(b"Return to gpt64. Sign-in is being verified." if good else b"Sign-in callback could not be verified.")
            class Listener(HTTPServer):
                def get_request(self):
                    socket, address = super().get_request()
                    socket.settimeout(5)
                    return socket, address
            with Listener(("127.0.0.1", 0), Callback) as server:
                server.timeout = 0.5
                redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
                params = {"client_id": client_id, "ext_agent_host_id": value["host_id"], "response_type": "code",
                          "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE, "state": state,
                          "nonce": nonce, "code_challenge_method": "S256",
                          "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
                if not old:
                    params["agent_name_hint"] = "gpt64"
                elif old.get("email"):
                    params["login_hint"] = old["email"]
                if enable_plan:
                    params["prompt"] = "consent"
                if not browser_open(ISSUER + "/api/accounts/authorize?" + urlencode(params)):
                    raise ModelError("The system browser could not open. Run login from your Windows desktop.")
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    server.handle_request()
            if not result:
                raise ModelError("ChatGPT sign-in timed out. Run login again.")
            if result.get("error"):
                raise ModelError("ChatGPT sign-in was declined. No inference was sent.")
            issued = result.get("client_id", client_id if old else None)
            if not issued or issued == "dynamic_agent_client" or (old and issued != client_id) or not result.get("code"):
                raise ModelError("ChatGPT registration did not return the expected client ID and code")
            tokens = auth_request(ISSUER + "/api/accounts/oauth/token", {"grant_type": "authorization_code",
                                  "client_id": issued, "code": result["code"], "code_verifier": verifier,
                                  "redirect_uri": redirect, "resource": RESOURCE})
            metadata = auth_request(ISSUER + "/.well-known/openid-configuration")
            if metadata.get("issuer") != ISSUER:
                raise ModelError("Unexpected OpenAI identity issuer")
            claims = validate_identity(tokens.get("id_token"), issued, nonce, auth_request(metadata["jwks_uri"]))
            if old and claims["sub"] != old["subject"]:
                raise ModelError("The selected ChatGPT account changed. Use login --new for another account.")
            if issued in value["accounts"] and claims["sub"] != value["accounts"][issued]["subject"]:
                raise ModelError("The issued ChatGPT registration does not match its saved identity")
            record = self.token_record(tokens, old)
            record.update(client_id=issued, subject=claims["sub"], email=claims.get("email"), issuer=ISSUER)
            value["accounts"][issued] = record
            value["active"] = issued
            self.save(value)
        return self.public()

"""Loopback-only preview server; optional explicitly configured SQLite collection."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import sqlite3
import time
from threading import Lock
import json
from pathlib import Path
from urllib.parse import urlsplit
from .common import digest, require
from .design import public_bundle, validate_study

WEB = Path(__file__).parent / "web"


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # BaseServer's traceback includes the peer IP. Do not log participant connections.


def make_server(study, slot=0, prompt="next", port=8765, *, collection=None):
    validate_study(study, audio=True)
    bundle = public_bundle(study, slot, prompt)
    audio = {"/audio/" + digest({"study": study["sha256"], "track": tid})[:32]: Path(t["clip"]).read_bytes()
             for tid, t in study["tracks"].items()}
    static = {"/": (WEB / "index.html", "text/html; charset=utf-8"),
              "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
              "/style.css": (WEB / "style.css", "text/css; charset=utf-8")}

    external_origin = collection.config["public_origin"] if collection else None
    if external_origin:
        parsed = urlsplit(external_origin)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment, "Expected exact HTTPS origin")
    rate_lock, starts = Lock(), []

    class Handler(BaseHTTPRequestHandler):
        server_version = "ListeningStudy"

        def log_message(self, *_):
            pass  # No IP, URL, user agent or referrer logs.

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def allowed(self, *, mutation=False):
            origin = external_origin or f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != urlsplit(origin).netloc:
                self.reply(403, b"Use the printed loopback address", "text/plain")
                return False
            if self.headers.get("Origin", "" if mutation else origin) != origin or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.reply(403, b"Cross-origin access refused", "text/plain")
                return False
            return True

        def cookie(self):
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
                return cookies["study_session"].value if "study_session" in cookies else None
            except Exception:
                return None

        def json_reply(self, data, token=None):
            self.reply(200, json.dumps(data, ensure_ascii=False).encode(), "application/json", token=token)

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path in static:
                file, mime = static[path]
                self.reply(200, file.read_bytes(), mime)
            elif path == "/session":
                if collection:
                    self.json_reply({"collection": True, "demo": study["demo"],
                                     **{k: collection.config[k] for k in ("consent_version", "delete_on", "contact")}})
                else:
                    self.json_reply(bundle)
            elif path == "/api/state" and collection:
                if not self.cookie():
                    self.json_reply({"status": "new"})
                else:
                    try:
                        self.json_reply(collection.state(self.cookie()))
                    except ValueError:
                        self.json_reply({"status": "unavailable"})
            elif path in audio:
                if collection:
                    try:
                        require(collection.state(self.cookie())["status"] == "in_progress", "No active session")
                    except ValueError:
                        self.reply(403, b"No active session", "text/plain")
                        return
                self.reply(200, audio[path], "audio/wav")
            else:
                self.reply(404, b"Not found", "text/plain")

        def do_POST(self):
            if not collection:
                self.send_error(501)
                return
            if not self.allowed(mutation=True):
                return
            path = urlsplit(self.path).path
            if path not in ("/api/start", "/api/resume", "/api/answer", "/api/complete", "/api/withdraw"):
                self.reply(404, b"Not found", "text/plain")
                return
            try:
                require(self.headers.get("Content-Type") == "application/json"
                        and not self.headers.get("Transfer-Encoding"), "JSON required")
                length = int(self.headers.get("Content-Length", "0"))
                require(0 < length <= 16384, "Body too large or missing")
                payload = json.loads(self.rfile.read(length))
                require(isinstance(payload, dict), "Expected object")
                token = None
                if path in ("/api/start", "/api/resume"):
                    # Single-process preview guard; proxy adds a shared global limit before public use.
                    with rate_lock:
                        now = time.monotonic()
                        starts[:] = [t for t in starts if now - t < 60]
                        require(len(starts) < 60, "Please retry later")
                        starts.append(now)
                if path == "/api/start":
                    token, result = collection.start(self.cookie(), payload)
                elif path == "/api/resume":
                    require(set(payload) == {"code"}, "Unexpected recovery fields")
                    token, result = collection.resume(payload["code"])
                elif path == "/api/answer":
                    result = collection.answer(self.cookie(), payload)
                else:
                    require(not payload, "Unexpected fields")
                    result = (collection.complete if path == "/api/complete" else collection.withdraw)(self.cookie())
                self.json_reply(result, token)
            except (ValueError, TypeError, KeyError, UnicodeError):
                self.reply(400, b'{"error":"Request refused; reload saved progress or contact researcher"}', "application/json")
            except (sqlite3.Error, OSError):
                self.reply(503, b'{"error":"Storage unavailable; retry later"}', "application/json")

        def reply(self, code, body, mime, *, token=None):
            self.send_response(code)
            if token:
                secure = "; Secure" if external_origin else ""
                self.send_header("Set-Cookie", f"study_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=7776000{secure}")
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; media-src 'self'; "
                             "img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

    require(type(port) is int and 0 <= port <= 65535, "Invalid port")
    return QuietServer(("127.0.0.1", port), Handler)

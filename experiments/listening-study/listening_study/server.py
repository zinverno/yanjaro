"""Read-only loopback server. No response endpoint, request logs or directory serving."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
from .common import digest, require
from .design import public_bundle, validate_study

WEB = Path(__file__).parent / "web"


def make_server(study, slot, prompt, port=8765):
    validate_study(study, audio=True)
    bundle = public_bundle(study, slot, prompt)
    audio = {"/audio/" + digest({"study": study["sha256"], "track": tid})[:32]: Path(t["clip"]).read_bytes()
             for tid, t in study["tracks"].items()}
    static = {"/": (WEB / "index.html", "text/html; charset=utf-8"),
              "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
              "/style.css": (WEB / "style.css", "text/css; charset=utf-8")}

    class Handler(BaseHTTPRequestHandler):
        server_version = "ListeningStudy"

        def log_message(self, *_):
            pass  # No IP, URL, user agent or referrer logs.

        def do_GET(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://"):
                self.reply(403, b"Use the printed loopback address", "text/plain")
                return
            if self.headers.get("Origin", origin) != origin or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.reply(403, b"Cross-origin access refused", "text/plain")
                return
            path = urlsplit(self.path).path
            if path in static:
                file, mime = static[path]
                self.reply(200, file.read_bytes(), mime)
            elif path == "/session":
                self.reply(200, json.dumps(bundle, ensure_ascii=False).encode(), "application/json")
            elif path in audio:
                self.reply(200, audio[path], "audio/wav")
            else:
                self.reply(404, b"Not found", "text/plain")

        def reply(self, code, body, mime):
            self.send_response(code)
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
    return HTTPServer(("127.0.0.1", port), Handler)

"""Real localhost HTTP and FFmpeg, synthetic OAuth/audio only; never contact Yandex/keyring."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime
runtime.configure()

import copy
from contextlib import contextmanager
import io
import json
import os
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
import unittest

import numpy as np
import requests
import core
import personal_index
import yandex_stream as stream

SECRET = "synthetic-authorization-only"
HOST = "fixture.storage.yandex.net"
CDN = "strm-fixture-1.strm.yandex.net"
CDN2 = "strm-fixture-2.strm.yandex.net"


def local_network_only(event, args):
    if event == "socket.connect":
        assert isinstance(args[1], tuple) and args[1][0] == "127.0.0.1", "Tests prohibit external connections"
    if event == "socket.getaddrinfo":
        assert args[0] == "127.0.0.1", "Tests prohibit external DNS"


sys.addaudithook(local_network_only)


def encoded(codec, seconds=90, level=1):
    t = np.arange(round(seconds * 48000)) / 48000
    pcm = ((.1 + .2 * np.exp(-(t % .4) / .025)) * np.sin(2 * np.pi * 220 * t) * level).astype('<f4')
    command = ["ffmpeg", "-v", "error", "-threads", "1", "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", "pipe:0",
               "-threads", "1", "-c:a", "libmp3lame" if codec == "mp3" else "aac", "-b:a", "192k",
               "-f", "mp3" if codec == "mp3" else "adts", "pipe:1"]
    try:
        return subprocess.run(command, input=pcm.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              check=True, timeout=15).stdout
    finally:
        pcm.fill(0)


@contextmanager
def fixture(audio, codec="mp3", mode="ok", redirect=None, media_steps=None, media_calls=None):
    calls = []
    media_calls = media_calls if media_calls is not None else []
    track = dict(id="123", title="Synthetic signal", artists=[dict(id=7, name="Fixture artist")],
                 albums=[dict(id=9, title="Fixture album")], durationMs=90000, available=True)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path
            auth = self.headers.get("Authorization")
            calls.append((path, auth))
            if redirect and path.startswith(redirect[0]) and sum(p.startswith(redirect[0]) for p, _ in calls) == redirect[1]:
                self.send_response(redirect[2])
                if redirect[3] is not None:
                    self.send_header("Location", redirect[3])
                self.send_header("Set-Cookie", "private=" + SECRET)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 200
            location = None
            if path == "/account/status":
                result = dict(account=dict(uid=1))
            elif path == "/tracks":
                mismatch = mode == "id_mismatch" or mode == "changed_id" and sum(p == "/tracks" for p, _ in calls) == 2
                result = [dict(track, id="456") if mismatch else track]
            elif path == "/tracks/123/download-info":
                result = [dict(codec=codec, bitrateInKbps=192, gain=False, preview=mode == "preview",
                               downloadInfoUrl="https://" + HOST + "/info", direct=False)]
            elif path == "/info":
                result = None
                origin = HOST if media_steps is None else "api.music.yandex.net"
                body = (f'<download-info><host>{origin}</host><path>/fixture.{codec}</path>'
                        '<ts>1</ts><s>synthetic</s></download-info>').encode()
            else:
                result = None
                body = audio
                if mode in ("expired", "denied", "redirect"):
                    status = {"expired": 410, "denied": 403, "redirect": 302}[mode]
                    body = b""
                elif mode in ("partial", "broken"):
                    body = audio[:10000]
                if media_steps is not None:
                    media_calls.append((self.headers.get("Host"), self.path, auth, self.headers.get("Cookie"),
                                        self.headers.get("Proxy-Authorization")))
                    if len(media_calls) <= len(media_steps):
                        status, location = media_steps[len(media_calls) - 1]
                        if status != 200:
                            body = b""
            if result is not None:
                if auth != "OAuth " + SECRET:
                    status = 401
                body = json.dumps(dict(result=result)).encode()
            self.send_response(status)
            if mode == "redirect" and path.startswith("/get-mp3"):
                self.send_header("Location", "http://127.0.0.1/private")
            if location is not None:
                self.send_header("Location", location)
            if status == 308:
                self.send_header("Set-Cookie", "private=" + SECRET + "; Domain=.yandex.net; Path=/")
            self.send_header("Content-Length", str(len(audio) if mode == "broken" and path.startswith("/get-mp3") else len(body)))
            self.end_headers()
            try:
                for offset in range(0, len(body), 4096):
                    self.wfile.write(body[offset:offset + 4096])
                    self.wfile.flush()
                    if mode == "slow":
                        time.sleep(.02)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = stream.session
    def local_session():
        http = original()
        call = http.request
        def local(method, url, **kwargs):
            parsed = urlsplit(url)
            assert parsed.hostname in (HOST, CDN, CDN2, "api.music.yandex.net")
            kwargs["headers"] = {**kwargs.get("headers", {}), "Host": parsed.netloc}
            return call(method, f"http://127.0.0.1:{server.server_port}" + parsed.path +
                        ("?" + parsed.query if parsed.query else ""), **kwargs)
        http.request = local
        return http
    try:
        with patch("yandex_stream.session", side_effect=local_session):
            yield calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class RedirectDiagnosticsTests(unittest.TestCase):
    def test_requests_does_not_buffer_redirect_body_or_prepare_next_request(self):
        for status in (302, 307, 308):
            with self.subTest(status=status), stream.session() as http:
                response = requests.Response()
                response.status_code = status
                response.url = "https://api.music.yandex.net/tracks/123/download-info"
                response.headers.update(Location="https://" + HOST + "/private?signature=" + SECRET,
                                        **{"Content-Length": str(stream.MAX_BYTES * 2)})
                response.raw = Mock(_original_response=None)
                response.raw.stream.side_effect = AssertionError("Redirect body must not be buffered")
                response.raw.read.side_effect = AssertionError("Redirect body must not be read")
                adapter = Mock()
                adapter.send.return_value = response
                with patch.object(http, "get_adapter", return_value=adapter), \
                        http.get(response.url, stream=True, allow_redirects=False,
                                 headers={"Authorization": "OAuth " + SECRET}) as result:
                    self.assertIs(result, response)
                    self.assertIsNone(result.next)
                    adapter.send.assert_called_once()
                response.raw.stream.assert_not_called()
                response.raw.read.assert_not_called()
                response.raw.close.assert_called_once()

    def test_stage_comes_from_sdk_operation_without_automatic_redirect_or_body_read(self):
        for operation, stage, method in (("tracks", "metadata_api", "POST"),
                                         ("download", "tracks_download_info", "GET"),
                                         ("xml", "download_info_xml", "GET")):
            with self.subTest(operation=operation), patch("yandex_stream.session") as factory, \
                    patch("sys.stderr", new_callable=io.StringIO) as output:
                request = stream.BoundedRequest()
                request.set_authorization(SECRET)
                client = stream.ObservedClient(request=request)
                http = factory.return_value.__enter__.return_value
                response = http.request.return_value.__enter__.return_value
                response.status_code = 308
                response.headers = {"Location": "https://" + HOST + "/private?signature=" + SECRET}
                with self.assertRaisesRegex(core.Rejected, "^STREAM_REDIRECT_REJECTED$"):
                    if operation == "tracks":
                        client.tracks(["123"])
                    elif operation == "download":
                        client.tracks_download_info("123")
                    else:
                        # The operation, not the hostname/path, determines the XML stage.
                        request.retrieve("https://api.music.yandex.net/unusual-xml-path")
                event = json.loads(output.getvalue())
                self.assertEqual((event["stage"], event["method"]), (stage, method))
                http.request.assert_called_once()
                self.assertFalse(http.request.call_args.kwargs["allow_redirects"])
                self.assertNotIn("_stage", http.request.call_args.kwargs)
                self.assertEqual(request.calls, 1)
                response.iter_content.assert_not_called()
                http.request.return_value.__exit__.assert_called_once()
                factory.return_value.__exit__.assert_called_once()
                self.assertNotIn(SECRET, output.getvalue())

    def test_classification_never_emits_private_url_components(self):
        source = "https://" + HOST + "/private-path?signature=" + SECRET
        cases = [
            (None, None, "MISSING_LOCATION"), ("", None, "MISSING_LOCATION"),
            ("/new-private-path?signature=" + SECRET, HOST, "SAME_ORIGIN"),
            ("https://" + HOST + ":443/new?signature=" + SECRET, HOST, "SAME_ORIGIN"),
            ("//another.storage.yandex.net/private?signature=" + SECRET, "another.storage.yandex.net", "CROSS_ORIGIN_WITHIN_ALLOWLIST"),
            (source, HOST, "SELF_REDIRECT"),
            ("https://external.invalid/private?signature=" + SECRET, "external.invalid", "HOST_NOT_ALLOWLISTED"),
            ("https://yandex.net.external.invalid/private", "yandex.net.external.invalid", "HOST_NOT_ALLOWLISTED"),
            ("http://" + HOST + "/private", HOST, "HTTPS_DOWNGRADE"),
            ("file:///private-path", None, "UNSUPPORTED_SCHEME"),
            ("data:text/plain," + SECRET, None, "UNSUPPORTED_SCHEME"),
            ("https://user:" + SECRET + "@" + HOST + "/private", HOST, "USERINFO_REJECTED"),
            ("https://@" + HOST + "/private", HOST, "USERINFO_REJECTED"),
            ("https://" + HOST + ":444/private", HOST, "PORT_REJECTED"),
            ("https://" + HOST + ":bad/private", HOST, "INVALID_LOCATION"),
            ("https://" + HOST + ":65536/private", HOST, "INVALID_LOCATION"),
            ("/private#" + SECRET, HOST, "FRAGMENT_REJECTED"),
            ("/private#", HOST, "FRAGMENT_REJECTED"),
            ("https://[invalid/private", None, "INVALID_LOCATION"),
            ("https://bad%20host.yandex.net/private", None, "INVALID_LOCATION"),
            ("https://" + "a" * 64 + ".yandex.net/private", None, "INVALID_LOCATION"),
            ("https://" + HOST + "/private\r\n" + SECRET, None, "INVALID_LOCATION"),
            (" https://" + HOST + "/private", None, "INVALID_LOCATION"),
            ("https://" + HOST + "\\private", None, "INVALID_LOCATION"),
            ("/" + "x" * 8192, None, "INVALID_LOCATION"),
        ]
        for status in (302, 307):
            for location, host, classification in cases:
                with self.subTest(status=status, classification=classification), patch("sys.stderr", new_callable=io.StringIO) as output:
                    response = Mock(status_code=status, headers={} if location is None else {"Location": location})
                    with self.assertRaisesRegex(core.Rejected, "^STREAM_REDIRECT_REJECTED$"):
                        stream.response_check(response, stage="media_get", url=source, method="GET")
                    self.assertEqual(json.loads(output.getvalue()), dict(event="STREAM_REDIRECT", stage="media_get", method="GET",
                                     http_status=status, source_hostname=HOST, target_hostname=host,
                                     classification=classification, followed=False))
                    for private in (SECRET, "private-path", "signature", "Authorization", "Cookie", "https://"):
                        self.assertNotIn(private, output.getvalue())

    def test_diagnostic_output_failure_still_rejects_and_success_is_quiet(self):
        response = Mock(status_code=302, headers={"Location": "https://" + HOST + "/private"})
        with patch("sys.stderr.write", side_effect=OSError(SECRET)):
            with self.assertRaisesRegex(core.Rejected, "^STREAM_REDIRECT_REJECTED$"):
                stream.response_check(response, stage="media_get", url="https://" + HOST + "/old", method="GET")
        with patch("sys.stderr", new_callable=io.StringIO) as output:
            for status, reason in ((200, None), (410, "STREAM_LINK_EXPIRED"), (403, "STREAM_ACCESS_DENIED_OR_EXPIRED")):
                response.status_code = status
                if reason:
                    with self.assertRaisesRegex(core.Rejected, reason):
                        stream.response_check(response, stage="media_get", url="https://" + HOST + "/old", method="GET")
                else:
                    stream.response_check(response, stage="media_get", url="https://" + HOST + "/old", method="GET")
            self.assertEqual(output.getvalue(), "")


class MediaRedirectTests(unittest.TestCase):
    @contextmanager
    def transport(self, replies):
        original = stream.session
        calls, responses = [], []
        def session():
            http = original()
            self.assertFalse(http.trust_env)
            adapter = Mock()
            def send(request, **kwargs):
                if responses:
                    responses[-1].raw.close.assert_called_once()
                self.assertEqual(kwargs["proxies"], {})
                self.assertTrue(kwargs["verify"])
                self.assertTrue(kwargs["stream"])
                self.assertEqual(request.method, "GET")
                for header in ("Authorization", "Cookie", "Proxy-Authorization", "Referer"):
                    self.assertNotIn(header, request.headers)
                item = replies[len(calls)]
                calls.append(request.url)
                if isinstance(item, BaseException):
                    raise item
                if callable(item):
                    item = item()
                response = requests.Response()
                response.status_code, location = item
                response.url = request.url
                if location is not None:
                    response.headers["Location"] = location
                response.raw = Mock(_original_response=None)
                response.raw.stream.side_effect = AssertionError("No implicit body buffering")
                response.raw.read.side_effect = AssertionError("No body read before decoder")
                responses.append(response)
                return response
            adapter.send.side_effect = send
            http.get_adapter = lambda url: adapter
            return http
        with patch("yandex_stream.session", side_effect=session), \
                patch("requests.sessions.get_netrc_auth", side_effect=AssertionError("No netrc")), \
                patch("requests.sessions.get_environ_proxies", side_effect=AssertionError("No environment proxy")):
            try:
                yield calls
            finally:
                for response in responses:
                    response.raw.close.assert_called_once()
                    response.raw.read.assert_not_called()
                    response.raw.stream.assert_not_called()

    def test_strict_raw_and_resolved_location_validation(self):
        source = "https://api.music.yandex.net/private/start?old=signature"
        for location, expected in (("../audio?signature=" + SECRET, "https://api.music.yandex.net/audio?signature=" + SECRET),
                                   ("//" + CDN + "/audio?x=%2F", "https://" + CDN + "/audio?x=%2F"),
                                   ("https://" + CDN2 + ":443/audio?x=1&x=2", "https://" + CDN2 + ":443/audio?x=1&x=2")):
            self.assertEqual(stream.redirect_target(source, location), expected)
        for location in (None, "", "https:///" + CDN + "/a", "///" + CDN + "/a", "https:audio", "http://" + CDN + "/a",
                         "ftp://" + CDN + "/a", "data:text/plain,private", "file:///private", "https://outside.invalid/a",
                         "https://yandex.net.evil.invalid/a", "https://" + CDN + ":444/a", "https://" + CDN + ":/a",
                         "https://" + CDN + ":bad/a", "https://" + CDN + ":65536/a", "https://@" + CDN + "/a",
                         "https://user:private@" + CDN + "/a", "/audio#", "/audio#private", "/audio\\private",
                         " /audio", "/audio\nprivate", "https://[bad/a", "/audio?x=%zz", "/audio?x=%", "/" + "x" * 8192,
                         "https://" + "a" * 64 + ".yandex.net/a"):
            with self.subTest(location=location), self.assertRaisesRegex(core.Rejected, "STREAM_REDIRECT_REJECTED"):
                stream.redirect_target(source, location)
        with self.assertRaisesRegex(core.Rejected, "STREAM_REDIRECT_REJECTED"):
            stream.redirect_target("https://" + CDN + "/" + "a/" * 4000 + "a", "b" * 500)

    def test_two_manual_hops_close_before_next_get_and_preserve_private_query(self):
        source = "https://api.music.yandex.net/start"
        target = "https://" + CDN + "/private?signature=" + SECRET
        last = "https://" + CDN2 + "/final?signature=" + SECRET
        with self.transport([(308, target), (308, last), (200, None)]) as calls, \
                patch("sys.stderr", new_callable=io.StringIO) as output:
            with stream.media_response(source) as response:
                self.assertEqual(response.status_code, 200)
            self.assertEqual(calls, [source, target, last])
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(events), 2)
            self.assertTrue(all(e["followed"] and e["http_status"] == 308 and e["stage"] == "media_get" for e in events))
            for private in (SECRET, "signature", "/private", "/final", "https://"):
                self.assertNotIn(private, output.getvalue())

    def test_loops_and_third_redirect_never_make_extra_request(self):
        source = "https://api.music.yandex.net/start"
        target = "https://" + CDN + "/next"
        for replies, reason, count in (([(308, source)], "STREAM_REDIRECT_LOOP", 1),
                                       ([(308, "https://API.MUSIC.YANDEX.NET:443/%73tart")], "STREAM_REDIRECT_LOOP", 1),
                                       ([(308, target), (308, source)], "STREAM_REDIRECT_LOOP", 2),
                                       ([(308, target), (308, "/second"), (308, "/third")], "STREAM_REDIRECT_LIMIT", 3)):
            with self.subTest(reason=reason, count=count), self.transport(replies) as calls, \
                    patch("sys.stderr", new_callable=io.StringIO) as output:
                with self.assertRaisesRegex(core.Rejected, reason), stream.media_response(source):
                    self.fail("No final response permitted")
                self.assertEqual(len(calls), count)
                self.assertFalse(json.loads(output.getvalue().splitlines()[-1])["followed"])

    def test_invalid_location_and_other_3xx_stop_without_next_get(self):
        for status, location in ((308, None), (308, "http://" + CDN + "/private"), (308, "https://external.invalid/private"),
                                 (308, "https:///" + CDN + "/private"), (302, "https://" + CDN + "/private"),
                                 (307, "https://" + CDN + "/private")):
            with self.subTest(status=status, location=location), self.transport([(status, location)]) as calls, \
                    patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaisesRegex(core.Rejected, "STREAM_REDIRECT_REJECTED"), \
                        stream.media_response("https://api.music.yandex.net/start"):
                    self.fail("No final response permitted")
                self.assertEqual(len(calls), 1)

    def test_tls_access_cancel_and_chain_deadline_wipe_pcm(self):
        real_timeout = stream.timeout
        def delayed():
            time.sleep(.1)
            return 200, None
        cases = [(requests.exceptions.SSLError(SECRET), core.Rejected, "STREAM_TRANSPORT_OR_DECODER_FAILED"),
                 (KeyboardInterrupt(), KeyboardInterrupt, ""), ((401, None), core.Rejected, "STREAM_ACCESS_DENIED_OR_EXPIRED"),
                 ((403, None), core.Rejected, "STREAM_ACCESS_DENIED_OR_EXPIRED"),
                 ((410, None), core.Rejected, "STREAM_LINK_EXPIRED"), (delayed, core.Rejected, "STREAM_DECODE_TIMEOUT")]
        for reply, error, reason in cases:
            allocated = np.ones((12 * 48000 + 1, 2), dtype="<f4")
            with self.subTest(reason=reason), self.transport([(308, "https://" + CDN + "/next"), reply]) as calls, \
                    patch("yandex_stream.np.zeros", return_value=allocated), patch("yandex_stream.subprocess.Popen") as decoder, \
                    patch("sys.stderr", new_callable=io.StringIO) as output, \
                    patch("yandex_stream.timeout", side_effect=lambda _, reason: real_timeout(.03 if reply is delayed else 60, reason)) as timer:
                with self.assertRaisesRegex(error, reason):
                    stream.decode("https://api.music.yandex.net/start", "mp3", 30, 12)
                self.assertTrue((allocated == 0).all())
                self.assertEqual(len(calls), 2)
                timer.assert_called_once_with(60, "STREAM_DECODE_TIMEOUT")
                decoder.assert_not_called()
                self.assertNotIn(SECRET, output.getvalue())


class YandexStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mp3 = encoded("mp3")
        cls.aac = encoded("aac")

    def test_real_http_mp3_aac_prefix_decode_and_repeat(self):
        for codec, data in (("mp3", self.mp3), ("aac", self.aac)):
            with self.subTest(codec=codec), fixture(data, codec) as calls:
                first, count = stream.decode("https://" + HOST + "/get-mp3/fixture", codec, 30, 12)
                second, count2 = stream.decode("https://" + HOST + "/get-mp3/fixture", codec, 30, 12)
                try:
                    self.assertEqual(first.shape, (12 * 48000, 2))
                    self.assertTrue(np.array_equal(first, second))
                    self.assertLess(count, len(data) * .7)
                    self.assertLess(count2, len(data) * .7)
                    core.signal_quality(first, 48000)
                finally:
                    first.fill(0)
                    second.fill(0)
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(auth is None for _, auth in calls))

    def test_real_http_308_cli_mp3_to_profile_and_index_without_credentials(self):
        first = "https://" + CDN + "/private-audio?signature=" + SECRET + "&part=1"
        second = "https://" + CDN2 + "/private-audio?signature=" + SECRET + "&part=2"
        profiles = []
        for hops in (1, 2):
            access = []
            with self.subTest(hops=hops), fixture(self.mp3, media_steps=[(308, first), (308, second)][:hops], media_calls=access) as calls, \
                    tempfile.TemporaryDirectory(dir="/tmp") as tmp, patch("sys.stdin.isatty", return_value=True), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, patch("sys.stdout.isatty", return_value=True), \
                    patch("sys.stderr", new_callable=io.StringIO) as diagnostic, \
                    patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value="START 123"):
                directory = Path(tmp) / "private"
                store.return_value.read.return_value = SECRET
                argv = ["personal_index", "--yandex-stream", "--track-id", "123", "--start", "30", "--seconds", "12",
                        "--index-dir", str(directory)]
                with patch.object(sys, "argv", argv):
                    personal_index.main()
                row, = core.Index(directory).records()
                profiles.append(row["profile"])
                self.assertEqual(row["source"], "yandex_stream")
                self.assertEqual(row["identity"], core.stream_identity("123", "123"))
                self.assertEqual(row["capture"]["seconds"], 12)
                self.assertLess(row["capture"]["received_bytes"], len(self.mp3) * .7)
                self.assertIn('"status": "INSERTED"', output.getvalue())
                self.assertIn('"dimensions": 705', output.getvalue())
                self.assertEqual(len(calls), 6 + hops)
                self.assertEqual([c[0] for c in access], ["api.music.yandex.net", CDN, CDN2][:hops + 1])
                self.assertEqual([c[1] for c in access[1:]], ["/private-audio?signature=" + SECRET + "&part=" + str(i)
                                                            for i in range(1, hops + 1)])
                self.assertTrue(all(auth is cookie is proxy is None for _, _, auth, cookie, proxy in access))
                self.assertTrue(all(json.loads(line)["followed"] for line in diagnostic.getvalue().splitlines()))
                self.assertEqual([p.relative_to(tmp).as_posix() for p in Path(tmp).rglob("*") if p.is_file()], ["private/index.sqlite3"])
                for forbidden in (SECRET, "signature", "/private-audio", "https://", "Authorization", "Cookie"):
                    self.assertNotIn(forbidden, output.getvalue() + diagnostic.getvalue())
                    self.assertNotIn(forbidden.encode(), (directory / "index.sqlite3").read_bytes())
                for forbidden in (b"ID3", b"RIFF", CDN.encode(), CDN2.encode()):
                    self.assertNotIn(forbidden, (directory / "index.sqlite3").read_bytes())
                store.return_value.write.assert_not_called()
                store.return_value.delete.assert_not_called()
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0], profiles[1])

    def test_real_http_308_failure_partial_and_byte_limit_never_open_index(self):
        first = "https://" + CDN + "/one?signature=" + SECRET
        cases = [([(308, first), (308, first)], "ok", "STREAM_REDIRECT_LOOP", 2, stream.MAX_BYTES),
                 ([(308, first), (308, "/two"), (308, "/three")], "ok", "STREAM_REDIRECT_LIMIT", 3, stream.MAX_BYTES),
                 ([(308, first), (403, None)], "ok", "STREAM_ACCESS_DENIED_OR_EXPIRED", 2, stream.MAX_BYTES),
                 ([(308, first), (410, None)], "ok", "STREAM_LINK_EXPIRED", 2, stream.MAX_BYTES),
                 ([(308, first)], "partial", "STREAM_(PARTIAL_PCM|DECODE_FAILED)", 2, stream.MAX_BYTES),
                 ([(308, first)], "ok", "STREAM_BYTE_LIMIT", 2, 100)]
        for steps, mode, reason, count, limit in cases:
            access = []
            with self.subTest(reason=reason), fixture(self.mp3, mode=mode, media_steps=steps, media_calls=access), \
                    patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                    patch("builtins.print"), patch("yandex_stream.SecretStore") as store, \
                    patch("builtins.input", return_value="START 123"), patch("personal_index.Index") as index, \
                    patch("yandex_stream.MAX_BYTES", limit), \
                    patch.object(sys, "argv", ["personal_index", "--yandex-stream", "--track-id", "123", "--start", "30", "--seconds", "12"]):
                store.return_value.read.return_value = SECRET
                with self.assertRaisesRegex(core.Rejected, reason):
                    personal_index.main()
                self.assertEqual(len(access), count)
                self.assertTrue(all(auth is cookie is proxy is None for _, _, auth, cookie, proxy in access))
                index.assert_not_called()

    def test_complete_cli_sdk_synthetic_auth_index_and_legacy_migration(self):
        with fixture(self.mp3) as calls, tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            directory = Path(tmp) / "private"
            index = core.Index(directory)
            with index.connection() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            argv = ["personal_index", "--yandex-stream", "--track-id", "123", "--start", "30", "--seconds", "12",
                    "--index-dir", str(directory)]
            with patch.object(sys, "argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, patch("sys.stdout.isatty", return_value=True), \
                    patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value="START 123"), \
                    patch("live.Mpris", side_effect=AssertionError("No MPRIS")), \
                    patch("live.Capture", side_effect=AssertionError("No Pulse")):
                store.return_value.read.return_value = SECRET
                personal_index.main()
                original_profile = index.records()[0]["profile"]
                personal_index.main()
                self.assertEqual(index.records()[0]["profile"], original_profile)
                self.assertIn('"status": "UNCHANGED"', output.getvalue())
                self.assertIn('"dimensions": 705', output.getvalue())
                self.assertNotIn(SECRET, output.getvalue())
                self.assertNotIn(HOST, output.getvalue())
                store.return_value.write.assert_not_called()
                store.return_value.delete.assert_not_called()
            row, = index.records()
            self.assertEqual(row["source"], "yandex_stream")
            self.assertEqual(row["identity"], core.stream_identity("123", "123"))
            self.assertEqual(row["capture"]["start_seconds"], 30)
            self.assertEqual(row["capture"]["codec"], "mp3")
            self.assertEqual(row["capture"]["extractor_schema"], row["profile"]["feature_schema"])
            self.assertEqual(sum(core.retrieval.SHAPES.values()), 705)
            with index.connection() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual([p.name for p in directory.iterdir()], ["index.sqlite3"])
            for forbidden in (SECRET.encode(), HOST.encode(), b"https://", b"Authorization", b"ID3", b"RIFF"):
                self.assertNotIn(forbidden, index.path.read_bytes())
            legacy = copy.deepcopy(row)
            legacy.update(schema=core.SCHEMA, source="file", identity=core.identity(), capture=None)
            legacy["quality"] = {k: legacy["quality"][k] for k in core.LEGACY_QUALITY_FIELDS}
            legacy["profile"].update(id="legacy", recording_group="legacy")
            migration = core.Index(Path(tmp) / "legacy-index")
            migration.put(legacy)
            with migration.connection() as db:
                before = db.execute("SELECT payload FROM records WHERE id='legacy'").fetchone()[0]
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            migration.put(row)
            with migration.connection() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(db.execute("SELECT payload FROM records WHERE id='legacy'").fetchone()[0], before)
            self.assertEqual({r["source"] for r in migration.records()}, {"file", "yandex_stream"})
            self.assertEqual(len(calls), 12)
            self.assertEqual([auth for path, auth in calls if path in ("/account/status", "/tracks", "/tracks/123/download-info")],
                             ["OAuth " + SECRET] * 8)
            self.assertTrue(all(auth is None for path, auth in calls if path not in
                                ("/account/status", "/tracks", "/tracks/123/download-info")))
            for mutation in (lambda r: r.update(source="file"), lambda r: r.update(source="live"),
                             lambda r: r["identity"].update(observed_id="456"),
                             lambda r: r["identity"].update(master_match=True),
                             lambda r: r["capture"].update(url="https://private.invalid"),
                             lambda r: r["capture"].update(start_seconds=61),
                             lambda r: r["capture"].update(received_bytes=stream.MAX_BYTES + 1),
                             lambda r: r["capture"]["metadata"].update(album_title="https://secret.invalid")):
                bad = copy.deepcopy(row)
                mutation(bad)
                with self.assertRaises(core.Rejected):
                    index.put(bad, replace=True)

    def test_partial_disconnect_expired_redirect_reject_and_wipe(self):
        for mode in ("partial", "broken", "expired", "denied", "redirect"):
            with self.subTest(mode=mode), fixture(self.mp3, mode=mode) as calls:
                allocated = np.zeros((12 * 48000 + 1, 2), dtype="<f4")
                with patch("yandex_stream.np.zeros", return_value=allocated):
                    with self.assertRaises(core.Rejected):
                        stream.decode("https://" + HOST + "/get-mp3/fixture", "mp3", 30, 12)
                self.assertTrue((allocated == 0).all())
                self.assertEqual(len(calls), 1)

    def test_real_http_redirect_at_every_stage_stops_before_index_and_followup(self):
        stages = [("/account/status", 1, "metadata_api", "GET", 1),
                  ("/tracks", 1, "metadata_api", "POST", 2),
                  ("/tracks", 2, "metadata_api", "POST", 3),
                  ("/tracks/123/download-info", 1, "tracks_download_info", "GET", 4),
                  ("/info", 1, "download_info_xml", "GET", 5),
                  ("/get-mp3/", 1, "media_get", "GET", 6)]
        for status in (302, 307):
            for path, occurrence, stage, method, count in stages:
                location = "https://external.invalid/private-path?signature=" + SECRET
                with self.subTest(status=status, stage=stage, count=count), \
                        fixture(self.mp3, redirect=(path, occurrence, status, location)) as calls, \
                        tempfile.TemporaryDirectory(dir="/tmp") as tmp, \
                        patch("sys.stdin.isatty", return_value=True), \
                        patch("sys.stdout", new_callable=io.StringIO) as output, \
                        patch("sys.stdout.isatty", return_value=True), \
                        patch("sys.stderr", new_callable=io.StringIO) as diagnostic, \
                        patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value="START 123"), \
                        patch("yandex_stream.subprocess.Popen") as decoder, patch("personal_index.Index") as index:
                    store.return_value.read.return_value = SECRET
                    directory = Path(tmp) / "private"
                    argv = ["personal_index", "--yandex-stream", "--track-id", "123", "--start", "30", "--seconds", "12",
                            "--index-dir", str(directory)]
                    with patch.object(sys, "argv", argv), self.assertRaisesRegex(core.Rejected, "^STREAM_REDIRECT_REJECTED$"):
                        personal_index.main()
                    self.assertEqual(json.loads(diagnostic.getvalue()), dict(event="STREAM_REDIRECT", stage=stage, method=method,
                                     http_status=status, source_hostname="api.music.yandex.net" if count <= 4 else HOST,
                                     target_hostname="external.invalid", classification="HOST_NOT_ALLOWLISTED", followed=False))
                    self.assertEqual(len(calls), count)
                    self.assertTrue(all(auth is None for p, auth in calls if p == "/info" or p.startswith("/get-mp3/")))
                    decoder.assert_not_called()
                    index.assert_not_called()
                    self.assertFalse(directory.exists())
                    for private in (SECRET, "private-path", "signature", "Authorization", "Cookie", "https://"):
                        self.assertNotIn(private, output.getvalue() + diagnostic.getvalue())

    def test_partial_decode_cli_does_not_open_index(self):
        with fixture(self.mp3, mode="partial"), patch("sys.stdin.isatty", return_value=True), \
                patch("sys.stdout.isatty", return_value=True), patch("builtins.print"), \
                patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value="START 123"), \
                patch("personal_index.Index") as index, \
                patch.object(sys, "argv", ["personal_index", "--yandex-stream", "--track-id", "123", "--start", "30", "--seconds", "12"]):
            store.return_value.read.return_value = SECRET
            with self.assertRaises(core.Rejected):
                personal_index.main()
            index.assert_not_called()

    def test_untrusted_url_and_bad_windows_never_start_transport(self):
        for url in ("http://" + HOST + "/a", "https://127.0.0.1/a", "https://yandex.net.evil.test/a",
                    "https://user:secret@" + HOST + "/a", "https://" + HOST + ":444/a", "file:///private",
                    "https://" + HOST + "/a#fragment", "https://" + HOST + "/a\nsecret"):
            with self.subTest(url=url), patch("yandex_stream.session") as http:
                with self.assertRaisesRegex(core.Rejected, "STREAM_URL_REJECTED"):
                    stream.decode(url, "mp3", 30, 12)
                http.assert_not_called()
        for start, seconds in ((-1, 12), (61, 12), (0, 16), (0, 9), (float("nan"), 12), (0, float("inf"))):
            with self.subTest(start=start, seconds=seconds), patch("yandex_stream.SecretStore") as store:
                with self.assertRaises(core.Rejected):
                    stream.acquire("123", start, seconds)
                store.assert_not_called()

    def test_manual_cancel_identity_mismatch_and_preview_no_audio_or_index(self):
        for mode, answer, reason, count in (("ok", "cancel", "OWNER_CANCELLED", 2),
                                           ("id_mismatch", "START 123", "STREAM_TRACK_ID_MISMATCH", 2),
                                           ("changed_id", "START 123", "STREAM_TRACK_ID_MISMATCH", 5),
                                           ("preview", "START 123", "Полного аудио нет", 4)):
            with self.subTest(mode=mode), fixture(self.mp3, mode=mode) as calls, \
                    patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                    patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value=answer), \
                    patch("builtins.print"):
                store.return_value.read.return_value = SECRET
                with self.assertRaisesRegex(Exception, reason):
                    stream.acquire("123", 30, 12)
                self.assertEqual(len(calls), count)
                self.assertFalse(any(path.startswith("/get-mp3") for path, _ in calls))

    def test_byte_limit_cancel_and_decoder_memory_limit(self):
        real_popen = subprocess.Popen
        processes = []
        def popen(*args, **kwargs):
            self.assertNotIn(HOST, str(args))
            self.assertEqual(kwargs["env"].get("FFREPORT"), None)
            p = real_popen(*args, **kwargs)
            processes.append(p)
            return p
        with fixture(self.mp3), patch("yandex_stream.subprocess.Popen", side_effect=popen):
            with patch("yandex_stream.MAX_BYTES", 100):
                with self.assertRaisesRegex(core.Rejected, "STREAM_BYTE_LIMIT"):
                    stream.decode("https://" + HOST + "/get-mp3/fixture", "mp3", 30, 12)
            with patch("yandex_stream.os.readv", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    stream.decode("https://" + HOST + "/get-mp3/fixture", "mp3", 30, 12)
            with patch("yandex_stream.DECODER_MEMORY", 8 * 1024**2):
                with self.assertRaises(core.Rejected):
                    stream.decode("https://" + HOST + "/get-mp3/fixture", "mp3", 30, 12)
        self.assertTrue(all(p.poll() is not None for p in processes))

    def test_metadata_budget_no_credentials_to_cdn_and_hard_timeout(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            keylog = Path(tmp) / "tls-secrets.log"
            result = subprocess.run([sys.executable, str(Path(personal_index.__file__)), "--help"],
                                    env={**os.environ, "SSLKEYLOGFILE": str(keylog)},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(keylog.exists())
        request = stream.BoundedRequest()
        with patch("yandex_stream.session") as http:
            request.calls = 8
            with self.assertRaisesRegex(core.Rejected, "STREAM_REQUEST_LIMIT"):
                request.get("https://api.music.yandex.net/tracks")
            request.calls = 0
            request.set_authorization(SECRET)
            with self.assertRaisesRegex(core.Rejected, "STREAM_AUTH_DESTINATION_REJECTED"):
                request.get("https://" + HOST + "/metadata")
            http.assert_not_called()
        with self.assertRaisesRegex(core.Rejected, "TEST_TIMEOUT"):
            with stream.timeout(.02, "TEST_TIMEOUT"):
                time.sleep(.1)

    def test_metadata_body_limit_and_excessive_amplitude_no_profile(self):
        with fixture(self.mp3) as calls:
            request = stream.BoundedRequest()
            with self.assertRaisesRegex(core.Rejected, "STREAM_METADATA_LIMIT"):
                request.retrieve("https://" + HOST + "/get-mp3/fixture")
            self.assertEqual(len(calls), 1)
        with fixture(encoded("aac", 20, 12), "aac"), \
                patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("yandex_stream.SecretStore") as store, patch("builtins.input", return_value="START 123"), \
                patch("builtins.print"):
            store.return_value.read.return_value = SECRET
            pcm, capture = stream.acquire("123", 0, 12)
            with self.assertRaisesRegex(core.Rejected, "AMPLITUDE_OUT_OF_POLICY"):
                core.extract(pcm, stream.RATE, "yandex-stream-123", core.stream_identity("123", "123"),
                             "yandex_stream", capture["metadata"]["title"], capture["metadata"]["artists"], capture)
            self.assertTrue((pcm == 0).all())

    def test_slow_http_deadline_and_missing_owner_login(self):
        real_timeout = stream.timeout
        with fixture(self.mp3, mode="slow"), patch("yandex_stream.timeout", side_effect=lambda _, reason: real_timeout(.1, reason)):
            with self.assertRaisesRegex(core.Rejected, "STREAM_DECODE_TIMEOUT"):
                stream.decode("https://" + HOST + "/get-mp3/fixture", "mp3", 30, 12)
        with patch("sys.stdin.isatty", return_value=False), patch("yandex_stream.SecretStore") as store:
            with self.assertRaisesRegex(core.Rejected, "OWNER_TERMINAL_REQUIRED"):
                stream.acquire("123", 30, 12)
            store.assert_not_called()
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("yandex_stream.SecretStore") as store, patch("yandex_stream.session") as http:
            store.return_value.read.return_value = None
            with self.assertRaisesRegex(core.Rejected, "YANJARO_SAVED_LOGIN_REQUIRED"):
                stream.acquire("123", 30, 12)
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()

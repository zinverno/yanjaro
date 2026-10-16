"""Explicit single-track acquisition. Secrets/URLs stay in RAM; FFmpeg sees only pipes."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import resource
import select
import signal
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

import numpy as np
import requests
from urllib3.exceptions import HTTPError

from core import Rejected, require, safe_text, track_id

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from yandex_music import Client
from yanjaro.api import AccountRequest, MusicApi
from yanjaro.storage import SecretStore

RATE = 48000
MAX_BYTES = 8 * 1024**2
MAX_METADATA = 1024**2
CHUNK = 16384
DECODER_MEMORY = 768 * 1024**2


@contextmanager
def timeout(seconds, reason):
    require(seconds > 0, reason)
    def expired(*_):
        raise Rejected(reason)
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def window(start, seconds):
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, seconds)) and
            0 <= start <= 60 and 10 <= seconds <= 15, "STREAM_WINDOW_LIMIT")


def validate_url(url):
    try:
        parsed = urlsplit(url)
        require(isinstance(url, str) and len(url) <= 8192 and all(32 < ord(c) < 127 for c in url) and
                parsed.scheme == "https" and parsed.hostname and
                parsed.hostname.endswith((".yandex.net", ".yandex.ru")) and
                not parsed.username and not parsed.password and not parsed.fragment and
                parsed.port in (None, 443), "STREAM_URL_REJECTED")
        return parsed.hostname
    except (ValueError, TypeError):
        raise Rejected("STREAM_URL_REJECTED") from None


def session():
    result = requests.Session()
    result.trust_env = False  # No proxy/netrc credentials or inherited environment authorization.
    result.headers["Accept-Encoding"] = "identity"
    return result


def diagnostic_hostname(url):
    try:
        host = urlsplit(url).hostname
        if host and len(host) <= 253 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                           for label in host.split(".")):
            return host
    except (TypeError, ValueError):
        pass
    return None


def redirect_details(url, location):
    """Classify only; never return a URL or authorize a follow-up request."""
    if location is None or location == "":
        return None, "MISSING_LOCATION"
    if not isinstance(location, str) or len(location) > 8192 or "\\" in location or \
            not all(32 < ord(c) < 127 for c in location):
        return None, "INVALID_LOCATION"
    host = None
    try:
        target = urljoin(url, location)
        parsed = urlsplit(target)
        host = diagnostic_hostname(target)
        if parsed.scheme != "https":
            return host, "HTTPS_DOWNGRADE" if parsed.scheme == "http" else "UNSUPPORTED_SCHEME"
        if parsed.username is not None or parsed.password is not None:
            return host, "USERINFO_REJECTED"
        if "#" in location:
            return host, "FRAGMENT_REJECTED"
        if parsed.port not in (None, 443):
            return host, "PORT_REJECTED"
        if not host:
            return None, "INVALID_LOCATION"
        if not host.endswith((".yandex.net", ".yandex.ru")):
            return host, "HOST_NOT_ALLOWLISTED"
        if target == url:
            return host, "SELF_REDIRECT"
        return host, "SAME_ORIGIN" if host == diagnostic_hostname(url) else "CROSS_ORIGIN_WITHIN_ALLOWLIST"
    except (TypeError, ValueError):
        return host, "INVALID_LOCATION"


def response_check(response, *, stage, url, method):
    if response.status_code == 410:
        raise Rejected("STREAM_LINK_EXPIRED")
    if response.status_code in (401, 403):
        raise Rejected("STREAM_ACCESS_DENIED_OR_EXPIRED")
    if 300 <= response.status_code < 400:
        target, classification = redirect_details(url, response.headers.get("Location"))
        try:
            print(json.dumps(dict(event="STREAM_REDIRECT", stage=stage, method=method,
                                  http_status=response.status_code, source_hostname=diagnostic_hostname(url),
                                  target_hostname=target, classification=classification, followed=False)),
                  file=sys.stderr, flush=True)
        except OSError:
            pass  # Diagnostic output failure must not permit the redirect.
        raise Rejected("STREAM_REDIRECT_REJECTED")
    require(response.status_code == 200, "STREAM_HTTP_FAILED")
    require(response.headers.get("Content-Encoding", "identity").lower() == "identity", "STREAM_ENCODING_REJECTED")


class BoundedRequest(AccountRequest):
    """Keep the existing SDK/account adapter, bound its metadata HTTP transport."""
    def __init__(self):
        super().__init__(timeout=3)
        self.calls = 0
        self.deadline = time.monotonic() + 30

    def _request_wrapper(self, method, url, **kwargs):
        host = validate_url(url)
        stage = kwargs.pop("_stage", "metadata_api")
        require(method in ("GET", "POST") and self.calls < 8, "STREAM_REQUEST_LIMIT")
        require(time.monotonic() < self.deadline, "STREAM_METADATA_TIMEOUT")
        kwargs = self._prepare_kwargs(kwargs)
        kwargs["headers"] = {**kwargs["headers"], "Accept-Encoding": "identity"}
        require(host == "api.music.yandex.net" or not any(k.lower() == "authorization" for k in kwargs["headers"]),
                "STREAM_AUTH_DESTINATION_REJECTED")
        kwargs.pop("proxies", None)
        kwargs["timeout"] = (3, 3)
        self.calls += 1
        try:
            with timeout(self.deadline - time.monotonic(), "STREAM_METADATA_TIMEOUT"), session() as http, \
                    http.request(method, url, stream=True, allow_redirects=False, **kwargs) as response:
                response_check(response, stage=stage, url=url, method=method)
                body = bytearray()
                for part in response.iter_content(CHUNK):
                    require(time.monotonic() < self.deadline, "STREAM_METADATA_TIMEOUT")
                    require(len(body) + len(part) <= MAX_METADATA, "STREAM_METADATA_LIMIT")
                    body.extend(part)
                return bytes(body)
        except requests.RequestException:
            raise Rejected("STREAM_METADATA_NETWORK_ERROR") from None

    def retrieve(self, *args, **kwargs):
        return super().retrieve(*args, **kwargs, _stage="download_info_xml")


class ObservedClient(Client):
    # MusicApi.stream selects the variant; retain only its SDK objects until that call returns.
    def tracks_download_info(self, *args, **kwargs):
        self.variants = super().tracks_download_info(*args, **kwargs, _stage="tracks_download_info")
        return self.variants


def decoder_limits():
    resource.setrlimit(resource.RLIMIT_AS, (DECODER_MEMORY, DECODER_MEMORY))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def decode(url, codec, start, seconds):
    window(start, seconds)
    validate_url(url)
    require(codec in ("mp3", "aac"), "STREAM_CODEC_REJECTED")
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-max_alloc", "33554432",
            "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "pipe",
            "-format_whitelist", "mp3" if codec == "mp3" else "aac,mov",
            "-codec_whitelist", "mp3,mp3float" if codec == "mp3" else "aac",
            "-probesize", "32768", "-analyzeduration", "1000000", "-i", "pipe:0",
            "-ss", str(start), "-t", str(seconds), "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-map_metadata", "-1", "-threads", "1", "-ac", "2", "-ar", str(RATE),
            "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
    expected = round(seconds * RATE) * 8
    pcm = np.zeros((round(seconds * RATE) + 1, 2), dtype="<f4")
    raw = memoryview(pcm).cast("B")
    process = None
    success = False
    deadline = time.monotonic() + 60
    received = written = 0
    pending = b""
    try:
        with timeout(60, "STREAM_DECODE_TIMEOUT"), session() as http, \
                http.get(url, stream=True, allow_redirects=False, timeout=(3, 3)) as response:
            response_check(response, stage="media_get", url=url, method="GET")
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       bufsize=0, preexec_fn=decoder_limits, close_fds=True,
                                       env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
                                            "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            input_open = True
            while True:
                require(time.monotonic() < deadline, "STREAM_DECODE_TIMEOUT")
                readable, writable, _ = select.select([process.stdout], [process.stdin] if input_open else [], [], .1)
                if readable:
                    n = os.readv(process.stdout.fileno(), [raw[written:min(written + CHUNK, len(raw))]])
                    if not n:
                        break
                    written += n
                    require(written <= expected, "STREAM_PCM_LIMIT")
                if writable:
                    if not pending:
                        require(received < MAX_BYTES, "STREAM_BYTE_LIMIT")
                        pending = response.raw.read(min(CHUNK, MAX_BYTES - received), decode_content=False)
                        received += len(pending)
                        if not pending:
                            process.stdin.close()
                            input_open = False
                            continue
                    try:
                        n = os.write(process.stdin.fileno(), pending)
                        pending = pending[n:]
                    except BrokenPipeError:
                        process.stdin.close()
                        input_open = False
            if input_open:
                process.stdin.close()
            require(process.wait(timeout=3) == 0, "STREAM_DECODE_FAILED")
            require(written == expected, "STREAM_PARTIAL_PCM")
        success = True
        return pcm[:-1], received
    except (requests.RequestException, HTTPError, OSError, subprocess.SubprocessError):
        raise Rejected("STREAM_TRANSPORT_OR_DECODER_FAILED") from None
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            for pipe in (process.stdin, process.stdout):
                pipe.close()
        if not success:
            pcm.fill(0)


def metadata(track, requested):
    require(track_id(track.id) == requested, "STREAM_TRACK_ID_MISMATCH")
    require(track.available is True and type(track.duration) in (int, float) and
            math.isfinite(track.duration) and 0 < track.duration <= 86400, "STREAM_TRACK_UNAVAILABLE")
    require(len(track.artists) <= 10, "INVALID_ARTISTS")
    return dict(id=track.id, title=safe_text(track.title), artists=[safe_text(a["title"]) for a in track.artists],
                duration_seconds=track.duration, album_id=track_id(track.album_id) if track.album_id else None,
                album_title=safe_text(track.album_title))


def acquire(requested, start, seconds):
    """Called only by the explicit owner CLI. Never writes or deletes credentials."""
    from yanjaro.api import track_model
    from core import retrieval
    window(start, seconds)
    track_id(requested)
    require(sys.stdin.isatty() and sys.stdout.isatty(), "OWNER_TERMINAL_REQUIRED")
    request = BoundedRequest()
    api = MusicApi(ObservedClient(request=request))
    pcm = None
    success = False
    try:
        token = SecretStore().read()
        require(bool(token), "YANJARO_SAVED_LOGIN_REQUIRED")
        api.restore(token)
        token = None
        tracks = api.client.tracks([requested])
        require(tracks is not None and len(tracks) == 1, "STREAM_TRACK_UNAVAILABLE")
        before = metadata(track_model(tracks[0]), requested)
        require(start + seconds <= before["duration_seconds"], "STREAM_WINDOW_PAST_END")
        print(json.dumps(before, ensure_ascii=False))
        print(f"Один разрешённый эксперимент: {start:g}–{start + seconds:g} s. Ctrl-C отменяет; аудиофайл не сохраняется.")
        require(input("Для загрузки введите START " + requested + ": ") == "START " + requested, "OWNER_CANCELLED")
        request.deadline = time.monotonic() + 30
        started = datetime.now(timezone.utc).isoformat()
        stream = api.stream(requested)
        after = metadata(stream.track, requested)
        require(after == before, "STREAM_METADATA_CHANGED")
        chosen = [v for v in api.client.variants if v.direct_link == stream.url]
        require(len(chosen) == 1 and chosen[0].preview is False and chosen[0].codec in ("mp3", "aac"),
                "STREAM_VARIANT_UNCONFIRMED")
        variant = chosen[0]
        require(type(variant.bitrate_in_kbps) is int and 0 < variant.bitrate_in_kbps <= 512, "STREAM_BITRATE_REJECTED")
        pcm, received = decode(stream.url, variant.codec, start, seconds)
        capture = dict(method="authorized-yandex-stream-ffmpeg", sample_rate=RATE, codec=variant.codec,
                       bitrate_kbps=variant.bitrate_in_kbps, start_seconds=start, seconds=len(pcm) / RATE,
                       received_bytes=received, metadata=after, started_at=started,
                       extractor_schema=retrieval.FEATURE_SCHEMA,
                       stopped_at=datetime.now(timezone.utc).isoformat())
        success = True
        return pcm, capture
    finally:
        api.logout()
        if pcm is not None and not success:
            pcm.fill(0)

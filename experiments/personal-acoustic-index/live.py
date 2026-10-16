"""Explicit owner action, MPRIS identity/state guard and one process's audio stream."""
from collections import deque
from datetime import datetime, timezone
import json
import os
import re
import select
import subprocess
import sys
import time

from core import Rejected, identity, require, safe_text
from pulse import Capture, RATE, SERVER, object_id

SERVICE = "org.mpris.MediaPlayer2.yanjaro"
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"


def pactl(kind):
    command = ["pactl", "--server", SERVER, "-f", "json", "list", kind]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2)
    require(result.returncode == 0 and len(result.stdout) < 1024**2, "LOCAL_PULSE_METADATA_UNAVAILABLE")
    return json.loads(result.stdout)


def volume(item):
    result = [v["value"] for v in item["volume"].values()]
    require(result and all(type(v) is int and 0 < v <= 65536 * 2 for v in result), "UNSAFE_GAIN")
    return result


def select_audio(pid, inputs, sinks, clients):
    clients = [dict(c, index=object_id(c.get("index"))) for c in clients]
    sinks = [dict(s, index=object_id(s.get("index"))) for s in sinks]
    candidates = []
    for stream in inputs:
        stream = dict(stream, index=object_id(stream.get("index")), sink=object_id(stream.get("sink")),
                      client=object_id(stream["client"]) if stream.get("client") is not None else None)
        direct_pid = stream.get("properties", {}).get("application.process.id")
        linked = [c for c in clients if c["index"] == stream["client"]]
        client_pid = linked[0].get("properties", {}).get("application.process.id") if len(linked) == 1 else None
        if str(pid) not in (direct_pid, client_pid):
            continue
        # Keep a verifiable client link even when the stream publishes its own PID.
        require(len(linked) == 1, "AUDIO_CLIENT_UNAVAILABLE")
        require(direct_pid is None or client_pid is None or direct_pid == client_pid, "AUDIO_PROCESS_ID_CONFLICT")
        candidates.append((stream, direct_pid, client_pid))
    require(candidates, "YANJARO_AUDIO_STREAM_NOT_FOUND")
    require(len(candidates) == 1, "YANJARO_AUDIO_STREAM_NOT_UNIQUE")
    stream, direct_pid, client_pid = candidates[0]
    matches = [s for s in sinks if s["index"] == stream["sink"]]
    require(len(matches) == 1, "AUDIO_SINK_UNAVAILABLE")
    sink = matches[0]
    require(not stream.get("mute", True) and not stream.get("corked", True) and not sink.get("mute", True),
            "AUDIO_MUTED_OR_PAUSED")
    require(isinstance(sink.get("monitor_source"), str) and
            re.fullmatch(r"[a-zA-Z0-9_.:-]{1,256}", sink["monitor_source"]), "NO_SINK_INPUT_MONITOR")
    return dict(index=stream["index"], sink=stream["sink"], monitor=sink["monitor_source"],
                client=stream["client"], direct_pid=direct_pid, client_pid=client_pid,
                stream_volume=volume(stream), sink_volume=volume(sink))


def audio_route(pid):
    return select_audio(pid, pactl("sink-inputs"), pactl("sinks"), pactl("clients"))


def signal_ok(member, body):
    require(member != "Seeked", "PLAYBACK_SEEKED")
    if member == "PropertiesChanged" and body[0] == PLAYER:
        changed, invalidated = body[1], body[2]
        critical = {"Metadata", "PlaybackStatus", "Volume", "Rate"}
        require(not critical.intersection(invalidated), "MPRIS_INVALIDATED")
        require(not critical.intersection(changed), "PLAYBACK_CHANGED_DURING_CAPTURE")


def check_snapshot(initial, current, elapsed):
    require(current["status"] == "Playing", "PLAYBACK_NOT_PLAYING")
    require(all(initial[k] == current[k] for k in ("path", "title", "artists", "length", "volume", "rate")),
            "TRACK_OR_GAIN_CHANGED")
    require(abs((current["position"] - initial["position"]) / 1e6 - elapsed) <= 1.0,
            "PLAYBACK_POSITION_DISCONTINUITY")


class Mpris:
    def __init__(self):
        from jeepney import DBusAddress, MatchRule, new_method_call
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection
        self.address = DBusAddress(PATH, bus_name=SERVICE, interface="org.freedesktop.DBus.Properties")
        self.call = new_method_call
        self.message_bus = message_bus
        try:
            self.bus = open_dbus_connection(bus=f"unix:path=/run/user/{os.getuid()}/bus", auth_timeout=2)
        except PermissionError:
            raise Rejected("DBUS_PERMISSION_DENIED") from None
        try:
            self.owner = self.reply(message_bus.GetNameOwner(SERVICE))[0]
            self.pid = self.reply(message_bus.GetConnectionUnixProcessID(self.owner))[0]
            require(self.reply(message_bus.GetConnectionUnixUser(self.owner))[0] == os.getuid(), "MPRIS_NOT_OWNER_SESSION")
            self.messages = deque(maxlen=65)
            rule = MatchRule(type="signal", sender=self.owner, path=PATH)
            self.filter = self.bus.filter(rule, queue=self.messages)
            self.reply(message_bus.AddMatch(rule))
        except BaseException:
            self.bus.close()
            raise

    def reply(self, message):
        from jeepney.low_level import MessageType
        reply = self.bus.send_and_get_reply(message, timeout=1)
        require(reply.header.message_type == MessageType.method_return, "MPRIS_REQUEST_FAILED")
        return reply.body

    def snapshot(self):
        require(self.reply(self.message_bus.GetNameOwner(SERVICE))[0] == self.owner, "MPRIS_OWNER_CHANGED")
        raw = self.reply(self.call(self.address, "GetAll", "s", (PLAYER,)))[0]
        values = {k: v[1] for k, v in raw.items()}
        meta = {k: v[1] for k, v in values.get("Metadata", {}).items()}
        result = dict(path=meta.get("mpris:trackid"), title=safe_text(meta.get("xesam:title", "")),
                      artists=[safe_text(a) for a in meta.get("xesam:artist", [])],
                      length=meta.get("mpris:length"), status=values.get("PlaybackStatus"),
                      position=values.get("Position"), volume=values.get("Volume"), rate=values.get("Rate"))
        require(type(result["position"]) is int and type(result["length"]) is int and
                result["length"] > result["position"] >= 0 and result["rate"] == 1.0 and
                0 < result["volume"] <= 1.0, "PLAYBACK_CONTEXT_UNSUITABLE")
        return result

    def events(self, discard=False):
        from jeepney.low_level import HeaderFields
        for _ in range(100):
            try:
                self.bus.recv_messages(timeout=0)
            except TimeoutError:
                break
        else:
            raise Rejected("MPRIS_EVENT_OVERLOAD")
        require(len(self.messages) < 65, "MPRIS_EVENTS_LOST")
        while self.messages:
            msg = self.messages.popleft()
            if not discard:
                signal_ok(msg.header.fields.get(HeaderFields.member), msg.body)

    def close(self):
        self.bus.close()


def capture_owner(requested, *, diagnostic=False):
    require(sys.stdin.isatty() and sys.stdout.isatty(), "OWNER_TERMINAL_REQUIRED")
    observer = Mpris()
    cap = None
    pcm = None
    success = False
    try:
        initial = observer.snapshot()
        binding = identity(requested, initial["path"])
        require(initial["status"] == "Playing", "PLAYBACK_NOT_PLAYING")
        route = audio_route(observer.pid)
        print(json.dumps({"requested_id": requested, "title": initial["title"], "artists": initial["artists"]}, ensure_ascii=False))
        print("Личное использование не подтверждает разрешение сервиса на анализ.")
        if diagnostic:
            print("Проверьте ID и песню. Диагностика: 2 s до monitor, затем около 3 s доставки PCM без копирования, DSP или индекса. Enter: STOP, Ctrl-C: отмена.")
        else:
            print("Проверьте ID и песню в Yanjaro. Только этот sink-input; 10–15 секунд, Enter для остановки, Ctrl-C для отмены.")
        require(input("Для начала введите START " + requested + ": ") == "START " + requested, "OWNER_CANCELLED")
        observer.events(discard=True)
        latest = observer.snapshot()
        identity(requested, latest["path"])
        require(latest["title"] == initial["title"] and latest["artists"] == initial["artists"], "TRACK_CHANGED_BEFORE_START")
        initial = latest
        require(initial["status"] == "Playing", "PLAYBACK_NOT_PLAYING")
        require(initial["length"] - initial["position"] > 16_000_000, "TRACK_END_TOO_CLOSE")
        observer.events()
        require(audio_route(observer.pid) == route, "AUDIO_ROUTE_OR_GAIN_CHANGED")
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        if diagnostic:
            def verify():
                observer.events()
                check_snapshot(initial, observer.snapshot(), time.monotonic() - started)
                require(audio_route(observer.pid) == route, "AUDIO_ROUTE_OR_GAIN_CHANGED")
                observer.events()
            cap = Capture(route["index"], route["sink"], route["monitor"], diagnostic=True, verify=verify)
        else:
            cap = Capture(route["index"], route["sink"], route["monitor"])
        next_check = started
        shown = -1
        while True:
            cap.check(started)
            observer.events()
            now = time.monotonic()
            require(now - started < 17, "OWNER_STOP_TIMEOUT")
            if now >= next_check:
                check_snapshot(initial, observer.snapshot(), now - started)
                require(audio_route(observer.pid) == route, "AUDIO_ROUTE_OR_GAIN_CHANGED")
                observer.events()
                next_check = now + .2
            elapsed = cap.frames / RATE
            if int(elapsed) != shown:
                shown = int(elapsed)
                print(f"PCM: {elapsed:.1f} s. " + ("Диагностика: буферы освобождаются." if diagnostic else
                                                 "Enter: STOP" if elapsed >= 10 else "Сбор..."), flush=True)
            automatic_stop = diagnostic and elapsed >= 3
            owner_stop = bool(select.select([sys.stdin], [], [], 0)[0])
            if owner_stop:
                sys.stdin.readline()
            if automatic_stop or owner_stop:
                require(diagnostic or elapsed >= 10, "OWNER_STOP_BEFORE_10_SECONDS")
                frames = cap.frames
                stopped_at = datetime.now(timezone.utc).isoformat()
                cap.phase = "after_stop"
                cap.set_stage("after_stop")
                break
            time.sleep(.005)
        observer.events()
        check_snapshot(initial, observer.snapshot(), time.monotonic() - started)
        require(audio_route(observer.pid) == route, "AUDIO_ROUTE_OR_GAIN_CHANGED")
        observer.events()
        cap.iterate()
        if diagnostic:
            require(frames > 0, "DIAGNOSTIC_NO_PCM")
            return dict(status="DIAGNOSTIC_ONLY", pcm_delivery="OBSERVED", frames_discarded=cap.frames,
                        sample_rate=RATE, accepted_capture=False, vector_saved=False,
                        stop="AUTOMATIC_LIMIT" if automatic_stop else "OWNER_STOP")
        pcm = cap.pcm[:frames].copy()
        capture = dict(method="libpulse-single-sink-input", sample_rate=RATE, player_volume=initial["volume"],
                       sink_input_volume=route["stream_volume"], sink_volume=route["sink_volume"],
                       position_start_us=initial["position"], started_at=started_at, stopped_at=stopped_at)
        success = True
        return pcm, RATE, binding, initial["title"], initial["artists"], capture
    finally:
        if cap:
            cap.close()
        observer.close()
        if pcm is not None and not success:
            pcm.fill(0)

"""One libpulse sink-input monitor, synchronous callbacks, bounded RAM only.

Contracts: /usr/include/pulse/stream.h (set_monitor_stream, peek, overflow).
No default/system monitor fallback, routing changes or audio files.
"""
import ctypes as C
import json
import os
import re
import sys
import time
import numpy as np
from core import Rejected, require

SERVER = f"unix:/run/user/{os.getuid()}/pulse/native"
RATE = 48000
SUBSCRIPTION_MASK = 0x0001 | 0x0004  # PA_SUBSCRIPTION_MASK_SINK | SINK_INPUT


def object_id(value):
    if type(value) is str:
        require(re.fullmatch(r"[0-9]+", value) is not None, "INVALID_PULSE_OBJECT_ID")
        digits = value.lstrip("0") or "0"
        require(len(digits) <= 10, "INVALID_PULSE_OBJECT_ID")
        value = int(digits)
    # UINT32_MAX is PA_INVALID_INDEX, never a concrete object or monitor target.
    require(type(value) is int and 0 <= value < 0xffffffff, "INVALID_PULSE_OBJECT_ID")
    return value


class SampleSpec(C.Structure):
    _fields_ = [("format", C.c_int), ("rate", C.c_uint32), ("channels", C.c_uint8)]


class BufferAttr(C.Structure):
    _fields_ = [(k, C.c_uint32) for k in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


class Capture:
    def __init__(self, sink_input, sink, monitor_source, *, diagnostic=False, verify=None):
        self.sink_input = sink_input = object_id(sink_input)
        self.sink = object_id(sink)
        require(not diagnostic or callable(verify), "DIAGNOSTIC_GUARD_REQUIRED")
        self.diagnostic = diagnostic
        self.origin = self.stage_started = time.monotonic()
        self.phase = "initialization"
        self.stage = "context_connection"
        self.lib = C.CDLL("libpulse.so.0")
        self.loop = self.context = self.stream = None
        self.error = None
        self.frames = 0
        self.first_data = self.last_data = None
        self.pcm = None if diagnostic else np.zeros((15 * RATE, 2), dtype=np.float32)
        self.callbacks = []
        self.bind()
        try:
            self.set_stage("context_connection")
            self.loop = self.lib.pa_mainloop_new()
            require(bool(self.loop), "PULSE_MAINLOOP_FAILED")
            self.context = self.lib.pa_context_new(self.lib.pa_mainloop_get_api(self.loop), b"Yanjaro personal acoustic observation")
            require(bool(self.context), "PULSE_CONTEXT_FAILED")
            require(self.lib.pa_context_connect(self.context, SERVER.encode(), 0, None) == 0, "PULSE_LOCAL_CONNECT_FAILED")
            self.wait_ready(self.lib.pa_context_get_state, self.context, 4, 5)
            self.set_stage("subscription")
            self.subscribed = False
            subscription = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p)(self.changed)
            def accepted(context, success, userdata):
                self.subscribed = bool(success)
                if not success:
                    self.fail("PULSE_SUBSCRIPTION_FAILED")
            accepted_cb = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_void_p)(accepted)
            self.callbacks.extend((subscription, accepted_cb))
            self.lib.pa_context_set_subscribe_callback(self.context, subscription, None)
            operation = self.lib.pa_context_subscribe(self.context, SUBSCRIPTION_MASK, accepted_cb, None)
            require(bool(operation), "PULSE_SUBSCRIPTION_FAILED")
            self.lib.pa_operation_unref(operation)
            deadline = time.monotonic() + 2
            while not self.subscribed:
                require(time.monotonic() < deadline, "PULSE_SUBSCRIPTION_TIMEOUT")
                self.iterate()
                time.sleep(.005)
            require(self.error is None, self.error)
            if diagnostic:
                self.set_stage("subscription_baseline")
                deadline = time.monotonic() + 2
                next_check = 0
                while time.monotonic() < deadline:
                    self.iterate()
                    if time.monotonic() >= next_check:
                        verify()
                        next_check = time.monotonic() + .2
                    time.sleep(.005)
                verify()
            self.set_stage("stream_creation")
            spec = SampleSpec(5, RATE, 2)  # PA_SAMPLE_FLOAT32LE
            self.stream = self.lib.pa_stream_new(self.context, b"explicit single-input PCM", C.byref(spec), None)
            require(bool(self.stream), "PULSE_STREAM_FAILED")
            self.set_stage("monitor_binding")
            require(self.lib.pa_stream_set_monitor_stream(self.stream, sink_input) == 0, "SINGLE_INPUT_MONITOR_UNSUPPORTED")
            read = C.CFUNCTYPE(None, C.c_void_p, C.c_size_t, C.c_void_p)(self.read)
            self.callbacks.append(read)
            self.lib.pa_stream_set_read_callback(self.stream, read, None)
            for name in ("overflow", "underflow", "moved"):
                callback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)(
                    lambda *_, code="PULSE_" + name.upper(): self.fail(code))
                self.callbacks.append(callback)
                getattr(self.lib, "pa_stream_set_" + name + "_callback")(self.stream, callback, None)
            attr = BufferAttr(RATE * 8, 0xffffffff, 0xffffffff, 0xffffffff, RATE * 8 // 20)
            self.set_stage("record_connection")
            require(self.lib.pa_stream_connect_record(self.stream, str(monitor_source).encode(), C.byref(attr), 0x0200) == 0,
                    "PULSE_RECORD_CONNECT_FAILED")  # PA_STREAM_DONT_MOVE
            self.wait_ready(self.lib.pa_stream_get_state, self.stream, 2, 3)
            self.set_stage("ready")
            require(self.lib.pa_stream_get_monitor_stream(self.stream) == sink_input, "MONITOR_TARGET_NOT_CONFIRMED")
            self.iterate()
            if diagnostic:
                self.set_stage("route_revalidation")
                verify()
                self.iterate()
            self.observation_started = time.monotonic()
            self.phase = "diagnostic" if diagnostic else "active_capture"
            self.set_stage("diagnostic_observation" if diagnostic else "active_capture")
        except BaseException:
            self.close()
            raise

    def bind(self):
        ptr = C.c_void_p
        declarations = {
            "pa_mainloop_new": (ptr, []), "pa_mainloop_get_api": (ptr, [ptr]),
            "pa_mainloop_iterate": (C.c_int, [ptr, C.c_int, C.POINTER(C.c_int)]),
            "pa_mainloop_free": (None, [ptr]),
            "pa_context_new": (ptr, [ptr, C.c_char_p]),
            "pa_context_connect": (C.c_int, [ptr, C.c_char_p, C.c_int, ptr]),
            "pa_context_get_state": (C.c_int, [ptr]),
            "pa_context_disconnect": (None, [ptr]), "pa_context_unref": (None, [ptr]),
            "pa_context_set_subscribe_callback": (None, [ptr, ptr, ptr]),
            "pa_context_subscribe": (ptr, [ptr, C.c_int, ptr, ptr]),
            "pa_operation_unref": (None, [ptr]),
            "pa_stream_new": (ptr, [ptr, C.c_char_p, C.POINTER(SampleSpec), ptr]),
            "pa_stream_set_monitor_stream": (C.c_int, [ptr, C.c_uint32]),
            "pa_stream_get_monitor_stream": (C.c_uint32, [ptr]),
            "pa_stream_connect_record": (C.c_int, [ptr, C.c_char_p, C.POINTER(BufferAttr), C.c_int]),
            "pa_stream_get_state": (C.c_int, [ptr]), "pa_stream_is_suspended": (C.c_int, [ptr]),
            "pa_stream_peek": (C.c_int, [ptr, C.POINTER(ptr), C.POINTER(C.c_size_t)]),
            "pa_stream_drop": (C.c_int, [ptr]), "pa_stream_disconnect": (C.c_int, [ptr]),
            "pa_stream_unref": (None, [ptr]),
        }
        for name in ("read", "overflow", "underflow", "moved"):
            declarations["pa_stream_set_" + name + "_callback"] = (None, [ptr, ptr, ptr])
        for name, (result, args) in declarations.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args

    def fail(self, code):
        self.error = self.error or code

    def emit(self, event, **fields):
        try:
            now = time.monotonic()
            print(json.dumps(dict(event=event, phase=self.phase, stage=self.stage,
                                  observed_ms=round((now - self.origin) * 1000, 3),
                                  stage_ms=round((now - self.stage_started) * 1000, 3), **fields)),
                  file=sys.stderr, flush=True)
        except BaseException:
            self.fail("PULSE_EVENT_CALLBACK_FAILED")

    def set_stage(self, stage):
        self.stage = stage
        self.stage_started = time.monotonic()
        if self.diagnostic:
            require(self.stage_started - self.origin < 12, "PULSE_DIAGNOSTIC_TIMEOUT")
        self.emit("PULSE_STAGE")
        require(self.error is None, self.error)

    def changed(self, context, event, index, userdata):
        try:
            facility = {0: "SINK", 2: "SINK_INPUT"}.get(event & 0x0f, "UNKNOWN")
            kind = {0: "NEW", 0x10: "CHANGE", 0x20: "REMOVE"}.get(event & 0x30, "UNKNOWN")
            selected = ((event & 0x0f) == 0 and index == self.sink or
                        (event & 0x0f) == 2 and index == self.sink_input)
            reason = "PULSE_UNRELATED_OBJECT"
            if facility == "UNKNOWN" or kind == "UNKNOWN" or event & ~0x3f or index == 0xffffffff:
                reason = "PULSE_UNEXPECTED_EVENT"
            elif selected:
                # CHANGE has no field/cause: unchanged metadata cannot exclude change-and-revert.
                reason = "PULSE_SELECTED_" + facility + "_" + kind
            reject = reason != "PULSE_UNRELATED_OBJECT"
            observe = (self.diagnostic and self.phase == "initialization" and selected and
                       kind == "CHANGE" and reason != "PULSE_UNEXPECTED_EVENT")
            if reject and not observe:
                self.fail(reason)
            self.emit("PULSE_EVENT", facility=facility, type=kind, index=index,
                      decision="OBSERVE_ONLY" if observe else "REJECT" if reject else "IGNORE", reason=reason)
        except BaseException:
            self.fail("PULSE_EVENT_CALLBACK_FAILED")

    def wait_ready(self, getter, obj, ready, failed):
        deadline = time.monotonic() + 3
        while getter(obj) != ready:
            require(getter(obj) < failed and time.monotonic() < deadline, "PULSE_NOT_READY")
            self.iterate()
            time.sleep(.005)

    def iterate(self):
        # shortcut: IPC can delay deadline checks; add cancellation if a hard wall limit is required.
        if self.diagnostic:
            require(time.monotonic() - self.origin < 12, "PULSE_DIAGNOSTIC_TIMEOUT")
        require(self.lib.pa_mainloop_iterate(self.loop, 0, None) >= 0, "PULSE_CONNECTION_LOST")
        require(self.error is None, self.error)

    def append(self, data):
        require(not self.diagnostic, "DIAGNOSTIC_PCM_STORAGE_FORBIDDEN")
        require(data.ndim == 2 and data.shape[1] == 2, "PCM_FRAME_ALIGNMENT")
        require(self.frames + len(data) < len(self.pcm), "OWNER_STOP_REQUIRED_BEFORE_15_SECONDS")
        self.pcm[self.frames:self.frames + len(data)] = data
        self.frames += len(data)
        self.last_data = time.monotonic()
        self.first_data = self.first_data or self.last_data

    def read(self, stream, size, userdata):
        try:
            pointer, count = C.c_void_p(), C.c_size_t()
            require(self.lib.pa_stream_peek(stream, C.byref(pointer), C.byref(count)) == 0, "PCM_PEEK_FAILED")
            if not count.value:
                return
            try:
                require(bool(pointer.value), "PCM_HOLE")
                require(count.value % 8 == 0 and count.value <= 15 * RATE * 8, "PCM_FRAME_ALIGNMENT")
                if self.diagnostic:
                    # Count delivery without dereferencing or copying the server's PCM.
                    require(self.frames + count.value // 8 < 15 * RATE, "PULSE_DIAGNOSTIC_LIMIT")
                    if not self.frames:
                        self.emit("PULSE_PCM", disposition="DISCARDED_NO_COPY")
                    self.frames += count.value // 8
                    self.last_data = time.monotonic()
                    self.first_data = self.first_data if self.first_data is not None else self.last_data
                elif self.stage != "after_stop":
                    array = np.ctypeslib.as_array((C.c_float * (count.value // 4)).from_address(pointer.value))
                    self.append(array.reshape(-1, 2))
            finally:
                require(self.lib.pa_stream_drop(stream) == 0, "PCM_DROP_FAILED")
        except Rejected as exc:
            self.fail(str(exc))
        except BaseException:
            self.fail("PCM_CALLBACK_FAILED")

    def check(self, started):
        if self.diagnostic:
            started = self.observation_started
        self.iterate()
        require(self.lib.pa_context_get_state(self.context) == 4 and
                self.lib.pa_stream_get_state(self.stream) == 2, "PULSE_CONNECTION_LOST")
        require(self.lib.pa_stream_is_suspended(self.stream) == 0, "PULSE_SUSPENDED")
        now = time.monotonic()
        require(now - (self.last_data or started) < (0.6 if self.last_data else 2), "PCM_STALLED")
        if self.first_data:
            require(abs(self.frames / RATE - (now - self.first_data)) < .4, "PCM_TIMING_LOSS")

    def close(self):
        self.phase = self.stage = "cleanup"
        if self.stream:
            self.lib.pa_stream_disconnect(self.stream)
            self.lib.pa_stream_unref(self.stream)
            self.stream = None
        if self.context:
            self.lib.pa_context_disconnect(self.context)
            self.lib.pa_context_unref(self.context)
            self.context = None
        if self.loop:
            self.lib.pa_mainloop_free(self.loop)
            self.loop = None
        if self.pcm is not None:
            self.pcm.fill(0)

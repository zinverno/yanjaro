"""Controlled transport, real requests/SDK/API/controller; no sockets or account.

This is not a TCP outage or a live Yandex test. Even proxy/netrc discovery is
disabled. Every HTTP request terminates at this process-local adapter.
"""
from collections import Counter
import json
import os
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import requests
from PySide6.QtCore import QTimer
from yandex_music import Client
from yandex_music.exceptions import NetworkError
from yanjaro.api import AccountRequest, ApiError, MusicApi, Track
from yanjaro.controller import PlaybackController
from test_desktop import APP, until
from test_wave import StubPlayer


class Transport(requests.adapters.BaseAdapter):
    def __init__(self):
        self.calls = Counter()
        self.failure = lambda path, count: None

    def send(self, request, **kwargs):
        assert 'Authorization' not in request.headers  # No real or synthetic token needed.
        path = urlsplit(request.url).path
        self.calls[path] += 1
        status = self.failure(path, self.calls[path]) or 200
        response = requests.Response()
        response.status_code, response.request, response.url = status, request, request.url
        if path == '/tracks':
            body = request.body.decode() if isinstance(request.body, bytes) else request.body
            ids = parse_qs(body)['track-ids'][0].split(',')
            result = [dict(id=id, title='Synthetic', artists=[], albums=[], durationMs=180000,
                           available=True) for id in ids]
        elif path.endswith('/download-info'):
            result = [dict(codec='mp3', bitrateInKbps=192, gain=False, preview=False,
                           downloadInfoUrl='https://audio.example.invalid/fixture.xml', direct=False)]
        elif path == '/fixture.xml':
            response._content = (b'<download-info><host>audio.example.invalid</host><path>/fixture</path>'
                                 b'<ts>1</ts><s>synthetic</s></download-info>')
            return response
        elif path == '/play-audio' or '/feedback/' in path:
            result = 'ok'
        else:
            raise AssertionError('Unexpected endpoint in controlled transport')
        response._content = json.dumps({'result': result} if status == 200 else {'error': {}}).encode()
        return response

    def close(self):
        pass


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, XDG_CONFIG_HOME=self.tmp.name, XDG_STATE_HOME=self.tmp.name)
        self.env.start(); self.addCleanup(self.env.stop)
        self.transport = Transport()
        original = requests.sessions.Session
        def session():
            value = original()
            value.trust_env = False
            value.mount('https://', self.transport)
            value.mount('http://', self.transport)
            return value
        self.session_patch = patch('requests.sessions.Session', session)
        self.session_patch.start(); self.addCleanup(self.session_patch.stop)
        self.api = MusicApi(Client(request=AccountRequest(timeout=1)))
        self.api.authenticated = True
        self.player, self.store = StubPlayer(), Mock()
        self.c = PlaybackController(self.player, self.api, self.store)
        self.c._state['signedIn'] = True
        self.c.pages['likes'].update(rows=[Track(str(i), 'Synthetic', '', 180, True).row() for i in (1, 2)],
                                     ids=('1', '2'), status='ready')
        self.addCleanup(self.c.close)

    def test_timeout_then_success_is_responsive_and_retries_only_failed_read(self):
        def failure(path, count):
            if path == '/tracks/1/download-info' and count == 1:
                raise requests.ConnectTimeout('synthetic transport failure')
        self.transport.failure = failure
        ticks = []
        timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
        self.c.play('1')
        until(lambda: self.c.play_session is not None)
        timer.stop()
        self.assertGreater(len(ticks), 5)
        self.assertEqual(self.transport.calls, Counter({'/tracks': 1, '/tracks/1/download-info': 2, '/fixture.xml': 1}))
        self.assertEqual(self.player.played, ['1'])
        self.assertTrue(self.c.state['signedIn'])
        self.store.delete.assert_not_called()

    def test_repeated_http_failure_finishes_then_explicit_retry_recovers(self):
        self.transport.failure = lambda path, count: 503 if path.endswith('/download-info') else None
        self.c.play('1'); until(lambda: bool(self.c.state['playerError']))
        self.assertIn('Временный сбой', self.c.state['playerError'])
        self.assertFalse(self.c.state['loading'])
        self.assertEqual(self.transport.calls['/tracks/1/download-info'], 2)
        self.assertTrue(self.c.state['signedIn'])
        self.store.delete.assert_not_called()
        self.transport.failure = lambda *_: None
        self.c.retry_play(); until(lambda: self.c.play_session is not None)
        self.assertEqual(self.player.played, ['1'])

    def test_switch_discards_late_success_and_cancels_late_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                entered, release = threading.Event(), threading.Event()
                self.transport.calls.clear(); self.player.played.clear()
                def failure(path, count):
                    if path == '/tracks/1/download-info':
                        entered.set(); release.wait(2)
                        if fail: raise requests.ConnectTimeout('synthetic')
                self.transport.failure = failure
                try:
                    self.c.play('1'); until(entered.is_set)
                    self.c.play('2'); self.c.pause(); release.set()
                    until(lambda: self.c.play_session is not None and self.c.state['currentId'] == '2')
                    self.assertEqual(self.player.played, ['2'])
                    self.assertTrue(self.player.state['paused'])
                    self.assertEqual(self.transport.calls['/tracks/1/download-info'], 1)
                finally:
                    release.set()

    def test_close_cancels_pending_retry_without_start_or_store_deletion(self):
        entered, release = threading.Event(), threading.Event()
        def failure(path, count):
            if path.endswith('/download-info'):
                entered.set(); release.wait(2)
                raise requests.ConnectTimeout('synthetic')
        self.transport.failure = failure
        self.c.play('1'); until(entered.is_set)
        # close() sets cancellation before waiting for the in-flight worker.
        timer = threading.Timer(.05, release.set); timer.start()
        self.c.close(); timer.join(); APP.processEvents()
        self.assertEqual(self.player.played, [])
        self.assertEqual(self.transport.calls['/tracks/1/download-info'], 1)
        self.store.delete.assert_not_called()

    def test_feedback_and_listening_report_do_not_retry_transport_failure(self):
        def failure(*_):
            raise requests.ConnectTimeout('synthetic')
        self.transport.failure = failure
        with self.assertRaises(NetworkError):
            self.api.feedback('user:onyourwave', 'skip', '1', 'synthetic-batch', 2)
        with self.assertRaises(NetworkError):
            self.api.report_play(Track('1', 'Synthetic', '', 180, True, '2'), 'synthetic-play',
                                 '2026-10-08T00:00:00Z', 2, 2)
        self.assertEqual(sum(self.transport.calls.values()), 2)
        self.assertEqual(max(self.transport.calls.values()), 1)

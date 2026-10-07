import io
import logging
import threading
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import Mock, patch

from yanjaro.api import ApiError, MusicApi, Track, safe_error, track_model


def track(id="1", **kw):
    return Obj(**(dict(id=id, title="Test track", artists=[Obj(name="Test artist")],
                      duration_ms=180000, available=True) | kw))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.request.headers = {}
        self.api = MusicApi(self.client)
        self.api.authenticated = True

    def test_login_pending_success_and_cancellation(self):
        self.api.authenticated = False
        self.client.request_device_code.return_value = Obj(
            verification_url="https://ya.ru/device", device_code="private-code",
            user_code="TEST", expires_in=300, interval=1)
        self.client.poll_device_token.side_effect = [None, Obj(access_token="SECRET")]
        self.client.me = Obj(account=Obj(uid=123))
        cancel = Mock()
        cancel.wait.return_value = False
        cancel.is_set.return_value = False
        seen = []
        self.api.login(lambda *args: seen.append(args), cancel)
        self.assertEqual(seen, [("https://ya.ru/device", "TEST")])
        self.assertTrue(self.api.authenticated)
        self.client.request.set_authorization.assert_called_once_with("SECRET")
        self.api.logout()
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(ApiError, "отменён"):
            self.api.login(lambda *_: None, event)
        self.assertFalse(self.api.authenticated)
        self.assertIsNone(self.client.token)

    def test_likes_pagination_keeps_order_and_missing_entries(self):
        self.client.users_likes_tracks.return_value = Obj(
            tracks=[Obj(track_id=f"{i}:77") for i in range(52)])
        self.client.tracks.return_value = [track(str(i)) for i in reversed(range(49))]
        page = self.api.likes()
        self.assertEqual(len(page.rows), 50)
        self.assertEqual(page.rows[0]["id"], "0")
        self.assertFalse(page.rows[-1]["available"])
        self.assertTrue(page.more)
        self.client.tracks.return_value = [track("50"), track("51")]
        self.assertFalse(self.api.likes(1).more)
        self.client.users_likes_tracks.assert_called_once()

    def test_radio_batch_uses_previous_track_and_preserves_settings2(self):
        from yandex_music import Client
        from yandex_music.utils.request import Request
        request = Request()
        request.get = Mock(return_value={"batchId": "batch-2", "sequence": [], "pumpkin": False})
        api = MusicApi(Client(request=request))
        api.authenticated = True
        batch = api.wave_batch("user:onyourwave", "123")
        self.assertEqual(batch.batch, "batch-2")
        params = request.get.call_args.args[1] if len(request.get.call_args.args) > 1 else request.get.call_args.kwargs["params"]
        self.assertEqual(params, {"settings2": "True", "queue": "123"})

    def test_stations_feedback_and_server_history(self):
        self.client.rotor_stations_list.return_value = [Obj(station=Obj(
            id=Obj(type="genre", tag="rock"), name="Rock"))]
        self.assertEqual(self.api.stations().rows[0]["id"], "genre:rock")
        self.api.feedback("user:onyourwave", "skip", "1", "batch-1", 4.5)
        self.client.rotor_station_feedback.assert_called_once_with(
            "user:onyourwave", "skip", track_id="1", batch_id="batch-1",
            total_played_seconds=4.5, from_="yanjaro-music")
        from yandex_music import MusicHistory
        self.client.music_history.return_value = MusicHistory.de_json({"historyTabs": [{
            "date": "2026-10-07", "items": [{"tracks": [
                {"type": "track", "data": {"itemId": {"trackId": "1", "albumId": "2"},
                 "fullModel": {"id": "1", "title": "From server", "artists": [], "albums": [],
                               "durationMs": 200000, "available": True}}},
                {"type": "track", "data": {"itemId": {"trackId": "3", "albumId": "4"}}}
            ]}]}]}, None)
        page = self.api.history()
        self.assertEqual([r["id"] for r in page.rows], ["1", "3"])
        self.assertIn("2026-10-07", page.rows[0]["detail"])
        self.assertFalse(page.rows[1]["available"])
        self.client.music_history.return_value = None
        with self.assertRaises(ApiError):
            self.api.history()

    def test_search_empty_and_paged(self):
        self.client.search.return_value = Obj(tracks=None)
        self.assertEqual(self.api.search("no matches").rows, [])
        self.client.search.return_value = Obj(tracks=Obj(results=[track()], per_page=20, total=21))
        self.assertTrue(self.api.search("song").more)
        self.assertFalse(self.api.search("song", 1).more)
        with self.assertRaises(ApiError):
            self.api.search(" ")

    def test_artwork_only_uses_public_service_hosts(self):
        for host in ('avatars.yandex.net', 'avatars.mds.yandex.net'):
            self.assertEqual(track_model(track(cover_uri=host + '/get-music/%%')).cover,
                             'https://' + host + '/get-music/100x100')
        for uri in ('file:///etc/passwd', 'evil.example/image', 'user:password@avatars.yandex.net/image'):
            self.assertEqual(track_model(track(cover_uri=uri)).cover, '')

    def test_full_audio_only_and_fresh_link_on_each_play(self):
        self.client.tracks.return_value = [track()]
        preview = Mock(preview=True, codec="mp3", bitrate_in_kbps=320)
        full = Mock(preview=False, codec="mp3", bitrate_in_kbps=192)
        full.get_direct_link.return_value = "https://cdn.example/audio?signature=SECRET"
        self.client.tracks_download_info.return_value = [preview, full]
        stream = self.api.stream("1")
        self.assertEqual(stream.track.duration, 180)
        self.assertNotIn("SECRET", repr(stream))
        self.api.stream("1")
        self.assertEqual(full.get_direct_link.call_count, 2)
        preview.get_direct_link.assert_not_called()
        self.client.tracks_download_info.return_value = [preview]
        with self.assertRaisesRegex(ApiError, "превью"):
            self.api.stream("1")
        self.client.tracks.return_value = [track(available=False)]
        with self.assertRaisesRegex(ApiError, "недоступен"):
            self.api.stream("1")

    def test_errors_and_sdk_logging_do_not_disclose_secrets(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            logging.getLogger("yandex_music._client.device_auth").critical("SECRET")
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("SECRET", safe_error(RuntimeError("https://cdn/SECRET")))
        finally:
            root.removeHandler(handler)

    def test_transient_stream_failure_retries_only_failed_read_once(self):
        from yandex_music.exceptions import TimedOutError
        self.client.tracks.return_value = [track()]
        full = Mock(preview=False, codec='mp3', bitrate_in_kbps=192)
        full.get_direct_link.return_value = 'https://cdn.example/audio?signature=SECRET'
        self.client.tracks_download_info.side_effect = [TimedOutError(), [full]]
        cancel = Mock(); cancel.is_set.return_value = False; cancel.wait.return_value = False
        with patch('yanjaro.api.Event.wait', return_value=False) as wait:
            self.assertEqual(self.api.stream('1').track.id, '1')
        wait.assert_called_once_with(.4)
        self.client.tracks.assert_called_once()
        self.assertEqual(self.client.tracks_download_info.call_count, 2)
        full.get_direct_link.assert_called_once()
        # One retry for the whole preparation, never one retry per phase.
        self.client.tracks_download_info.side_effect = [TimedOutError(), [full]]
        full.get_direct_link.side_effect = TimedOutError()
        with self.assertRaisesRegex(ApiError, 'адрес аудио'):
            self.api.stream('1', cancel=cancel)
        self.assertEqual(full.get_direct_link.call_count, 2)

    def test_stream_cancellation_and_http_errors_are_not_blindly_retried(self):
        from yandex_music.exceptions import TimedOutError
        from yanjaro.api import AccountRequest
        from yandex_music import Client
        cancel = Mock(); cancel.is_set.return_value = False; cancel.wait.return_value = True
        self.client.tracks.side_effect = TimedOutError()
        with self.assertRaisesRegex(ApiError, 'отменена'):
            self.api.stream('1', cancel=cancel)
        self.client.tracks.assert_called_once()
        self.client.tracks_download_info.assert_not_called()
        request = AccountRequest(timeout=8); client = Client(request=request)
        for status in (400,404,429,502):
            try: request._handle_error_response(status, b'{}')
            except Exception as error:
                self.assertEqual(error.http_status, status)
                self.assertNotIn('Сеть недоступна', safe_error(error))
                self.assertNotIn('истёк таймаут', safe_error(error))
                if status < 500:
                    self.client.tracks.reset_mock()
                    self.client.tracks.side_effect = error
                    cancel.wait.return_value = False
                    with self.assertRaises(ApiError): self.api.stream('1', cancel=cancel)
                    self.client.tracks.assert_called_once()
        # Device Flow still depends on the SDK's 400/authorization_pending contract.
        response = Mock(status_code=400, content=b'{"error":"authorization_pending"}')
        with patch('requests.request', return_value=response):
            self.assertIsNone(client.poll_device_token('synthetic-code'))

    def test_login_rejects_untrusted_url_expiry_and_clears_failed_token(self):
        self.api.authenticated = False
        code = Obj(verification_url="https://attacker.example/device", device_code="private",
                   user_code="TEST", expires_in=60, interval=1)
        self.client.request_device_code.return_value = code
        callback = Mock()
        cancel = Mock()
        cancel.wait.return_value = False
        cancel.is_set.return_value = False
        with self.assertRaises(ApiError):
            self.api.login(callback, cancel)
        callback.assert_not_called()
        code.verification_url = "https://ya.ru/device"
        code.expires_in = -1
        with self.assertRaisesRegex(ApiError, "истекло"):
            self.api.login(callback, cancel)
        self.client.poll_device_token.assert_not_called()
        code.expires_in = 60
        self.client.poll_device_token.return_value = Obj(access_token="SECRET")
        self.client.init.side_effect = RuntimeError("SECRET")
        with self.assertRaises(RuntimeError):
            self.api.login(callback, cancel)
        self.assertFalse(self.api.authenticated)
        self.assertIsNone(self.client.token)
        self.assertNotIn("Authorization", self.client.request.headers)

    def test_report_listen_uses_actual_time_and_same_play_id(self):
        track = Track("1", "Synthetic", "", 180, True, "2")
        self.api.report_play(track, "play-1", "2026-10-07T10:00:00Z", 12.5, 150)
        self.client.play_audio.assert_called_once_with(
            "1", from_="yanjaro-music", album_id="2", play_id="play-1",
            timestamp="2026-10-07T10:00:00Z", track_length_seconds=180,
            total_played_seconds=12.5, end_position_seconds=150)


if __name__ == "__main__":
    unittest.main()

"""Synthetic SDK/transport fixtures only: these tests perform no network or secret reads."""

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import probe


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = probe.sdk()
        cls.sample, cls.history = probe.inputs()
        cls.ids = [r["yandex_track_id"] for r in cls.sample]

    def model(self, id=None, **extra):
        return self.module.Track.de_json({
            "id": id or self.ids[0], "title": "Synthetic title",
            "artists": [{"id": 1, "name": "Synthetic artist"}],
            "durationMs": 123000, "version": "Live", "available": False,
            "albums": [{"id": 10, "title": "Synthetic release"}], **extra,
        }, None)

    def test_sdk_fields_unknown_isrc_and_projection_privacy(self):
        source = self.model(isrc="USXXX1234567", metaData={"version": "edit", "lyricist": "PRIVATE_SENTINEL"},
                            storageDir="PRIVATE_SENTINEL", coverUri="PRIVATE_SENTINEL",
                            matchedTrack={"id": "999", "title": "PRIVATE_SENTINEL"})
        self.assertNotIn("isrc", self.module.Track.__dataclass_fields__)
        self.assertFalse(hasattr(source, "isrc"))
        result = probe.project(source)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        self.assertIsNone(result["isrc"])
        self.assertEqual(result["matched_track_id"], "999")
        self.assertEqual(result["version"], "Live")
        self.assertIs(result["available"], False)
        self.assertEqual(result["duration_ms"], 123000)

    def test_private_upload_and_unknown_values(self):
        self.assertIsNone(probe.project(self.model(trackSource="OWN")))
        result = probe.project(self.model(durationMs=None, available=None, version=None))
        self.assertIsNone(result["duration_ms"])
        self.assertIsNone(result["available"])
        self.assertIsNone(result["version"])
        self.assertIn("version", result["missing_reasons"])

    def test_correlation_uses_ids_not_order_or_real_id(self):
        returned = [self.model(self.ids[1]), self.model(self.ids[0]),
                    self.model("999", realId=self.ids[2])]
        result = probe.report(self.sample, self.history, {}, {}, returned)
        self.assertEqual(result["summary"]["api_resolved"], 2)
        self.assertEqual(result["tracks"][0]["metadata"]["returned_id"], self.ids[0])
        self.assertIsNone(result["tracks"][2]["metadata"])
        self.assertEqual(result["tracks"][2]["reason"], "REQUESTED_ID_NOT_RETURNED")
        self.assertEqual(result["uncorrelated_responses"][0]["returned_id"], "999")
        self.assertTrue(all(not r["recording_master_match"] for r in result["tracks"]))

    def test_duplicate_ids_and_no_request_do_not_create_success(self):
        result = probe.report(self.sample, self.history, {}, {}, [self.model(), self.model()])
        self.assertEqual(result["summary"]["api_resolved"], 0)
        self.assertEqual(result["tracks"][0]["reason"], "DUPLICATE_RETURNED_ID")
        result = probe.report(self.sample, self.history, {}, {"attempts": 0})
        self.assertEqual(len(result["tracks"]), 30)
        self.assertEqual(result["summary"]["api_status_counts"], {"BLOCKED": 30})
        self.assertEqual(result["summary"]["previous_status_counts"], {"BLOCKED": 17, "METADATA_ONLY": 13})

    def test_existing_ui_adapter_is_lossy(self):
        import sys
        sys.path.insert(0, str(probe.STUDY.parents[1]))
        from yanjaro.api import MusicApi
        source = self.model(durationMs=None, albums=[{"id": 1, "title": "First"}, {"id": 2, "title": "Second"}])
        client = SimpleNamespace(tracks=lambda ids: [source])
        api = MusicApi(client=client)
        api.authenticated = True
        row = api.track_rows([source.id])[0]
        self.assertEqual(row["duration"], 0)
        self.assertEqual(row["albumId"], "1")
        self.assertNotIn("version", row)
        self.assertNotIn("real_id", row)

    def test_sdk_tracks_makes_one_bounded_metadata_call(self):
        import requests
        payload = json.dumps({"result": [{"id": self.ids[0], "title": "Synthetic"}]}).encode()
        seen = []

        class Response:
            status_code = 200
            headers = {"Content-Type": "application/json"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, size): yield payload

        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, url, **kwargs):
                seen.append((method, url, kwargs, self.trust_env))
                return Response()

        request = probe.restricted_request(self.ids)
        client = self.module.Client(token="SYNTHETIC_NOT_A_TOKEN", request=request)
        with patch.object(requests, "Session", Session):
            result = client.tracks(self.ids)
            with self.assertRaises(probe.Blocked):
                client.tracks(self.ids)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(seen), 1)
        method, url, kwargs, trust_env = seen[0]
        self.assertEqual((method, url), ("POST", probe.ENDPOINT))
        self.assertEqual(kwargs["data"]["track-ids"], self.ids)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(trust_env)
        self.assertIsNone(client.me)
        self.assertEqual(request.attempts, 1)

    def test_other_endpoint_extra_ids_and_audio_content_rejected(self):
        request = probe.restricted_request(self.ids)
        for method, url, data in [
            ("GET", probe.ENDPOINT, {}),
            ("POST", "https://api.music.yandex.net/account/status", {}),
            ("POST", probe.ENDPOINT, {"track-ids": self.ids + ["999"], "with-positions": "True"}),
        ]:
            with self.assertRaises(probe.Blocked):
                request._request_wrapper(method, url, data=data)
        self.assertEqual(request.attempts, 0)
        import requests
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.headers = {"Content-Type": "audio/mpeg"}
        session = unittest.mock.MagicMock()
        session.__enter__.return_value = session
        session.request.return_value = response
        with patch.object(requests, "Session", return_value=session), self.assertRaises(probe.Blocked):
            self.module.Client(request=request).tracks(self.ids)
        response.iter_content.assert_not_called()

    def test_preflight_does_not_read_or_unlock_secret(self):
        import secretstorage
        item = unittest.mock.MagicMock()
        item.is_locked.return_value = False
        collection = unittest.mock.MagicMock()
        collection.is_locked.return_value = False
        collection.search_items.return_value = [item]
        with patch.object(secretstorage, "dbus_init"), patch.object(secretstorage, "Collection", return_value=collection):
            result, secret = probe.saved_session()
        self.assertIsNone(secret)
        self.assertEqual(result["status"], "ITEM_PRESENT_UNLOCKED_SECRET_NOT_READ")
        collection.search_items.assert_called_once_with(probe.ATTRIBUTES)
        collection.unlock.assert_not_called()
        item.get_secret.assert_not_called()

    def test_preflight_permission_error_is_safe_and_precise(self):
        import secretstorage
        with patch.object(secretstorage, "dbus_init", side_effect=PermissionError(1, "PRIVATE_SENTINEL")):
            result, secret = probe.saved_session()
        self.assertEqual(result, {"status": "LOCAL_PERMISSION_DENIED", "stage": "DBUS_CONNECT", "errno": 1})
        self.assertIsNone(secret)

    def test_no_owner_terminal_no_request_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "safe.json"
            with patch.object(probe.sys, "argv", ["probe.py", "--owner-run", "--output", str(output)]), \
                 patch.object(probe.sys.stdin, "isatty", return_value=False), \
                 patch.object(probe, "saved_session", return_value=({"status": "ITEM_PRESENT_UNLOCKED_SECRET_NOT_READ"}, None)) as store, \
                 patch.object(probe, "restricted_request") as request, self.assertRaises(probe.Blocked):
                probe.main()
            store.assert_called_once_with()
            request.assert_not_called()
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                probe.save(output, {}, reserve=True)


if __name__ == "__main__":
    unittest.main()

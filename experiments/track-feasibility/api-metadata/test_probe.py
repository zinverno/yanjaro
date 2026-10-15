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

    def test_source_flags_do_not_discard_allowlisted_metadata(self):
        for flag in ("OWN", "OWN_REPLACED_TO_UGC", None):
            source = self.model(trackSource=flag)
            source.user_info = SimpleNamespace(uid="PRIVATE_SENTINEL", name="PRIVATE_SENTINEL")
            result = probe.report(self.sample, self.history, {}, {}, [source])
            self.assertEqual(result["summary"]["api_resolved"], 1)
            self.assertEqual(result["summary"]["uniquely_correlated_ids"], 1)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_unknown_values_remain_unknown(self):
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
        self.assertEqual(set(result["uncorrelated_responses"][0]), {"returned_id"})
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

    def test_saved_owner_evidence_is_bounded_and_consistent(self):
        result_path = probe.ROOT / "owner-results.json"
        result = json.loads(result_path.read_text())
        assessment = json.loads((probe.ROOT / "assessment.json").read_text())
        self.assertEqual(probe.digest(result_path), assessment["evidence_sha256"])
        self.assertEqual(result["probe_sha256"], probe.digest(Path(probe.__file__)))
        self.assertEqual([r["requested_id"] for r in result["tracks"]], self.ids)
        self.assertEqual(result["request_audit"]["attempts"], 1)
        self.assertEqual(result["request_audit"]["http_status"], 200)
        self.assertFalse(result["uncorrelated_responses"])
        metadata_keys = {"returned_id", "title", "artists", "duration_ms", "version", "albums", "available",
                         "real_id", "matched_track_id", "substituted_track_id", "meta_data", "isrc",
                         "remote_error_present", "missing_reasons"}
        for row in result["tracks"]:
            m = row["metadata"]
            self.assertEqual(set(m), metadata_keys)
            self.assertEqual(row["requested_id"], m["returned_id"])
            self.assertEqual(row["status"], "METADATA_ONLY")
            self.assertFalse(row["recording_master_match"])
            self.assertIsNone(row["acoustic_features"])
            self.assertIsNone(m["isrc"])
            for artist in m["artists"]:
                self.assertEqual(set(artist), {"id", "name"})
            for album in m["albums"]:
                self.assertEqual(set(album), {"id", "title", "version", "year", "release_date", "type", "position"})
                self.assertEqual(set(album["position"]), {"volume", "index"})
            self.assertEqual(set(m["meta_data"]), {"album", "version", "year", "volume", "number"})
        metas = [r["metadata"] for r in result["tracks"]]
        self.assertEqual(sum(m["duration_ms"] > 0 for m in metas), result["summary"]["with_duration"])
        self.assertEqual(sum(bool(m["version"]) for m in metas), result["summary"]["with_named_track_version"])
        self.assertEqual(result["summary"]["api_resolved"], 30)
        self.assertEqual(result["summary"]["with_named_track_version"], 4)
        self.assertEqual(sum(m["real_id"] != m["returned_id"] for m in metas), 1)
        komanda = next(r["metadata"] for r in result["tracks"] if r["requested_id"] == "149359136")
        self.assertEqual((komanda["albums"][0]["id"], komanda["albums"][0]["position"]["index"]), ("41194184", 7))
        self.assertEqual(komanda["duration_ms"] - 174000, assessment["crosswalk_reviews"][0]["evidence"]["duration_delta_ms"])


if __name__ == "__main__":
    unittest.main()

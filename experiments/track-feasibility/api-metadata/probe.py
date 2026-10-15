#!/usr/bin/env python3
"""Fixed 30-ID SDK metadata audit. Default preflight never reads a secret or uses HTTP."""

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import fields
from datetime import datetime, timezone
from functools import partial
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import resource
import sys
import tempfile

logging.disable(logging.CRITICAL)
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent
PINNED_HEAD = "49d381fc5bcbe8e9e95b9d306653e888b42ae193"
SAMPLE_HASH = "7499bd512e07694e841054f70b7cb58d6bc9d6c1c43489884b8ff656ca3a29d5"
HISTORY_HASH = "1e93cf9995398d384cc0e5685b391cb019d5da4f4c6f4066de05a110dd46bfe9"
ATTRIBUTES = {"application": "yanjaro", "purpose": "active-account-v1"}
ENDPOINT = "https://api.music.yandex.net/tracks"


class Blocked(Exception):
    """Only fixed local reason codes, never server messages."""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    if digest(STUDY / "sample.json") != SAMPLE_HASH or digest(STUDY / "results.json") != HISTORY_HASH:
        raise Blocked("FROZEN_INPUT_CHANGED")
    sample = json.loads((STUDY / "sample.json").read_text())["tracks"]
    history = json.loads((STUDY / "results.json").read_text())["tracks"]
    ids = [r["yandex_track_id"] for r in sample]
    if len(ids) != 30 or len(set(ids)) != 30 or ids != [r["yandex_track_id"] for r in history]:
        raise Blocked("FROZEN_IDS_INVALID")
    return sample, history


def sdk():
    # The native launcher uses this prefix; no installation or dependency update.
    try:
        importlib.metadata.version("yandex-music")
    except importlib.metadata.PackageNotFoundError:
        if Path("/usr/lib/yanjaro/yandex_music").is_dir():
            sys.path.insert(0, "/usr/lib/yanjaro")
    try:
        import yandex_music
        if importlib.metadata.version("yandex-music") != "3.2.0" or yandex_music.__version__ != "3.2.0":
            raise Blocked("SDK_VERSION_NOT_3_2_0")
    except ImportError:
        raise Blocked("SDK_NOT_AVAILABLE") from None
    return yandex_music


def schema(module):
    return {
        "version": "3.2.0",
        "track_fields": sorted(f.name for f in fields(module.Track) if f.name != "client"),
        "meta_data_fields": sorted(f.name for f in fields(module.MetaData) if f.name != "client"),
        "track_isrc_declared": "isrc" in module.Track.__dataclass_fields__,
        "unknown_fields": "SDK drops undeclared fields; raw JSON is not inspected for ISRC",
        "source_sha256": {name: digest(Path(module.__file__).parent / name) for name in (
            "track/track.py", "track/meta_data.py", "album/album.py", "base.py",
            "_client/tracks.py", "_client/_batch.py", "_client/account.py", "utils/request.py",
        )},
    }


def saved_session(read_secret=False):
    """Exact app item, no unlock, no labels/attributes/account data exported."""
    stage = "IMPORT_SECRETSTORAGE"
    try:
        import secretstorage
        stage = "DBUS_CONNECT"
        with closing(secretstorage.dbus_init()) as bus:
            bus.send_and_get_reply = partial(bus.send_and_get_reply, timeout=8)
            bus.recv_until_filtered = partial(bus.recv_until_filtered, timeout=8)
            stage = "DEFAULT_COLLECTION"
            collection = secretstorage.Collection(bus)
            if collection.is_locked():
                return {"status": "KEYRING_LOCKED", "stage": stage}, None
            stage = "APPLICATION_ITEM_SEARCH"
            items = list(collection.search_items(ATTRIBUTES))
            if not items:
                return {"status": "NO_SAVED_YANJARO_SESSION", "stage": stage}, None
            if len(items) != 1:
                return {"status": "AMBIGUOUS_SAVED_SESSION", "stage": stage}, None
            if items[0].is_locked():
                return {"status": "ITEM_LOCKED", "stage": stage}, None
            if not read_secret:
                return {"status": "ITEM_PRESENT_UNLOCKED_SECRET_NOT_READ", "stage": stage}, None
            stage = "READ_APPLICATION_SECRET"
            secret = items[0].get_secret().decode("utf-8")
            if not secret or any(c.isspace() for c in secret):
                return {"status": "SAVED_CREDENTIAL_INVALID", "stage": stage}, None
            return {"status": "SAVED_CREDENTIAL_READ_LOCALLY", "stage": stage}, secret
    except PermissionError as exc:
        return {"status": "LOCAL_PERMISSION_DENIED", "stage": stage, "errno": exc.errno}, None
    except Exception:
        return {"status": "SECRET_SERVICE_UNAVAILABLE", "stage": stage}, None


def text(value):
    return value if isinstance(value, str) and 0 < len(value.strip()) <= 512 else None


def identifier(value):
    if type(value) not in (int, str):
        return None
    value = str(value)
    parts = value.split(":")
    return value if len(parts) <= 2 and all(p.isascii() and p.isdecimal() and len(p) <= 24 for p in parts) else None


def integer(value):
    return value if type(value) is int and 0 <= value <= 10**10 else None


def boolean(value):
    return value if type(value) is bool else None


def project(track):
    """Allowlist SDK fields only. No model repr/to_dict, URLs, lyrics, uploader or raw error."""
    # Source flags are not a privacy classifier; never export user_info or other private fields.
    albums = []
    for album in track.albums or []:
        position = getattr(album, "track_position", None)
        albums.append({
            "id": identifier(album.id), "title": text(album.title),
            "version": text(album.version), "year": integer(album.year),
            "release_date": text(album.release_date), "type": text(album.type),
            "position": {"volume": integer(getattr(position, "volume", None)),
                         "index": integer(getattr(position, "index", None))},
        })
    meta = getattr(track, "meta_data", None)
    result = {
        "returned_id": identifier(track.id), "title": text(track.title),
        "artists": [{"id": identifier(a.id), "name": text(a.name)} for a in track.artists or []],
        "duration_ms": integer(track.duration_ms), "version": text(track.version),
        "albums": albums, "available": boolean(track.available),
        "real_id": identifier(track.real_id),
        "matched_track_id": identifier(getattr(track.matched_track, "id", None)),
        "substituted_track_id": identifier(getattr(track.substituted, "id", None)),
        "meta_data": {"album": text(getattr(meta, "album", None)),
                      "version": text(getattr(meta, "version", None)),
                      "year": integer(getattr(meta, "year", None)),
                      "volume": integer(getattr(meta, "volume", None)),
                      "number": integer(getattr(meta, "number", None))},
        "isrc": None, "remote_error_present": bool(getattr(track, "error", None)),
    }
    # 3.2.0 does not declare Track.isrc. Never mine raw/unknown fields for it.
    result["missing_reasons"] = {key: "SDK_NULL_EMPTY_OR_INVALID" for key, value in result.items()
                                 if key != "isrc" and (value is None or value == [])}
    result["missing_reasons"]["isrc"] = "SDK_3_2_0_TRACK_ISRC_NOT_DECLARED"
    for index, album in enumerate(albums):
        for key, value in album.items():
            if value is None:
                result["missing_reasons"][f"albums[{index}].{key}"] = "SDK_NULL_EMPTY_OR_INVALID"
        for key, value in album["position"].items():
            if value is None:
                result["missing_reasons"][f"albums[{index}].position.{key}"] = "SDK_NULL_EMPTY_OR_INVALID"
    for index, artist in enumerate(result["artists"]):
        for key, value in artist.items():
            if value is None:
                result["missing_reasons"][f"artists[{index}].{key}"] = "SDK_NULL_EMPTY_OR_INVALID"
    for key, value in result["meta_data"].items():
        if value is None:
            result["missing_reasons"][f"meta_data.{key}"] = "SDK_NULL_EMPTY_OR_INVALID"
    return result


def candidate_comparison(metadata, old):
    comparisons = []
    if metadata is None:
        return comparisons
    for candidate in old["external_candidates"]:
        if not candidate["namespace"].startswith("musicbrainz_"):
            continue
        duration = candidate.get("duration_ms")
        comparisons.append({
            "namespace": candidate["namespace"], "id": candidate["id"],
            "duration_delta_ms": metadata["duration_ms"] - duration
            if metadata["duration_ms"] is not None and duration is not None else None,
            "title_equal": metadata["title"].casefold() == candidate["title"].casefold()
            if metadata["title"] and candidate.get("title") else None,
            "release_album_link_equal": candidate["yandex_album_id"] in [a["id"] for a in metadata["albums"]]
            if candidate.get("yandex_album_id") else None,
            "recording_master_match": False,
        })
    return comparisons


def report(sample, history, preflight, audit, returned=None, reason="OWNER_RUN_REQUIRED"):
    ids = [r["yandex_track_id"] for r in sample]
    groups = {}
    unassigned = []
    for model in returned or []:
        key = identifier(model.id)
        if key not in ids:
            unassigned.append({"returned_id": key})
        else:
            groups.setdefault(key, []).append(project(model))
    rows = []
    for frozen, old in zip(sample, history):
        matches = groups.get(frozen["yandex_track_id"], [])
        metadata = matches[0] if len(matches) == 1 else None
        row_reason = reason
        if returned is not None:
            row_reason = "REQUESTED_ID_NOT_RETURNED" if not matches else "DUPLICATE_RETURNED_ID" if len(matches) > 1 else None
        if metadata:
            row_reason = "REMOTE_TRACK_ERROR" if metadata["remote_error_present"] else None
        resolved = bool(metadata and not row_reason and metadata["title"] and
                        metadata["artists"] and all(a["name"] for a in metadata["artists"]))
        rows.append({
            "requested_id": frozen["yandex_track_id"], "previous_status": old["status"],
            "status": "METADATA_ONLY" if resolved else "BLOCKED",
            "metadata_resolved": resolved, "reason": row_reason or (None if resolved else "INCOMPLETE_CORE_METADATA"),
            "metadata": metadata,
            "missing_reasons": {} if metadata else {
                key: "NO_CORRELATED_SDK_RESPONSE" for key in
                ("returned_id", "title", "artists", "duration_ms", "version", "albums", "available", "real_id", "matched_track_id", "substituted_track_id", "meta_data")
            } | {"isrc": "SDK_3_2_0_TRACK_ISRC_NOT_DECLARED"},
            "musicbrainz_comparison": candidate_comparison(metadata, old),
            "recording_master_match": False, "acoustic_features": None,
        })
    valid = [r["metadata"] for r in rows if r["metadata_resolved"]]
    return {
        "schema": "yanjaro.api-metadata.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
        "probe_sha256": digest(Path(__file__)),
        "historical_head": PINNED_HEAD, "sample_sha256": SAMPLE_HASH, "history_sha256": HISTORY_HASH,
        "session_preflight": preflight, "request_audit": audit,
        "summary": {
            "sample_size": 30, "api_resolved": len(valid),
            "returned_sdk_objects": len(returned) if returned is not None else 0,
            "uniquely_correlated_ids": sum(len(matches) == 1 for matches in groups.values()),
            "with_duration": sum(m["duration_ms"] is not None and m["duration_ms"] > 0 for m in valid),
            "with_named_track_version": sum(m["version"] is not None for m in valid),
            "with_duration_and_named_track_version": sum(bool(m["duration_ms"] and m["version"]) for m in valid),
            "isrc_exposed_by_sdk": 0, "verified_recording_master_matches": 0,
            "verified_acoustic_feature_sources": 0,
            "previous_status_counts": dict(Counter(r["status"] for r in history)),
            "api_status_counts": dict(Counter(r["status"] for r in rows)),
            "interpretation": "One bounded metadata observation; no recording/master or acoustic rights inferred."
            if returned is not None else "No SDK response measured; not evidence of API/catalog absence.",
        },
        "rights": {"metadata_access": "Technical response only; no new permission inferred",
                   "catalog_copying": "NOT_CLEARED", "audio_processing": "NOT_AUTHORIZED",
                   "commercial_derived_features": "NOT_CLEARED"},
        "tracks": rows, "uncorrelated_responses": unassigned,
        "correlation_rule": "Exact returned ID only; never positional assignment or undocumented real_id inference",
    }


def restricted_request(ids):
    from yandex_music.utils.request import Request
    import requests

    class MetadataRequest(Request):
        attempts = 0
        http_status = None

        def _request_wrapper(self, method, url, **kwargs):
            if self.attempts or method != "POST" or url != ENDPOINT or kwargs.get("data") != {
                "track-ids": ids, "with-positions": "True"
            }:
                raise Blocked("OUT_OF_SCOPE_REQUEST")
            self.attempts += 1
            kwargs = self._prepare_kwargs(kwargs)
            kwargs.pop("proxies", None)
            kwargs["allow_redirects"] = False
            kwargs["timeout"] = 8
            kwargs["stream"] = True
            # No environment proxy/netrc credentials, redirects, retry adapter, or persistent cookies.
            with requests.Session() as session:
                session.trust_env = False
                with session.request(method, url, **kwargs) as response:
                    self.http_status = response.status_code
                    if response.status_code != 200:
                        raise Blocked(f"HTTP_{response.status_code}")
                    if "application/json" not in response.headers.get("Content-Type", "").lower():
                        raise Blocked("NON_JSON_RESPONSE")
                    chunks, length = [], 0
                    for chunk in response.iter_content(65536):
                        length += len(chunk)
                        if length > 2 * 1024 * 1024:
                            raise Blocked("METADATA_RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    return b"".join(chunks)

    return MetadataRequest(timeout=8)


def save(path, document, reserve=False):
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if reserve:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".metadata-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-run", action="store_true", help="Owner-only interactive local launch; one metadata request")
    parser.add_argument("--output", type=Path, required=True, help="New JSON path; existing files are never reused")
    args = parser.parse_args()
    sample, history = inputs()
    module = sdk()
    sdk_schema = schema(module)
    if sdk_schema["track_isrc_declared"]:
        raise Blocked("SDK_SCHEMA_CHANGED_REVIEW_REQUIRED")
    preflight, _ = saved_session()
    audit = {"mode": "OWNER_LOCAL" if args.owner_run else "PREFLIGHT_ONLY", "attempts": 0,
             "http_status": None, "outcome": "NOT_RUN", "secret_read": False,
             "owner_confirmation": False, "max_http_calls": 1}
    reason = "OWNER_RUN_REQUIRED" if preflight["status"] == "ITEM_PRESENT_UNLOCKED_SECRET_NOT_READ" else preflight["status"]
    document = report(sample, history, preflight, audit, reason=reason)
    document["sdk"] = sdk_schema
    save(args.output, document, reserve=True)
    if not args.owner_run:
        print("PREFLIGHT_SAVED_NO_SECRET_READ_NO_HTTP")
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Blocked("OWNER_TERMINAL_REQUIRED")
    if preflight["status"] != "ITEM_PRESENT_UNLOCKED_SECRET_NOT_READ":
        print("BLOCKED_SESSION_PREFLIGHT_SEE_JSON")
        return
    print("Один POST /tracks, ровно 30 замороженных ID. Без аудио, аккаунтных запросов и повторов.")
    if input("Для локального запуска владельцем введите RUN 30: ") != "RUN 30":
        print("NOT_RUN_OWNER_CANCELLED")
        return
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    audit["owner_confirmation"] = True
    preflight, secret = saved_session(read_secret=True)
    audit["secret_read"] = secret is not None
    client = request = returned = None
    reason = preflight["status"]
    try:
        if secret is not None:
            request = restricted_request([r["yandex_track_id"] for r in sample])
            client = module.Client(token=secret, request=request, report_unknown_fields=False)
            secret = None
            audit["outcome"] = "RESERVED_REQUEST_RESULT_UNKNOWN"
            document = report(sample, history, preflight, audit, reason="REQUEST_RESULT_UNKNOWN")
            document["sdk"] = sdk_schema
            save(args.output, document)
            returned = client.tracks([r["yandex_track_id"] for r in sample])
            audit["outcome"] = "SDK_RESPONSE_RECEIVED"
            reason = None
    except Blocked as exc:
        reason = str(exc)
        audit["outcome"] = "BLOCKED"
    except (Exception, KeyboardInterrupt):
        reason = "SDK_OR_TRANSPORT_ERROR_NO_RETRY"
        audit["outcome"] = "BLOCKED"
    finally:
        secret = None
        if client is not None:
            client.token = None
        if request is not None:
            request.headers.pop("Authorization", None)
            audit.update(attempts=request.attempts, http_status=request.http_status)
    document = report(sample, history, preflight, audit, returned, reason)
    document["sdk"] = sdk_schema
    save(args.output, document)
    print("SAFE_METADATA_RESULT_SAVED")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt):
        # Third-party exception messages/tracebacks may contain credentials or response bodies.
        print("BLOCKED_LOCAL_CHECK_OR_OUTPUT_ERROR_NO_AUTOMATIC_RETRY", file=sys.stderr)
        sys.exit(2)

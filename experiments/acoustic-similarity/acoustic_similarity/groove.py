"""Bounded acquisition of a pinned, official GMD cohort; no full ZIP download."""
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

from .data import digest, require, write_new

LIMIT = 512 * 1024**2
MIDI_SHA = "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e"
SCHEMA = "yanjaro.gmd-rhythm-data.v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Acquisition:
    """No retries, redirects, unbounded reads, or fallback to a complete archive."""
    def __init__(self, plan, receipt_path):
        self.plan = plan
        self.receipt_path = Path(receipt_path)
        self.received = 0
        self.requests = []

    def fetch(self, url, size, start=None):
        require(0 < size <= 40 * 1024**2, "Oversize request")
        require(self.received + self.plan["local_preflight_dataset_bytes"] + size <= LIMIT - 2 * 1024**2,
                "512 MiB acquisition budget exhausted (2 MiB transport/artifact reserve)")
        headers = {"Accept-Encoding": "identity"}
        if start is not None:
            headers["Range"] = f"bytes={start}-{start + size - 1}"
            headers["If-Match"] = self.plan["audio_etag"]
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=45) as response:
            require(response.geturl() == url, "Unexpected source redirect")
            require(response.status == (206 if start is not None else 200), "Range unavailable; refusing full download")
            require(int(response.headers.get("Content-Length", -1)) == size, "Unexpected response size")
            if start is not None:
                require(response.headers.get("ETag") == self.plan["audio_etag"], "Source ETag changed")
                require(response.headers.get("Content-Range") ==
                        f"bytes {start}-{start + size - 1}/{self.plan['audio_bytes']}", "Incorrect byte range")
            chunks = []
            remaining = size
            try:
                while remaining:
                    chunk = response.read(min(1024**2, remaining))
                    require(chunk, "Truncated response")
                    chunks.append(chunk)
                    self.received += len(chunk)
                    remaining -= len(chunk)
            finally:
                self.requests.append({"url": url, "start": start, "requested_bytes": size,
                                      "received_bytes": size - remaining})
                # This mutable operational receipt is retained even on a failed acquisition.
                self.receipt_path.write_text(json.dumps(self.receipt(), indent=2) + "\n")
        return b"".join(chunks)

    def receipt(self):
        return {"remote_dataset_bytes": self.received,
                "local_preflight_dataset_bytes": self.plan["local_preflight_dataset_bytes"],
                "total_dataset_body_bytes": self.received + self.plan["local_preflight_dataset_bytes"],
                "budget_bytes": LIMIT, "requests": self.requests}


class RangeZip(io.RawIOBase):
    def __init__(self, acquisition, directory):
        self.acquisition = acquisition
        self.plan = acquisition.plan
        self.directory = directory
        self.position = 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset + (self.position if whence == 1 else self.plan["audio_bytes"] if whence == 2 else 0)
        require(0 <= self.position <= self.plan["audio_bytes"], "Invalid ZIP seek")
        return self.position

    def read(self, size=-1):
        size = self.plan["audio_bytes"] - self.position if size < 0 else size
        size = min(size, self.plan["audio_bytes"] - self.position)
        if size == 0:
            return b""
        offset = self.position - self.plan["directory_offset"]
        if offset >= 0:
            data = self.directory[offset:offset + size]
        else:
            data = self.acquisition.fetch(self.plan["audio_url"], size, self.position)
        self.position += len(data)
        return data


def acquire(plan, output):
    """Yield verified originals, one at a time; bytes never enter the Git repository."""
    require(plan["schema"] == "yanjaro.gmd-cohort.v1" and plan["license"] == "CC-BY-4.0" and
            plan["midi_sha256"] == MIDI_SHA, "Unreviewed dataset plan")
    acquisition = Acquisition(plan, output / "acquisition.json")
    midi_bytes = acquisition.fetch(plan["midi_url"], plan["midi_bytes"])
    require(sha(midi_bytes) == MIDI_SHA, "Official MIDI archive SHA-256 mismatch")
    midi = zipfile.ZipFile(io.BytesIO(midi_bytes))
    metadata_bytes = midi.read("groove/info.csv")
    metadata = {r["id"]: r for r in csv.DictReader(io.StringIO(metadata_bytes.decode()))}
    directory = acquisition.fetch(plan["audio_url"], plan["directory_bytes"], plan["directory_offset"])
    require(sha(directory) == plan["directory_sha256"], "Pinned ZIP directory changed")
    archive = zipfile.ZipFile(RangeZip(acquisition, directory))
    # Validate every metadata row and archive entry before receiving any audio.
    for item in plan["records"]:
        r = item["metadata"]
        require(metadata.get(r["id"]) == r, "Cohort metadata differs from official MIDI archive")
        require(item["zip_member"] == "groove/" + r["audio_filename"], "Audio/MIDI association changed")
        info = archive.getinfo(item["zip_member"])
        require((info.compress_size, info.file_size, info.CRC) ==
                (item["compressed_bytes"], item["uncompressed_bytes"], item["crc32"]), "ZIP entry changed")
        require(info.file_size <= 64 * 1024**2, "Uncompressed member exceeds memory bound")
    write_new(output / "sources.json", {"plan": plan, "plan_sha256": digest(plan),
              "metadata_sha256": sha(metadata_bytes), "midi_archive_sha256": sha(midi_bytes),
              "directory_sha256": sha(directory), "full_audio_archive_sha256_verified": False,
              "integrity": "HTTPS immutable generation + pinned directory SHA256 + ZIP member CRC32; per-member SHA256 recorded"})
    for item in plan["records"]:
        audio = archive.read(item["zip_member"])  # zipfile verifies uncompressed CRC32.
        annotation = midi.read("groove/" + item["metadata"]["midi_filename"])
        yield item, audio, annotation

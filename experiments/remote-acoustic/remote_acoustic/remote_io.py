"""Anonymous, strictly bounded HTTP range reads; never a full-download fallback."""
from __future__ import annotations

import io
import re
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

REVISION = "dd6f3a19eef5866e346c3270e098baa641a44948"
EMBEDDINGS = f"hf://datasets/yandex/yambda@{REVISION}/embeddings.parquet"
MIB = 1024**2


class RangeFile(io.RawIOBase):
    """Seekable public Yambda object with a byte budget and wall-clock deadline.

    No read-ahead, retries, disk cache, tokens, or fallback on ignored Range.
    The budget counts requested payload bytes, including repeated reads.
    """

    def __init__(self, filename, *, max_bytes, max_seconds, opener=urlopen):
        super().__init__()
        if filename not in ("embeddings.parquet", "flat/50m/likes.parquet",
                            "flat/50m/dislikes.parquet"):
            raise ValueError("Unsupported Yambda file")
        if max_bytes <= 0 or max_seconds <= 0:
            raise ValueError("Positive I/O limits required")
        self.url = f"https://huggingface.co/datasets/yandex/yambda/resolve/{REVISION}/{filename}"
        self.max_bytes = max_bytes
        self.requested_bytes = 0
        self.received_bytes = 0
        self.requests = 0
        self.started = time.monotonic()
        self.deadline = self.started + max_seconds
        self.opener = opener
        self.pos = 0
        self.size = None
        self._fetch(0, 1)

    def _fetch(self, start, length):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Yambda I/O deadline exceeded")
        if self.requested_bytes + length > self.max_bytes:
            raise ValueError("Yambda byte budget exceeded before request")
        self.requested_bytes += length
        self.requests += 1
        req = Request(self.url, headers={"Range": f"bytes={start}-{start+length-1}",
                                        "Accept-Encoding": "identity"})
        try:
            with self.opener(req, timeout=min(30, remaining)) as response:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                                     response.headers.get("Content-Range", ""))
                if response.status != 206 or not match:
                    raise ValueError("Server did not honor Range; full download forbidden")
                first, last, size = map(int, match.groups())
                if (first != start or last != start+length-1 or last >= size or
                        (self.size is not None and size != self.size)):
                    raise ValueError("Unexpected Content-Range")
                self.size = size
                payload = bytearray()
                while len(payload) < length:
                    if time.monotonic() >= self.deadline:
                        raise TimeoutError("Yambda I/O deadline exceeded")
                    chunk = response.read(min(MIB, length-len(payload)))
                    self.received_bytes += len(chunk)
                    if not chunk:
                        raise ValueError("Truncated range response")
                    payload.extend(chunk)
                return bytes(payload)
        except URLError:
            # Do not expose redirect URLs or environment proxy details in CI logs.
            raise OSError("Yambda range request failed; no download fallback") from None

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        origins = {0: 0, 1: self.pos, 2: self.size}
        if whence not in origins or origins[whence] + offset < 0:
            raise ValueError("Invalid seek")
        self.pos = origins[whence] + offset
        return self.pos

    def read(self, size=-1):
        if size is None or size < 0:
            raise ValueError("Unbounded read forbidden")
        size = max(0, min(size, self.size-self.pos))
        if not size:
            return b""
        data = self._fetch(self.pos, size)
        self.pos += len(data)
        return data

    def stats(self):
        return {"file_bytes": self.size, "requested_bytes": self.requested_bytes,
                "received_bytes": self.received_bytes, "requests": self.requests,
                "seconds": round(time.monotonic()-self.started, 3),
                "max_bytes": self.max_bytes}


def parquet_layout(pf):
    """Compressed projection size, not a batch-size-based traffic estimate."""
    wanted = {"item_id", "normalized_embed.list.element"}
    groups = []
    for i in range(pf.num_row_groups):
        group = pf.metadata.row_group(i)
        columns = [group.column(j) for j in range(group.num_columns)
                   if group.column(j).path_in_schema in wanted]
        if len(columns) != 2:
            raise ValueError("Unexpected Yambda embedding schema")
        groups.append({"index": i, "rows": group.num_rows,
                       "compressed_bytes": sum(c.total_compressed_size for c in columns),
                       "uncompressed_bytes": sum(c.total_uncompressed_size for c in columns)})
    return {"rows": pf.metadata.num_rows, "row_groups": groups,
            "schema": str(pf.schema_arrow),
            "projected_full_scan_bytes": sum(g["compressed_bytes"] for g in groups)}

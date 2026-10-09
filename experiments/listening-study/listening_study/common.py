"""Small, explicit versioned file contracts. Research files are private by default."""
import hashlib
import json
import math
import os
from pathlib import Path
import re

VERSION = "yanjaro.listening.v0.1"
PROMPTS = {
    "next": "Какую песню ты бы включил следующей, чтобы сохранить текущий настрой?",
    "similarity": "Какая песня в целом больше похожа на исходный отрывок?",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(x, low, high):
    return type(x) in (int, float) and math.isfinite(x) and low <= x <= high


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value) is not None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    require(Path(path).stat().st_size <= 16 * 1024 * 1024, "JSON exceeds 16 MiB")
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def write_new(path, value):
    """Never silently replace a frozen manifest or a previous result."""
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)

"""Import only an explicit, small ID allowlist from an already local MTG TSV."""
import csv
import re
from .common import VERSION, file_hash, require


def import_mtg(path, ids, revision):
    require(1 <= len(ids) <= 60 and len(set(ids)) == len(ids), "Select 1..60 unique track IDs")
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "Pin the MTG Git revision")
    require(all(re.fullmatch(r"track_\d+", x) for x in ids), "Use MTG track_ IDs")
    wanted, rows = set(ids), {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        require(next(reader)[:6] == ["TRACK_ID", "ARTIST_ID", "ALBUM_ID", "PATH", "DURATION", "TAGS"],
                "Unexpected MTG header")
        for row in reader:
            if not row or row[0] not in wanted:
                continue
            require(row[0] not in rows and len(row) >= 5, "Duplicate or malformed selected row")
            tags = {"genre": set(), "instrument": set()}
            for raw in row[5:]:
                category, sep, value = raw.partition("---")
                if sep and category in tags:
                    tags[category].update(x for x in value.split(",") if x)
            rows[row[0]] = {"id": row[0], "artist_id": row[1], "album_id": row[2],
                            "genre": sorted(tags["genre"]), "instrument": sorted(tags["instrument"])}
    require(set(rows) == wanted, "Some selected IDs were not found")
    return {"schema": VERSION, "source": "MTG-Jamendo", "revision": revision,
            "metadata_sha256": file_hash(path), "metadata_license": "CC-BY-NC-SA-4.0",
            "missing_tags": "unknown, never negative", "tracks": [rows[x] for x in ids]}

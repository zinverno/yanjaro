"""Metadata-only preparation for a separate, pitch/velocity-controlled note pilot."""
from collections import defaultdict
import hashlib

from .data import require


def prepare_note_triplets(metadata):
    """Official qualities are mixed human/heuristic annotations, not song judgements.

    Input is the unmodified examples.json mapping. This prepares an experiment;
    it does not admit audio for training or claim that metadata alone is sufficient.
    """
    require(1 <= len(metadata) <= 4096, "Bounded NSynth pilot accepts at most the 4096-note test archive")
    instruments = sorted({v["instrument_str"] for v in metadata.values()},
                         key=lambda key: hashlib.sha256(key.encode()).hexdigest())
    require(len(instruments) >= 12, "Need >=12 independent instruments for three-way note pilot")
    splits = {key: ("train", "train", "validation", "test")[i % 4] for i, key in enumerate(instruments)}
    groups = defaultdict(list)
    for note_id, note in sorted(metadata.items()):
        require(note_id == note["note_str"] and note["sample_rate"] == 16000 and
                type(note["pitch"]) is int and 21 <= note["pitch"] <= 108 and
                note["velocity"] in (25, 50, 75, 100, 127), "Invalid official note metadata")
        require(len(note["qualities"]) == 10 and set(note["qualities"]) <= {0, 1}, "Invalid quality annotations")
        # Ignore tempo-synced; timbre experiment must not become another rhythm target.
        qualities = {i for i, value in enumerate(note["qualities"][:9]) if value}
        if qualities and note["pitch"] in (48, 60, 72) and note["velocity"] == 100:
            groups[splits[note["instrument_str"]], note["pitch"], note["velocity"]].append((note_id, note, qualities))
    triplets = []
    for (split, pitch, velocity), group in sorted(groups.items()):
        for aid, a, aq in group:
            pairs = []
            for pid, p, pq in group:
                positive = len(aq & pq) / len(aq | pq)
                for nid, n, nq in group:
                    if len({a["instrument_str"], p["instrument_str"], n["instrument_str"]}) != 3:
                        continue
                    gap = positive - len(aq & nq) / len(aq | nq)
                    if positive >= .5 and gap >= .5:
                        pairs.append((gap, pid, nid))
            if pairs:
                _, pid, nid = sorted(pairs, key=lambda x: (-x[0], x[1], x[2]))[0]
                triplets.append({"anchor": aid, "positive": pid, "negative": nid, "split": split,
                                 "pitch": pitch, "velocity": velocity, "source": "NSynth official qualities (human + heuristic)"})
    return {"schema": "yanjaro.nsynth-note-protocol.v1", "training_status": "NOT RUN",
            "instrument_splits": splits, "triplets": triplets,
            "audio_admission": "NOT RUN: official source receipt, archive hash and duplicate-audio audit required",
            "performer_disjointness": "UNKNOWN: NSynth does not supply performer identities",
            "song_similarity": "NOT EVALUATED"}

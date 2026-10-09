"""Manufactured signals and scripted responses: functional demo, not music evidence."""
from pathlib import Path
import uuid
import numpy as np
import soundfile as sf
from .audio import prepare
from .common import VERSION, write_new
from .design import freeze, schedule, screen


def signal(frequency, *, busy=False, seed=0, seconds=8, sr=16000):
    rng = np.random.default_rng(seed)
    time = np.arange(seconds * sr) / sr
    wave = np.zeros(len(time))
    if busy:
        wave += .055 * np.sin(2 * np.pi * frequency * time)
        positions = np.arange(0, seconds, 60 / 172)
        positions = sorted([*positions, *(p + rng.uniform(.07, .24) for p in positions)])
    else:
        positions = np.arange(0, seconds, .5)
    for index, position in enumerate(positions):
        offset = time - position
        active = (offset >= 0) & (offset < (.11 if busy else .17))
        amplitude = (.04 + .18 * (index % 2 == 0)) if busy else .25
        wave[active] += amplitude * np.exp(-offset[active] * (55 if busy else 32)) * np.sin(2 * np.pi * frequency * time[active])
    return wave


def build_demo(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    raw = out / "raw"
    raw.mkdir(mode=0o700)
    rows, trials = [], []
    for i in range(8):
        source, first, second = (f"d{i:02d}{j}" for j in range(3))
        control = i >= 6
        for j, tid in enumerate((source, first, second)):
            frequency = 180 + i * 19 + j * 150
            path = raw / f"{tid}.wav"
            sf.write(path, signal(frequency, busy=j == 2, seed=i), 16000, subtype="PCM_16")
            same_tags = j == 0 or (j == 1 if control else j == 2)
            rows.append({"id": tid, "artist_id": "synthetic_" + tid, "path": str(path.resolve()),
                         "start": 0, "seconds": 8, "genre": ["demo_group_one" if same_tags else "demo_group_two"],
                         "instrument": ["demo_timbre_one" if same_tags else "demo_timbre_two"],
                         "rights": {"reviewed": True, "local_analysis": True, "excerpt_derivatives": True,
                                    "local_listening": True, "blind_presentation": True, "license": "self-generated-demo",
                                    "evidence": "demo.py deterministic oscillator; no recordings or samples",
                                    "attribution": "Yanjaro synthetic demo", "verified_on": "2026-10-09",
                                    "scope": "Synthetic local software validation only"}})
        trials.append({"id": f"t{i:02d}", "kind": "control" if control else "primary", "source": source, "first": first, "second": second})
    manifest = {"schema": VERSION, "demo": True, "tracks": rows}
    write_new(out / "sample.json", manifest)
    catalog = prepare(manifest, out / "prepared")
    review = screen(catalog)
    review["trials"] = trials
    for pair in review["pairs"]:
        pair["review"] = {"approved": True, "rhythm_checked": True, "tags_checked": True,
                          "tempo_alias_checked": True, "notes": "DEMO: scripted fixture approval, NOT human perceptual validation"}
    write_new(out / "demo-review.json", review)
    study = freeze(catalog, review, study_id="demo-v0_1", seed=20261009, phase="demo")
    write_new(out / "study.json", study)
    from .collection import demo_config
    write_new(out / "collection.demo.json", demo_config())
    from .portable import export_demo
    export_demo(study, out / "demo-next.html")
    export_demo(study, out / "demo-similarity.html", prompt="similarity")
    # 16 completed synthetic participants per wording, one full 2N schedule block.
    responses = out / "responses"
    for prompt in ("next", "similarity"):
        for slot in range(16):
            data = {k: study[k] for k in ("schema", "study_id", "demo", "phase")}
            data.update(study_sha256=study["sha256"], slot=slot, prompt_id=prompt, status="complete",
                        participant_id=str(uuid.UUID(int=1 + slot + (100 if prompt == "similarity" else 0), version=4)), answers=[])
            for i, task in enumerate(schedule(study, slot, prompt)):
                first = (i + slot) % (3 if prompt == "next" else 2) != 0
                choice = "left" if first == task["first_left"] else "right"
                if (i + slot) % 17 == 0:
                    choice = "neither"
                if (i + slot) % 19 == 0:
                    choice = "skip"
                data["answers"].append({"trial_id": task["id"], "choice": choice,
                                         "heard": dict.fromkeys(("source", "left", "right"), True)})
            write_new(responses / f"{prompt}-{slot:02d}.json", data)
    return study

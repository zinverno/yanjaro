"""Fixed-scale DSP baseline. Genre, artist and reactions never enter distances."""
from pathlib import Path
import numpy as np
import soundfile as sf

from . import lab_audio
from .data import SCHEMA, ASPECTS, digest, file_hash, require, validate_manifest

FEATURE_SCHEMA = "lab27-mfcc19x4-onset-ac64-energy-v1"
DIMENSIONS = {"rhythm": 72, "timbre": 85, "energy": 10}


def load_window(track, sr=16000):
    import librosa
    with sf.SoundFile(track["path"]) as audio:
        require(8000 <= audio.samplerate <= 96000 and 1 <= audio.channels <= 2,
                "Supported audio: mono/stereo, 8..96 kHz")
        audio.seek(round(track["start"] * audio.samplerate))
        count = round(track["seconds"] * audio.samplerate)
        y = audio.read(count, dtype="float32", always_2d=True).mean(axis=1)
        require(len(y) == count and np.isfinite(y).all(), "Short/nonfinite audio window")
        y = librosa.resample(y, orig_sr=audio.samplerate, target_sr=sr)
    require(np.max(np.abs(y)) > 1e-5, "Silent window")
    return y


def extract(track):
    return {"id": track["id"], "sha256": track["sha256"], **extract_pcm(load_window(track))}


def extract_pcm(y):
    """The same fixed DSP calculation on caller-owned mono PCM at 16 kHz."""
    import librosa
    from scipy.signal import correlate
    sr, hop = lab_audio.SAMPLE_RATE, lab_audio.HOP
    f = lab_audio.extract_signal(y, sr)
    power = np.abs(librosa.stft(y, n_fft=lab_audio.FFT, hop_length=hop))**2
    mel = librosa.feature.melspectrogram(S=power, sr=sr, n_mels=40)
    cepstra = librosa.feature.mfcc(S=librosa.power_to_db(mel, ref=1.0), n_mfcc=20)[1:]
    delta = librosa.feature.delta(cepstra)
    # Fixed physical scales, no statistics fitted on the search corpus or test set.
    timbre = np.concatenate([cepstra.mean(axis=1) / 100, cepstra.std(axis=1) / 50,
                             delta.mean(axis=1) / 20, delta.std(axis=1) / 20,
                             [f["brightness"] / 8000, f["flatness"], f["low_band_ratio"]],
                             [f[f"brightness_curve_{i}"] / 2 for i in range(6)]])
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    ac = correlate(onset - onset.mean(), onset - onset.mean(), mode="full", method="fft")[len(onset)-1:]
    ac = ac / max(float(ac[0]), 1e-9)
    profile = np.interp(np.linspace(.064, 2.048, 64), np.arange(len(ac)) * hop / sr, ac)
    rhythm = np.r_[f["beat_regularity"], f["onset_density"] / 10,
                   [f[f"rhythm_curve_{i}"] / 2 for i in range(6)], profile]
    rms = librosa.feature.rms(S=np.sqrt(power), frame_length=lab_audio.FFT, hop_length=hop).ravel()
    db = 20 * np.log10(np.maximum(rms, 1e-4))
    energy = np.r_[f["energy_db"] / 60, f["energy_variation"] / 3,
                   (np.percentile(db, 90) - np.percentile(db, 10)) / 40,
                   20 * np.log10(max(float(np.max(np.abs(y))), 1e-4) /
                                max(float(np.sqrt(np.mean(y**2))), 1e-4)) / 40,
                   [f[f"energy_curve_{i}"] / 2 for i in range(6)]]
    vectors = {k: np.clip(v, -3, 3).tolist() for k, v in
               zip(ASPECTS, (rhythm, timbre, energy))}
    for k in ASPECTS:
        require(len(vectors[k]) == DIMENSIONS[k] and np.isfinite(vectors[k]).all(), "Invalid features")
    return {"bpm": f["bpm"] or None,
            "bpm_alternatives": [f["bpm"] / 2, f["bpm"], f["bpm"] * 2] if f["bpm"] else [],
            "bpm_status": "estimated_unverified" if f["bpm"] else "unknown",
            "lab27": f, "vectors": vectors}


def code_hash():
    return digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def build_index(manifest):
    validate_manifest(manifest, verify_files=True)
    rows = [extract(t) for t in manifest["tracks"]]
    require(all(file_hash(t["path"]) == t["sha256"] for t in manifest["tracks"]),
            "Audio changed during extraction")
    import librosa
    import scipy
    return {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "dataset_sha256": digest(manifest),
            "kind": manifest["kind"], "code_sha256": code_hash(), "encoder": None,
            "environment": {"numpy": np.__version__, "librosa": librosa.__version__,
                            "scipy": scipy.__version__, "soundfile": sf.__version__,
                            "libsndfile": sf.__libsndfile_version__}, "tracks": rows}


def validate_index(index, manifest):
    tracks = validate_manifest(manifest)
    require(index.get("schema") == SCHEMA and index.get("feature_schema") == FEATURE_SCHEMA,
            "Incompatible feature schema")
    require(index.get("dataset_sha256") == digest(manifest) and index.get("kind") == manifest["kind"],
            "Index/dataset mismatch")
    rows = index.get("tracks", [])
    require(len(rows) == len(tracks) and {t["id"] for t in rows} == set(tracks), "Incomplete index")
    for t in rows:
        require(t["sha256"] == tracks[t["id"]]["sha256"], "Feature/audio mismatch")
        require(t["bpm"] is None or (type(t["bpm"]) in (float, int) and 35 <= t["bpm"] <= 260), "Invalid tempo")
        for k in ASPECTS:
            v = np.asarray(t["vectors"][k])
            require(v.shape == (DIMENSIONS[k],) and np.isfinite(v).all() and np.max(np.abs(v)) <= 3,
                    "Malformed feature vector")
    return {t["id"]: t for t in rows}


def tempo_distance(a, b):
    if a is None or b is None:
        return .5  # Unknown is not zero-distance evidence.
    gap = float(np.log2(max(a, b) / min(a, b)))
    return min(1., gap, abs(gap - 1) + .15)

"""Bounded local decoding and explicit DSP proxies, never perceptual ground truth."""
import math
import os
from pathlib import Path
import numpy as np
import soundfile as sf
from .common import VERSION, digest, file_hash, identifier, number, require, write_new


def extract(y, sr):
    y = np.asarray(y, dtype=np.float64)
    require(y.ndim == 1 and 8000 <= sr <= 96000 and len(y) >= sr * 8,
            "Need at least 8 seconds of mono audio at 8..96 kHz")
    require(np.isfinite(y).all() and np.max(np.abs(y)) > 1e-5, "Silent/nonfinite audio")
    hop = round(sr * .01)
    size = 2 ** math.ceil(math.log2(sr * .04))
    frames = np.lib.stride_tricks.sliding_window_view(y, size)[::hop]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1))
    power = spectrum ** 2
    freq = np.fft.rfftfreq(size, 1 / sr)
    # Positive spectral flux; level-normalized, with an explicit peak floor.
    flux = np.maximum(np.diff(spectrum, axis=0), 0).sum(axis=1)
    flux = flux / max(float(np.max(flux)), 1e-12)
    peaks = np.flatnonzero((flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) &
                          (flux[1:-1] > max(.08, float(np.median(flux) + np.std(flux) * .5)))) + 1
    chosen = []
    for p in sorted(peaks, key=lambda p: -flux[p]):
        if all(abs(p - q) * hop / sr >= .08 for q in chosen):
            chosen.append(int(p))
    chosen.sort()
    ac = np.correlate(flux - flux.mean(), flux - flux.mean(), mode="full")[len(flux)-1:]
    low, high = math.ceil(60 * sr / (240 * hop)), math.floor(60 * sr / (50 * hop))
    lag = low + int(np.argmax(ac[low:high+1]))
    periodicity = max(0., float(ac[lag] / max(ac[0], 1e-12)))
    reliable = len(chosen) >= 6 and periodicity >= .15
    bpm = 60 * sr / (lag * hop) if reliable else None
    intervals = np.diff(chosen) * hop / sr
    # Explicit -80 dBFS analysis floor; digital silence is not infinite dynamics.
    db = 20 * np.log10(np.maximum(rms, 1e-4))
    active = rms > 1e-4
    require(bool(np.any(active)), "Audio below the analysis floor")
    totals = np.maximum(power.sum(axis=1), 1e-12)
    centroid = (power * freq).sum(axis=1) / totals
    cumulative = np.cumsum(power, axis=1)
    rolloff = freq[np.argmax(cumulative >= totals[:, None] * .85, axis=1)]
    flatness = np.exp(np.log(power + 1e-12).mean(axis=1)) / np.maximum(power.mean(axis=1), 1e-12)
    return {
        "extractor": "explicit-dsp-v1", "bpm": bpm,
        "bpm_alternatives": [] if bpm is None else [bpm / 2, bpm, bpm * 2],
        "tempo_confidence_proxy": periodicity,
        "onsets_per_second": len(chosen) / (len(y) / sr),
        "onset_strength": float(flux[chosen].mean()) if chosen else 0.,
        "onset_regularity": float(1 / (1 + intervals.std() / intervals.mean())) if len(intervals) >= 3 else None,
        "rms_db": float(20 * np.log10(max(np.sqrt(np.mean(y ** 2)), 1e-8))),
        "dynamic_range_db": float(np.percentile(db, 90) - np.percentile(db, 10)),
        "energy_curve_db": [float(v.mean()) for v in np.array_split(db, 6)],
        "centroid_hz": float(centroid[active].mean()), "rolloff85_hz": float(rolloff[active].mean()),
        "spectral_flatness": float(flatness[active].mean()),
        "low_band_ratio": float((power[:, freq < 250].sum(axis=1) / totals)[active].mean()),
    }


def rights_ok(rights):
    required = ("local_analysis", "excerpt_derivatives", "local_listening", "blind_presentation")
    require(isinstance(rights, dict) and all(rights.get(k) is True for k in required),
            "Explicit analysis, excerpt, listening and blind-presentation permissions required")
    for key in ("license", "evidence", "attribution", "verified_on", "scope"):
        require(isinstance(rights.get(key), str) and bool(rights[key].strip()), "Missing rights evidence: " + key)
    # Human verification is mandatory, including when the source has a CC license.
    require(rights.get("reviewed") is True, "Rights must be reviewed")


def prepare(manifest, out):
    require(manifest.get("schema") == VERSION and type(manifest.get("demo")) is bool, "Invalid sample schema")
    rows = manifest.get("tracks", [])
    require(3 <= len(rows) <= 60, "Explicit local sample must contain 3..60 tracks")
    require(len({t["id"] for t in rows}) == len(rows), "Duplicate track IDs")
    out = Path(out)
    require(not out.exists(), "Output directory must be new")
    # Preflight all permissions before reading a single recording.
    for t in rows:
        require(identifier(t["id"]) and identifier(t["artist_id"]), "Invalid identifiers")
        rights_ok(t.get("rights"))
        for category in ("genre", "instrument"):
            require(isinstance(t.get(category), list) and all(isinstance(x, str) and x for x in t[category]),
                    "Tags must be positive string lists (empty = unknown)")
        require(number(t.get("start"), 0, 3600) and number(t.get("seconds"), 8, 30), "Invalid excerpt bounds")
        path = Path(t["path"])
        require(path.is_file() and path.stat().st_size <= 100 * 1024 * 1024, "Need a local file <=100 MiB")
    out.mkdir(parents=True, mode=0o700)
    (out / "clips").mkdir(mode=0o700)
    tracks = []
    for t in rows:
        path = Path(t["path"])
        with sf.SoundFile(path) as audio:
            require(8000 <= audio.samplerate <= 96000 and 1 <= audio.channels <= 2, "Unsupported rate/channels")
            audio.seek(round(t["start"] * audio.samplerate))
            count = round(t["seconds"] * audio.samplerate)
            y = audio.read(count, dtype="float64", always_2d=True).mean(axis=1)
            sr = audio.samplerate
        require(len(y) == count and np.isfinite(y).all(), "Short/nonfinite excerpt")
        require(np.mean(np.abs(y) >= .999) < .005, "Clipped source: review another excerpt")
        original = extract(y, sr)
        # Fixed RMS target; gain only, no compressor/limiter. Fail if target would clip.
        gain = 10 ** ((-23 - original["rms_db"]) / 20)
        require(np.max(np.abs(y * gain)) <= .98, "Target RMS would clip: reject, do not limit")
        y *= gain
        fade = min(round(.025 * sr), len(y) // 2)
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
        clip = out / "clips" / (digest({"id": t["id"], "sample": manifest})[:24] + ".wav")
        sf.write(clip, y, sr, subtype="PCM_16")
        os.chmod(clip, 0o600)
        rendered, _ = sf.read(clip)
        tracks.append({k: t[k] for k in ("id", "artist_id", "genre", "instrument", "rights")} |
                      {"clip": str(clip.resolve()), "clip_sha256": file_hash(clip),
                       "source_sha256": file_hash(path), "start": t["start"], "seconds": t["seconds"],
                       "gain_db": float(20 * np.log10(gain)), "raw_features": original,
                       "features": extract(rendered, sr)})
    catalog = {"schema": VERSION, "demo": manifest["demo"], "sample_sha256": digest(manifest),
               "metadata_provenance": manifest.get("metadata_provenance"), "tracks": tracks}
    write_new(out / "catalog.json", catalog)
    return catalog

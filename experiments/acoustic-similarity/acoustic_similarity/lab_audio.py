"""Deterministic, CPU-first acoustic descriptors from authorized *local* audio.

Estimated BPM is not a time signature. The 6 temporal buckets are coarse dynamics,
not guaranteed verse/chorus sections. No decoding or downloading from Yandex Music.
"""
from __future__ import annotations

from pathlib import Path
import math
import numpy as np

from . import FEATURE_NAMES, SEGMENTS

SAMPLE_RATE = 16_000
HOP = 512
FFT = 2048
MAX_SECONDS = 180


def _curve(values: np.ndarray, n: int = SEGMENTS, relative: bool = True) -> list[float]:
    values = np.asarray(values, dtype=np.float64).ravel()
    if not len(values):
        return [0.0] * n
    parts = np.array_split(values, n)
    averages = np.array([np.mean(p) if len(p) else 0.0 for p in parts])
    if relative:
        avg = float(np.mean(averages))
        if avg > 1e-9:
            averages = np.log1p(averages / avg)
        else:
            averages[:] = 0.0
    return [round(float(v), 6) for v in averages]


def extract_signal(y: np.ndarray, sr: int = SAMPLE_RATE) -> dict:
    """Extract 27 numeric descriptors. At least 1 second of non-silent signal required."""
    import librosa

    if sr <= 0:
        raise ValueError("Sample rate must be positive")
    y = np.asarray(y, dtype=np.float32).ravel()
    if len(y) < sr or not np.isfinite(y).all():
        raise ValueError("Audio must have at least 1 second of finite samples")
    if max(abs(float(y.max())), abs(float(y.min()))) < 1e-5:
        raise ValueError("Silence cannot produce reliable acoustic features")

    # Reuse STFT for low-CPU spectral descriptors. Frame-aligned arrays.
    stft = np.abs(librosa.stft(y=y, n_fft=FFT, hop_length=HOP))
    centroid = librosa.feature.spectral_centroid(S=stft, sr=sr).ravel()
    flat = librosa.feature.spectral_flatness(S=stft).ravel()
    rms = librosa.feature.rms(S=stft, frame_length=FFT, hop_length=HOP).ravel()
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo_est, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, trim=False)
    tempo = float(np.asarray(tempo_est).reshape(-1)[0]) if np.size(tempo_est) else 0.0
    tempo = tempo if len(beats) >= 4 and 35 <= tempo <= 260 else 0.0

    if len(beats) >= 4:
        intervals = np.diff(np.asarray(beats, dtype=float)) * HOP / sr
        # Proxy for stability of beats detected, not a meter or time signature.
        beat_regularity = 1.0 / (1.0 + float(np.std(intervals)) / max(float(np.mean(intervals)), 1e-6))
    else:
        beat_regularity = 0.0

    onset_peaks = librosa.onset.onset_detect(onset_envelope=onset, sr=sr, hop_length=HOP)
    duration = len(y) / sr
    # Detectable onsets per second (not a genre or emotional state).
    onset_density = min(20.0, len(onset_peaks) / duration)
    energy_db = float(20 * np.log10(max(np.mean(rms), 1e-8)))
    energy_db = max(-90.0, min(0.0, energy_db))
    energy_variation = float(np.std(rms) / max(np.mean(rms), 1e-7))
    freqs = np.fft.rfftfreq(FFT, d=1 / sr)
    low_band_ratio = float(stft[freqs < 250].sum() / max(float(stft.sum()), 1e-9))

    features = {
        "bpm": tempo,
        "beat_regularity": beat_regularity,
        "onset_density": onset_density,
        "onset_strength": float(np.mean(onset)),
        "energy_db": energy_db,
        "energy_variation": energy_variation,
        "brightness": float(np.mean(centroid)),
        "flatness": float(np.mean(flat)),
        "low_band_ratio": low_band_ratio,
    }
    features.update({f"energy_curve_{i}": x for i,x in enumerate(_curve(rms))})
    features.update({f"rhythm_curve_{i}": x for i,x in enumerate(_curve(onset))})
    # Spectral centroid is positive and is normalized relative to its track average.
    features.update({f"brightness_curve_{i}": x for i,x in enumerate(_curve(centroid))})
    if tuple(features) != FEATURE_NAMES or not all(math.isfinite(v) for v in features.values()):
        raise ValueError("Invalid acoustic descriptor schema")
    return features


def extract_file(path: Path, max_seconds: int = MAX_SECONDS) -> dict:
    """Analyze at most the *first* max_seconds of a user-provided local file."""
    if not 10 <= max_seconds <= 300:
        raise ValueError("max_seconds must be between 10 and 300")
    import librosa
    import soundfile as sf
    p = Path(path).resolve(strict=True)
    if not p.is_file():
        raise ValueError("Expected a regular local audio file")
    # Decode local bytes with libsndfile only. No external decoder/playlist fallback.
    with sf.SoundFile(p) as audio:
        native_sr = audio.samplerate
        y = audio.read(frames=max_seconds * native_sr, dtype="float32", always_2d=True).mean(axis=1)
    sr = SAMPLE_RATE
    y = librosa.resample(y, orig_sr=native_sr, target_sr=sr)
    features = extract_signal(y, sr)
    features["analysis_seconds"] = round(len(y) / sr, 2)
    features["sample_rate"] = sr
    features["limited_to_first_seconds"] = max_seconds
    return features

"""Separate, untrained rhythm descriptor with explicit bar phase and sample ownership."""
import math

import numpy as np
from scipy import signal

from .data import require

FEATURE_SCHEMA = "audio-attacks-softphase16-circularac64-equalblocks.v2"
MAX_PHASE_ERROR_BEATS = 1 / 16
WINDOW_SECONDS = .032
HOP_SECONDS = .002
MIN_SEPARATION_SECONDS = WINDOW_SECONDS
RELATIVE_PROMINENCE = .05


def sample_bounds(sr, bpm, start_beat, beat_zero_seconds, phase_uncertainty_beats):
    """Uncertainty must cover the WHOLE bar, including accumulated tempo error."""
    require(type(sr) is int and 8000 <= sr <= 96000, "Unsupported sample rate")
    require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in (bpm, start_beat, beat_zero_seconds, phase_uncertainty_beats)),
            "Known finite BPM, beat origin and phase uncertainty required")
    require(40 <= bpm <= 260 and start_beat >= 0 and start_beat % 4 == 0,
            "Need a four-beat bar at supported BPM")
    require(0 <= phase_uncertainty_beats <= MAX_PHASE_ERROR_BEATS,
            "Beat phase too uncertain for phase-sensitive features")
    begin = beat_zero_seconds + start_beat * 60 / bpm
    end = beat_zero_seconds + (start_beat + 4) * 60 / bpm
    require(begin >= 0, "Bar begins before recording")
    return round(begin * sr), round(end * sr)


def spectral_attacks(y, sr):
    """Fixed engineering detector, not an instrument recognizer or beat estimator.

    Centered Hann flux nominates peaks. A waveform energy rise refines their
    sample positions; frame centers themselves are NOT physical onset timestamps.
    """
    require(type(sr) is int and 8000 <= sr <= 96000, "Unsupported sample rate")
    y = np.asarray(y, dtype=float)
    require(y.ndim == 1 and 0 < len(y) <= sr * 16 and np.isfinite(y).all(),
            "Need finite mono audio, at most 16 seconds")
    peak_amplitude = np.max(np.abs(y))
    require(peak_amplitude > 1e-5, "Silent audio")
    y = y / peak_amplitude
    window = 2 * round(WINDOW_SECONDS * sr / 2)
    hop = max(1, round(HOP_SECONDS * sr))
    # Real context supplied by extract_bar; padding here represents recording edges.
    padded = np.pad(y, (window, window))
    f, centers, z = signal.stft(padded, fs=sr, nperseg=window, noverlap=window-hop,
                                boundary=None, padded=False)
    magnitude = np.abs(z)
    flux = np.maximum(np.diff(magnitude, axis=1, prepend=np.zeros_like(magnitude[:, :1])), 0)
    bands = np.array([flux[(f >= lo) & (f < hi)].sum(axis=0)
                      for lo, hi in ((0, 200), (200, 800), (800, 3000), (3000, 8001))])
    envelope = bands.sum(axis=0)
    peaks, _ = signal.find_peaks(envelope, prominence=RELATIVE_PROMINENCE * envelope.max(),
                                 distance=max(1, round(MIN_SEPARATION_SECONDS * sr / hop)))
    # For an impulse, Hann's rising derivative peaks N/4 before the impulse;
    # a finite difference belongs halfway between adjacent frame centers.
    candidates = centers[peaks] - window / sr + (window / 4 - hop / 2) / sr
    width = max(1, round(.002 * sr))
    energy = signal.lfilter(np.ones(width) / width, [1], y * y)
    rise = np.maximum(np.diff(energy, prepend=0), 0)
    indices, strengths, frame_times = [], [], []
    for peak, seconds in zip(peaks, candidates):
        center = round(seconds * sr)
        low, high = max(0, center-window//4), min(len(y), center+window//4+1)
        if low >= high or rise[low:high].max() <= 0:
            continue
        index = low + int(np.argmax(rise[low:high]))
        if indices and index <= indices[-1]:
            continue
        indices.append(index)
        strengths.append(bands[:, peak])
        frame_times.append(float(centers[peak] - window / sr))
    return {"samples": np.asarray(indices, dtype=int),
            "strengths": np.asarray(strengths, dtype=float).reshape(-1, 4),
            "frame_center_seconds": frame_times, "window_samples": window, "hop_samples": hop}


def soft_grid(phases, strengths, bins):
    """Circular linear assignment: bounded shifts redistribute mass continuously."""
    grid = np.zeros((strengths.shape[1], bins))
    for phase, strength in zip(phases, strengths):
        position = phase * bins / 4
        left = math.floor(position)
        fraction = position-left
        grid[:, left % bins] += strength * (1-fraction)
        grid[:, (left+1) % bins] += strength * fraction
    return grid


def equal_blocks(features):
    """Fixed 50:50 squared-norm budget; also usable as a labelled cache-only probe."""
    values = np.asarray(features, dtype=float)
    require(values.shape == (128,) and np.isfinite(values).all(), "Need 128 finite coordinates")
    blocks = values.reshape(2, 64).copy()
    norms = np.linalg.norm(blocks, axis=1, keepdims=True)
    blocks /= np.maximum(norms, 1e-12) * np.sqrt(2)
    return blocks.ravel().tolist()


def extract_bar(y, sr, bpm, *, start_beat, beat_zero_seconds, phase_uncertainty_beats):
    """Read a bar from an explicitly phased recording; return a distinct v2 receipt.

    No MIDI notes enter the extractor. Unknown phase is rejected, not inferred.
    The caller must not label an arbitrary crop or unverified BPM as known phase.
    """
    begin, end = sample_bounds(sr, bpm, start_beat, beat_zero_seconds, phase_uncertainty_beats)
    y = np.asarray(y, dtype=float)
    require(y.ndim == 1 and end <= len(y), "Incomplete bar")
    context = round(WINDOW_SECONDS * sr)
    left, right = max(0, begin-context), min(len(y), end+context)
    attacks = spectral_attacks(y[left:right], sr)
    absolute = attacks["samples"] + left
    keep = (absolute >= begin) & (absolute < end)
    samples, strengths = absolute[keep], attacks["strengths"][keep]
    require(len(samples) > 0, "No eligible attacks in bar")
    phases = (samples / sr - beat_zero_seconds) * bpm / 60 - start_beat
    grid = soft_grid(phases, strengths, 16)
    grid /= np.maximum(np.linalg.norm(grid, axis=1, keepdims=True), 1e-12)
    onset = soft_grid(phases, strengths.sum(axis=1, keepdims=True), 256)[0]
    # A fixed triangular kernel spans the declared 1/16-beat timing uncertainty.
    radius = round(MAX_PHASE_ERROR_BEATS * 64)
    onset = sum((radius+1-abs(k))*np.roll(onset,k) for k in range(-radius,radius+1)) / (radius+1)**2
    onset -= onset.mean()
    ac = np.fft.irfft(np.abs(np.fft.rfft(onset))**2, n=len(onset))
    ac /= max(float(ac[0]), 1e-12)
    # A four-beat circular autocorrelation is symmetric: retain the unique half.
    profile = np.interp(np.arange(1,65)/32, np.arange(len(ac)) / 64, ac)
    features = equal_blocks(np.r_[grid.ravel(), profile])
    return {"feature_schema": FEATURE_SCHEMA, "features": features,
            "start_sample": begin, "end_sample_exclusive": end,
            "bpm": bpm, "beat_zero_seconds": beat_zero_seconds, "start_beat": start_beat,
            "phase_uncertainty_beats": phase_uncertainty_beats,
            "attack_samples": samples.tolist(), "attack_phases_beats": phases.tolist(),
            "initial_context": "recording-start zero extension" if left == 0 else "real pre-roll",
            "status": "UNTRAINED RESEARCH DESCRIPTOR; onset completeness on real music unvalidated"}

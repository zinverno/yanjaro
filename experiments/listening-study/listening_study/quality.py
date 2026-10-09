"""Bounded full-file decode diagnostics; audible artifacts still need a listener."""
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from .common import file_hash, number, require


def inspect_audio(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= 100 * 1024 * 1024, "Need a local file <=100 MiB")
    with sf.SoundFile(path) as audio:
        sr, channels = audio.samplerate, audio.channels
        require(8000 <= sr <= 96000 and 1 <= channels <= 2 and 0 < len(audio) <= sr * 3600,
                "Unsupported rate/channels/duration")
        count = clipped = silent = frames = 0
        peak = step = squares = mono_squares = 0.
        previous = None
        hop = round(sr * .02)
        # Multiples of the QC frame keep the silence statistic independent of blocks.
        for y in audio.blocks(blocksize=hop * 50, dtype="float64", always_2d=True):
            require(np.isfinite(y).all(), "Nonfinite decoded samples")
            count += len(y)
            peak = max(peak, float(np.max(np.abs(y))))
            clipped += int(np.count_nonzero(np.abs(y) >= .999))
            squares += float(np.sum(y * y))
            mono_squares += float(np.sum(y.mean(axis=1) ** 2))
            joined = y if previous is None else np.vstack((previous, y))
            if len(joined) > 1:
                step = max(step, float(np.max(np.abs(np.diff(joined, axis=0)))))
            previous = y[-1:]
            for start in range(0, len(y), hop):
                rms = np.sqrt(np.mean(y[start:start+hop] ** 2, axis=0))
                silent += int(np.max(rms) <= 1e-4)
                frames += 1
        require(count == len(audio), "Incomplete decode")
        return {"source_sha256": file_hash(path), "bytes": path.stat().st_size,
                "decode": "PASS", "frames": count, "duration_seconds": count / sr,
                "sample_rate": sr, "channels": channels, "format": audio.format, "subtype": audio.subtype,
                "peak_abs": peak, "near_full_scale_sample_fraction": clipped / (count * channels),
                "silent_20ms_fraction": silent / frames, "silence_floor_dbfs": -80,
                "rms_dbfs": 10 * math.log10(max(squares / (count * channels), 1e-16)),
                "mono_rms_dbfs": 10 * math.log10(max(mono_squares / count, 1e-16)),
                "max_adjacent_sample_step": step,
                "audible_artifacts": None, "human_listening": "NOT RUN"}


def excerpt_window(duration):
    require(number(duration, 15, 3600), "Need at least 15 seconds; no looping or padding")
    start = 30. if duration >= 45 else (duration - 15) / 2
    return {"start": start, "seconds": 15.,
            "window_rule": "fixed-30s" if duration >= 45 else "short-track-centre",
            "window_review": "PROVISIONAL: no listening-based window adjustment"}

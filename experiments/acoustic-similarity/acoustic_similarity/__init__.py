"""Feature constants from Acoustic Lab PR #6; no session/preference state."""

SEGMENTS = 6
FEATURE_NAMES = (
    "bpm", "beat_regularity", "onset_density", "onset_strength",
    "energy_db", "energy_variation", "brightness", "flatness", "low_band_ratio",
    *(f"energy_curve_{i}" for i in range(SEGMENTS)),
    *(f"rhythm_curve_{i}" for i in range(SEGMENTS)),
    *(f"brightness_curve_{i}" for i in range(SEGMENTS)),
)

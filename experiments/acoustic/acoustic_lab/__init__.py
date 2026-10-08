"""Local-only experimental acoustic analysis and session ranking for Yanjaro."""

SCHEMA_VERSION = 1
SEGMENTS = 6
FEATURE_NAMES = (
    "bpm", "beat_regularity", "onset_density", "onset_strength",
    "energy_db", "energy_variation", "brightness", "flatness", "low_band_ratio",
    *(f"energy_curve_{i}" for i in range(SEGMENTS)),
    *(f"rhythm_curve_{i}" for i in range(SEGMENTS)),
    *(f"brightness_curve_{i}" for i in range(SEGMENTS)),
)

# Strong prior for short-term rhythm, intensity and changes within the song.
PRIOR = {
    "bpm": 2.5, "beat_regularity": 1.5, "onset_density": 2.0,
    "onset_strength": 1.2, "energy_db": .8, "energy_variation": 1.5,
    "brightness": .65, "flatness": .45, "low_band_ratio": .5,
    **{f"energy_curve_{i}": .30 for i in range(SEGMENTS)},
    **{f"rhythm_curve_{i}": .34 for i in range(SEGMENTS)},
    **{f"brightness_curve_{i}": .14 for i in range(SEGMENTS)},
}

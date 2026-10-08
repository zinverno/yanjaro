"""Small generated waveform, no copyrighted recordings or external downloads."""
import unittest
import numpy as np

from acoustic_lab import FEATURE_NAMES
from acoustic_lab.audio import extract_signal


class AudioTests(unittest.TestCase):
    def test_short_synthetic_rhythmic_audio(self):
        sr=8000
        t=np.arange(sr*8)/sr
        # Clicks at 2Hz + a tone; deliberately synthetic audio only.
        click=(np.mod(t,0.5)<.025).astype(np.float32)
        sample=(.12*np.sin(2*np.pi*220*t)+.5*click).astype(np.float32)
        features=extract_signal(sample,sr)
        self.assertEqual(list(features),list(FEATURE_NAMES))
        self.assertGreater(features['energy_variation'],.01)
        self.assertGreater(features['onset_density'],0)
        self.assertTrue(all(np.isfinite(v) for v in features.values()))

    def test_silence_and_nonfinite_audio_refused(self):
        with self.assertRaisesRegex(ValueError,'Silence'):
            extract_signal(np.zeros(8000,dtype=np.float32),8000)
        with self.assertRaisesRegex(ValueError,'finite'):
            extract_signal(np.full(8000,np.nan,dtype=np.float32),8000)


if __name__=='__main__':
    unittest.main()

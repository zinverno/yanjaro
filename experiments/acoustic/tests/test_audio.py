"""Small generated waveform, no copyrighted recordings or external downloads."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np

from acoustic_lab import FEATURE_NAMES
from acoustic_lab.audio import extract_file, extract_signal


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

    def test_local_file_missing_corrupt_and_bounded_stereo(self):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(OSError):
                extract_file(root/'missing.wav')
            (root/'playlist.wav').write_text('#EXTM3U\nhttps://example.invalid/private-audio\n')
            with patch('audioread.audio_open', side_effect=AssertionError('External decoder fallback')) as fallback:
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    extract_file(root/'playlist.wav')
                fallback.assert_not_called()
            sr = 8000
            t = np.arange(sr*12)/sr
            mono = .2*np.sin(2*np.pi*220*t) + .4*(np.mod(t,.5)<.025)
            sf.write(root/'stereo.wav', np.column_stack([mono, mono]), sr)
            first = extract_file(root/'stereo.wav', max_seconds=10)
            second = extract_file(root/'stereo.wav', max_seconds=10)
            self.assertEqual(first, second)
            self.assertEqual(first['sample_rate'], 16000)
            self.assertEqual(first['analysis_seconds'], 10)


if __name__=='__main__':
    unittest.main()

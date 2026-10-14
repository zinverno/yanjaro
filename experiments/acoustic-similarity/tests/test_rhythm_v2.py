"""Known sample positions, no real fit, acquisition or revealed held-out scores."""
import unittest

import numpy as np

from acoustic_similarity.rhythm import rhythm_features
from acoustic_similarity.rhythm_v2 import (FEATURE_SCHEMA, equal_blocks, extract_bar,
                                          sample_bounds, soft_grid, spectral_attacks)


def impulses(sr=16000, bpm=120, beats=(0, .25, 1, 1.75, 3.75, 4, 5, 7.75), origin=.05):
    y = np.zeros(round((8 * 60/bpm + origin + .1)*sr))
    samples = np.rint((origin + np.asarray(beats)*60/bpm)*sr).astype(int)
    y[samples] = 1
    return y, samples


class RhythmV2Tests(unittest.TestCase):
    def test_all_impulses_correct_samples_across_rates_tempos_and_adjacent_bars(self):
        for sr in (8000, 16000, 44100, 48000, 96000):
            for bpm in (60, 123, 200, 260):
                y, samples = impulses(sr, bpm)
                for beat in (0, 4):
                    with self.subTest(sr=sr, bpm=bpm, beat=beat):
                        r = extract_bar(y, sr, bpm, start_beat=beat, beat_zero_seconds=.05,
                                        phase_uncertainty_beats=0)
                        expected = samples[(samples >= r['start_sample']) & (samples < r['end_sample_exclusive'])]
                        self.assertEqual(r['attack_samples'], expected.tolist())
                        self.assertEqual(r['feature_schema'], FEATURE_SCHEMA)
                        np.testing.assert_allclose(np.linalg.norm(np.array(r['features']).reshape(2,64), axis=1),
                                                   [2**-.5]*2, atol=1e-12)

    def test_first_impulse_not_erased_and_end_is_exclusive(self):
        y = np.zeros(32001); y[[0, 16000, 32000]] = 1
        old = np.array(rhythm_features(y[:32000], 16000, 120)).reshape(2,64)
        self.assertEqual(float(np.linalg.norm(old[0].reshape(4,16)[:,0])), 0)
        r = extract_bar(y, 16000, 120, start_beat=0, beat_zero_seconds=0, phase_uncertainty_beats=0)
        self.assertEqual(r['attack_samples'], [0,16000])
        self.assertGreater(min(np.array(r['features'][:64]).reshape(4,16)[:,0]), 0)

    def test_all_sixteenth_phases_and_initial_transient_have_same_norm(self):
        for phase in range(16):
            y, indices = impulses(beats=(phase/4,), origin=0)
            r = extract_bar(y, 16000, 120, start_beat=0, beat_zero_seconds=0, phase_uncertainty_beats=0)
            self.assertEqual(r['attack_samples'], indices.tolist())
            self.assertEqual(np.argmax(np.array(r['features'][:64]).reshape(4,16),axis=1).tolist(), [phase]*4)

    def test_real_preroll_avoids_false_cut_attack(self):
        y, samples = impulses(beats=(3.99,4.25,5,6,8), origin=0)
        r = extract_bar(y, 16000, 120, start_beat=4, beat_zero_seconds=0, phase_uncertainty_beats=0)
        self.assertEqual(r['attack_samples'], samples[1:-1].tolist())
        self.assertEqual(r['initial_context'], 'real pre-roll')

    def test_absolute_rounding_has_no_gap_or_overlap(self):
        mismatch_found = False
        for sr in (8000,16000,44100,48000):
            for bpm in range(40,261):
                for start in (0,4,8,12,16):
                    begin,end = sample_bounds(sr,bpm,start,0,0)
                    following,_ = sample_bounds(sr,bpm,start+4,0,0)
                    self.assertEqual(end,following)
                    self.assertLessEqual(abs(begin/sr-start*60/bpm), .500001/sr)
                    self.assertLessEqual(abs(end/sr-(start+4)*60/bpm), .500001/sr)
                    mismatch_found |= begin+round(4*60/bpm*sr) != end
        self.assertTrue(mismatch_found)

    def test_tone_transients_in_all_four_bands_detected_once(self):
        for hz in (60,300,1200,5000):
            y = np.zeros(36000)
            positions = np.array([0,.5,1,1.875])
            for seconds, amplitude in zip(positions,[1,.2,.5,1]):
                i = round(seconds*16000); t = np.arange(800)/16000
                y[i:i+len(t)] += amplitude*np.sin(2*np.pi*hz*t)*np.exp(-t/.008)
            attacks = spectral_attacks(y,16000)
            self.assertEqual(len(attacks['samples']),4)
            np.testing.assert_allclose(attacks['samples']/16000,positions,atol=.004,rtol=0)

    def test_small_jitter_is_bounded_not_claimed_invariant(self):
        for bpm in (60,120,200,260):
            origin = .1; beats = np.array([.5,1.25,2.25,3.5])
            y,_ = impulses(bpm=bpm,beats=beats,origin=origin)
            reference = extract_bar(y,16000,bpm,start_beat=0,beat_zero_seconds=origin,phase_uncertainty_beats=0)
            for shift in (-.01,-.005,-.001,.001,.005,.01):
                changed,_ = impulses(bpm=bpm,beats=beats+shift*bpm/60,origin=origin)
                actual = extract_bar(changed,16000,bpm,start_beat=0,beat_zero_seconds=origin,phase_uncertainty_beats=0)
                self.assertEqual(len(actual['attack_samples']),4)
                self.assertLess(np.linalg.norm(np.array(actual['features'][:64])-reference['features'][:64]),.25)
            changed,_ = impulses(bpm=bpm,beats=beats+np.array([-.01,.01,-.01,.01])*bpm/60,origin=origin)
            actual = extract_bar(changed,16000,bpm,start_beat=0,beat_zero_seconds=origin,phase_uncertainty_beats=0)
            self.assertLess(np.linalg.norm(np.array(actual['features'])-reference['features']),.65)

    def test_gain_invariance_and_detector_resolution_limit(self):
        y,_ = impulses()
        kwargs = dict(sr=16000,bpm=120,start_beat=0,beat_zero_seconds=.05,phase_uncertainty_beats=0)
        np.testing.assert_allclose(extract_bar(y,**kwargs)['features'],
                                   extract_bar(y*.2,**kwargs)['features'],atol=1e-12)
        y = np.zeros(32000); y[8000] = 1; y[8000+160] = .2
        # A ten-millisecond flam is outside the declared 32 ms detector resolution.
        self.assertLess(len(spectral_attacks(y,16000)['samples']),2)

    def test_soft_assignment_continuous_at_old_rounding_boundary(self):
        a = soft_grid([.125-1e-6],np.ones((1,4)),16)
        b = soft_grid([.125+1e-6],np.ones((1,4)),16)
        self.assertLess(np.linalg.norm(a-b),3e-5)
        self.assertEqual(a.sum(),4)
        np.testing.assert_allclose(equal_blocks(np.r_[a.ravel(),np.ones(64)]),
                                   equal_blocks(np.r_[a.ravel()*100,np.ones(64)*.01]),atol=1e-12)

    def test_unknown_or_inaccurate_phase_is_rejected(self):
        for origin,uncertainty in ((None,0),(0,None),(float('nan'),0),(0,.063),(0,-.1)):
            with self.assertRaises(ValueError): sample_bounds(16000,120,0,origin,uncertainty)
        with self.assertRaises(ValueError): sample_bounds(16000,120,1,0,0)
        with self.assertRaises(ValueError): extract_bar(np.ones(100),16000,120,start_beat=0,
                                                        beat_zero_seconds=0,phase_uncertainty_beats=0)

    def test_silence_nonfinite_and_oversize_fail(self):
        for y in (np.zeros(32000),np.array([np.nan]),np.zeros(16000*17)):
            with self.assertRaises(ValueError): spectral_attacks(y,16000)


if __name__ == '__main__': unittest.main()

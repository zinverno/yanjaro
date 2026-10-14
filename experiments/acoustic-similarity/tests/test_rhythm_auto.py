"""Known pulse mechanics and conservative gates; no real recordings or fitting."""
import unittest
from unittest.mock import patch

import numpy as np

from acoustic_similarity.rhythm_auto import (analyze_attacks, meter_hypotheses, phase_offset,
                                             tempo_candidates, track_beats)
from acoustic_similarity.rhythm_v2 import spectral_attacks


class RhythmAutoTests(unittest.TestCase):
    def setUp(self):
        self.times=np.arange(.3,14.9,.5)
        self.strengths=np.ones((len(self.times),4))

    def test_known_pulse_period_is_retained_with_octave_ambiguity(self):
        ranks,_=tempo_candidates(self.times,self.strengths.sum(axis=1),15)
        self.assertTrue(any(abs(c['bpm']-120)<.5 for c in ranks))
        offset=phase_offset(self.times,self.strengths.sum(axis=1),.5)
        self.assertLess(abs(offset-.3),.5/128)
        _,beats,observed,_=track_beats(self.times,self.strengths,120,offset,15)
        np.testing.assert_allclose(beats,self.times,atol=1e-12)
        self.assertTrue(all(observed))

    def test_absolute_origin_changes_timestamps_not_estimates(self):
        a=analyze_attacks(self.times,self.strengths,15,0)
        b=analyze_attacks(self.times,self.strengths,15,30.123)
        self.assertEqual(a['estimated_bpm'],b['estimated_bpm'])
        np.testing.assert_allclose(np.array(b['beat_candidates_seconds_absolute'])-a['beat_candidates_seconds_absolute'],30.123)

    def test_self_consistency_never_certifies_phase(self):
        with patch('acoustic_similarity.rhythm_v2.extract_bar',side_effect=AssertionError('Forbidden')):
            r=analyze_attacks(self.times,self.strengths,15,30)
        self.assertEqual(r['status'],'AUTO_CANDIDATE')
        self.assertIsNone(r['phase_uncertainty_beats'])
        self.assertEqual(r['strict_v2_extractions'],0)
        self.assertEqual(r['rhythm_v2_gate'],'ABSTAIN')

    def test_largest_accent_does_not_select_downbeat(self):
        accents=self.strengths.copy();accents[2::4]*=10
        meters=meter_hypotheses(self.times,accents,30)
        for m in meters:
            self.assertIsNone(m['chosen_offset'])
            self.assertEqual(len(m['downbeat_alternatives_seconds_absolute']),m['beats_per_group'])
        self.assertGreater(meters[2]['accent_repeat_correlation'],.99)

    def test_empty_sparse_and_changing_pulse_abstain(self):
        for times in (np.array([]),np.array([1.,5.,9.]),np.r_[np.arange(.3,5,.5),np.arange(5.3,10,.7),np.arange(10.3,15,.4)]):
            r=analyze_attacks(times,np.ones((len(times),4)),15,30)
            self.assertEqual(r['status'],'ABSTAIN')

    def test_window_edges_excluded_without_reading_extra_context(self):
        times=np.r_[.001,self.times,14.999]
        r=analyze_attacks(times,np.ones((len(times),4)),15,3.6244671201814054)
        self.assertEqual(r['edge_candidates_excluded'],2)

    def test_melodic_transients_are_not_identified_as_non_drums(self):
        sr=16000;y=np.zeros(15*sr)
        y[np.rint(self.times*sr).astype(int)]=1
        melodic=self.times[self.times+.24<15]+.2
        t=np.arange(640)/sr
        for seconds in melodic:
            i=round(seconds*sr)
            y[i:i+len(t)]+=.8*np.sin(2*np.pi*700*t)*np.exp(-t/.008)
        attacks=spectral_attacks(y,sr)['samples']/sr
        matched=(np.abs(melodic[:,None]-attacks).min(axis=1)<.01).sum()
        self.assertGreater(matched,len(melodic)*.9)

    def test_invalid_events_rejected(self):
        for times,strengths in (([1,1],np.ones((2,4))),([float('nan')],np.ones((1,4))),([16],np.ones((1,4)))):
            with self.assertRaises(ValueError):analyze_attacks(times,strengths,15,30)


if __name__=='__main__':unittest.main()

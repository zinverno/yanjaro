"""Known events validate mechanics, never label real-song similarity."""
import copy
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import numpy as np

from acoustic_similarity.rhythm_pi import describe_events, distance, extract, search


def events(times, amplitudes=None):
    weights=np.ones((len(times),4))
    if amplitudes is not None: weights*=np.asarray(amplitudes)[:,None]
    return describe_events(times,weights,15)


def waveform(times,amplitudes=None,hz=None):
    sr=16000; y=np.zeros(15*sr)
    for seconds,amplitude in zip(times,np.ones(len(times)) if amplitudes is None else amplitudes):
        start=round(seconds*sr)
        if hz is None: y[start]+=amplitude
        else:
            t=np.arange(640)/sr
            y[start:start+len(t)]+=amplitude*np.sin(2*np.pi*hz*t)*np.exp(-t/.008)
    return y


def synthetic_measurements():
    times=np.arange(.5,12.1,.5)
    base=events(times)
    altered=np.concatenate([b+np.array([0,.375,1.,1.75]) for b in np.arange(.5,11,2)])
    rng=np.random.default_rng(20261014)
    cases={'translated_events':events(times+.137),
           'same_120bpm_different_pattern':events(altered),
           'independent_jitter_10ms':events(times+rng.uniform(-.01,.01,len(times))),
           'accent_change':events(times,np.tile([1.,.2,.2,.2],6)),
           'twice_event_density':events(np.arange(.5,12.1,.25)),
           'dense_irregular':events(np.cumsum(rng.uniform(.033,.085,210)))}
    measurements={k:distance(base,v) for k,v in cases.items()}
    for label,factor in (('half_tempo',2.),('double_tempo',.5)):
        measurements[label]=distance(base,events(np.arange(.5,12.1,.5*factor)))
    clean=extract(waveform(times),16000)
    shifted=extract(waveform(times+.137),16000)
    jitter=extract(waveform(times+rng.uniform(-.01,.01,len(times))),16000)
    weak=extract(waveform(times,np.tile([1.,.2],12)),16000)
    tonal=extract(waveform(times)+waveform(times+.2,hz=700),16000)
    for label,row in [('translated_waveform',shifted),('waveform_jitter_10ms',jitter),
                      ('weak_strong_hits',weak),('tonal_offbeats',tonal)]:
        measurements[label]={**distance(clean,row),'detected_events':row['diagnostics']['onsets']}
    measurements['clean_detected_events']=clean['diagnostics']['onsets']
    measurements['dense_irregular_diagnostics']=cases['dense_irregular']['diagnostics']
    return measurements


class PhaseIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.measurements=synthetic_measurements()

    def test_translation_invariance_with_same_events_and_bounded_audio_error(self):
        m=self.measurements
        self.assertLess(m['translated_events']['distance'],1e-10)
        self.assertLess(m['translated_waveform']['distance'],.03)
        self.assertEqual(m['clean_detected_events'],24)
        self.assertEqual(m['translated_waveform']['detected_events'],24)

    def test_pattern_and_density_not_only_bpm(self):
        m=self.measurements
        self.assertGreater(m['same_120bpm_different_pattern']['distance'],.05)
        self.assertGreater(m['twice_event_density']['contributions']['density'],.01)
        self.assertGreater(m['accent_change']['distance'],1e-4)

    def test_half_double_keep_normalized_intervals_but_not_absolute_density(self):
        for name in ('half_tempo','double_tempo'):
            r=self.measurements[name]
            self.assertLess(r['contributions']['intervals'],1e-10)
            self.assertGreater(r['contributions']['density'],.01)
            self.assertGreater(r['distance'],0)

    def test_independent_jitter_is_bounded_not_invariant(self):
        for name in ('independent_jitter_10ms','waveform_jitter_10ms'):
            self.assertGreater(self.measurements[name]['distance'],0)
            self.assertLess(self.measurements[name]['distance'],.15)

    def test_weak_hits_and_tonal_attacks_are_visible_not_drum_labels(self):
        m=self.measurements
        self.assertEqual(m['weak_strong_hits']['detected_events'],24)
        self.assertEqual(m['tonal_offbeats']['detected_events'],48)
        self.assertGreater(m['tonal_offbeats']['distance'],.01)

    def test_density_never_certifies_similarity_and_unknown_tempo_is_neutral(self):
        d=self.measurements['dense_irregular_diagnostics']
        self.assertGreater(d['event_rate'],12)
        self.assertEqual(d['acoustic_quality'],'UNVALIDATED')
        a=events(np.arange(.5,14,.5)); b=copy.deepcopy(a)
        b['blocks']['tempo']=[0.]*64
        self.assertEqual(distance(a,b),distance(b,a))
        self.assertEqual(distance(a,b)['contributions']['tempo'],.125)
        self.assertTrue(distance(b,b)['unknown_tempo'])
        self.assertEqual(distance(b,b)['quality'],'UNVALIDATED')

    def test_symmetric_bounded_search_excludes_source_aliases(self):
        a=events(np.arange(.5,14,.5)); b=events(np.arange(.5,14,.375))
        self.assertEqual(distance(a,b),distance(b,a))
        self.assertTrue(0<=distance(a,b)['distance']<=1)
        rows=[dict(a,id='a',audio_sha256='a'*64,recording_group='a'),
              dict(b,id='b',audio_sha256='b'*64,recording_group='b'),
              dict(a,id='alias',audio_sha256='a'*64,recording_group='alias'),
              dict(b,id='crop',audio_sha256='c'*64,recording_group='a')]
        self.assertEqual([r['id'] for r in search('a',rows)],['b'])
        rows[1]['title']='changed metadata'; rows[1]['genre']='irrelevant'
        self.assertEqual(search('a',rows)[0]['distance'],distance(a,b)['distance'])

    def test_fail_closed_silence_sparse_nonfinite_and_wrong_schema(self):
        self.assertEqual(extract(np.zeros(16000*15),16000)['status'],'ABSTAIN')
        self.assertEqual(events([1.,2.,3.])['status'],'ABSTAIN')
        for t,w in (([1.,1.],np.ones((2,4))),([float('nan')],np.ones((1,4))),
                    ([16.],np.ones((1,4))),([1.],-np.ones((1,4)))):
            with self.assertRaises(ValueError): describe_events(t,w,15)
        a=events(np.arange(.5,14,.5)); b=copy.deepcopy(a)
        for value in ('v2','garbage'):
            b['feature_schema']=value
            with self.assertRaises(ValueError):distance(a,b)
        b=copy.deepcopy(a); b['blocks']['periodicity'][0][0]=float('nan')
        with self.assertRaises(ValueError):distance(a,b)

    def test_changed_manifest_stops_before_decoding(self):
        runner=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/rhythm_pi_study.py'))
        preflight=runner['preflight']
        with patch.dict(preflight.__globals__,file_hash=lambda path:'0'*64), patch('soundfile.SoundFile') as decoder:
            with self.assertRaisesRegex(ValueError,'Unapproved manifest'):
                preflight('unused','unused')
            decoder.assert_not_called()


if __name__=='__main__':unittest.main()

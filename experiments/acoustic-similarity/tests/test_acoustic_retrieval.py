"""Mechanics and known signal interventions; no synthetic musical relevance labels."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from acoustic_similarity import features
from acoustic_similarity.data import digest, file_hash
from acoustic_similarity import rhythm_pi as pi
from acoustic_similarity.acoustic_retrieval import (NAMES, combine, compare, perturb, search, validate)


def row(tid,times=None):
    if times is None:times=np.arange(.5,14,.5)
    p=pi.describe_events(times,np.ones((len(times),4)),15)
    p.update(id=tid,audio_sha256=tid[0]*64,recording_group=tid,title='synthetic',
             evidence_sha256='e'*64,sample_rate=16000,start_sample=0,end_sample_exclusive=240000)
    d=dict(id=tid,sha256=p['audio_sha256'],vectors=dict(timbre=[0.]*85,energy=[0.]*10))
    return combine(p,d)


def missing(r,keys):
    r=copy.deepcopy(r)
    for k in keys:
        r['blocks'][k]=None;r['missing_reasons'][k]='CONTROLLED_MISSINGNESS'
    return r


def signal_fixtures():
    sr=16000;t=np.arange(1600)/sr;times=np.arange(.5,14,.5)
    rows=[];receipts=[]
    with tempfile.TemporaryDirectory() as root:
        for tid,hz,gain in [('a',220.,1.),('b',2200.,1.),('c',220.,.2)]:
            y=np.zeros(15*sr)
            for seconds in times:
                start=round(seconds*sr)
                y[start:start+len(t)]+=gain*np.sin(2*np.pi*hz*t)*np.exp(-t/.02)
            path=Path(root)/(tid+'.wav');sf.write(path,y,sr,subtype='FLOAT')
            h=file_hash(path);track=dict(id=tid,path=str(path),start=0,seconds=15,sha256=h)
            first=features.extract(track);second=features.extract(track)
            assert digest(first)==digest(second) and file_hash(path)==h
            audio,_=sf.read(path)
            p=pi.extract(audio,sr)
            assert digest(p)==digest(pi.extract(audio,sr))
            p.update(id=tid,audio_sha256=h,recording_group=tid,title='synthetic',
                     evidence_sha256='e'*64,sample_rate=sr,start_sample=0,end_sample_exclusive=len(y))
            rows.append(combine(p,first))
            receipts.append(dict(id=tid,audio_sha256=h,dsp_sha256=digest(first),pi_sha256=digest(p),repeat_equal=True))
    return dict(same_timing_different_carrier=compare(rows[0],rows[1]),
                same_carrier_lower_gain=compare(rows[0],rows[2]),repeat_receipts=receipts)


class AcousticRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.signals=signal_fixtures()

    def test_unknown_query_candidate_and_both_are_null_and_symmetric(self):
        a,b=row('a'),row('b');u=missing(a,['tempo']);v=missing(b,['tempo'])
        for x,y in [(u,b),(a,v),(u,v)]:
            d=compare(x,y)
            self.assertEqual(d,compare(y,x))
            self.assertIsNone(d['components']['tempo']['distance'])
            self.assertEqual(d['coverage'],.75)
            self.assertEqual(d['common_distance'],0)
            self.assertEqual(d['quality'],'UNVALIDATED')
        self.assertEqual(compare(u,v)['missing']['tempo'],['a','b'])

    def test_coverage_strata_never_mix_scores(self):
        q,full,partial=row('a'),row('b'),missing(row('c'),['tempo'])
        full['blocks']['timbre']=[1.]*85
        ranked=search('a',[q,partial,full])['results']
        self.assertEqual([r['id'] for r in ranked],['b','c'])
        self.assertGreater(ranked[0]['common_distance'],ranked[1]['common_distance'])
        self.assertEqual([r['coverage_tier'] for r in ranked],[1,2])
        partial=missing(partial,['periodicity_0','timbre'])
        d=compare(q,partial)
        self.assertEqual(d['components']['rhythm']['coverage'],11/12)
        self.assertLess(d['coverage'],.75)

    def test_equal_coverage_different_masks_use_fixed_mask_order(self):
        q=row('a');b=missing(row('b'),['timbre']);c=missing(row('c'),['tempo'])
        b['blocks']['energy']=[1.]*10
        result=search('a',[q,c,b])['results']
        self.assertEqual([r['id'] for r in result],['b','c'])
        self.assertEqual(result[0]['coverage'],result[1]['coverage'])
        self.assertGreater(result[0]['common_distance'],result[1]['common_distance'])
        self.assertNotEqual(result[0]['coverage_tier'],result[1]['coverage_tier'])

    def test_known_pi_pairs_preserve_original_formula(self):
        a=row('a');b=row('b',np.arange(.5,14,.3))
        def old(r):
            v=r['blocks']
            return dict(feature_schema=pi.FEATURE_SCHEMA,status='INDEXED_UNVERIFIED',
                blocks=dict(periodicity=[v[f'periodicity_{i}'] for i in range(4)],
                            intervals=v['intervals'],density=v['density'],tempo=v['tempo']))
        self.assertAlmostEqual(compare(a,b,'pi_coverage_v2')['common_distance'],pi.distance(old(a),old(b))['distance'])

    def test_no_common_features_abstains(self):
        a=row('a');b=missing(row('b'),NAMES)
        self.assertEqual(compare(a,b)['status'],'ABSTAIN')
        self.assertIsNone(compare(a,b)['conditional_score'])
        self.assertEqual(search('a',[a,b])['abstentions'],[dict(id='b',reason='NO_COMMON_FEATURES')])

    def test_rhythm_abstention_still_allows_timbre_and_energy(self):
        p=pi.describe_events([],np.empty((0,4)),15)
        p.update(id='a',audio_sha256='a'*64,recording_group='a',title='synthetic',
                 evidence_sha256='e'*64,sample_rate=16000,start_sample=0,end_sample_exclusive=240000)
        r=combine(p,dict(id='a',sha256='a'*64,vectors=dict(timbre=[0.]*85,energy=[0.]*10)))
        self.assertEqual(compare(r,row('b'))['coverage'],.5)

    def test_known_tempo_changes_and_rhythm_patterns_are_separate(self):
        a=row('a');faster=row('b',np.arange(.5,14,.25))
        pattern=np.concatenate([b+np.array([0,.375,1.,1.75]) for b in np.arange(.5,12,2)])
        different=row('c',pattern)
        self.assertLess(compare(a,faster)['atomic_distances']['intervals'],1e-10)
        self.assertGreater(compare(a,faster)['components']['tempo']['distance'],.01)
        self.assertGreater(compare(a,different)['components']['rhythm']['distance'],.1)
        changed=copy.deepcopy(a);changed['id']='b';changed['blocks']['tempo']=faster['blocks']['tempo']
        d=compare(a,changed)
        self.assertEqual(d['components']['rhythm']['distance'],0)
        self.assertAlmostEqual(d['common_distance'],d['components']['tempo']['distance']/4)

    def test_timbre_and_energy_interventions_do_not_mutate_rhythm_or_double_tempo(self):
        a=row('a');b=row('b');b['blocks']['timbre']=[1.]*85
        c=row('c');c['blocks']['energy']=[1.]*10
        for r,k in [(b,'timbre'),(c,'energy')]:
            d=compare(a,r)
            self.assertEqual(d['components'][k]['distance'],.5)
            self.assertEqual(d['common_distance'],.125)
            for other in set(d['components'])-{k}:
                self.assertEqual(d['components'][other]['distance'],0)

    def test_one_aspect_influence_is_bounded_and_missing_renormalization_explicit(self):
        a=row('a');b=row('b');b['blocks']['timbre']=[1.]*85;a['blocks']['timbre']=[-1.]*85
        d=compare(a,b)
        self.assertEqual(d['common_distance'],.25)
        partial=compare(missing(a,['tempo']),b)
        self.assertEqual(partial['components']['timbre']['weighted_contribution'],.25)
        self.assertAlmostEqual(partial['common_distance'],1/3)

    def test_signal_extraction_repeats_and_interventions_are_observed(self):
        self.assertTrue(all(r['repeat_equal'] for r in self.signals['repeat_receipts']))
        self.assertGreater(self.signals['same_timing_different_carrier']['components']['timbre']['distance'],.01)
        self.assertGreater(self.signals['same_carrier_lower_gain']['components']['energy']['distance'],.01)

    def test_ordering_hashes_aliases_and_small_feature_perturbations(self):
        rows=[row('a'),row('b'),row('c')]
        self.assertEqual(digest(search('a',rows)),digest(search('a',rows[::-1])))
        self.assertEqual([r['id'] for r in search('a',rows)['results']],['b','c'])
        alias=copy.deepcopy(rows[0]);alias['id']='alias'
        crop=copy.deepcopy(rows[1]);crop['id']='crop';crop['recording_group']='a'
        self.assertEqual(len(search('a',rows+[alias,crop])['results']),2)
        changed=perturb(rows,0)
        self.assertEqual(digest(changed),digest(perturb(rows,0)))
        self.assertEqual(digest(changed),digest(perturb(json.loads(json.dumps(rows,sort_keys=True)),0)))
        for a,b in zip(rows,changed):
            validate(b);d=compare(a,b)
            self.assertEqual(d['coverage'],1)
            self.assertLess(d['common_distance'],.1)

    def test_invalid_inputs_fail_closed(self):
        a=row('a')
        for value in ([float('nan')]*85,[2.]*85,[0.]*84):
            b=copy.deepcopy(a);b['blocks']['timbre']=value
            with self.assertRaises(ValueError):compare(a,b)
        b=copy.deepcopy(a);b['blocks']['tempo']=[0.]*64
        with self.assertRaises(ValueError):compare(a,b)
        b=copy.deepcopy(a);b['blocks']['tempo']=None
        with self.assertRaises(ValueError):compare(a,b)


if __name__=='__main__':unittest.main()

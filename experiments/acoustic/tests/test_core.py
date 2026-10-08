import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from acoustic_lab import FEATURE_NAMES, SCHEMA_VERSION
from acoustic_lab.core import (distance_vector,empty_library,empty_sessions,load_library,
                               load_sessions,new_session,rate,recommend,train_ranker,write_json,
                               normalization,prior_weights)


def feat(tempo=100, rhythm=1.0, bright=1000, energy=-12):
    f={k:0.0 for k in FEATURE_NAMES}
    f.update(bpm=float(tempo),beat_regularity=.8,onset_density=float(rhythm),
             onset_strength=.4, energy_db=float(energy),energy_variation=.1,
             brightness=float(bright),flatness=.1,low_band_ratio=.25)
    for i in range(6):
        f[f"energy_curve_{i}"]=float(i%3)/10+float(rhythm)/20
        f[f"rhythm_curve_{i}"]=float(i%2)/10+float(rhythm)/20
        f[f"brightness_curve_{i}"]=float(i%2)/10
    return f


def fake_lib():
    lib=empty_library()
    # Contexts span short-term tempo/rhythm, not static genre labels.
    tracks=[("slow","Slow Seed",70,.5,650,-20),
            ("medium","Medium Seed",110,1.2,1100,-13),
            ("fast","Fast Seed",160,3.0,1800,-8),
            ("slow-good","Slow Good",72,.55,690,-20),
            ("slow-bad","Slow Bad",130,2.7,1800,-6),
            ("mid-good","Mid Good",112,1.1,1120,-12),
            ("mid-bad","Mid Bad",70,.5,630,-24),
            ("fast-good","Fast Good",155,3.1,1750,-7),
            ("fast-bad","Fast Bad",80,.7,700,-20),
            ("other","Other",90,2,1300,-14)]
    for id,name,t,r,b,e in tracks:
        lib["tracks"][id]={"name":name,"path":"/fake/"+id,"features":feat(t,r,b,e)}
    return lib


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.lib=fake_lib()

    def test_schema_and_cache_are_local_and_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"private"/"library.json"
            write_json(p,self.lib)
            self.assertEqual(load_library(p),self.lib)
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            p.write_text(json.dumps({"version":999}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Unsupported"):
                load_library(p)
            self.assertEqual(load_sessions(Path(td)/"missing"),empty_sessions())

    def test_tempo_octave_equivalence_and_finite_distance(self):
        means,scales=normalization(self.lib)
        same=distance_vector(feat(140),[feat(70)],means,scales)
        distant=distance_vector(feat(105),[feat(70)],means,scales)
        bpm_idx=FEATURE_NAMES.index("bpm")
        self.assertLess(same[bpm_idx],distant[bpm_idx])
        self.assertTrue(np.isfinite(same).all())
        self.assertAlmostEqual(prior_weights().sum(),1.0)

    def test_sessions_are_explicit_not_inferred_from_skips(self):
        data=empty_sessions()
        new_session(data,"evening",["slow"],self.lib)
        rate(data,"evening","slow-good",True,self.lib)
        rate(data,"evening","slow-bad",False,self.lib)
        self.assertEqual(data["sessions"][0]["ratings"],{"slow-good":True,"slow-bad":False})
        with self.assertRaisesRegex(ValueError,"non-seed"):
            rate(data,"evening","slow",True,self.lib)
        with self.assertRaisesRegex(ValueError,"already"):
            new_session(data,"evening",["slow"],self.lib)

    def test_recommend_baseline_and_exclusions(self):
        data=empty_sessions()
        new_session(data,"x",["slow"],self.lib)
        rate(data,"x","slow-bad",False,self.lib)
        s=data["sessions"][0]
        results=recommend(self.lib,s,limit=20)
        ids=[r['id'] for r in results]
        self.assertNotIn("slow",ids)
        self.assertNotIn("slow-bad",ids)
        # Another synthetic candidate can be acoustically even closer; no title-based ranking.
        self.assertLess(ids.index("slow-good"), ids.index("fast-good"))
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(recommend(self.lib,s,limit=1)[0]['id'],ids[0])

    def test_model_training_and_holdout_metadata(self):
        data=empty_sessions()
        recipes=[('slow','slow-good','slow-bad'),('medium','mid-good','mid-bad'),
                 ('fast','fast-good','fast-bad')]*3
        for i,(seed,yes,no) in enumerate(recipes):
            new_session(data,f"session_{i:02d}",[seed],self.lib)
            rate(data,f"session_{i:02d}",yes,True,self.lib)
            rate(data,f"session_{i:02d}",no,False,self.lib)
        model=train_ranker(self.lib,data)
        self.assertEqual(model['model_type'],'nonnegative_pairwise_logistic_distance_reranker')
        self.assertEqual(model['training']['train_sessions'],6)
        self.assertEqual(model['training']['holdout_sessions'],3)
        self.assertGreaterEqual(min(model['weights']),0)
        self.assertEqual(len(model['weights']),len(FEATURE_NAMES))
        new_session(data,'test',['medium'],self.lib)
        ranks=recommend(self.lib,data['sessions'][-1],model)
        self.assertEqual(len(ranks),len(self.lib['tracks'])-1)
        with self.assertRaisesRegex(ValueError,'Model version'):
            recommend(self.lib,data['sessions'][-1],{**model,'version':999})

    def test_not_enough_labels_refuses_training(self):
        with self.assertRaisesRegex(ValueError,'Need 6 sessions'):
            train_ranker(self.lib,empty_sessions())


if __name__=='__main__':
    unittest.main()

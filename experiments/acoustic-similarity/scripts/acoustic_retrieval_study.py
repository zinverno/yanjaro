"""Bounded offline common acoustic retrieval using only the ten approved originals."""
import argparse
import copy
import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import resource
import runpy
import subprocess
import sys
import time
import unittest

import numpy as np
import soundfile as sf

from acoustic_similarity import features, rhythm_pi
from acoustic_similarity.acoustic_retrieval import (DISTANCE_SCHEMA,FEATURE_SCHEMA,MISSING_POLICY,
                                                   NAMES,POLICY,combine,compare,perturb,search)
from acoustic_similarity.data import digest,file_hash,read_json,require,validate_manifest,write_new

ROOT=Path(__file__).resolve().parents[1]
BASE_HEAD='277f26d56cc71bcca02a61d88414062f13f3ac6c'
PI_INDEX=ROOT/'validation/rhythm-pi-v1/index.json'
PI_SHA='e5b4bc2d890b8d6dbea7353b8a9de87292ec761219aacf6f04f315b261b8ae87'


def rank_all(rows,profile='acoustic'):
    return {r['id']:search(r['id'],rows,9,profile) for r in rows}


def snapshot(ranking):
    return dict(order=[r['id'] for r in ranking['results']],
                top3=[dict(id=r['id'],coverage=r['coverage'],mask=r['coverage_mask'],
                           conditional_score=r['conditional_score']) for r in ranking['results'][:3]])


def near_ties(rankings):
    output=[]
    for query,r in rankings.items():
        for a,b in zip(r['results'],r['results'][1:]):
            if a['coverage_mask']==b['coverage_mask'] and b['common_distance']-a['common_distance']<=.005:
                output.append(dict(query=query,ids=[a['id'],b['id']],ranks=[a['rank'],b['rank']],
                                   coverage_mask=a['coverage_mask'],gap=b['common_distance']-a['common_distance']))
    return output


def stability(rows,baseline):
    scenarios=[(f'noise_seed_{seed}',perturb(rows,seed)) for seed in POLICY['perturbation']['seeds']]
    drops=[('tempo_from_'+r['id'],[r['id']],['tempo']) for r in rows]
    drops += [('all_'+name,[r['id'] for r in rows],keys) for name,keys in
              [('rhythm',NAMES[:6]),('tempo',['tempo']),('timbre',['timbre']),('energy',['energy'])]]
    for name,ids,keys in drops:
        changed=copy.deepcopy(rows)
        for r in changed:
            if r['id'] in ids:
                for k in keys:
                    r['blocks'][k]=None;r['missing_reasons'][k]='CONTROLLED_SENSITIVITY_DROPOUT'
        scenarios.append((name,changed))
    output=[]
    for name,changed in scenarios:
        ranks=rank_all(changed); comparisons={}; deltas=[]; coverage_changes=0
        for query,r in ranks.items():
            before=baseline[query]['results'];after=r['results']
            a,b=[v['id'] for v in before],[v['id'] for v in after]
            comparisons[query]=dict(before_order=a,after_order=b,after_top3=snapshot(r)['top3'],
                top3_common=len(set(a[:3])&set(b[:3])),top3_order_unchanged=a[:3]==b[:3],
                top1_unchanged=a[0]==b[0],rank_displacement={tid:b.index(tid)-i for i,tid in enumerate(a)})
            old={v['id']:v for v in before}
            for v in after:
                if v['coverage_mask']==old[v['id']]['coverage_mask']:
                    deltas.append(abs(v['common_distance']-old[v['id']]['common_distance']))
                else:coverage_changes+=1
        output.append(dict(scenario=name,comparisons=comparisons,near_ties=near_ties(ranks),
                           changed_pair_masks=coverage_changes,max_same_mask_distance_change=max(deltas,default=0.)))
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--dsp-index',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    require(not args.out.exists(),'Create-only output required')
    require(all(os.environ.get(k)=='2' for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','NUMBA_NUM_THREADS')),
            'Two configured compute threads required')
    resource.setrlimit(resource.RLIMIT_CPU,(540,540));resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    def offline(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto'):
            raise RuntimeError('Study is offline')
    sys.addaudithook(offline);started=time.perf_counter()
    try:
        require(file_hash(PI_INDEX)==PI_SHA,'Historical PI index changed')
        preflight=runpy.run_path(str(ROOT/'scripts/rhythm_pi_study.py'))['preflight']
        manifest,tracks,_,dsp_rows=preflight(args.manifest,args.dsp_index)
        pi_index=read_json(PI_INDEX)
        require(pi_index['dataset_sha256']==digest(manifest),'PI manifest mismatch')
        pi_rows={r['id']:r for r in pi_index['tracks']}
        require(set(pi_rows)==set(tracks),'PI IDs mismatch')
    except (OSError,ValueError):
        write_new(args.out/'status.json',dict(status='BLOCKED',reason='Approved local inputs absent or hash mismatch',
                                            audio_decoded=False,new_audio_download_bytes=0))
        return 2
    files=['acoustic_similarity/acoustic_retrieval.py','acoustic_similarity/features.py',
           'acoustic_similarity/lab_audio.py','acoustic_similarity/rhythm_pi.py','acoustic_similarity/rhythm_auto.py',
           'acoustic_similarity/rhythm_v2.py','scripts/rhythm_pi_study.py','scripts/acoustic_retrieval_study.py',
           'tests/test_acoustic_retrieval.py','ACOUSTIC_RETRIEVAL_SPEC.md','requirements.lock']
    write_new(args.out/'frozen.json',dict(feature_schema=FEATURE_SCHEMA,distance_schema=DISTANCE_SCHEMA,
        policy=POLICY,base_head=BASE_HEAD,code_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        code_sha256={f:file_hash(ROOT/f) for f in files},manifest_sha256=file_hash(args.manifest),
        dsp_index_sha256=file_hash(args.dsp_index),pi_index_sha256=PI_SHA,
        order='Frozen before decoding and before corrected PI/general real rankings',input_preflight='PASS'))
    tests=runpy.run_path(str(ROOT/'tests/test_acoustic_retrieval.py'))['AcousticRetrievalTests']
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(tests))
    require(result.wasSuccessful(),'Synthetic regression failed')
    write_new(args.out/'synthetic.json',dict(status='PASS',tests=result.testsRun,signals=tests.signals))
    rows=[];receipts=[]
    for tid,track in tracks.items():
        with sf.SoundFile(track['path']) as audio:
            require(audio.channels in (1,2),'Unexpected channels')
            sr=audio.samplerate;start=round(track['start']*sr);count=round(track['seconds']*sr)
            audio.seek(start);y=audio.read(count,dtype='float64',always_2d=True).mean(axis=1)
        require(len(y)==count and pi_rows[tid]['start_sample']==start and
                pi_rows[tid]['end_sample_exclusive']==start+count,'Window mismatch')
        p1=rhythm_pi.extract(y,sr);p2=rhythm_pi.extract(y,sr)
        d1=features.extract(track);d2=features.extract(track)
        require(digest(p1)==digest(p2) and digest(d1)==digest(d2),'Repeated extraction differs')
        pi_error=max(float(np.max(np.abs(np.asarray(p1['blocks'][k])-pi_rows[tid]['blocks'][k]))) for k in p1['blocks'])
        dsp_error=max(float(np.max(np.abs(np.asarray(d1['vectors'][k])-dsp_rows[tid]['vectors'][k]))) for k in ('timbre','energy'))
        require(pi_error<=1e-6 and dsp_error<=1e-6,'Historical feature drift exceeds frozen tolerance')
        rows.append(combine(pi_rows[tid],dsp_rows[tid]))
        receipts.append(dict(id=tid,audio_sha256=track['sha256'],evidence_sha256=track['rights']['evidence_sha256'],
            native_mono_window_sha256=hashlib.sha256(y.astype('<f8').tobytes()).hexdigest(),
            pi_repeat_digests=[digest(p1),digest(p2)],dsp_repeat_digests=[digest(d1),digest(d2)],
            max_pi_cache_error=pi_error,max_dsp_cache_error=dsp_error,
            pi_cache_exact=digest(p1['blocks'])==digest(pi_rows[tid]['blocks']),
            dsp_cache_exact=all(digest(d1['vectors'][k])==digest(dsp_rows[tid]['vectors'][k]) for k in ('timbre','energy'))))
        print(tid+' repeated PI/DSP extraction PASS',flush=True)
    validate_manifest(manifest,purpose='analysis',verify_files=True)
    index=dict(feature_schema=FEATURE_SCHEMA,distance_schema=DISTANCE_SCHEMA,missing_policy=MISSING_POLICY,
               dataset_sha256=digest(manifest),tracks=sorted(rows,key=lambda r:r['id']))
    rebuilt=dict(index,tracks=sorted([combine(pi_rows[k],dsp_rows[k]) for k in tracks],key=lambda r:r['id']))
    require(digest(index)==digest(rebuilt),'Nondeterministic index composition')
    write_new(args.out/'index.json',index)
    write_new(args.out/'repeat-extraction.json',dict(records=receipts,index_digests=[digest(index),digest(rebuilt)],
                                                   inputs_after_extraction='PASS',values_used='Validated historical cached coordinates'))
    common=rank_all(rows);corrected=rank_all(rows,'pi_coverage_v2')
    legacy={tid:rhythm_pi.search(tid,list(pi_rows.values()),9) for tid in tracks}
    max_symmetry=max(abs(compare(a,b)['common_distance']-compare(b,a)['common_distance']) for a in rows for b in rows)
    require(max_symmetry<1e-12,'Asymmetric distance')
    require(digest(common)==digest(rank_all(list(reversed(rows)))),'Input-order-dependent search')
    changes={q:dict(pi_v1=[r['id'] for r in legacy[q]],pi_coverage_v2=snapshot(corrected[q]),acoustic=snapshot(common[q]))
             for q in tracks}
    write_new(args.out/'retrieval.json',dict(acoustic=common,pi_coverage_v2=corrected,
        comparison=changes,maximum_symmetry_error=max_symmetry,near_ties=near_ties(common)))
    write_new(args.out/'sensitivity.json',dict(policy=POLICY['perturbation'],scenarios=stability(rows,common)))
    write_new(args.out/'summary.json',dict(indexed=len(rows),independent_acoustic_quality='NOT RUN',
        accuracy='NOT RUN',recall_at_k='NOT RUN',real_training='NOT RUN',new_audio_download_bytes=0,audio_published=False))
    usage=resource.getrusage(resource.RUSAGE_SELF)
    write_new(args.out/'resources.json',dict(cpu_seconds_including_imports=usage.ru_utime+usage.ru_stime,
        wall_seconds_after_imports=time.perf_counter()-started,peak_rss_mib=usage.ru_maxrss/1024,
        hard_cpu_limit_seconds=540,hard_virtual_limit_mib=1024,compute_threads=2,gpu=False,
        python=platform.python_version(),versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','librosa','soundfile','numba')},
        new_audio_download_bytes=0,network_in_study_bytes=0,
        infrastructure='Separate new environment installed from unchanged requirements.lock; nonzero package traffic'))
    write_new(args.out/'hashes.json',{p.name:file_hash(p) for p in sorted(args.out.glob('*.json'))})
    total=sum(p.stat().st_size for p in args.out.iterdir());require(total<=2*1024**2,'Artifact budget exceeded')
    print('COMPLETE; numerical bytes='+str(total))
    return 0


if __name__=='__main__':raise SystemExit(main())

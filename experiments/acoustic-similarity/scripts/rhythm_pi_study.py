"""One bounded, offline PI-v1 search on the ten hash-pinned PR9 windows."""
import argparse
import importlib.metadata
import json
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

from acoustic_similarity.data import digest, file_hash, read_json, require, validate_manifest, write_new
from acoustic_similarity.model import distances, vectors
from acoustic_similarity.rhythm_pi import FEATURE_SCHEMA, POLICY, distance, extract, search

ROOT=Path(__file__).resolve().parents[1]
MANIFEST_SHA='24ce999d2b1175640ad4ae73e0d1c487a8fa80cc2ca5581819f391e0a29a0b1e'
DSP_INDEX_SHA='9055df4ac720fa5c3ca83ff69c363bd7e33e1962cab40cb64cd642aa6ef1152f'
BASE_HEAD='c9ca0bfd87fd9bbc12f42aa27eacdd66963c3dfa'


def preflight(manifest_path,index_path):
    require(file_hash(manifest_path)==MANIFEST_SHA,'Unapproved manifest/windows')
    require(file_hash(index_path)==DSP_INDEX_SHA,'Unexpected historical DSP index')
    manifest=read_json(manifest_path)
    tracks=validate_manifest(manifest,purpose='analysis',verify_files=True)
    require(len(tracks)==10 and all(t['seconds']==15 and t['split']=='diagnostic' and
            t['rights']['license']=='CC0-1.0' and not t['rights']['training'] and
            not t['rights']['remote'] for t in tracks.values()),'Unexpected authorized scope')
    index=read_json(index_path)
    bank,rows=vectors(index,manifest)
    return manifest,tracks,bank,rows


def review_cases(rankings,dsp):
    """Informative sample only; selection is not a label or a quality estimate."""
    cases=[]; seen=set()
    def add(anchor,a,b,reason):
        key=(anchor,*sorted((a,b)))
        if a==b or key in seen:return
        seen.add(key); cases.append(dict(anchor=anchor,candidates=[a,b],selection=reason))
    for anchor,ranks in sorted(rankings.items()):
        first=ranks[0]['id']; old=dsp[anchor][0]
        add(anchor,first,old if old!=first else ranks[1]['id'],
            'PI/DSP first-neighbor disagreement' if old!=first else 'PI nearest alternatives')
    for anchor,ranks in sorted(rankings.items(),key=lambda item:item[1][1]['distance']-item[1][0]['distance']):
        if len(cases)>=12:break
        add(anchor,ranks[0]['id'],ranks[1]['id'],'small PI first/second margin')
    rng=np.random.default_rng(20261014)
    for i,row in enumerate(cases):
        if rng.integers(2):row['candidates'].reverse()
        row['case_id']=f'r{i+1:02}'
        row['answer']=None
    return dict(status='NOT RUN',unique_comparisons=len(cases),planned_blind_repeats=2,
                protocol='RHYTHM_PI_REVIEW.md',cases=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--dsp-index',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    require(not args.out.exists(),'Create-only output required')
    require(all(os.environ.get(k)=='2' for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','NUMBA_NUM_THREADS')),
            'Exactly two configured compute threads required')
    resource.setrlimit(resource.RLIMIT_CPU,(540,540))
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    def offline(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto'):
            raise RuntimeError('Study is offline')
    sys.addaudithook(offline)
    started=time.perf_counter()
    try:
        manifest,tracks,bank,old_rows=preflight(args.manifest,args.dsp_index)
    except (OSError,ValueError):
        write_new(args.out/'status.json',dict(status='BLOCKED',reason='Approved local inputs absent or hash mismatch',
                                            audio_decoded=False,new_audio_download_bytes=0))
        return 2
    source_files=['acoustic_similarity/rhythm_pi.py','acoustic_similarity/rhythm_auto.py',
                  'acoustic_similarity/rhythm_v2.py','scripts/rhythm_pi_study.py','tests/test_rhythm_pi.py',
                  'RHYTHM_PI_SPEC.md']
    write_new(args.out/'frozen.json',dict(feature_schema=FEATURE_SCHEMA,policy=POLICY,base_head=BASE_HEAD,
        code_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        manifest_sha256=MANIFEST_SHA,dsp_index_sha256=DSP_INDEX_SHA,
        code_sha256={p:file_hash(ROOT/p) for p in source_files},
        order='Saved before decoding and before any real pairwise comparison',
        input_hash_checks='PASS: all ten audio files and evidence snapshots'))
    fixture=runpy.run_path(str(ROOT/'tests/test_rhythm_pi.py'))
    test_class=fixture['PhaseIndependentTests']
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(test_class))
    require(result.wasSuccessful(),'Synthetic mechanics failed; real study not run')
    write_new(args.out/'synthetic.json',dict(status='PASS',tests=result.testsRun,measurements=test_class.measurements))
    reports=[]
    for t in tracks.values():
        with sf.SoundFile(t['path']) as audio:
            require(audio.channels in (1,2),'Unexpected channels')
            sr=audio.samplerate;start=round(t['start']*sr);count=round(t['seconds']*sr)
            audio.seek(start);y=audio.read(count,dtype='float64',always_2d=True).mean(axis=1)
        require(len(y)==count,'Incomplete approved window')
        row=dict(extract(y,sr),id=t['id'],title=t['rights']['attribution'].split(' — ')[0],
                 recording_group=t['recording_group'],audio_sha256=t['sha256'],
                 evidence_sha256=t['rights']['evidence_sha256'],source_url=t['rights']['source_url'],
                 sample_rate=sr,start_sample=start,end_sample_exclusive=start+count,
                 start_seconds_requested=t['start'],start_seconds_actual=start/sr,seconds=count/sr)
        reports.append(row)
        print(json.dumps(dict(id=t['id'],status=row['status'])),flush=True)
    index=dict(feature_schema=FEATURE_SCHEMA,dataset_sha256=digest(manifest),tracks=reports)
    write_new(args.out/'index.json',index)
    eligible=[r for r in reports if r['status']=='INDEXED_UNVERIFIED']
    rankings={r['id']:search(r['id'],reports,9) for r in eligible}
    symmetry_error=max((abs(distance(a,b)['distance']-distance(b,a)['distance'])
                        for a in eligible for b in eligible),default=0.)
    require(symmetry_error<1e-12,'Asymmetric distance')
    dsp={a:sorted((b for b in tracks if b!=a and tracks[b]['recording_group']!=tracks[a]['recording_group']),
                 key=lambda b:(distances(a,b,old_rows,bank)['rhythm'],b)) for a in rankings}
    comparison={a:dict(pi_top3=[r['id'] for r in ranks[:3]],dsp_rhythm_top3=dsp[a][:3],
                      common_top3=len({r['id'] for r in ranks[:3]}&set(dsp[a][:3])),
                      first_second_margin=ranks[1]['distance']-ranks[0]['distance'])
                for a,ranks in rankings.items() if len(ranks)>=3}
    write_new(args.out/'retrieval.json',dict(rankings=rankings,dsp_comparison=comparison,
        comparison_scope='Old DSP rhythm component only, uniform weights; rank overlap is NOT accuracy',
        maximum_symmetry_error=symmetry_error))
    if len(rankings)==10 and all(len(r)>=3 for r in rankings.values()):
        write_new(args.out/'review-cases.json',review_cases(rankings,dsp))
    write_new(args.out/'summary.json',dict(records=len(reports),indexed=len(eligible),
        abstained=len(reports)-len(eligible),tempo_unknown=sum(r['diagnostics']['tempo_status']=='UNKNOWN' for r in eligible),
        real_accuracy='NOT RUN',real_recall='NOT RUN',independent_rhythm_similarity='NOT RUN',
        learned_weights='NOT RUN',audio_published=False,new_audio_download_bytes=0))
    usage=resource.getrusage(resource.RUSAGE_SELF)
    write_new(args.out/'resources.json',dict(wall_seconds_after_imports=time.perf_counter()-started,
        cpu_seconds_including_imports=usage.ru_utime+usage.ru_stime,peak_rss_mib=usage.ru_maxrss/1024,
        hard_cpu_limit_seconds=540,hard_virtual_limit_mib=1024,compute_threads=2,
        python=platform.python_version(),versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','soundfile')},
        audio_download_bytes=0,network_in_study_bytes=0,new_dependencies_downloaded=False,gpu=False))
    write_new(args.out/'hashes.json',{p.name:file_hash(p) for p in sorted(args.out.glob('*.json'))})
    total=sum(p.stat().st_size for p in args.out.iterdir())
    require(total<=2*1024**2,'Numerical artifact cap exceeded')
    print(json.dumps(dict(status='COMPLETE',numerical_artifact_bytes=total)))
    return 0


if __name__=='__main__':raise SystemExit(main())

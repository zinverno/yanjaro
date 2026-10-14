"""Bounded offline applicability audit of the exact ten existing PR9 windows."""
import argparse
from collections import Counter
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
from unittest.mock import patch

import numpy as np
import soundfile as sf

from acoustic_similarity.data import file_hash, require, validate_manifest, write_new
from acoustic_similarity.rhythm_auto import (POLICY, SCHEMA, analyze_attacks, energy_candidates,
                                             grid_support, phase_offset, tempo_candidates)
from acoustic_similarity.rhythm_v2 import spectral_attacks

MANIFEST_SHA = '24ce999d2b1175640ad4ae73e0d1c487a8fa80cc2ca5581819f391e0a29a0b1e'
BASE_HEAD = 'd039093b09cf7a8f79d47238e855bbd911bb6068'
ROOT = Path(__file__).resolve().parents[1]


def preflight(path):
    require(file_hash(path)==MANIFEST_SHA,'Unapproved manifest or windows')
    tracks=validate_manifest(json.loads(Path(path).read_text()),purpose='analysis',verify_files=True)
    require(len(tracks)==10 and all(t['seconds']==15 and t['split']=='diagnostic' and
            t['rights']['license']=='CC0-1.0' and t['rights']['training'] is False and
            t['rights']['remote'] is False for t in tracks.values()),'Unexpected scope')
    return tracks


def audit_track(track):
    with sf.SoundFile(track['path']) as audio:
        require(audio.channels in (1,2),'Unexpected channels')
        sr=audio.samplerate;start=round(track['start']*sr);count=round(track['seconds']*sr)
        audio.seek(start)
        channels=audio.read(count,dtype='float64',always_2d=True)
    require(len(channels)==count,'Incomplete approved window')
    y=channels.mean(axis=1)
    mono_ratio=float(np.mean(y*y)/max(float(np.mean(channels*channels)),1e-12))
    attacks=spectral_attacks(y,sr)
    times=attacks['samples']/sr
    report=analyze_attacks(times,attacks['strengths'],count/sr,start/sr)
    energy=energy_candidates(y,sr)
    energy=energy[(energy>=.032)&(energy<count/sr-.032)]
    interior=np.asarray(report['attack_seconds_absolute'])-start/sr
    distance=np.abs(interior[:,None]-energy) if len(interior) and len(energy) else np.empty((0,0))
    report.update({'id':track['id'],'title':track['rights']['attribution'].split(' — ')[0],
        'source_url':track['rights']['source_url'],'audio_sha256':track['sha256'],
        'evidence_sha256':track['rights']['evidence_sha256'],'sample_rate':sr,
        'window_start_sample':start,'window_end_sample_exclusive':start+count,
        'window_start_seconds_requested':track['start'],'window_start_seconds_actual':start/sr,
        'window_seconds':count/sr,'mono_to_channel_mean_energy_ratio':mono_ratio,
        'energy_detector_comparison':{'energy_candidates':len(energy),
            'flux_without_energy_within_20ms':int((distance.min(axis=1)>.02).sum()) if distance.size else len(interior),
            'energy_without_flux_within_20ms':int((distance.min(axis=0)>.02).sum()) if distance.size else len(energy),
            'interpretation':'Detector disagreement, NOT false positives/negatives or precision/recall'},
        'independent_bpm_evidence':None,'independent_downbeat_evidence':None})
    if track['id']=='o02':
        # The author tag is diagnostic metadata, never an estimator input or phase label.
        require('129bpm' in Path(track['rights']['evidence_path']).read_text(),'Expected saved author tag missing')
        mask=(times>=.032)&(times<count/sr-.032)
        t=times[mask];w=attacks['strengths'][mask].sum(axis=1)
        _,ac=tempo_candidates(t,w,15)
        probes=[]
        for bpm in (86.,129.):
            offset=phase_offset(t,w,60/bpm)
            probes.append({'bpm':bpm,'ac_score':float(np.interp(60/bpm/.005,np.arange(len(ac)),ac)),
                           **grid_support(t,w,bpm,offset,15)})
        report['independent_bpm_evidence']={'type':'saved author tag','bpm':129,
            'precision':None,'beat_unit':None,'phase':None,'sufficient_for_v2':False}
        report['o02_fixed_diagnostic_probes']=probes
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    require(not args.out.exists(),'Create-only output required')
    require(all(os.environ.get(v)=='2' for v in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','NUMBA_NUM_THREADS')),
            'Exactly two configured compute threads required')
    resource.setrlimit(resource.RLIMIT_CPU,(540,540))
    # Virtual cap is stricter than the requested RSS bound on this Linux runner.
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    def offline(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto'):
            raise RuntimeError('Audit is offline')
    sys.addaudithook(offline)
    started=time.perf_counter()
    try:
        tracks=preflight(args.manifest)
    except (FileNotFoundError,ValueError):
        write_new(args.out/'status.json',{'status':'BLOCKED','reason':'Local approved files/evidence unavailable or hashes differ',
                                        'audio_download_bytes':0,'audio_decoded':False})
        raise SystemExit(2)
    write_new(args.out/'policy.json',{'schema':SCHEMA,'base_head':BASE_HEAD,'policy':POLICY,
              'manifest_sha256':MANIFEST_SHA,'strict_v2':'VERIFIED only; no independent phase evidence supplied',
              'code_sha256':{p:file_hash(ROOT/p) for p in ('acoustic_similarity/rhythm_auto.py','scripts/rhythm_auto_audit.py')},
              'audio_and_evidence_hashes':'PASS before decoding','threshold_selection':'Fixed before this real-data audit'})
    reports=[]
    with patch('acoustic_similarity.rhythm_v2.extract_bar',side_effect=AssertionError('No independent verification')):
        for track in tracks.values():
            report=audit_track(track);reports.append(report)
            write_new(args.out/(track['id']+'.json'),report)
            print(json.dumps({'id':track['id'],'status':report['status'],'bpm':report.get('estimated_bpm')}),flush=True)
    counts=Counter(r['status'] for r in reports)
    write_new(args.out/'summary.json',{'records':len(reports),'statuses':dict(counts),
        'stable_automatic_hypotheses':sum(r['stable_automatic_hypothesis'] for r in reports),
        'verified':0,'strict_v2_extractions':0,'strict_gate_abstentions':len(reports),
        'reason_counts':dict(Counter(reason for r in reports for reason in r['reasons'])),
        'new_audio_download_bytes':0,'real_training':'NOT RUN','audio_published':False})
    usage=resource.getrusage(resource.RUSAGE_SELF)
    write_new(args.out/'resources.json',{'wall_seconds_after_imports':time.perf_counter()-started,
        'cpu_seconds_including_imports':usage.ru_utime+usage.ru_stime,'peak_rss_mib':usage.ru_maxrss/1024,
        'hard_cpu_limit_seconds':540,'hard_virtual_limit_mib':1024,'compute_threads':2,
        'python':platform.python_version(),'versions':{p:importlib.metadata.version(p) for p in ('numpy','scipy','soundfile')},
        'network_bytes_in_audit':0,'gpu':False})
    write_new(args.out/'hashes.json',{p.name:file_hash(p) for p in sorted(args.out.glob('*.json'))})
    total=sum(p.stat().st_size for p in args.out.iterdir())
    require(total<=2*1024**2,'Numerical artifact cap exceeded')
    print(json.dumps({'artifacts_bytes':total,'status':'COMPLETE; hypotheses are not verified rhythm-v2 inputs'}))


if __name__=='__main__':main()

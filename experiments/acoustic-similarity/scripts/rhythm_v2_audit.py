"""Offline v2 diagnostics: synthetic truth, immutable development cache, opt-in local CC0."""
import argparse
from collections import Counter
import json
from pathlib import Path
import resource
import sys
import time
import zipfile

import numpy as np
from scipy import signal
import soundfile as sf

from acoustic_similarity.data import file_hash, require, validate_manifest, write_new
from acoustic_similarity.diagnostics import ARTIFACT_SHA, components, development_only
from acoustic_similarity.rhythm import rhythm_features, validate_dataset
from acoustic_similarity.rhythm_v2 import FEATURE_SCHEMA, equal_blocks, extract_bar, sample_bounds, spectral_attacks

ROOT = Path(__file__).resolve().parents[1]


def counts(margins):
    v = np.asarray(margins)
    ties = int((np.abs(v)<=1e-12).sum())
    correct = int((v < -1e-12).sum())
    return {"n":len(v),"correct":correct,"incorrect":len(v)-correct-ties,"ties":ties,
            "accuracy":(correct+.5*ties)/len(v)}


def summary(values):
    values = np.asarray(values)
    return {"min":float(values.min()),"mean":float(values.mean()),"max":float(values.max())}


def cached_development():
    archive = ROOT/'validation/groove-cpu-v1/artifacts.zip'
    require(file_hash(archive)==ARTIFACT_SHA,"Historical source hash changed")
    with zipfile.ZipFile(archive) as z:
        dev = development_only(json.loads(z.read('dataset.json')))
    return analyze_cache(dev)


def analyze_cache(dev):
    require(all(r['split'] in ('train','validation') for r in dev['rows']) and
            all(t['split'] in ('train','validation') for t in dev['triplets']),"Held-out data forbidden")
    validate_dataset(dev)
    groups = components(dev['rows'],dev['triplets'])
    result = {"input_sha256":ARTIFACT_SHA,"kind":"CACHE-ONLY DIAGNOSTIC; NOT RE-EXTRACTED V2",
              "true_v2_uniform_comparison":"NOT RUN: original GMD WAV unavailable locally",
              "learned_v2":"NOT RUN; not authorized","held_out_evaluation":"NOT RUN",
              "splits":{}}
    for split in ('train','validation'):
        rows = [r for r in dev['rows'] if r['split']==split]
        trips = [t for t in dev['triplets'] if t['split']==split]
        vectors = {r['id']:np.asarray(r['features']) for r in rows}
        balanced = {k:np.asarray(equal_blocks(v)) for k,v in vectors.items()}
        def margins(bank):
            return np.array([np.mean((bank[t['anchor']]-bank[t['positive']])**2)-
                             np.mean((bank[t['anchor']]-bank[t['negative']])**2) for t in trips])
        old,new = margins(vectors),margins(balanced)
        norms = np.linalg.norm(np.array([r['features'] for r in rows]).reshape(-1,2,64),axis=2)
        zero_corr, best_shifts, energy, occupied = [],[],[],[]
        for r in rows:
            a = np.asarray(r['features'][:64]).reshape(4,16).sum(axis=0)
            t = np.asarray(r['target']).reshape(9,16).sum(axis=0)
            energy.append(a / max(a.sum(),1e-12)); occupied.append(t>0)
            a,t = a-a.mean(),t-t.mean(); norm=np.linalg.norm(a)*np.linalg.norm(t)
            correlations=[float(a@np.roll(t,k)/norm) if norm>1e-12 else 0 for k in range(16)]
            zero_corr.append(correlations[0]); best_shifts.append(int(np.argmax(correlations)))
        group_results=[]
        for component in sorted({groups[t['anchor']] for t in trips}):
            mask=np.array([groups[t['anchor']]==component for t in trips])
            group_results.append({'component':component,'v1_uniform':counts(old[mask]),
                                  'cached_equal_blocks_uniform':counts(new[mask])})
        aliases=0
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                if a['bpm']!=b['bpm'] or a['drummer']!=b['drummer']: continue
                x,y=(np.asarray(r['target']).reshape(9,16) for r in (a,b))
                aliases += int(np.array_equal(x.any(axis=0),y.any(axis=0)) and not np.array_equal(x,y))
        result['splits'][split]={'bars':len(rows),'originals':len({r['original_id'] for r in rows}),
            'v1_uniform':counts(old),'cached_equal_blocks_uniform':counts(new),
            'delta_percentage_points':100*(counts(new)['accuracy']-counts(old)['accuracy']),
            'correct_to_incorrect':int(((old < -1e-12)&(new > 1e-12)).sum()),
            'incorrect_to_correct':int(((old > 1e-12)&(new < -1e-12)).sum()),
            'block_norms':{'flux':summary(norms[:,0]),'ac':summary(norms[:,1])},
            'audio_phase_mass_mean':np.mean(energy,axis=0).tolist(),
            'midi_phase_occupancy_mean':np.mean(occupied,axis=0).tolist(),
            'audio_midi_zero_shift_correlation':summary(zero_corr),
            'diagnostic_best_shift_histogram':dict(sorted(Counter(best_shifts).items())),
            'shift_warning':'Diagnostic upper bound only; not an inferred alignment or correction',
            'same_temporal_occupancy_different_drum_target_pairs':aliases,'components':group_results}
    return result


def synthetic():
    initial=[]
    for sample in (0,1,64,128,8000):
        y=np.zeros(32000);y[sample]=1
        old=np.array(rhythm_features(y,16000,120))
        new=extract_bar(y,16000,120,start_beat=0,beat_zero_seconds=0,phase_uncertainty_beats=0)
        initial.append({'known_sample':sample,'v1_flux_norm':float(np.linalg.norm(old[:64])),
                        'v2_detected_samples':new['attack_samples'],
                        'v2_flux_norm':float(np.linalg.norm(new['features'][:64]))})
    f,t,z=signal.stft(np.eye(1,32000,8000)[0],fs=16000,nperseg=512,noverlap=384,boundary='zeros',padded=False)
    flux=np.maximum(np.diff(np.abs(z),axis=1,prepend=np.abs(z[:,:1])),0).sum(axis=0)
    first=next((sr,bpm,b) for sr in (8000,16000,44100,48000) for bpm in range(40,261)
               for b in (4,8,12,16) if round(b*60/bpm*sr)+round(4*60/bpm*sr)!=round((b+4)*60/bpm*sr))
    sr,bpm,b=first
    jitters=[]
    for bpm in (60,120,200,260):
        beats=np.array([.5,1.25,2.25,3.5]); origin=.1
        def get(jitter):
            y=np.zeros(round((4*60/bpm+.2)*16000))
            y[np.rint((origin+beats*60/bpm+jitter)*16000).astype(int)]=1
            return np.array(extract_bar(y,16000,bpm,start_beat=0,beat_zero_seconds=origin,
                                       phase_uncertainty_beats=0)['features'])
        baseline=get(np.zeros(4))
        for milliseconds in (1,5,10):
            delta=get(np.array([-1,1,-1,1])*milliseconds/1000)-baseline
            jitters.append({'bpm':bpm,'independent_jitter_ms':milliseconds,
                            'flux_l2':float(np.linalg.norm(delta[:64])),
                            'ac_l2':float(np.linalg.norm(delta[64:])),
                            'full_l2':float(np.linalg.norm(delta))})
    phases=[]
    for phase in range(16):
        y=np.zeros(32000);y[phase*2000]=1
        old=np.array(rhythm_features(y,16000,120)[:64]).reshape(4,16)
        new=extract_bar(y,16000,120,start_beat=0,beat_zero_seconds=0,phase_uncertainty_beats=0)
        phases.append({'known_phase':phase,'v1_flux_norm':float(np.linalg.norm(old)),
                       'v1_argmax_phases':old.argmax(axis=1).tolist() if old.any() else None,
                       'v2_samples':new['attack_samples'],
                       'v2_argmax_phases':np.array(new['features'][:64]).reshape(4,16).argmax(axis=1).tolist()})
    return {'kind':'CONTROLLED SYNTHETIC SIGNALS; NOT MUSIC QUALITY','initial_transient':initial,
            'all_sixteenth_phases':phases,'v1_stft':{'known_impulse_seconds':.5,'flux_peak_frame_center_seconds':float(t[flux.argmax()]),
            'nperseg':512,'hop':128,'sample_rate':16000},
            'rounding_counterexample':{'sr':sr,'bpm':first[1],'start_beat':b,
                'v1_end':round(b*60/first[1]*sr)+round(4*60/first[1]*sr),
                'v2_end':sample_bounds(sr,first[1],b,0,0)[1]},'independent_jitter':jitters}


def local_waveforms(path):
    manifest=json.loads(Path(path).read_text())
    tracks=validate_manifest(manifest,purpose='analysis',verify_files=True)
    require(len(tracks)==10 and all(t['split']=='diagnostic' and t['rights']['license']=='CC0-1.0'
            and t['rights']['remote'] is False and t['rights']['training'] is False for t in tracks.values()),
            'Only the previously authorized ten local diagnostic CC0 recordings')
    rows=[]
    for t in tracks.values():
        with sf.SoundFile(t['path']) as audio:
            require(audio.channels in (1,2),'Unexpected channels')
            audio.seek(round(t['start']*audio.samplerate))
            y=audio.read(round(t['seconds']*audio.samplerate),dtype='float64',always_2d=True).mean(axis=1)
            require(len(y)==round(t['seconds']*audio.samplerate),'Short authorized window')
            started=time.perf_counter(); attacks=spectral_attacks(y,audio.samplerate)
            offset=attacks['samples']/audio.samplerate-np.array(attacks['frame_center_seconds'])
            rows.append({'id':t['id'],'audio_sha256':t['sha256'],'evidence_sha256':t['rights']['evidence_sha256'],
                'source_url':t['rights']['source_url'],'attribution':t['rights']['attribution'],'license':'CC0-1.0',
                'artist_ids':t['artist_ids'],'original_bytes':Path(t['path']).stat().st_size,
                'original_duration_seconds':audio.frames/audio.samplerate,'analyzed_seconds':len(y)/audio.samplerate,
                'sample_rate':audio.samplerate,'candidate_attacks':len(attacks['samples']),
                'frame_to_refined_seconds':summary(offset) if len(offset) else None,
                'wall_seconds':time.perf_counter()-started,
                'phase_sensitive_features':'NOT RUN: no verified bar phase/tempo uncertainty',
                'onset_precision_recall':'NOT RUN: no independent onset labels'})
    return {'kind':'REAL LOCAL WAVEFORM DIAGNOSTICS; NOT TRAIN/VALIDATION QUALITY',
            'rights_and_hashes':'PASS','records':rows,'audio_published':False,'new_audio_download_bytes':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--local-manifest',type=Path)
    args=parser.parse_args()
    require(not args.out.exists(),'Create-only output directory required')
    def no_network(event, arguments):
        if event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
            raise RuntimeError('Offline audit forbids network')
    sys.addaudithook(no_network)
    started,cpu=time.perf_counter(),time.process_time()
    write_new(args.out/'synthetic.json',synthetic())
    write_new(args.out/'cached-development.json',cached_development())
    write_new(args.out/'local-waveforms.json',local_waveforms(args.local_manifest) if args.local_manifest else
              {'status':'NOT RUN: no explicit local manifest'})
    write_new(args.out/'resources.json',{'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,
              'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
              'network_bytes':0,'real_fits':0,'held_out_evaluations':0,'feature_schema':FEATURE_SCHEMA})
    write_new(args.out/'hashes.json',{p.name:file_hash(p) for p in sorted(args.out.glob('*.json'))})
    print(json.dumps({'output':str(args.out),'status':'PASS; real re-extracted GMD comparison NOT RUN'}))


if __name__=='__main__': main()

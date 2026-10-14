"""Untrained phase-independent point-process rhythm retrieval, separate from v1/v2."""
import numpy as np
from scipy.ndimage import gaussian_filter1d

from .data import require
from .rhythm_auto import tempo_candidates
from .rhythm_v2 import spectral_attacks

FEATURE_SCHEMA = 'onset-pairac128x4-ioi32-density2-tempo64.pi-v1'
POLICY = dict(edge_seconds=.032, minimum_events=8, band_relative_threshold=.2,
              pair_lag_seconds=[.04,4.], pair_bins=128, interval_log2_range=[-3.,3.],
              interval_bins=32, histogram_smoothing_bins=.75, tempo_bins=64,
              tempo_bpm_range=[40.,260.], tempo_max_candidates=4, tempo_min_ac=.1,
              tempo_octave_masses=[.25,.5,.25], density_scale_per_second=4.,
              dense_warning_per_second=12., missing_component_distance=.5,
              component_weights=dict(periodicity=.25,intervals=.25,density=.25,tempo=.25),
              score='100 * (1 - distance); NOT probability or validated similarity')
SHAPES = dict(periodicity=(4,128), intervals=(32,), density=(2,), tempo=(64,))


def histogram(values, weights, low, high, bins):
    """Log coordinates supplied by caller; linear assignment, then fixed smoothing."""
    result = np.zeros(bins)
    positions = (np.clip(values,low,high)-low)/(high-low)*(bins-1)
    left = np.floor(positions).astype(int); fraction = positions-left
    np.add.at(result,left,np.asarray(weights)*(1-fraction))
    np.add.at(result,np.minimum(left+1,bins-1),np.asarray(weights)*fraction)
    result = gaussian_filter1d(result,POLICY['histogram_smoothing_bins'],mode='nearest')
    return result/max(float(result.sum()),1e-12)


def describe_events(times, strengths, duration):
    """Only relative lags enter features; no BPM/phase/genre/title input."""
    t=np.asarray(times,dtype=float); w=np.asarray(strengths,dtype=float)
    require(np.isfinite(duration) and 10<=duration<=15 and t.ndim==1 and
            w.shape==(len(t),4) and len(t)<=1000 and np.isfinite(t).all() and
            np.isfinite(w).all() and (w>=0).all() and (t>=0).all() and
            (t<duration).all() and (np.diff(t)>0).all(),'Invalid bounded onset series')
    mask=(t>=POLICY['edge_seconds'])&(t<duration-POLICY['edge_seconds'])
    t,w=t[mask],w[mask]
    weights=w.sum(axis=1)
    strong=weights>=POLICY['band_relative_threshold']*max(float(weights.max(initial=0)),1e-12)
    diagnostics={'onsets':len(times),'interior_onsets':len(t),'strong_onsets':int(strong.sum()),
                 'downbeat':'UNKNOWN; not required','acoustic_quality':'UNVALIDATED',
                 'independent_similarity_labels':False}
    if strong.sum()<POLICY['minimum_events']:
        return dict(feature_schema=FEATURE_SCHEMA,status='ABSTAIN',blocks=None,
                    reasons=['INSUFFICIENT_EVENTS'],diagnostics=diagnostics)
    # Square root compression retains accents without letting one hit dominate all lags.
    w=np.sqrt(w/max(float(w.max()),1e-12))
    weights=np.sqrt(weights/max(float(weights.max()),1e-12))
    periodicity=[]; band_counts=[]
    for band in w.T:
        selected=band>=np.sqrt(POLICY['band_relative_threshold'])*max(float(band.max()),1e-12)
        bt,bw=t[selected],band[selected]; band_counts.append(len(bt))
        i,j=np.triu_indices(len(bt),1); lag=bt[j]-bt[i]
        valid=(lag>=.04)&(lag<=4.)
        # Positive-lag autocorrelation of weighted impulses, with finite-window correction.
        mass=bw[i[valid]]*bw[j[valid]]/(duration-lag[valid])
        periodicity.append(histogram(np.log2(lag[valid]),mass,np.log2(.04),2.,128))
    st,sw=t[strong],weights[strong]
    gaps=np.diff(st); median=float(np.median(gaps))
    intervals=histogram(np.log2(gaps/median),np.sqrt(sw[:-1]*sw[1:]),-3.,3.,32)
    rate=len(t)/duration
    effective=float(weights.sum()**2/max(float(weights@weights),1e-12)/duration)
    density=np.array([rate,effective]); density=density/(density+4.)
    # Canonical first-event origin also removes the rasterizer's arbitrary time origin.
    candidates,_=tempo_candidates(st-st[0]+.032,sw,duration)
    candidates=[c for c in candidates if 40<=c['bpm']<=260 and c['ac_score']>=.1][:4]
    tempo=np.zeros(64); alternatives=[]
    for c in candidates:
        for factor,mass in zip((.5,1.,2.),(.25,.5,.25)):
            bpm=c['bpm']*factor
            if 40<=bpm<=260:
                alternatives.append((bpm,c['ac_score']*mass))
    if alternatives:
        bpm,mass=np.asarray(alternatives).T
        tempo=histogram(np.log2(bpm),mass,np.log2(40),np.log2(260),64)
    reasons=['NO_INDEPENDENT_RHYTHM_LABELS']
    if not candidates: reasons.append('UNKNOWN_TEMPO')
    if len(candidates)>1: reasons.append('MULTIPLE_TEMPO_HYPOTHESES')
    if rate>12: reasons.append('DENSE_DETECTOR_OUTPUT_NOT_CONFIDENCE')
    if min(band_counts)<3: reasons.append('SPARSE_SPECTRAL_BAND')
    diagnostics.update(band_events=band_counts,event_rate=rate,effective_event_rate=effective,
                       median_ioi_seconds=median,tempo_candidates=candidates,
                       tempo_status='AUTO_CANDIDATE' if candidates else 'UNKNOWN',
                       tempo_alternatives_bpm=[float(b) for b,_ in alternatives])
    blocks=dict(periodicity=np.asarray(periodicity).tolist(),intervals=intervals.tolist(),
                density=density.tolist(),tempo=tempo.tolist())
    return dict(feature_schema=FEATURE_SCHEMA,status='INDEXED_UNVERIFIED',blocks=blocks,
                reasons=reasons,diagnostics=diagnostics)


def extract(y,sr):
    y=np.asarray(y,dtype=float)
    require(type(sr) is int and 8000<=sr<=96000 and y.ndim==1 and
            10*sr<=len(y)<=15*sr and np.isfinite(y).all(),'Invalid audio window')
    if np.max(np.abs(y))<=1e-5:
        return describe_events([],np.empty((0,4)),len(y)/sr)
    attacks=spectral_attacks(y,sr)
    return describe_events(attacks['samples']/sr,attacks['strengths'],len(y)/sr)


def validate(row):
    require(row.get('feature_schema')==FEATURE_SCHEMA and row.get('status')=='INDEXED_UNVERIFIED',
            'Incompatible or abstained descriptor')
    arrays={}
    for name,shape in SHAPES.items():
        value=np.asarray(row['blocks'][name],dtype=float)
        require(value.shape==shape and np.isfinite(value).all() and
                (value>=0).all() and (value<=1+1e-10).all(),'Invalid descriptor block')
        if name!='density':
            sums=value.sum(axis=-1)
            require(np.all(np.isclose(sums,0,atol=1e-10)|np.isclose(sums,1,atol=1e-10)),
                    'Unnormalized descriptor block')
        arrays[name]=value
    return arrays


def hellinger(a,b):
    if a.sum()<1e-12 or b.sum()<1e-12:
        return POLICY['missing_component_distance']
    return float(np.sqrt(np.sum((np.sqrt(a)-np.sqrt(b))**2)/2))


def distance(a,b):
    """Symmetric bounded dissimilarity; neutral missing evidence is not a metric."""
    a,b=validate(a),validate(b)
    raw=dict(periodicity=float(np.mean([hellinger(x,y) for x,y in zip(a['periodicity'],b['periodicity'])])),
             intervals=hellinger(a['intervals'],b['intervals']),
             density=float(np.mean(np.abs(a['density']-b['density']))),
             tempo=hellinger(a['tempo'],b['tempo']))
    contributions={k:float(v*POLICY['component_weights'][k]) for k,v in raw.items()}
    total=sum(contributions.values())
    return dict(distance=total,score=100*(1-total),contributions=contributions,
                quality='UNVALIDATED',unknown_tempo=bool(a['tempo'].sum()==0 or b['tempo'].sum()==0))


def search(query_id,rows,top=3):
    require(type(top) is int and 1<=top<=100,'Invalid top')
    require(len({r['id'] for r in rows})==len(rows),'Duplicate record IDs')
    lookup={r['id']:r for r in rows}
    require(query_id in lookup,'Unknown query')
    query=lookup[query_id]
    validate(query)
    results=[]
    for row in rows:
        # Exclude aliases/crops of the same source, not only the query row.
        if row['id']==query_id or row['audio_sha256']==query['audio_sha256'] or row['recording_group']==query['recording_group']:
            continue
        if row['status']=='INDEXED_UNVERIFIED':
            results.append(dict(id=row['id'],**distance(query,row)))
    return sorted(results,key=lambda r:(r['distance'],r['id']))[:top]


def main():
    import argparse
    import json
    from .data import read_json
    parser=argparse.ArgumentParser(description='Offline search of a saved PI-v1 index; score is unvalidated')
    parser.add_argument('--index',required=True)
    parser.add_argument('--query',required=True)
    args=parser.parse_args()
    index=read_json(args.index)
    require(index.get('feature_schema')==FEATURE_SCHEMA,'Wrong index version')
    print(json.dumps(search(args.query,index['tracks']),indent=2,allow_nan=False))


if __name__=='__main__':main()

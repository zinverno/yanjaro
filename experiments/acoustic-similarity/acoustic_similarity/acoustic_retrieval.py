"""Untrained common-coverage retrieval; missing data never receives a distance."""
import numpy as np

from .data import is_hash, require
from .rhythm_pi import FEATURE_SCHEMA as PI_SCHEMA, validate as validate_pi

FEATURE_SCHEMA='pi610-lab-timbre85-energy10.acoustic-v1'
DISTANCE_SCHEMA='hellinger-rms-equal-aspects.acoustic-v1'
MISSING_POLICY='common-mask-coverage-first.v1'
NAMES=tuple(f'periodicity_{i}' for i in range(4))+('intervals','density','tempo','timbre','energy')
SHAPES=dict(zip(NAMES,(128,128,128,128,32,2,64,85,10)))
PROFILES={'acoustic':dict(zip(NAMES,(1,1,1,1,4,4,12,12,12))),
          'pi_coverage_v2':dict(zip(NAMES[:7],(1,1,1,1,4,4,4)))}
POLICY=dict(missing_policy=MISSING_POLICY,profiles=PROFILES,
            normalization='PI unit-mass histograms; DSP fixed scales / 3; no fitted statistics',
            order='descending common weight, fixed availability mask, common distance, ID',
            mask_order=list(NAMES),near_tie_distance=.005,
            perturbation=dict(seeds=[0,1,2,3,4],histogram_replacement_mass=.01,coordinate_delta=.005),
            quality='UNVALIDATED; coverage is availability, not correctness')


def combine(pi,dsp):
    """Join existing descriptors only; old DSP rhythm/BPM never enters this schema."""
    require(pi['id']==dsp['id'] and pi['audio_sha256']==dsp['sha256'],'Source identity mismatch')
    require(pi.get('feature_schema')==PI_SCHEMA,'Incompatible PI source')
    if pi.get('status')=='ABSTAIN':
        require(pi.get('blocks') is None and bool(pi.get('reasons')),'Invalid PI abstention')
        blocks=dict.fromkeys(NAMES[:7])
    else:
        p=validate_pi(pi)
        blocks={f'periodicity_{i}':v.tolist() if v.sum()>0 else None for i,v in enumerate(p['periodicity'])}
        blocks.update({k:p[k].tolist() if k=='density' or p[k].sum()>0 else None
                       for k in ('intervals','density','tempo')})
    for k in ('timbre','energy'):
        v=np.asarray(dsp['vectors'][k],dtype=float)
        require(v.shape==(SHAPES[k],) and np.isfinite(v).all() and (np.abs(v)<=3).all(),'Invalid DSP block')
        blocks[k]=(v/3).tolist()
    row={k:pi[k] for k in ('id','audio_sha256','recording_group','title','evidence_sha256',
                            'sample_rate','start_sample','end_sample_exclusive')}
    row.update(feature_schema=FEATURE_SCHEMA,blocks=blocks,
               missing_reasons={k:'PI_ABSTAIN' if pi['status']=='ABSTAIN' else
                                'NO_QUALIFYING_TEMPO_PEAK' if k=='tempo' else 'NO_HISTOGRAM_MASS'
                                for k,v in blocks.items() if v is None},
               tempo_hypotheses=pi['diagnostics'].get('tempo_candidates',[]),downbeat='UNKNOWN; unused')
    validate(row)
    return row


def validate(row):
    require(row.get('feature_schema')==FEATURE_SCHEMA,'Incompatible feature schema')
    require(isinstance(row.get('id'),str) and row['id'] and is_hash(row.get('audio_sha256')) and
            isinstance(row.get('recording_group'),str) and row['recording_group'],'Invalid identity')
    require(isinstance(row.get('blocks'),dict) and set(row['blocks'])==set(NAMES),'Wrong feature blocks')
    arrays={}
    for k,n in SHAPES.items():
        v=row['blocks'][k]
        if v is None:
            require(bool(row.get('missing_reasons',{}).get(k)),'Missing reason required')
            arrays[k]=None
            continue
        v=np.asarray(v,dtype=float)
        lower=-1 if k in ('timbre','energy') else 0
        require(v.shape==(n,) and np.isfinite(v).all() and (v>=lower).all() and (v<=1).all(),
                'Invalid normalized block: '+k)
        if k not in ('density','timbre','energy'):
            require(abs(float(v.sum())-1)<1e-9,'Histogram must have unit mass; unknown must be null')
        arrays[k]=v
    return arrays


def compare(a,b,profile='acoustic'):
    require(profile in PROFILES,'Unknown distance profile')
    x,y=validate(a),validate(b)
    units=PROFILES[profile]; total=sum(units.values())
    values={}; missing={}; reasons={}; mask=''; contributions={}
    for k,u in units.items():
        shared=x[k] is not None and y[k] is not None
        mask+='1' if shared else '0'
        if not shared:
            values[k]=None
            missing[k]=sorted([r['id'] for r,v in ((a,x[k]),(b,y[k])) if v is None])
            reasons[k]={r['id']:r['missing_reasons'][k] for r in sorted((a,b),key=lambda r:r['id'])
                        if r['blocks'][k] is None}
            contributions[k]=None
        else:
            if k in ('timbre','energy'): d=float(np.sqrt(np.mean(((x[k]-y[k])/2)**2)))
            elif k=='density': d=float(np.mean(np.abs(x[k]-y[k])))
            else: d=float(np.sqrt(np.sum((np.sqrt(x[k])-np.sqrt(y[k]))**2)/2))
            values[k]=d; contributions[k]=u/total*d
    common=sum(u for k,u in units.items() if values[k] is not None)
    numerator=sum(v for v in contributions.values() if v is not None)
    distance=numerator/(common/total) if common else None
    aspects={}
    for name,keys in dict(rhythm=NAMES[:6],tempo=('tempo',),timbre=('timbre',),energy=('energy',)).items():
        keys=[k for k in keys if k in units]
        if not keys:continue
        available=[k for k in keys if values[k] is not None]
        mass=sum(units[k] for k in available); possible=sum(units[k] for k in keys)
        aspects[name]=dict(distance=sum(units[k]*values[k] for k in available)/mass if mass else None,
            coverage=mass/possible,weighted_contribution=sum(contributions[k] for k in available) if mass else None,
            status='AVAILABLE_UNVERIFIED' if mass==possible else 'PARTIAL' if mass else 'MISSING')
    return dict(distance_schema=DISTANCE_SCHEMA,missing_policy=MISSING_POLICY,profile=profile,
                common_units=common,total_units=total,coverage=common/total,coverage_mask=mask,
                common_distance=distance,conditional_score=100*(1-distance) if distance is not None else None,
                weighted_numerator=numerator if common else None,components=aspects,
                atomic_distances=values,missing=missing,missing_reasons=reasons,
                status='COMPARABLE' if common else 'ABSTAIN',quality='UNVALIDATED')


def rank_key(result):
    return (-result['common_units'],tuple(c=='0' for c in result['coverage_mask']),
            result['common_distance'],result['id'])


def search(query_id,rows,top=3,profile='acoustic'):
    require(type(top) is int and 1<=top<=100,'Invalid top')
    require(len({r['id'] for r in rows})==len(rows),'Duplicate IDs')
    lookup={r['id']:r for r in rows}; require(query_id in lookup,'Unknown query')
    for row in rows:validate(row)
    q=lookup[query_id]; results=[]; excluded=[]
    for row in rows:
        if row['id']==query_id or row['audio_sha256']==q['audio_sha256'] or row['recording_group']==q['recording_group']:
            continue
        result=dict(id=row['id'],**compare(q,row,profile))
        if result['status']=='ABSTAIN': excluded.append(dict(id=row['id'],reason='NO_COMMON_FEATURES'))
        else:results.append(result)
    results.sort(key=rank_key)
    previous=None;tier=0
    for i,r in enumerate(results):
        if r['coverage_mask']!=previous:tier+=1
        r.update(rank=i+1,coverage_tier=tier)
        previous=r['coverage_mask']
    return dict(query=query_id,profile=profile,results=results[:top],abstentions=excluded,
                score_scope='Compare conditional scores ONLY within identical coverage masks')


def perturb(rows,seed):
    """Frozen sensitivity diagnostic, not alternate parameter selection."""
    import copy
    rng=np.random.default_rng(seed); changed=copy.deepcopy(sorted(rows,key=lambda r:r['id']))
    for row in changed:
        for k in NAMES:
            v=row['blocks'][k]
            if v is None:continue
            v=np.asarray(v)
            if k in ('density','timbre','energy'):
                v=np.clip(v+rng.uniform(-.005,.005,len(v)),0 if k=='density' else -1,1)
            else:
                noise=rng.random(len(v));noise/=noise.sum()
                v=.99*v+.01*noise
            row['blocks'][k]=v.tolist()
    return changed


def main():
    import argparse
    import json
    from .data import read_json
    parser=argparse.ArgumentParser(description='Local acoustic search; coverage strata precede distance')
    parser.add_argument('--index',required=True)
    parser.add_argument('--query',required=True)
    parser.add_argument('--profile',choices=PROFILES,default='acoustic')
    args=parser.parse_args();index=read_json(args.index)
    require(index.get('feature_schema')==FEATURE_SCHEMA and index.get('distance_schema')==DISTANCE_SCHEMA and
            index.get('missing_policy')==MISSING_POLICY,'Incompatible index contract')
    print(json.dumps(search(args.query,index['tracks'],profile=args.profile),indent=2,allow_nan=False))


if __name__=='__main__':main()

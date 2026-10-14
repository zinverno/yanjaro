"""Small untrained pulse audit; estimates never certify musical bar phase.

FFT correlation contract: https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.signal.correlate.html
No song distances, labels, model fitting, acquisition, or strict v2 extraction.
"""
import numpy as np
from scipy import ndimage, signal

from .data import require

SCHEMA = 'yanjaro.rhythm-auto-applicability.v1'
DT = .005
POLICY = dict(bpm_range=[40,260], minimum_strong_events=8, strong_relative_amplitude=.2,
              minimum_ac=.1, segment_bpm_relative_tolerance=.02,
              maximum_internal_phase_drift_beats=1/16, minimum_grid_support=.6,
              edge_exclusion_seconds=.032, meters_examined=[2,3,4,6],
              independent_phase_verification_required=True)


def envelope(times, weights, duration):
    grid = np.zeros(round(duration/DT)+1)
    positions = np.asarray(times)/DT
    left = np.floor(positions).astype(int)
    fraction = positions-left
    np.add.at(grid, np.clip(left,0,len(grid)-1), weights*(1-fraction))
    np.add.at(grid, np.clip(left+1,0,len(grid)-1), weights*fraction)
    return ndimage.gaussian_filter1d(grid, .01/DT, mode='constant')


def tempo_candidates(times, weights, duration):
    if len(times)<3 or np.sum(weights)<=0:
        return [], np.zeros(round(duration/DT)+1)
    onset = envelope(times,weights,duration)
    onset -= onset.mean()
    ac = signal.correlate(onset,onset,mode='full',method='fft')[len(onset)-1:]
    ac /= max(float(ac[0]),1e-12)
    ac *= len(onset)/np.maximum(len(onset)-np.arange(len(onset)),1)
    peaks,_ = signal.find_peaks(ac)
    peaks = [p for p in peaks if 40<=60/(p*DT)<=260 and ac[p]>0]
    result=[]
    for p in sorted(peaks,key=lambda p:(-ac[p],p))[:8]:
        denominator=ac[p-1]-2*ac[p]+ac[p+1]
        offset=.5*(ac[p-1]-ac[p+1])/denominator if abs(denominator)>1e-12 else 0
        bpm=60/((p+np.clip(offset,-.5,.5))*DT)
        result.append({'bpm':float(bpm),'ac_score':float(ac[p])})
    return result,ac


def phase_offset(times, weights, period):
    if len(times)==0 or np.sum(weights)<=0:
        return None
    offsets=np.arange(128)*period/128
    distance=(np.asarray(times)[:,None]-offsets+period/2)%period-period/2
    support=(np.asarray(weights)[:,None]*np.exp(-.5*(distance/(period/16))**2)).sum(axis=0)
    return float(offsets[np.argmax(support)])


def grid_support(times, weights, bpm, offset, duration):
    period=60/bpm
    beats=np.arange(offset,duration,period)
    if not len(times) or not len(beats):
        return {'grid_beats':len(beats),'supported_fraction':0.,'weighted_onset_near_beat':0.}
    distance=np.abs(np.asarray(times)[:,None]-beats)
    return {'grid_beats':len(beats),
            'supported_fraction':float(np.mean(distance.min(axis=0)<=period/16)),
            'weighted_onset_near_beat':float(np.sum(weights*(distance.min(axis=1)<=period/16))/np.sum(weights))}


def track_beats(times, strengths, bpm, offset, duration):
    period=60/bpm
    grid=np.arange(offset,duration,period)
    weights=strengths.sum(axis=1)
    refined,observed,accents=[],[],[]
    for beat in grid:
        eligible=np.flatnonzero(np.abs(times-beat)<=period/8)
        if len(eligible):
            score=weights[eligible]*np.exp(-.5*((times[eligible]-beat)/(period/16))**2)
            i=eligible[np.argmax(score)]
            refined.append(float(times[i])); observed.append(True); accents.append(strengths[i])
        else:
            refined.append(float(beat)); observed.append(False); accents.append(np.zeros(4))
    return grid,np.asarray(refined),observed,np.asarray(accents)


def meter_hypotheses(beats, accents, absolute_start):
    """Repeated accent patterns suggest grouping, never choose the strongest as beat 1."""
    output=[]
    for meter in POLICY['meters_examined']:
        x,y=accents[:-meter],accents[meter:]
        x=x-x.mean(axis=0) if len(x) else x
        y=y-y.mean(axis=0) if len(y) else y
        norm=np.linalg.norm(x)*np.linalg.norm(y)
        similarity=float((x*y).sum()/norm) if norm>1e-12 else None
        output.append({'beats_per_group':meter,'meter_denominator':None,
            'accent_repeat_correlation':similarity,'complete_groups':len(beats)//meter,
            'downbeat_alternatives_seconds_absolute':[(absolute_start+beats[k::meter]).tolist() for k in range(meter)],
            'chosen_offset':None,'status':'UNVERIFIED; all rotations retained; grouping is not time signature'})
    return output


def analyze_attacks(times, strengths, duration, absolute_start):
    times,strengths=np.asarray(times,dtype=float),np.asarray(strengths,dtype=float)
    require(np.isfinite([duration,absolute_start]).all() and 10<=duration<=15 and absolute_start>=0,
            'Expected bounded window and absolute recording position')
    require(times.ndim==1 and strengths.shape==(len(times),4) and np.isfinite(times).all()
            and np.isfinite(strengths).all() and (strengths>=0).all() and
            (times>=0).all() and (times<duration).all() and (np.diff(times)>0).all(), 'Invalid attack candidates')
    raw_count=len(times)
    keep=(times>=.032)&(times<duration-.032)
    times,strengths=times[keep],strengths[keep]
    weights=strengths.sum(axis=1)
    strong=int((weights>=.2*weights.max()).sum()) if len(weights) and weights.max()>0 else 0
    ranks,ac=tempo_candidates(times,weights,duration)
    result={'schema':SCHEMA,'independent_phase_verification':False,'phase_uncertainty_beats':None,
            'rhythm_v2_gate':'ABSTAIN','strict_v2_extractions':0,
            'raw_attack_count':raw_count,'interior_attack_count':len(times),'strong_attack_count':strong,
            'edge_candidates_excluded':raw_count-len(times),'tempo_candidates':ranks,
            'attack_seconds_absolute':(times+absolute_start).tolist(),
            'attack_strengths_four_bands':strengths.tolist()}
    if not ranks:
        return {**result,'status':'ABSTAIN','reasons':['NO_PULSE_CANDIDATE','NO_INDEPENDENT_PHASE_EVIDENCE'],
                'stable_automatic_hypothesis':False}
    bpm=ranks[0]['bpm'];period=60/bpm
    offset=phase_offset(times,weights,period)
    support=grid_support(times,weights,bpm,offset,duration)
    segments=[]
    for left in (0,5,10):
        mask=(times>=left)&(times<left+5)
        local,_=tempo_candidates(times[mask]-left,weights[mask],5)
        phase=phase_offset(times[mask],weights[mask],period)
        phase_drift=abs((phase-offset+period/2)%period-period/2)/period if phase is not None else None
        segments.append({'start_seconds_absolute':absolute_start+left,'tempo_candidates':local[:3],
                         'internal_phase_drift_beats':phase_drift,
                         'top_bpm_relative_difference':abs(local[0]['bpm']/bpm-1) if local else None})
    reasons=[]
    if strong<POLICY['minimum_strong_events']:reasons.append('TOO_FEW_STRONG_EVENTS')
    if ranks[0]['ac_score']<POLICY['minimum_ac']:reasons.append('WEAK_PERIODICITY')
    if any(s['top_bpm_relative_difference'] is None or s['top_bpm_relative_difference']>.02 for s in segments):
        reasons.append('SEGMENT_TEMPO_DISAGREEMENT')
    if any(s['internal_phase_drift_beats'] is None or s['internal_phase_drift_beats']>1/16 for s in segments):
        reasons.append('SEGMENT_PHASE_DISAGREEMENT')
    if support['supported_fraction']<.6:reasons.append('SPARSE_GRID_SUPPORT')
    stable=not reasons
    grid,beats,observed,accents=track_beats(times,strengths,bpm,offset,duration)
    phase=((times-offset)/period)%1
    histogram=np.histogram(phase,bins=np.linspace(0,1,17),weights=weights)[0]
    histogram=histogram/max(float(histogram.sum()),1e-12)
    alternatives=[{'bpm':bpm*f,'relation':name,'inside_search_range':40<=bpm*f<=260}
                  for f,name in ((.5,'half'),(2,'double'))]
    sensitivity=[]
    for tempo_scale,phase_shift in ((.99,0),(1.01,0),(1,-1/16),(1,1/16)):
        changed_bpm=bpm*tempo_scale;changed_offset=(offset+phase_shift*period)%(60/changed_bpm)
        sensitivity.append({'tempo_scale':tempo_scale,'phase_shift_beats':phase_shift,
                            **grid_support(times,weights,changed_bpm,changed_offset,duration)})
    band_tempos=[]
    for i in range(4):
        candidates,_=tempo_candidates(times,strengths[:,i],duration)
        band_tempos.append({'band':i,'top':candidates[0] if candidates else None,
                            'strength_share':float(strengths[:,i].sum()/max(weights.sum(),1e-12))})
    retained=weights>=np.median(weights)
    strong_ranks,_=tempo_candidates(times[retained],weights[retained],duration)
    return {**result,'status':'AUTO_CANDIDATE' if stable else 'ABSTAIN',
        'stable_automatic_hypothesis':stable,'reasons':reasons+['NO_INDEPENDENT_PHASE_EVIDENCE','UNRESOLVED_METER_AND_DOWNBEAT'],
        'estimated_bpm':bpm,'half_double_alternatives':alternatives,'segments':segments,
        'grid_origin_seconds_absolute':absolute_start+offset,
        'grid_seconds_absolute':(grid+absolute_start).tolist(),
        'beat_candidates_seconds_absolute':(beats+absolute_start).tolist(),
        'beat_candidate_has_nearby_attack':observed,
        'beat_interval_cv':float(np.std(np.diff(beats))/np.mean(np.diff(beats))),
        'internal_support_not_accuracy':support,'weighted_phase_histogram_16_per_beat':histogram.tolist(),
        'sensitivity':sensitivity,'band_tempos':band_tempos,
        'upper_half_strength_tempo':strong_ranks[0] if strong_ranks else None,
        'meter_hypotheses':meter_hypotheses(beats,accents,absolute_start),
        'tempo_error_bpm_for_sixteenth_drift_over_window':60/(16*duration)}


def energy_candidates(y,sr):
    """Alternative energy-rise detector for disagreement counts, not ground truth."""
    width=max(1,round(.005*sr));hop=width
    energy=signal.lfilter(np.ones(width)/width,[1],y*y)
    rise=np.maximum(np.diff(energy,prepend=energy[0]),0)
    usable=len(rise)//hop*hop
    frames=rise[:usable].reshape(-1,hop).max(axis=1)
    peaks,_=signal.find_peaks(frames,prominence=.05*frames.max(),distance=max(1,round(.032*sr/hop)))
    return (peaks*hop+hop/2)/sr

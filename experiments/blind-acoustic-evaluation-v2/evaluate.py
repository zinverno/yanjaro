"""Bounded, consent-gated offline evaluation; never trains or acquires audio."""
import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import re
import resource
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAB = HERE.parent / 'acoustic-similarity'
PILOT = HERE.parent / 'acoustic-listening-pilot'
sys.path.insert(0, str(PILOT))
import pilot
from acoustic_similarity.data import artist_clusters, digest, file_hash, read_json, require, validate_manifest, write_new

SCHEMA = 'yanjaro.blind-acoustic-evaluation.v2'
SEED = 2026111301
ALGORITHMS = ('acoustic', 'pi_coverage_v2', 'tempo_only')


def private_path(path):
    path = path.resolve()
    require(not any((p / '.git').is_file() or (p / '.git' / 'HEAD').is_file() for p in (path, *path.parents)),
            'Private artifacts must be outside every Git checkout')
    require(not path.is_relative_to(ROOT), 'Private artifacts must be outside this checkout')
    return path


def source_hashes():
    lock = read_json(HERE / 'upstream-lock.json')
    for name, sha in lock['files'].items():
        require(file_hash(ROOT / name) == sha, 'Frozen upstream changed: ' + name)
    own = {p.name: file_hash(p) for p in (HERE / n for n in
           ('evaluate.py', 'app.js', 'PROTOCOL.md', 'upstream-lock.json'))}
    return dict(upstream=lock, evaluation=own)


def template():
    track = dict(id='t01', yandex_track_id=None, path='', sha256='', title='',
                 artist_ids=[''], recording_group='', split='test', start=30, seconds=15,
                 novelty_reviewed=False, rights=dict(reviewed=False, acquisition=False,
                 analysis=False, local_feature_storage=False, private_listening=False,
                 license='', source_url='', attribution='', verified_on='', scope='',
                 evidence_path='', evidence_sha256=''))
    return dict(schema=SCHEMA, study_id='blind-v2-owner-pool-1', kind='real',
                previous_yandex_track_ids=['', '', '', ''], excluded_recording_groups=['', '', '', ''],
                tracks=[dict(track, id=f't{i:02}') for i in range(1, 13)])


def preflight(plan, *, files=False):
    require(plan.get('schema') == SCHEMA, 'Wrong plan schema')
    require(isinstance(plan.get('study_id'), str) and
            re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', plan['study_id']), 'Invalid study ID')
    old = plan.get('previous_yandex_track_ids', [])
    require(len(old) == 4 and len(set(old)) == 4 and
            all(isinstance(v, str) and re.fullmatch(r'[0-9]+', v) for v in old),
            'List all four previously indexed Yandex IDs')
    groups = plan.get('excluded_recording_groups', [])
    require(isinstance(groups, list) and len(set(groups)) >= 4 and
            all(isinstance(g, str) and g.strip() for g in groups), 'Prior recording groups required')
    manifest = dict(schema='yanjaro.acoustic-similarity.v0.1', kind=plan.get('kind'),
                    dataset_id=plan['study_id'], tracks=plan.get('tracks'))
    require(isinstance(manifest['tracks'], list) and 12 <= len(manifest['tracks']) <= 16,
            'Exactly 12..16 explicitly listed recordings required')
    tracks = validate_manifest(manifest)
    historical = read_json(LAB / 'validation/acoustic-retrieval-v1/index.json')['tracks']
    old_hashes = {r['audio_sha256'] for r in historical}
    old_groups = {r['recording_group'] for r in historical} | set(groups)
    require(len({t['recording_group'] for t in tracks.values()}) == len(tracks),
            'Distinct recording groups required')
    yandex_ids = []
    for t in tracks.values():
        require(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', t['id']), 'Use opaque local track IDs')
        require(t.get('novelty_reviewed') is True and t['recording_group'] not in old_groups and
                t['sha256'] not in old_hashes, 'Previously exposed or unreviewed recording')
        yid = t.get('yandex_track_id')
        require(yid is None or (isinstance(yid, str) and re.fullmatch(r'[0-9]+', yid) and yid not in old),
                'Invalid or previously indexed Yandex ID')
        if yid is not None: yandex_ids.append(yid)
        require(t['split'] == 'test' and t['seconds'] == 15, 'Evaluation-only fixed 15-second windows')
        require(t['rights'].get('private_listening') is True and
                t['rights'].get('local_feature_storage') is True, 'Private listening/storage permission required')
        require(isinstance(t.get('path'), str) and Path(t['path']).is_absolute() and
                Path(t['rights']['evidence_path']).is_absolute(), 'Absolute local audio/evidence paths required')
    require(len(yandex_ids) == len(set(yandex_ids)), 'Duplicate Yandex IDs')
    if files: validate_manifest(manifest, verify_files=True)
    return tracks


def permutation(items, salt):
    return sorted(items, key=lambda v: (digest([SEED, salt, v]), str(v)))


def rankings(rows):
    from acoustic_similarity import acoustic_retrieval as ar
    result = {}
    for q in sorted(rows, key=lambda r: r['id']):
        ranked = {a: ar.search(q['id'], rows, len(rows), a) for a in ALGORITHMS[:2]}
        tempo, abstentions = [], []
        for candidate in sorted(rows, key=lambda r: r['id']):
            if (candidate['id'] == q['id'] or candidate['audio_sha256'] == q['audio_sha256'] or
                    candidate['recording_group'] == q['recording_group']): continue
            d = ar.compare(q, candidate)['atomic_distances']['tempo']
            if d is None: abstentions.append(dict(id=candidate['id'], reason='MISSING_TEMPO'))
            else: tempo.append(dict(id=candidate['id'], distance=d))
        tempo.sort(key=lambda r: (r['distance'], r['id']))
        ranked['tempo_only'] = dict(results=tempo, abstentions=abstentions)
        result[q['id']] = ranked
    return result


def preference(ranking, algorithm, a, b):
    from acoustic_similarity.acoustic_retrieval import rank_key
    lookup = {r['id']: r for r in ranking[algorithm]['results']}
    if a not in lookup or b not in lookup: return 'abstain'
    x, y = lookup[a], lookup[b]
    if algorithm == 'tempo_only':
        dx, dy = x['distance'], y['distance']
        return 'tie' if abs(dx - dy) <= 1e-12 else (a if dx < dy else b)
    if x['coverage_mask'] == y['coverage_mask'] and abs(x['common_distance'] - y['common_distance']) <= 1e-12:
        return 'tie'
    return a if rank_key(x)[:-1] < rank_key(y)[:-1] else b


def select_cases(ranked):
    pools = dict(disagreement=[], consensus=[])
    for q in sorted(ranked):
        candidates = sorted({r['id'] for rank in ranked[q].values() for r in rank['results']})
        top = {r['id'] for rank in ranked[q].values() for r in rank['results'][:3]}
        for a, b in itertools.combinations(candidates, 2):
            if not {a, b} & top: continue
            pred = {alg: preference(ranked[q], alg, a, b) for alg in ALGORITHMS}
            strict = [v for v in pred.values() if v in (a, b)]
            group = 'disagreement' if len(set(strict)) == 2 else (
                'consensus' if len(strict) == 3 and len(set(strict)) == 1 else None)
            if group:
                lookup = {r['id']: r for r in ranked[q]['acoustic']['results']}
                pools[group].append(dict(anchor=q, candidates=[a, b], group=group, predictions=pred,
                    partial_features=any(t not in lookup or lookup[t]['coverage'] < 1 for t in (a, b))))
    cases, anchors, used = [], set(), set()
    for group, quota in (('disagreement', 6), ('consensus', 4)):
        pool = pools[group]
        require(len(pool) >= quota, 'BLOCKED: insufficient ' + group + ' cases; do not relax quotas')
        for _ in range(quota):
            pick = min(pool, key=lambda c: (c['anchor'] in anchors,
                       -len(({c['anchor'], *c['candidates']}) - used),
                       digest([SEED, 'selection', c]), c['anchor'], c['candidates']))
            pool.remove(pick)
            cases.append(dict(pick, case_id=f'c{len(cases)+1:02}'))
            anchors.add(pick['anchor']); used.update((pick['anchor'], *pick['candidates']))
    return cases


def schedules(cases, binding):
    ids = [c['case_id'] for c in cases]
    orientation = {cid: int(i >= 5) for i, cid in enumerate(permutation(ids, 'orientation'))}
    groups = {c['case_id']: c['group'] for c in cases}
    repeat_pairs = [(a, b) for a in ids for b in ids if groups[a] == 'disagreement' and
                    groups[b] == 'consensus' and orientation[a] != orientation[b]]
    repeats = permutation(repeat_pairs, 'repeats')[0]
    by_id = {c['case_id']: c for c in cases}
    result = {}
    for slot in (1, 2):
        tokens = [(cid, False) for cid in ids] + [(cid, True) for cid in repeats]
        for attempt in range(1000):
            order = permutation(tokens, ['order', slot, attempt])
            positions = {item: i for i, item in enumerate(order)}
            if all(positions[(cid, True)] - positions[(cid, False)] >= 4 for cid in repeats): break
        else: raise ValueError('Cannot separate repeats with frozen schedule rule')
        ordered = []
        for cid, repeat in order:
            c = by_id[cid]
            a, b = c['candidates'][::(-1 if orientation[cid] ^ (slot - 1) ^ repeat else 1)]
            ordered.append(dict(token=digest([binding, SEED, slot, cid, repeat])[:24],
                                case_id=cid, repeat=repeat, X=c['anchor'], A=a, B=b))
        result[str(slot)] = ordered
    return result


def runtime():
    require(sys.version_info[:3] == (3, 12, 13), 'Use pinned Python 3.12.13')
    versions = {}
    for line in (LAB / 'requirements.lock').read_text().splitlines():
        if not line or line.startswith('#'): continue
        name, version = line.split()[0].split('==')
        versions[name] = importlib.metadata.version(name)
        require(versions[name] == version, 'Locked dependency mismatch: ' + name)
    import soundfile as sf
    return dict(python=sys.version, packages=versions, libsndfile=sf.__libsndfile_version__)


def extract_tracks(tracks):
    import numpy as np
    import soundfile as sf
    from acoustic_similarity import acoustic_retrieval as ar, features, rhythm_pi
    rows, clips, receipts = [], {}, []
    for tid, track in sorted(tracks.items()):
        with sf.SoundFile(track['path']) as audio:
            sr, channels = audio.samplerate, audio.channels
            require(8000 <= sr <= 96000 and channels in (1, 2), 'Unsupported sample rate/channels')
            start, count = round(track['start'] * sr), round(15 * sr)
            audio.seek(start); samples = audio.read(count, dtype='float64', always_2d=True)
        require(samples.shape == (count, channels) and np.isfinite(samples).all(), 'Short/nonfinite window')
        peak = float(np.max(np.abs(samples)))
        require(1e-5 < peak <= 1, 'Silent or above-full-scale window; no normalization applied')
        mono = samples.mean(axis=1)
        pi = dict(rhythm_pi.extract(mono, sr), id=tid, audio_sha256=track['sha256'],
                  recording_group=track['recording_group'], title='', evidence_sha256=track['rights']['evidence_sha256'],
                  sample_rate=sr, start_sample=start, end_sample_exclusive=start+count)
        rows.append(ar.combine(pi, features.extract(track)))
        pcm = samples.astype('<f4')
        error = float(np.max(np.abs(pcm.astype('float64') - samples)))
        require(error <= 2e-7, 'Unexpected float32 rounding')
        payload = pcm.tobytes()
        fmt = struct.pack('<HHIIHH', 3, channels, sr, sr*channels*4, channels*4, 32)
        chunks = b'fmt ' + struct.pack('<I', 16) + fmt + b'fact' + struct.pack('<II', 4, count)
        chunks += b'data' + struct.pack('<I', len(payload)) + payload
        clips[tid] = b'RIFF' + struct.pack('<I', 4+len(chunks)) + b'WAVE' + chunks
        receipts.append(dict(id=tid, clip_sha256=hashlib.sha256(clips[tid]).hexdigest(),
                             native_mono_sha256=hashlib.sha256(mono.astype('<f8').tobytes()).hexdigest(),
                             peak=peak, float32_max_error=error, sample_rate=sr, channels=channels,
                             start_sample=start, end_sample_exclusive=start+count))
    return rows, clips, receipts


def render(package, clips):
    data = json.dumps(dict(package, clips=clips), separators=(',', ':'), ensure_ascii=False)
    require('</' not in data and '<!--' not in data, 'Unsafe embedded data')
    script = 'const PILOT = ' + data + ';\n' + (HERE / 'app.js').read_text()
    sha = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    page = (PILOT / 'page.html').read_text().replace('14 коротких сравнений', '12 коротких сравнений')
    return page.replace('__SCRIPT_SHA__', sha).replace('__SCRIPT__', script)


def prepare(plan_path, out):
    plan_path = private_path(plan_path)
    plan = read_json(plan_path); tracks = preflight(plan)
    source = source_hashes(); env = runtime()
    out = private_path(out)
    require(not out.exists(), 'Create-only output required')
    binding = digest(plan)
    phrase = 'INDEX ' + binding[:12]
    require(sys.stdin.isatty(), 'Explicit local consent requires an interactive terminal')
    print(f'Local indexing of {len(tracks)} listed 15-second windows; no acquisition. Plan: {binding}')
    print('Confirm permission for local analysis, feature storage and both private listeners.')
    require(input('Type ' + phrase + ' to consent: ').strip() == phrase, 'No local consent; nothing indexed')
    os.umask(0o077)
    out.mkdir(mode=0o700)
    for name in ('organizer', 'listeners', 'responses'): (out / name).mkdir(mode=0o700)
    org = out / 'organizer'
    write_new(org / 'intent.json', dict(schema=SCHEMA, plan=plan, plan_sha256=binding,
              source=source, environment=env, consent=dict(phrase=phrase, local_tty=True,
              at=datetime.now(timezone.utc).isoformat()), human_evaluation='NOT RUN'))
    preflight(plan, files=True)
    rows, clips, receipts = extract_tracks(tracks)
    preflight(plan, files=True)
    require(read_json(plan_path) == plan and source_hashes() == source, 'Inputs/source changed during extraction')
    write_new(org / 'index.json', dict(schema=SCHEMA, kind=plan['kind'], tracks=rows, clips=receipts))
    ranked = rankings(rows)
    cases = select_cases(ranked)
    schedule = schedules(cases, binding)
    predictions = dict(schema=SCHEMA, seed=SEED, rankings=ranked, cases=cases, schedules=schedule)
    write_new(org / 'predictions.json', predictions)
    packages = {}
    for slot, trials in schedule.items():
        aliases = {tid: digest([binding, slot, 'clip', tid])[:24] for tid in tracks}
        package = dict(schema=SCHEMA, kind='human-self-report' if plan['kind'] == 'real' else 'technical-test-only',
                       reviewer=digest([binding, slot, 'reviewer'])[:24],
                       trials=[dict(token=t['token'], **{role: aliases[t[role]] for role in ('X', 'A', 'B')}) for t in trials])
        package['package'] = digest([package, digest(predictions), receipts, source])
        packages[slot] = package
        html = render(package, {aliases[tid]: base64.b64encode(raw).decode() for tid, raw in clips.items()})
        pilot.private_bytes(out / 'listeners' / f'listener-{slot}.html', html.encode())
    write_new(org / 'packages.json', packages)
    names = ['organizer/' + n for n in ('intent.json', 'index.json', 'predictions.json', 'packages.json')]
    names += [f'listeners/listener-{slot}.html' for slot in schedule]
    freeze = dict(schema=SCHEMA, files={n: file_hash(out / n) for n in names}, plan_sha256=binding,
                  new_audio_download_bytes=0, human_evaluation='NOT RUN', training='NOT RUN')
    write_new(org / 'freeze.json', freeze)
    seal = digest(freeze)
    pilot.private_bytes(org / 'seal.txt', (seal + '\n').encode())
    write_new(org / 'closeout.template.json', dict(schema=SCHEMA, seal=seal, slots={'1': 'pending', '2': 'pending'}))
    print('Prepared 12 blind presentations for each of two slots. Human evaluation NOT RUN. Seal: ' + seal)


def verify_run(run):
    org = run / 'organizer'; freeze = read_json(org / 'freeze.json')
    require(freeze['schema'] == SCHEMA and (org / 'seal.txt').read_text().strip() == digest(freeze), 'Freeze seal mismatch')
    for name, sha in freeze['files'].items():
        require((run / name).resolve().is_relative_to(run.resolve()), 'Invalid sealed path')
        require(file_hash(run / name) == sha, 'Sealed artifact changed: ' + name)
    intent = read_json(org / 'intent.json')
    require(intent['source'] == source_hashes(), 'Protocol or implementation changed since preparation')
    require(intent['plan_sha256'] == digest(intent['plan']) == freeze['plan_sha256'], 'Plan binding mismatch')
    return freeze, intent, read_json(org / 'predictions.json'), read_json(org / 'packages.json')


def read_response(path):
    require(path.stat().st_size <= 65536, 'Response too large')
    if path.suffix.lower() != '.csv': return read_json(path)
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    require(len(rows) == 12, 'CSV must have twelve slots')
    common = ('schema', 'kind', 'reviewer', 'package', 'position')
    for row in rows: pilot.strict_fields(row, (*common, 'token', 'choice', 'aspect', 'confidence'))
    require(all(all(r[k] == rows[0][k] for k in common) for r in rows), 'Mixed CSV sessions')
    result = {k: rows[0][k] for k in common}; result['position'] = int(result['position'])
    result['responses'] = [dict(token=r['token'], choice=r['choice'] or None, aspect=r['aspect'] or None,
                                confidence=int(r['confidence']) if r['confidence'] else None) for r in rows]
    return result


def validate_response(response, package):
    pilot.strict_fields(response, ('schema', 'kind', 'reviewer', 'package', 'position', 'responses'))
    require(response['schema'] == SCHEMA and response['kind'] == package['kind'] == 'human-self-report',
            'Only human self-report; technical fixtures are not evidence')
    require(all(response[k] == package[k] for k in ('reviewer', 'package')), 'Another reviewer/package')
    require(type(response['position']) is int and 0 <= response['position'] < 12, 'Invalid position')
    require(isinstance(response['responses'], list) and len(response['responses']) == 12, 'Need twelve slots')
    for row, trial in zip(response['responses'], package['trials']):
        pilot.strict_fields(row, ('token', 'choice', 'aspect', 'confidence'))
        require(row['token'] == trial['token'], 'Unexpected trial token/order')
        require(row['choice'] is None or row['choice'] in pilot.CHOICES, 'Invalid choice')
        require(row['aspect'] is None or row['aspect'] in pilot.ASPECTS, 'Invalid aspect')
        require(row['confidence'] is None or (type(row['confidence']) is int and 1 <= row['confidence'] <= 5),
                'Invalid confidence')


def counts(rows):
    agreement = {}
    for alg in ALGORITHMS:
        eligible = [r for r in rows if r['choice'] in ('A', 'B') and r['predictions'][alg] not in ('tie', 'abstain')]
        matches = sum(r['selected'] == r['predictions'][alg] for r in eligible)
        agreement[alg] = dict(matches=matches, eligible=len(eligible), fraction=matches/len(eligible) if eligible else None,
             model_ties=sum(r['predictions'][alg] == 'tie' for r in rows),
             model_abstentions=sum(r['predictions'][alg] == 'abstain' for r in rows),
             exact_human_model_ties=sum(r['choice'] == r['predictions'][alg] == 'tie' for r in rows))
    return dict(presentations=len(rows), choices={c: sum((r['choice'] or 'skipped') == c for r in rows)
                for c in (*pilot.CHOICES, 'skipped')}, agreement=agreement)


def summarize(decoded):
    originals = [r for rows in decoded.values() for r in rows if not r['repeat']]
    repeats = []
    for slot, rows in decoded.items():
        first = {r['case_id']: r for r in rows if not r['repeat']}
        for r in rows:
            if r['repeat']:
                initial = first[r['case_id']]
                evaluable = all(v['choice'] in ('A', 'B', 'tie', 'neither') for v in (initial, r))
                repeats.append(dict(slot=slot, case_id=r['case_id'], first=initial['selected'], repeat=r['selected'],
                                    consistent=initial['selected'] == r['selected'] if evaluable else None))
    cross = []
    for left, right in itertools.combinations(sorted(decoded), 2):
        a = {r['case_id']: r for r in decoded[left] if not r['repeat']}
        b = {r['case_id']: r for r in decoded[right] if not r['repeat']}
        for cid in sorted(a):
            x, y = a[cid], b[cid]
            decisive = x['choice'] in ('A', 'B') and y['choice'] in ('A', 'B')
            cross.append(dict(case_id=cid, slots=[left, right], choices=[x['selected'], y['selected']],
                              decisive_disagreement=(x['selected'] != y['selected']) if decisive else None,
                              categories=[v['canonical_choice'] for v in (x, y)]))
    categories = Counter('|'.join(r['categories']) for r in cross)
    groups = {g: counts([r for r in originals if r['group'] == g]) for g in ('disagreement', 'consensus')}
    groups.update({g: counts([r for r in originals if r['partial_features'] == flag])
                   for g, flag in (('complete_features', False), ('partial_features', True))})
    return dict(totals=counts(originals), by_listener={slot: counts([r for r in rows if not r['repeat']])
                    for slot, rows in decoded.items()}, by_group=groups,
                by_aspect={a: counts([r for r in originals if (r['aspect'] or 'unspecified') == a])
                           for a in (*pilot.ASPECTS, 'unspecified')}, repeats=repeats,
                between_listeners=dict(status='DESCRIPTIVE ONLY' if cross else 'NOT RUN', cases=cross,
                     jointly_decisive=sum(r['decisive_disagreement'] is not None for r in cross),
                     decisive_disagreements=sum(r['decisive_disagreement'] is True for r in cross),
                     category_cross_tab=dict(categories)))


def analyze(run, closeout_path, paths):
    freeze, intent, pred, packages = verify_run(private_path(run))
    closeout = read_json(closeout_path)
    pilot.strict_fields(closeout, ('schema', 'seal', 'slots'))
    require(closeout['schema'] == SCHEMA and closeout['seal'] == digest(freeze), 'Closeout seal mismatch')
    require(set(closeout['slots']) == set(packages) and
            all(v in ('completed', 'withdrawn') for v in closeout['slots'].values()), 'All listener slots must be closed')
    cases = {c['case_id']: c for c in pred['cases']}
    by_reviewer = {p['reviewer']: slot for slot, p in packages.items()}
    decoded, response_hashes = {}, {}
    for path in paths:
        response = read_response(path); slot = by_reviewer.get(response.get('reviewer'))
        require(slot is not None and slot not in decoded, 'Unknown or duplicate listener; choose one final export')
        require(closeout['slots'][slot] == 'completed', 'Withdrawn listener must not be analyzed')
        validate_response(response, packages[slot])
        response_hashes[slot] = file_hash(path)
        rows = []
        for answer, trial in zip(response['responses'], pred['schedules'][slot]):
            case = cases[trial['case_id']]; choice = answer['choice']
            selected = trial[choice] if choice in ('A', 'B') else choice
            canonical = ('candidate_1' if selected == case['candidates'][0] else 'candidate_2') if choice in ('A', 'B') else choice or 'skipped'
            rows.append(dict(case, **answer, repeat=trial['repeat'], selected=selected, canonical_choice=canonical))
        decoded[slot] = rows
    require(set(decoded) == {s for s, v in closeout['slots'].items() if v == 'completed'}, 'Missing completed listener export')
    result = summarize(decoded)
    answered = sum(r['choice'] is not None for rows in decoded.values() for r in rows if not r['repeat'])
    tracks = intent['plan']['tracks']
    return dict(schema=SCHEMA, status='DESCRIPTIVE EVALUATION ONLY' if answered else 'NOT RUN', seal=digest(freeze),
                response_sha256=response_hashes, closeout=closeout, **result,
                pool_size=len(tracks), used_recordings=len({v for c in pred['cases'] for v in (c['anchor'], *c['candidates'])}),
                artist_ids=len({a for t in tracks for a in t['artist_ids']}), unique_cases=10,
                artist_groups=len(set(artist_clusters({t['id']: t for t in tracks}).values())),
                population_accuracy='NOT ESTIMATED', training='NOT RUN', weights_changed=False,
                limitations=['selected dependent cases', '12–16 recordings', 'at most two listeners',
                             '15-second windows', 'evaluation-only; new data required after any tuning'])


def markdown(report):
    lines = ['# Blind Acoustic Evaluation v2', '', report['status'], '',
             'Descriptive agreement only. No population accuracy or model improvement claim.', '',
             f"Pool: {report['pool_size']}; used recordings: {report['used_recordings']}; artist groups: {report['artist_groups']}; unique cases: 10.", '']
    for label, subset in [('All original responses', report['totals']), *report['by_listener'].items(),
                           *report['by_group'].items(), *report['by_aspect'].items()]:
        lines += ['## ' + label, '', '| Comparator | Matches | Eligible decisive | Fraction | Model ties | Abstentions |',
                  '|---|---:|---:|---:|---:|---:|']
        for alg, r in subset['agreement'].items():
            fraction = 'N/A' if r['fraction'] is None else f"{r['fraction']:.3f}"
            lines.append(f"| {alg} | {r['matches']} | {r['eligible']} | {fraction} | {r['model_ties']} | {r['model_abstentions']} |")
        lines += ['', 'Answer counts: ' + json.dumps(subset['choices'], ensure_ascii=False), '']
    lines += ['## Between listeners', '', '```json', json.dumps(report['between_listeners'], indent=2), '```', '',
              '## Reversed repeats (excluded above)', '', '```json', json.dumps(report['repeats'], indent=2), '```', '',
              'Limitations: ' + '; '.join(report['limitations']) + '.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init'); p.add_argument('--plan', type=Path, required=True)
    p = sub.add_parser('preflight'); p.add_argument('--plan', type=Path, required=True)
    p = sub.add_parser('prepare'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('analyze'); p.add_argument('--run', type=Path, required=True)
    p.add_argument('--closeout', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('responses', nargs='*', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMBA_NUM_THREADS'): os.environ[name] = '2'
    resource.setrlimit(resource.RLIMIT_CPU, (540, 540))
    def offline(event, _):
        if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system'):
            raise RuntimeError('Offline evaluation only')
    sys.addaudithook(offline)
    source_hashes()
    if args.cmd == 'init': write_new(private_path(args.plan), template())
    elif args.cmd == 'preflight':
        tracks = preflight(read_json(private_path(args.plan)), files=True)
        print(f'PASS: {len(tracks)} declared files and rights hashes. No decoding/indexing. Consent still required.')
    elif args.cmd == 'prepare': prepare(args.plan, args.out)
    else:
        out = private_path(args.out)
        require(not out.exists(), 'Create-only report directory required')
        report = analyze(args.run, private_path(args.closeout), [private_path(p) for p in args.responses])
        out.mkdir(mode=0o700)
        write_new(out / 'report.json', report)
        pilot.private_bytes(out / 'report.md', markdown(report).encode())
        print(report['status'])


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        print('BLOCKED:', str(error), file=sys.stderr)
        raise SystemExit(2)

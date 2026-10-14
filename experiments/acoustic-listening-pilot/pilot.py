"""Offline listening packages and descriptive analysis; no feature extraction or training."""
import argparse
import base64
from collections import Counter
import csv
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import resource
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parent / 'acoustic-similarity'
sys.path.insert(0, str(LAB))
from acoustic_similarity.data import digest, file_hash, read_json, require, validate_manifest, write_new

BASE_HEAD = '35aecde3311fa302e0ac1548d9c53f336ed9c928'
MANIFEST_SHA = '24ce999d2b1175640ad4ae73e0d1c487a8fa80cc2ca5581819f391e0a29a0b1e'
SEED = 2026101401
SCHEMA = 'yanjaro.acoustic-listening.v1'
CHOICES = ('A', 'B', 'tie', 'neither', 'uncertain')
ASPECTS = ('rhythm', 'tempo', 'timbre', 'energy', 'combination')
PINS = {
    'rhythm-pi-v1/index.json': 'e5b4bc2d890b8d6dbea7353b8a9de87292ec761219aacf6f04f315b261b8ae87',
    'rhythm-pi-v1/retrieval.json': '3850f507b4f88731317ff9fd457abbfd50f088b6e126caa9e8e1286e3a62f15a',
    'rhythm-pi-v1/frozen.json': 'f1a31f7ac9b539bbb9d16830cffe4a2ab8cbcc457a37afcfcb03e91a6fcf070b',
    'acoustic-retrieval-v1/index.json': '4c8c0c2f18e47b016a4521cc1eb0f8a7a11d3f3cbd9afb303a36ea2444086a61',
    'acoustic-retrieval-v1/retrieval.json': 'ee38e1ec35c1926849a84a095bb26259101141f8d1bb3ecdb9c4021e7de086e8',
    'acoustic-retrieval-v1/frozen.json': '3b5cb3211bdcc134e9ce495dd2156b4977d11fe6d4d349eb34b7bf53f757262d',
    'acoustic-retrieval-v1/repeat-extraction.json': 'a349713f41a298a1af8224fcbbbccd93289b374689e34ec16e8009673dfd5240',
}


def frozen_inputs():
    for name, sha in PINS.items():
        require(file_hash(LAB / 'validation' / name) == sha, 'Frozen input changed: ' + name)
    pi = read_json(LAB / 'validation/rhythm-pi-v1/retrieval.json')['rankings']
    acoustic = read_json(LAB / 'validation/acoustic-retrieval-v1/retrieval.json')['acoustic']
    return pi, acoustic


def shuffled(items, salt):
    """Version-independent deterministic permutation, with a lexical collision tie-break."""
    return sorted(items, key=lambda x: (digest([SEED, salt, x]), str(x)))


def select_cases(pi, acoustic):
    rows = {q: {r['id']: r for r in v['results']} for q, v in acoustic.items()}
    order = {q: [r['id'] for r in v['results']] for q, v in acoustic.items()}
    old = {q: [r['id'] for r in v] for q, v in pi.items()}
    pools = {k: [] for k in ('small_margin', 'unknown_tempo', 'partial_features',
                            'tempo_timbre_energy', 'rhythm_tempo', 'rank_disagreement')}

    def add(category, q, a, b, metric, mandatory=False):
        if len({q, a, b}) == 3:
            pools[category].append(dict(anchor=q, candidates=sorted((a, b)),
                                        metric=metric, mandatory=mandatory))

    for q in sorted(rows):
        a, b, c = order[q][:3]
        if rows[q][a]['coverage_mask'] == rows[q][b]['coverage_mask']:
            add('small_margin', q, a, b, [rows[q][b]['common_distance'] - rows[q][a]['common_distance']])
        if q == 'u01':
            add('unknown_tempo', q, a, c, [0], True)
        else:
            add('unknown_tempo', q, a, 'u01', [order[q].index('u01')])
        if q == 's04':
            add('partial_features', q, a, b, [0], True)
        else:
            add('partial_features', q, a, 's04', [order[q].index('s04')])
        if old[q][0] != a:
            add('rank_disagreement', q, old[q][0], a,
                [-old[q].index(a) - order[q].index(old[q][0])])
        complete = [tid for tid, row in rows[q].items() if row['coverage'] == 1]
        for a, b in itertools.combinations(sorted(complete), 2):
            ca, cb = rows[q][a]['components'], rows[q][b]['components']
            h1, h2 = ca['tempo']['distance'], cb['tempo']['distance']
            r1, r2 = ca['rhythm']['distance'], cb['rhythm']['distance']
            te1 = (ca['timbre']['distance'] + ca['energy']['distance']) / 2
            te2 = (cb['timbre']['distance'] + cb['energy']['distance']) / 2
            if abs(te1 - te2) > 1e-12:
                add('tempo_timbre_energy', q, a, b, [max(h1, h2), -abs(te1 - te2)])
            if (r1 - r2) * (h1 - h2) < 0:
                add('rhythm_tempo', q, a, b, [min(r1, r2), -abs(h1 - h2)])
    selected, seen, anchors = [], set(), set()
    for category, pool in pools.items():
        for _ in range(2):
            available = [v for v in pool if (v['anchor'], *v['candidates']) not in seen]
            require(available, 'Insufficient unique cases: ' + category)
            pick = min(available, key=lambda v: (not v['mandatory'], v['anchor'] in anchors,
                                                 v['metric'], v['anchor'], v['candidates']))
            q, (a, b) = pick['anchor'], pick['candidates']
            case = dict(case_id=f'c{len(selected)+1:02}', category=category,
                        anchor=q, candidates=[a, b], selection_metric=pick['metric'],
                        frozen_pairs={tid: dict(pi_v1=pi[q][old[q].index(tid)], acoustic_v1=rows[q][tid])
                                      for tid in (a, b)})
            selected.append(case)
            seen.add((q, a, b)); anchors.add(q)
    require(len(selected) == 12 and len(seen) == 12, 'Expected twelve unique cases')
    return selected


def schedule(cases, slot):
    require(slot in (1, 2), 'Two independent reviewer slots supported')
    ids = [r['case_id'] for r in cases]
    orientation = {cid: int(i >= 6) ^ (slot - 1) for i, cid in enumerate(shuffled(ids, 'orientation'))}
    repeats = [next(cid for cid in shuffled(ids, 'repeat') if orientation[cid] == n) for n in (0, 1)]
    tokens = [(cid, False) for cid in ids] + [(cid, True) for cid in repeats]
    pending = shuffled(tokens, ['order', slot]); ordered = []; first = {}
    while pending:
        eligible = [v for v in pending if not v[1] or
                    (v[0] in first and len(ordered) - first[v[0]] >= 4)]
        require(eligible, 'Unable to separate blind repeats')
        item = eligible[0]; pending.remove(item)
        if not item[1]: first[item[0]] = len(ordered)
        ordered.append(item)
    by_id = {r['case_id']: r for r in cases}
    result = []
    for cid, repeat in ordered:
        case = by_id[cid]; a, b = case['candidates'][::(-1 if orientation[cid] ^ repeat else 1)]
        token = digest([SEED, 'presentation', slot, cid, repeat])[:24]
        result.append(dict(token=token, case_id=cid, repeat=repeat, X=case['anchor'], A=a, B=b))
    return result


def make_freeze():
    pi, acoustic = frozen_inputs()
    cases = select_cases(pi, acoustic)
    return dict(schema=SCHEMA, base_head=BASE_HEAD, seed=SEED, input_sha256=PINS,
                manifest_sha256=MANIFEST_SHA, protocol_sha256=file_hash(HERE / 'PROTOCOL.md'),
                cases=cases, schedules={str(n): schedule(cases, n) for n in (1, 2)},
                human_evaluation='NOT RUN', ground_truth=None,
                limitations=['10 recordings', '3 author groups', 'dependent selected comparisons',
                             '15 second excerpts', 'no independent acoustic labels yet'])


def verify_freeze():
    frozen = read_json(HERE / 'frozen.json')
    require(frozen == make_freeze(), 'Selection, inputs or protocol changed after freezing')
    return frozen


def strict_fields(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), 'Unexpected or missing fields')


def validate_response(response, package, *, allow_test=False):
    strict_fields(response, ('schema', 'kind', 'reviewer', 'package', 'position', 'responses'))
    require(response['schema'] == SCHEMA and response['kind'] == package['kind'], 'Invalid response kind/schema')
    require(allow_test or response['kind'] == 'human-self-report', 'Technical fixtures are not human evidence')
    require(response['reviewer'] == package['reviewer'] and response['package'] == package['package'],
            'Another reviewer/package: do not merge sessions')
    require(type(response['position']) is int and 0 <= response['position'] < 14, 'Invalid position')
    expected = [t['token'] for t in package['trials']]
    require(isinstance(response['responses'], list) and len(response['responses']) == 14, 'Need 14 slots')
    for row, token in zip(response['responses'], expected):
        strict_fields(row, ('token', 'choice', 'aspect', 'confidence'))
        require(row['token'] == token, 'Unexpected response order/token')
        require(row['choice'] is None or row['choice'] in CHOICES, 'Invalid choice')
        require(row['aspect'] is None or row['aspect'] in ASPECTS, 'Invalid aspect')
        require(row['confidence'] is None or (type(row['confidence']) is int and 1 <= row['confidence'] <= 5),
                'Invalid confidence')
    return response


def empty_response(package):
    return dict(schema=SCHEMA, kind=package['kind'], reviewer=package['reviewer'],
                package=package['package'], position=0,
                responses=[dict(token=t['token'], choice=None, aspect=None, confidence=None)
                           for t in package['trials']])


def csv_export(response):
    stream = io.StringIO(newline='')
    fields = ['schema', 'kind', 'reviewer', 'package', 'position', 'token', 'choice', 'aspect', 'confidence']
    writer = csv.DictWriter(stream, fields, lineterminator='\n'); writer.writeheader()
    for row in response['responses']:
        writer.writerow({**{k: response[k] for k in fields[:4]}, 'position': response['position'], **row})
    return stream.getvalue()


def read_response(path):
    if path.suffix.lower() != '.csv': return read_json(path)
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    require(len(rows) == 14, 'CSV must contain 14 slots')
    common = ('schema', 'kind', 'reviewer', 'package', 'position')
    for row in rows: strict_fields(row, (*common, 'token', 'choice', 'aspect', 'confidence'))
    require(all(all(row[k] == rows[0][k] for k in common) for row in rows), 'Mixed CSV sessions')
    result = {k: rows[0][k] for k in common}; result['position'] = int(result['position'])
    result['responses'] = []
    for row in rows:
        strict_fields(row, (*common, 'token', 'choice', 'aspect', 'confidence'))
        result['responses'].append(dict(token=row['token'], choice=row['choice'] or None,
                                       aspect=row['aspect'] or None,
                                       confidence=int(row['confidence']) if row['confidence'] else None))
    return result


def private_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as stream: stream.write(payload)
    path.chmod(0o600)


def render(package, clips):
    data = json.dumps(dict(package, clips=clips), separators=(',', ':'), ensure_ascii=False)
    require('</' not in data and '<!--' not in data, 'Unsafe embedded data')
    js = (HERE / 'app.js').read_text()
    script = 'const PILOT = ' + data + ';\n' + js
    sha = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return (HERE / 'page.html').read_text().replace('__SCRIPT_SHA__', sha).replace('__SCRIPT__', script)


def prepare(manifest_path, out):
    import numpy as np
    import soundfile as sf
    started = time.perf_counter()
    frozen = verify_freeze()
    require(not out.exists(), 'Create-only output required')
    require(not out.resolve().is_relative_to(HERE.parents[1]), 'Private output must be outside checkout')
    require(file_hash(manifest_path) == MANIFEST_SHA, 'Approved manifest changed; no audio decoded')
    tracks = validate_manifest(read_json(manifest_path), purpose='analysis', verify_files=True)
    require(len(tracks) == 10 and all(t['seconds'] == 15 and t['rights']['license'] == 'CC0-1.0'
                                   for t in tracks.values()), 'Unexpected audio scope')
    pi_index = read_json(LAB / 'validation/rhythm-pi-v1/index.json')
    pi_rows = {r['id']: r for r in pi_index['tracks']}
    receipt_rows = {r['id']: r for r in read_json(LAB / 'validation/acoustic-retrieval-v1/repeat-extraction.json')['records']}
    clips, receipts = {}, []
    for tid, track in sorted(tracks.items()):
        with sf.SoundFile(track['path']) as audio:
            sr, channels = audio.samplerate, audio.channels
            require(channels in (1, 2), 'Unsupported channel count')
            start, frames = round(track['start'] * sr), round(track['seconds'] * sr)
            audio.seek(start); samples = audio.read(frames, dtype='float64', always_2d=True)
        require(samples.shape == (frames, channels), 'Short window')
        require(start == pi_rows[tid]['start_sample'] and start + frames == pi_rows[tid]['end_sample_exclusive'],
                'Different historical window')
        mono_sha = hashlib.sha256(samples.mean(axis=1).astype('<f8').tobytes()).hexdigest()
        require(mono_sha == receipt_rows[tid]['native_mono_window_sha256'], 'Native waveform drift')
        require(np.isfinite(samples).all(), 'Nonfinite waveform')
        pcm = samples.astype('<f4')
        error = float(np.max(np.abs(pcm.astype('float64') - samples)))
        require(error <= 2e-7, 'Unexpected float32 rounding')
        # MP3 decoding can exceed full scale. Preserve native gain instead of clipping to PCM16.
        payload = pcm.tobytes()
        fmt = struct.pack('<HHIIHH', 3, channels, sr, sr*channels*4, channels*4, 32)
        chunks = b'fmt ' + struct.pack('<I', 16) + fmt + b'fact' + struct.pack('<II', 4, frames)
        chunks += b'data' + struct.pack('<I', len(payload)) + payload
        raw = b'RIFF' + struct.pack('<I', 4+len(chunks)) + b'WAVE' + chunks
        require(len(raw) == 56 + frames * channels * 4, 'Unexpected WAV metadata/chunks')
        clips[tid] = base64.b64encode(raw).decode()
        receipts.append(dict(id=tid, audio_sha256=track['sha256'], evidence_sha256=track['rights']['evidence_sha256'],
                             clip_sha256=hashlib.sha256(raw).hexdigest(), native_mono_sha256=mono_sha,
                             start_sample=start, end_sample_exclusive=start+frames, sample_rate=sr,
                             channels=channels, seconds=frames/sr, max_float32_rounding_error=error,
                             native_peak=float(np.max(np.abs(samples))),
                             above_full_scale_samples=int(np.count_nonzero(np.abs(samples)>1)), bytes=len(raw)))
    validate_manifest(read_json(manifest_path), purpose='analysis', verify_files=True)
    packages, keys, files = [], {}, {}
    for slot in (1, 2):
        trials = frozen['schedules'][str(slot)]
        reviewer = digest([SCHEMA, SEED, 'reviewer', slot])[:24]
        aliases = {tid: digest([SEED, slot, 'clip', tid])[:24] for tid in tracks}
        package = dict(schema=SCHEMA, kind='human-self-report', reviewer=reviewer,
                       trials=[dict(token=t['token'], **{k: aliases[t[k]] for k in ('X', 'A', 'B')}) for t in trials])
        package['package'] = digest([package, digest(frozen), {k: hashlib.sha256(v.encode()).hexdigest()
                                                            for k, v in sorted(clips.items())}])
        html = render(package, {aliases[tid]: v for tid, v in clips.items()})
        for forbidden in ('source_url', 'attribution', 'coverage_mask', 'conditional_score', 'frozen_pairs'):
            require(forbidden not in html, 'Metadata leak')
        name = f'listener-{slot}.html'
        private_bytes(out / name, html.encode()); files[name] = file_hash(out / name)
        packages.append(package)
        keys[reviewer] = dict(slot=slot, trials=trials, package=package)
    write_new(out / 'organizer-key.json', dict(schema=SCHEMA, frozen_sha256=digest(frozen), reviewers=keys))
    write_new(out / 'preparation.json', dict(schema=SCHEMA, status='PASS', base_head=BASE_HEAD,
        frozen_sha256=digest(frozen), manifest_sha256=MANIFEST_SHA, receipts=receipts,
        packages=[{k: p[k] for k in ('reviewer', 'package')} for p in packages], html_sha256=files,
        source_sha256={name: file_hash(HERE / name) for name in ('pilot.py', 'app.js', 'page.html', 'PROTOCOL.md')},
        new_audio_download_bytes=0, network_requests=0, human_evaluation='NOT RUN',
        wall_seconds=time.perf_counter()-started, cpu_seconds=cpu_seconds(), peak_rss_mib=rss_mib(),
        compute_threads=2, audio_published=False))
    print('Prepared two private offline pages; human evaluation NOT RUN')


def prediction(case, algorithm):
    a, b = case['candidates']; pa, pb = [case['frozen_pairs'][v][algorithm] for v in (a, b)]
    if algorithm == 'pi_v1':
        delta = pa['distance'] - pb['distance']
        return None if abs(delta) <= 1e-12 else (a if delta < 0 else b)
    if pa['coverage_mask'] == pb['coverage_mask'] and abs(pa['common_distance'] - pb['common_distance']) <= 1e-12:
        return None
    return a if pa['rank'] < pb['rank'] else b


def descriptive_counts(subset):
    return dict(cases=len(subset), counts=dict(Counter(r['choice'] or 'unanswered' for r in subset)),
                agreement={a: dict(matches=sum(r['agreement'][a] is True for r in subset),
                                   eligible=sum(r['agreement'][a] is not None for r in subset))
                           for a in ('pi_v1', 'acoustic_v1')})


def analyze(key_path, paths):
    frozen = verify_freeze(); key = read_json(key_path)
    require(key['frozen_sha256'] == digest(frozen), 'Key belongs to another pilot')
    cases = {r['case_id']: r for r in frozen['cases']}
    reviewers, seen, unique = [], set(), {}
    for path in paths:
        response = read_response(path); rid = response['reviewer']
        require(rid in key['reviewers'] and rid not in seen, 'Unknown or duplicate reviewer; choose one latest export')
        seen.add(rid); entry = key['reviewers'][rid]
        validate_response(response, entry['package'])
        require(entry['trials'] == frozen['schedules'][str(entry['slot'])], 'Organizer schedule drift')
        decoded, originals, repeats = [], {}, []
        for answer, trial in zip(response['responses'], entry['trials']):
            cid = trial['case_id']; case = cases[cid]
            choice = answer['choice']; selected = trial[choice] if choice in ('A', 'B') else choice
            if trial['repeat']:
                first = originals[cid]
                repeats.append(dict(case_id=cid, first=first, repeat=selected,
                                    consistent=None if first is None or selected is None else first == selected))
                continue
            originals[cid] = selected
            predictions = {a: prediction(case, a) for a in ('pi_v1', 'acoustic_v1')}
            masks = [case['frozen_pairs'][tid]['acoustic_v1']['coverage_mask'] for tid in case['candidates']]
            decoded.append(dict(case_id=cid, category=case['category'], choice=choice, selected=selected,
                aspect=answer['aspect'], confidence=answer['confidence'], predictions=predictions,
                agreement={a: None if choice not in ('A', 'B') or p is None else selected == p
                           for a, p in predictions.items()}, missing_data=any(m != '111111111' for m in masks),
                same_coverage_mask=masks[0] == masks[1], algorithms_disagree=len(set(predictions.values())) > 1))
        reviewers.append(dict(reviewer=rid, unique_cases=decoded, repeats=repeats,
                              all=descriptive_counts(decoded), missing=descriptive_counts([r for r in decoded if r['missing_data']]),
                              complete=descriptive_counts([r for r in decoded if not r['missing_data']]),
                              disagreements=descriptive_counts([r for r in decoded if r['algorithms_disagree']]),
                              optional_aspects=dict(Counter(r['aspect'] or 'unspecified' for r in decoded)),
                              optional_confidence=dict(Counter(str(r['confidence']) for r in decoded))))
        unique[rid] = originals
    cross = []
    for a, b in itertools.combinations(sorted(unique), 2):
        for cid in cases:
            x, y = unique[a][cid], unique[b][cid]
            cross.append(dict(reviewers=[a, b], case_id=cid, choices=[x, y],
                              consistent=None if x is None or y is None else x == y))
    count = sum(sum(v is not None for v in r.values()) for r in unique.values())
    all_rows = [row for reviewer in reviewers for row in reviewer['unique_cases']]
    return dict(schema=SCHEMA, status='DESCRIPTIVE PILOT ONLY' if count else 'NOT RUN',
                answered_unique_presentations=count, reviewers=reviewers, between_reviewers=cross,
                descriptive_totals=descriptive_counts(all_rows),
                population_accuracy='NOT RUN', recall_at_k='NOT RUN', training='NOT RUN',
                limitations=frozen['limitations'])


def cpu_seconds():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def rss_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('freeze')
    p = sub.add_parser('prepare'); p.add_argument('--manifest', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('analyze'); p.add_argument('--key', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('responses', nargs='*', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMBA_NUM_THREADS'): os.environ[name] = '2'
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    def offline(event, args):
        if event.startswith('socket.'): raise RuntimeError('Offline only')
    sys.addaudithook(offline)
    if args.cmd == 'freeze': write_new(HERE / 'frozen.json', make_freeze())
    elif args.cmd == 'prepare': prepare(args.manifest, args.out)
    else: write_new(args.out, analyze(args.key, args.responses))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as error:
        print('BLOCKED:', str(error), file=sys.stderr)
        raise SystemExit(2)

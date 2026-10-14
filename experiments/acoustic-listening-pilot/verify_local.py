"""Read-only private package verification. No listening judgments or saved answers."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import resource
import struct
import time

import pilot as p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); start = time.perf_counter()
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    key = p.read_json(args.run/'organizer-key.json'); receipt = p.read_json(args.run/'preparation.json')
    frozen = p.verify_freeze()
    p.require(key['frozen_sha256'] == p.digest(frozen) == receipt['frozen_sha256'], 'Freeze mismatch')
    by_id = {r['id']:r for r in receipt['receipts']}
    checked = 0; html_hashes = {}
    for slot in (1, 2):
        name = f'listener-{slot}.html'; path = args.run/name
        p.require(path.stat().st_mode & 0o077 == 0, 'Private page permissions')
        html_hashes[name] = p.file_hash(path)
        p.require(html_hashes[name] == receipt['html_sha256'][name], 'Page drift')
        html = path.read_text()
        script = html.split('<script>',1)[1].split('</script>',1)[0]
        p.require(base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() in html, 'Invalid CSP script hash')
        data = json.loads(script[len('const PILOT = '):].split(';\n/* Pure response contract',1)[0])
        entry = key['reviewers'][data['reviewer']]
        public = {k:v for k,v in data.items() if k != 'clips'}
        p.require(public == entry['package'], 'Different reviewer contract')
        clips = {}
        for alias, encoded in data['clips'].items():
            raw = base64.b64decode(encoded, validate=True)
            p.require(raw[:4] == b'RIFF' and raw[8:16] == b'WAVEfmt ' and raw[36:40] == b'fact' and raw[48:52] == b'data', 'Metadata/chunks')
            fmt, channels, sr, rate, align, bits = struct.unpack('<HHIIHH', raw[20:36])
            frames = struct.unpack('<I',raw[44:48])[0]
            p.require(fmt == 3 and bits == 32 and frames == sr*15 and len(raw) == 56+frames*channels*4, 'Window/format')
            # Native local decoder independently accepts the browser stimulus format.
            import soundfile as sf
            with sf.SoundFile(io.BytesIO(raw)) as audio:
                p.require(audio.frames == frames and audio.samplerate == sr and audio.channels == channels, 'Decode mismatch')
            clips[alias] = hashlib.sha256(raw).hexdigest()
        for presentation, trial in zip(data['trials'], entry['trials']):
            p.require(presentation['token'] == trial['token'], 'Trial order')
            for role in ('X','A','B'):
                p.require(clips[presentation[role]] == by_id[trial[role]]['clip_sha256'], 'Wrong stimulus mapping')
                checked += 1
        without_audio = dict(public)
        exposed = json.dumps(without_audio) + html.split('<script>',1)[0] + (p.HERE/'app.js').read_text()
        for forbidden in (*by_id, 'Joth', 'Junkala', 'Spring Spring', 'Bossa Nova', 'Funked Up',
                          'attribution', 'source_url', 'conditional_score', 'coverage_mask', '/home/', '/tmp/'):
            p.require(not re.search(r'(?<![a-zA-Z0-9])'+re.escape(forbidden)+r'(?![a-zA-Z0-9])', exposed), 'Metadata leak')
        p.require(all(t['choice'] is None for t in p.empty_response(public)['responses']), 'Assigned answers')
        p.require(len(clips) == 10, 'Expected ten originals')
        del html, script, data
    p.write_new(args.out, dict(status='PASS', windows=10, private_packages=2, checked_role_mappings=checked,
        metadata='No identifying fields in presentation, script or WAV chunks', audio_format='WAVE IEEE_FLOAT32',
        source_and_evidence_preflight=receipt['status'], frozen_sha256=p.digest(frozen), html_sha256=html_hashes,
        human_responses_created=0, human_evaluation='NOT RUN', cpu_seconds=p.cpu_seconds(),
        peak_rss_mib=p.rss_mib(), wall_seconds=time.perf_counter()-start))
    print('PASS: 84 role mappings, 10 exact 15 s clips per package, anonymous schema/CSP/WAV')


if __name__ == '__main__': main()

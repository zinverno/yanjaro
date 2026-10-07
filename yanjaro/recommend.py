"""Bounded, local rule-based finite mixes. No claim of learned audio similarity."""
import random
import time
from .storage import account_path, read_json, write_json

DAYS = 90
MAX_EVENTS = 5000
MAX_CANDIDATES = 180


class Profile:
    def __init__(self, uid='', persistent=False):
        self.path = account_path(uid, 'experiment.json') if uid and persistent else None
        self.data = read_json(self.path) if self.path else {}
        self.data.setdefault('enabled', False)
        self.data.setdefault('balance', .5)
        self.data.setdefault('ratings', {})
        self.data.setdefault('events', [])
        self.data.setdefault('seeds', [])
        self.prune()

    def prune(self):
        since = time.time() - DAYS * 86400
        self.data['events'] = [e for e in self.data['events'] if e['at'] >= since][-MAX_EVENTS:]
        self.data['ratings'] = {id:r for id,r in self.data['ratings'].items() if r['at'] >= since}

    def save(self):
        self.prune()
        if self.path:
            write_json(self.path, self.data)

    def record(self, play_id, track_id, source, seconds, cause):
        if not self.data['enabled'] or any(e['play'] == play_id for e in self.data['events']):
            return
        self.data['events'].append(dict(play=play_id, id=track_id, at=time.time(), source=source,
                                        seconds=round(seconds, 2), cause=cause))
        self.save()

    def rate(self, id, value):
        if self.data['enabled'] and id and value in (-2,-1,0,1):
            if value:
                self.data['ratings'][id] = dict(value=value, at=time.time())
            else:
                self.data['ratings'].pop(id, None)
            # ponytail: bounded local v0 profile; database only if a larger history is needed.
            self.data['ratings'] = dict(sorted(self.data['ratings'].items(), key=lambda p:p[1]['at'])[-2000:])
            self.save()


def mix(candidates, liked_ids, profile, seed, now=None, limit=30):
    now = time.time() if now is None else now
    rng = random.Random(seed)
    events, ratings = profile['events'], profile['ratings']
    latest = {}
    for event in events:
        if event['seconds'] > 0:
            latest[event['id']] = max(latest.get(event['id'],0), event['at'])
    previous = max(latest, key=latest.get) if latest else None
    balance = max(0, min(profile['balance'], 1))
    pool = {}
    familiar = {a['id'] for row in candidates if row['id'] in liked_ids or 'seed' in row.get('origins', [])
                for a in row.get('artists', [])}
    for row in candidates[:MAX_CANDIDATES]:
        id = row['id'].split(':')[0]
        if not row['available'] or ratings.get(id,{}).get('value') == -2 or id == previous:
            continue
        if id in pool:
            continue
        liked = id in liked_ids
        age = (now - latest[id]) / 86400 if id in latest else None
        vote = ratings.get(id,{}).get('value',0)
        skips = sum(e['id'] == id and e['cause'] == 'manual-skip' and e['seconds'] < 30 for e in events)
        score = (1-balance if liked else balance) * 2 + vote * 3 - min(skips,3) * .2
        score += .7 * bool(familiar.intersection(a['id'] for a in row.get('artists', [])))
        if age is not None:
            score += min(age / 30,1) * .5 - max(0, 1-age) * 2
        score += rng.random() * .2
        origins = row.get('origins', ['liked'])
        if liked:
            reason = 'Из любимого, давно не слушали' if age is not None and age >= 7 else 'Из любимого'
        elif 'artist' in origins:
            reason = 'Другие песни знакомого исполнителя'
        elif 'album' in origins:
            reason = 'Из альбома исходного трека'
        else:
            reason = 'Выбранный вами исходный трек'
        pool[id] = (score, dict(row, id=id, reason=reason, origins=origins))
    ranked = sorted(pool.values(), key=lambda item: (-item[0], item[1]['id']))
    result, counts, last_artists = [], {}, set()
    while ranked and len(result) < limit:
        selected = None
        for index, (_, row) in enumerate(ranked):
            artists = {a['id'] for a in row.get('artists', [])}
            if artists & last_artists or any(counts.get(a,0) >= 3 for a in artists):
                continue
            selected = index
            break
        if selected is None:
            break  # A small/diversity-limited pool stays smaller, never padded with duplicates.
        _, row = ranked.pop(selected)
        result.append(row)
        last_artists = {a['id'] for a in row.get('artists', [])}
        for artist in last_artists:
            counts[artist] = counts.get(artist,0) + 1
    return result

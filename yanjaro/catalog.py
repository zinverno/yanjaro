"""Conservative UI station groups. Unknown IDs remain visible in Other."""
GROUPS = ('Жанры', 'Настроение', 'Занятия', 'Для детей', 'Музыка стран и народов', 'Другие')


def classify(id, parent='', origin=''):
    family, _, tag = id.partition(':')
    ancestors = {id, parent}
    if ancestors & {'genre:children', 'genre:childrens', 'genre:kids', 'genre:lullaby', 'activity:children'}:
        return 'Для детей', 'children'
    if ancestors & {'genre:folk', 'genre:world', 'genre:ethnic'}:
        return 'Музыка стран и народов', 'world'
    if ancestors & {'genre:rock', 'genre:metal', 'genre:punk'}:
        return 'Жанры', 'guitar'
    if ancestors & {'genre:piano', 'genre:classicalpiano'}:
        return 'Жанры', 'piano'
    if id in {'activity:sleep', 'mood:sleep', 'activity:relax'}:
        return 'Занятия' if family == 'activity' else 'Настроение', 'moon'
    if id in {'activity:sport', 'activity:running', 'activity:workout'}:
        return 'Занятия', 'sport'
    return {'genre': ('Жанры','music'), 'mood': ('Настроение','mood'),
            'activity': ('Занятия','activity')}.get(family, ('Другие','music'))


def station_groups(rows, preferences, query=''):
    pins = preferences.get('pins', [])
    hidden = set(preferences.get('hidden', []))
    recent = preferences.get('recent', {})
    decorated = [dict(r, pinned=r['id'] in pins, hiddenTop=r['id'] in hidden) for r in rows]
    if query.strip():
        found = [r for r in decorated if query.casefold().strip() in r['title'].casefold()]
        return [dict(title='Результаты по всему каталогу', rows=found)] if found else []
    by_id = {r['id']:r for r in decorated}
    pinned = [by_id[id] for id in pins if id in by_id and id not in hidden]
    used = {r['id'] for r in pinned}
    top = [r for r in decorated if r['id'] in recent and r['id'] not in hidden | used]
    top.sort(key=lambda r: (recent[r['id']]['last'], recent[r['id']]['count']), reverse=True)
    top = top[:8]
    used.update(r['id'] for r in top)
    groups = [dict(title='Закреплено на этом устройстве', rows=pinned), dict(title='Недавно слушали', rows=top)]
    for title in GROUPS:
        groups.append(dict(title=title, rows=[r for r in decorated if r['id'] not in used and r.get('group','Другие') == title]))
    return [g for g in groups if g['rows']]

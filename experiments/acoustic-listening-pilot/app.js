/* Pure response contract is shared with Node tests. No predictions or answer key. */
'use strict';
const ResponseContract = (() => {
  const choices = ['A', 'B', 'tie', 'neither', 'uncertain'];
  const aspects = ['rhythm', 'tempo', 'timbre', 'energy', 'combination'];
  function fields(value, names) {
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        Object.keys(value).sort().join('|') !== names.slice().sort().join('|')) throw Error('Unexpected fields');
  }
  function empty(p) {
    return {schema:p.schema, kind:p.kind, reviewer:p.reviewer, package:p.package, position:0,
      responses:p.trials.map(t => ({token:t.token, choice:null, aspect:null, confidence:null}))};
  }
  function validate(s, p) {
    fields(s, ['schema','kind','reviewer','package','position','responses']);
    for (const k of ['schema','kind','reviewer','package']) if (s[k] !== p[k]) throw Error('Another session or schema');
    if (!Number.isInteger(s.position) || s.position < 0 || s.position >= 14 ||
        !Array.isArray(s.responses) || s.responses.length !== 14) throw Error('Invalid position/length');
    s.responses.forEach((r,i) => {
      fields(r, ['token','choice','aspect','confidence']);
      if (r.token !== p.trials[i].token || !(r.choice === null || choices.includes(r.choice)) ||
          !(r.aspect === null || aspects.includes(r.aspect)) || !(r.confidence === null ||
            (Number.isInteger(r.confidence) && r.confidence >= 1 && r.confidence <= 5))) throw Error('Invalid response');
    });
    return s;
  }
  function csv(s) {
    const fields = ['schema','kind','reviewer','package','position','token','choice','aspect','confidence'];
    const quote = x => '"' + String(x ?? '').replaceAll('"','""') + '"';
    return fields.join(',') + '\n' + s.responses.map(r => [s.schema,s.kind,s.reviewer,s.package,s.position,
      r.token,r.choice,r.aspect,r.confidence].map(quote).join(',')).join('\n') + '\n';
  }
  return {empty, validate, csv};
})();
if (typeof module !== 'undefined') module.exports = ResponseContract;
if (typeof document !== 'undefined' && typeof PILOT !== 'undefined') {
  const $ = id => document.getElementById(id);
  const storageKey = 'acoustic-listening:' + PILOT.reviewer + ':' + PILOT.package;
  let state = ResponseContract.empty(PILOT), lastSaved = null, conflict = false;
  let currentUrl = null;
  function status(text, error=false) { $('status').textContent = text; $('status').classList.toggle('error',error); }
  try {
    lastSaved = localStorage.getItem(storageKey);
    if (lastSaved) state = ResponseContract.validate(JSON.parse(lastSaved), PILOT);
  } catch {
    conflict = true;
    status('Сохранённое состояние недоступно или повреждено. Оно не перезаписано. Используйте экспорт / восстановление JSON.', true);
  }
  function save() {
    ResponseContract.validate(state, PILOT);
    try {
      if (conflict || localStorage.getItem(storageKey) !== lastSaved) {
        conflict = true; throw Error('Storage conflict');
      }
      const next = JSON.stringify(state);
      localStorage.setItem(storageKey,next); lastSaved = next;
      status('Сохранено локально. Ничего не отправлено.');
    } catch {
      status('Автосохранение недоступно или другая вкладка изменила ответы. Экспортируйте JSON, чтобы не потерять изменения.', true);
    }
  }
  function stop() {
    $('player').pause(); $('player').removeAttribute('src'); $('player').load();
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = null; $('playing').textContent = 'Выберите фрагмент.';
  }
  function show() {
    stop();
    const r = state.responses[state.position];
    document.querySelectorAll('[name=choice]').forEach(el => el.checked = el.value === r.choice);
    $('aspect').value = r.aspect ?? ''; $('confidence').value = r.confidence ?? '';
    const count = state.responses.filter(v => v.choice !== null).length;
    $('progress').textContent = `Сравнение ${state.position+1} из 14 · ответов ${count} из 14`;
    $('previous').disabled = state.position === 0; $('next').disabled = state.position === 13;
    $('finished').hidden = count !== 14;
  }
  $('start').onclick = () => { $('intro').hidden = true; $('study').hidden = false; show(); };
  for (const [id,delta] of [['previous',-1],['next',1]]) $(id).onclick = () => {
    state.position = Math.max(0,Math.min(13,state.position+delta)); save(); show();
  };
  document.querySelectorAll('[name=choice]').forEach(el => el.onchange = () => {
    state.responses[state.position].choice = el.value; save();
    const count = state.responses.filter(v => v.choice !== null).length;
    $('progress').textContent = `Сравнение ${state.position+1} из 14 · ответов ${count} из 14`;
    $('finished').hidden = count !== 14;
  });
  for (const id of ['aspect','confidence']) $(id).onchange = () => {
    state.responses[state.position][id] = $(id).value === '' ? null :
      (id === 'confidence' ? Number($(id).value) : $(id).value); save();
  };
  $('clear').onclick = () => {
    Object.assign(state.responses[state.position],{choice:null,aspect:null,confidence:null}); save(); show();
  };
  document.querySelectorAll('[data-play]').forEach(button => button.onclick = async () => {
    stop();
    const letter = button.dataset.play, alias = PILOT.trials[state.position][letter];
    const raw = atob(PILOT.clips[alias]), bytes = Uint8Array.from(raw,c => c.charCodeAt(0));
    currentUrl = URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
    $('player').src = currentUrl; $('playing').textContent = 'Фрагмент ' + letter;
    try { await $('player').play(); }
    catch { status('Нажмите Play в проигрывателе. Если звук не появился, экспортируйте прогресс и сообщите организатору.',true); }
  });
  function download(format) {
    ResponseContract.validate(state,PILOT);
    const payload = format === 'json' ? JSON.stringify(state,null,2) + '\n' : ResponseContract.csv(state);
    const url = URL.createObjectURL(new Blob([payload],{type:format === 'json' ? 'application/json' : 'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url;
    link.download = 'listening-' + PILOT.reviewer + '.' + format;
    link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
    status('Экспорт создан локально. Передача организатору — только по вашему решению.');
  }
  $('json').onclick = () => download('json'); $('csv').onclick = () => download('csv');
  $('restore').onclick = () => $('import').click();
  $('import').onchange = async () => {
    const file = $('import').files[0]; if (!file) return;
    try {
      if (file.size > 65536) throw Error('Too large');
      const restored = ResponseContract.validate(JSON.parse(await file.text()), PILOT);
      if (!confirm('Заменить текущий прогресс резервной копией этого же слушателя?')) return;
      state = restored;
      try { lastSaved = localStorage.getItem(storageKey); conflict = false; } catch { conflict = true; }
      save(); show();
    } catch { status('Файл не принят: другая сессия, повреждённые или лишние поля. Текущий прогресс сохранён.',true); }
    finally { $('import').value = ''; }
  };
  $('withdraw').onclick = () => {
    if (!confirm('Удалить все ответы этой страницы из браузера? Скачанные копии нужно удалить отдельно.')) return;
    try { localStorage.removeItem(storageKey); lastSaved = null; conflict = false; }
    catch { status('Не удалось удалить сохранённое состояние. Используйте настройки браузера.',true); return; }
    state = ResponseContract.empty(PILOT); show(); status('Ответы удалены. Скачанные копии удаляются отдельно.');
  };
  if (PILOT.kind !== 'human-self-report') status('TECHNICAL TEST ONLY — не человеческая оценка');
}

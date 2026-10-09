# Форматы v0.1

Общая схема: `yanjaro.listening.v0.1`. JSON UTF-8, только конечные числа; неизвестные оценки — `null`, отсутствие тегов — `[]` с семантикой unknown. Авторитетны проверки Python и unit-тесты; свободные дополнительные поля в ответах запрещены.

## Частные исследовательские файлы

- `sample.json`: `schema`, boolean `demo`, `metadata_provenance`, `tracks`. Каждый track: neutral `id`, `artist_id`, положительные `genre`/`instrument`, локальный `path`, `start`, `seconds`, `rights`. Пример с неподтверждёнными правами намеренно отклоняется.
- `catalog.json`: `schema`, `demo`, `sample_sha256`, `metadata_provenance`, `tracks`; clip/source hashes, путь, границы, gain, права, raw/rendered features. Файлы записи не переносятся из пути TSV автоматически.
- `review.json`: `schema`, `catalog_sha256`, `policy`, `pairs`, добавленный вручную `trials`. Pair: source/candidate, provisional condition, дистанции, coverage reason, review. Итоговый review хранится отдельно от ответов; `freeze` сверяет его hash и классификацию с исходными признаками.
- `study.json`: immutable `study_id`, `sha256`, `demo`, `phase` (`demo`/`pilot`/`confirmatory`), seed, `assignment_version`, policy, catalog/review hashes, map tracks и массив trials. Trial: `id`, `kind` (`primary`/`control`), `source`, `first`, `second`. Для primary first=A/second=B; control first=C/second=D. Часть first/second скрыта от браузера. Форматы и code commit закрепить перед набором.

Права и локальные пути остаются у исследователя, не передаются слушателю или в ответы. Все реальные файлы держать вне Git. JSON writer создаёт файлы `0600`, новый audio-каталог `0700`; браузерный download управляется правами ОС, его приватность исследователь проверяет отдельно. CLI не заменяет предыдущий результат. Хэши защищают от случайного изменения, не от умышленной подделки оператором.

## Публичная локальная проекция

`/session`: schema, study_id/hash, demo, phase, slot, prompt_id, текст вопроса, trials (`id`, `source`, `left`, `right`). Аудио-URL — `/audio/<opaque hash>`, без ролей A/B/C/D, названий, артистов, жанров, признаков и локальных путей. Реальная слепота требует нейтральных `study_id`/trial IDs и отсутствия подсказок оператора. Это слепота для слушателя, не ослепление исследователя.

## Анонимный экспорт

```json
{
  "schema": "yanjaro.listening.v0.1",
  "study_id": "demo-v0_1",
  "study_sha256": "<64 hex characters from the frozen manifest>",
  "demo": true,
  "phase": "demo",
  "slot": 0,
  "prompt_id": "next",
  "participant_id": "<random UUIDv4 generated only after consent>",
  "status": "complete",
  "answers": [
    {"trial_id": "t00", "choice": "left", "heard": {"source": true, "left": true, "right": true}}
  ]
}
```

Это фрагмент, не валидный полный ответ: нужны все задания в назначенном порядке. `choice`: left/right/neither/skip. Heard — только три boolean, без временных меток, IP, устройства, аккаунта, токенов или свободного текста. Нельзя вычислить реальную личность из UUID без внешних сведений, но передача по личному каналу может раскрыть её исследователю: организационно отделить передачу от файла.

`analyze` проверяет exact allowlist всех response/answer/heard полей, UUIDv4, hash, phase, prompt, slot, полный порядок заданий, отсутствие повторного participant ID или slot в одном вопросе. Для содержательного ответа нужны три heard=true. Это контроль целостности формата, не доказательство внимательности/уникальности человека или аутентичности голосов. Изменённые, смешанные версии, незавершённые/отозванные файлы отклоняются; они не игнорируются незаметно.

После отказа нет сохраняемой withdrawal-записи. Для missingness оператор ведёт только отдельные агрегаты приглашений/согласий/отказов, без связи с личностью. Не публиковать сырой экспорт реального участника. Анализ группирует два вопроса раздельно, сохраняет demo/phase/hash, bootstrap seed/draws и условные/безусловные знаменатели.

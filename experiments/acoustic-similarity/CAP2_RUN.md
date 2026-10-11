# Единственный разрешённый cap2 run

Пользователь явно разрешил один ограниченный CPU fit/evaluation после HEAD
`15e911d829a6f3683129de2bfcac37e47f55e995`. Исторический
[next-run-proposal.json](validation/groove-diagnostics-v1/next-run-proposal.json)
сохранён неизменным: его `NOT AUTHORIZED` описывает состояние прошлого этапа,
а текущее разрешение получено отдельной инструкцией пользователя.

## До запуска

- HEAD локальной ветки и draft PR #10 совпал с ожидаемым.
- ZIP SHA-256: `72a1f4505afcc095d3ffaddd3cdc354cc1718c08861313fd91bfb6788b7fc79e`.
- Canonical proposal SHA-256:
  `3b1167534a85af7b043b792db8b1b2160b2d3c48aad33803d518510ce3c2d346`.
- Проверены source/model/features/targets identities и исторический training code.
- [Локальный MIDI-only preflight](validation/groove-cap2-v1/preflight-local.json)
  использует только ранее полученный официальный MIDI ZIP: **PASS, 3 оригинала,
  12 тактов, 29 допустимых triplets**, новых сетевых данных 0 байт.
- Нет пересечения original IDs, drummer и MIDI SHA-256 со всеми прежними splits.
  Аудиохеши будут проверены после получения, до извлечения/обучения.
- Triplets SHA-256:
  `9b05777ec3cfa5ff727c55489a65bf60b0b0cdbf748f85f56a04fae59a971480`.

Единственная конфигурация: **300 full-batch Adam steps, lr=0.1, L2=0.01,
margin=0.05, temperature=0.1, logits ±ln(2)/2**. Ровно прежние 332 train-triplets
и 140 тактов, без изменения признаков. Старый test drummer8 исключён из вычислений.
Модель сохраняется до validation и нового test; результаты не выбирают параметры.

## Ограничения запуска

Разрешён только `acoustic-similarity.yml`, **run_number=5, run_attempt=1**, PR #10,
та же ветка и repository, `cap2-pilot`, событие synchronize. Checkout должен иметь
ровно указанный исходный HEAD в качестве родителя. Внутри процесса повторная
проверка контекста и create-only каталога; нет CLI-режима обхода. Новый push имеет
другой run_number, manual rerun увеличивает run_attempt: оба отвергаются.
[Семантика GitHub run_number/run_attempt](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts).
После выполнения job снова будет явно отключён.

- Standard ubuntu-24.04 CPU runner, два вычислительных потока.
- Job wall ≤10 min, command timeout 540 s +10 s grace; CPU soft/hard 590/600 s,
  virtual memory ≤4 GiB. SIGTERM/SIGXCPU сохраняют failure receipt, если процесс
  ещё может исполнить finally; hard kill может оставить только журнал Actions.
- Получение данных: MIDI → preflight → pinned ZIP directory → только три WAV.
  На любой ошибке остановка без повтора; никаких redirects/full-archive fallback.
- Источники — только URL/immutable generation/ETag зафиксированного плана;
  metadata, MIDI SHA, directory SHA, ZIP member size/offset/CRC и audio SHA проверяются.
- Source HTTP bodies ≤**40 834 108 bytes**. Входной training artifact учитывается
  как 382 152 bytes. Ещё 2 MiB зарезервированы для передачи результатов и transport;
  сумма 43 313 412 <44 040 192 bytes (**42 MiB**). Проверка до каждого запроса.
- ZIP результата ≤64 KiB, его base64-передача <88 KiB, получение журнала ≤256 KiB.
  Их сумма меньше половины 2 MiB резерва. После получения будут указаны фактические
  размеры. HTTP/TLS overhead отдельно не измеряется; резерв не выдаётся за измерение.
- Git fetch и pip без автоматических повторов; используется уже установленный
  Python 3.12.13, без fallback-загрузки runtime. Зависимости и checkout, кроме учтённого
  research artifact, не входят в корпусный бюджет согласно исходному плану.

## Сохранение результата

Результат передаётся одним ZIP через native workflow log, в ограниченных строках
`CAP2_RESULT_DATA`; checksum/длина указаны в `CAP2_RESULT_START`. Это не исходное
аудио: allowlist включает только JSON модели, метрик, 12 test vectors/targets,
provenance, acquisition/resource/status receipts и hashes. После одного получения
журнала ZIP проверяется и сохраняется в ветке. Полные WAV и runtime credentials
не записываются в архив или логи; артефакты не содержат приватных рабочих путей.

Причина выбора транспорта: стандартный artifact SDK имеет автоматические
[повторы HTTP](https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/shared/artifact-twirp-client.ts),
которые не соответствуют запрету retries. Здесь нет artifact SDK/API uploader;
ошибка получения журнала не приводит к повторному обучению.

## Статус

Remote training/evaluation: **NOT RUN** до единственного разрешённого запуска.
Новый test содержит одного исполнителя, три связанные записи при 88 BPM и один
TD-11 kit. Даже положительный результат будет относиться только к этому cohort,
не к полноценным песням, тембровой универсальности или популяции исполнителей.

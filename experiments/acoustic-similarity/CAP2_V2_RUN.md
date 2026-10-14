# Cap2 v2: обучение выполнено, улучшение FAIL

Одна новая разрешённая попытка выполнена 2026-10-14:
[Actions run 38535139426, attempt 1](https://github.com/zinverno/yanjaro/actions/runs/38535139426),
[cap2-pilot job 115756440243](https://github.com/zinverno/yanjaro/actions/runs/38535139426/job/115756440243).
Источник — `7e541c2b52617b54135568c204246fbd44a27902`, родитель —
`0d8955f1788521f6458a64ceea3ba7db8e09b9ba`. Training job отключён сразу после
завершения отдельным commit `564330d762819f44a6ac5252eaac8ea7da19ec4d`.

Новый test дал **34,48% uniform против 27,59% cap2**, разница **−6,90 процентного
пункта**. Сохранён `FAIL: no improvement`; параметры после test не менялись.
Успех Actions означает завершённое измерение, а не положительный научный результат.

## Проверки и неизменная конфигурация

| Этап | Статус |
|---|---|
| Исходный HEAD, чистый checkout и открытый draft PR #10 | PASS |
| SHA исходного ZIP и frozen proposal | PASS |
| Python 3.12.13 через pinned setup-python внутри cap2 job | PASS |
| Hash-locked dependencies и pip check | PASS |
| Повторный MIDI-only preflight до WAV | PASS: 3 originals, 12 bars, 29 triplets |
| Metadata, MIDI SHA, directory SHA, ETag, ranges, ZIP CRC | PASS |
| Разделение performers/originals/MIDI/audio hashes | PASS |
| Единственный fit, сохранение модели до held-out оценки | PASS |
| Validation drummer7 и новый test drummer6 | PASS: измерены без настройки |
| Улучшение независимого test | FAIL |
| Старый test drummer8 | NOT RUN; исторические файлы неизменны |
| Модель, metrics, provenance, hashes и bounded JSON ZIP | PASS |
| Отключение обучения, запрет rerun | PASS |
| Качество на полноценной музыке, слуховая оценка | NOT RUN |

Использованы прежние **332 train-triplets / 140 bars / 128 features**; признаков
train заново не извлекали. **300 full-batch Adam steps, learning rate 0.1, L2 0.01,
margin 0.05, temperature 0.1, logits ±ln(2)/2**, нулевые начальные logits.
Фактическое максимальное отношение весов **2.0**. Validation использован только
для отчёта. Ни нового поиска конфигураций, ни early stopping не было.

Входной `validation/groove-cpu-v1/artifacts.zip`:
`72a1f4505afcc095d3ffaddd3cdc354cc1718c08861313fd91bfb6788b7fc79e`.
Исправлен только ошибочный SHA в пользовательском разрешении; сам ZIP и все
исторические контрольные суммы сохранены. Frozen proposal также не изменён.

Разрешение `cap2-2026-10-14-v2` привязано к **run_number=9 / attempt=1**, PR #10,
ветке, repository, job, synchronize event, указанному родителю и create-only
`runs/groove-cap2-v2`. Исторический run 38135097182 не перезапускался.
[Исходное разрешение](validation/groove-cap2-v2/authorization.json) и
[receipt об исполнении и расходовании разрешения](validation/groove-cap2-v2/execution.json)
хранятся отдельно. Unit-проверка ablation использует синтетический fixture, чтобы
CI не выполнял дополнительные реальные fits cap2; её проверки границ сохранены.

## Независимый test: drummer6, 88 BPM

| Модель | Сравнения | Правильно | Ошибки | Ничьи | Accuracy |
|---|---:|---:|---:|---:|---:|
| Uniform | 29 | 10 | 19 | 0 | 34,4828% |
| Cap2 | 29 | 8 | 21 | 0 | 27,5862% |

Разница cap2 − uniform: **−6,8966 п.п.** Ничья определяется фиксированным
epsilon `1e-12` и даёт половину балла; в этом test ничьих нет.

Группировка по исходному оригиналу anchor не пересекается и суммируется в 29:

| Anchor original | N | Uniform: верно / ошибки / ничьи | Cap2: верно / ошибки / ничьи | Accuracy uniform → cap2 |
|---|---:|---:|---:|---:|
| drummer6/session2/3 | 12 | 6 / 6 / 0 | 5 / 7 / 0 | 50,00% → 41,67% |
| drummer6/session3/6 | 16 | 3 / 13 / 0 | 2 / 14 / 0 | 18,75% → 12,50% |
| drummer6/session3/7 | 1 | 1 / 0 / 0 | 1 / 0 / 0 | 100,00% → 100,00% |

Все три оригинала составляют **одну связанную компоненту**: 29 сравнений,
uniform 10/29, cap2 8/29. Каждый triplet затрагивает все три оригинала; поэтому
`touching_*` показатели для каждого равны итоговым и не являются тремя независимыми
выборками. Один drummer, две sessions, rock и TD-11 — ограничения этого результата.

Validation drummer7: uniform **227/247**, 20 ошибок, 0 ничьих, **91,9028%**;
cap2 **226/247**, 21 ошибка, 0 ничьих, **91,4980%**; разница **−0,4049 п.п.**
Полные показатели по исходным оригиналам, компонентам и всем triplet margins
сохранены в [metrics.json](validation/groove-cap2-v2/metrics.json).

## Фактические ресурсы и передача

| Показатель | Измерение |
|---|---:|
| Cap2 job wall, включая setup и зависимости | 25 s |
| Тело экспериментального процесса | 3,959760 s wall / 0,635294 CPU s |
| CPU процесса с импортами | 1,223925 s |
| Единственный fit | 0,012511 s wall |
| Peak RSS / peak virtual memory | 192,332 / 454,348 MiB |
| Виртуальная память, установленный предел | 4096 MiB |
| CPU soft/hard limit | 590 / 600 s |
| Вычислительные потоки / GPU | 2 / нет |
| Source HTTP response bodies, 11 запросов без повторов | 40 834 108 bytes |
| Входной training ZIP, frozen charge | 382 152 bytes |
| Новый result ZIP / переданный base64 payload | 39 177 / 52 236 bytes |
| Успешно полученный журнал | 75 502 bytes |

Новые source bodies состоят из MIDI **3 260 318**, ZIP directory **286 439**
и трёх выбранных WAV members с заголовками **37 287 351 bytes**. Получались только
разрешённые ranges; полный архив не скачивался, source retries — **0**.

Сумма известных payload/charge в frozen scope — **41 343 998 bytes**.
Первое получение завершённого журнала было отклонено CLI из-за terminal escape
sequences; повторное чтение с разрешённым выводом вернуло тот же завершённый job log.
Это **два получения журнала**, а не повтор эксперимента или WAV acquisition.
Размер первого ответа отдельно не измерен: дополнительно учтён полный allowance
**262 144 bytes** для того же журнала, чей размер проверен вторым чтением.
Консервативная сумма с этим allowance — **41 606 142 bytes**.

Frozen source + input + полный резерв transport/output составляет
**43 313 412 bytes (41,3069 MiB)** при пределе **44 040 192 bytes (42 MiB)**.
В резерв 2 MiB входят доставка и сохранение результатов, дополнительное получение
журнала и transport overhead. Полный HTTP/TLS/Git wire traffic отдельно не измерен;
резерв и allowance не выдаются за фактические измерения. CPU/RSS всего runner,
включая установку инфраструктуры, также не измерялись: CPU/RSS выше относятся к
экспериментальному Python-процессу, job wall — ко всему job. Process receipts
сняты после оценки, перед финальной упаковкой ZIP; это не отдельный монитор всего job.

Инфраструктурный трафик **ненулевой и отдельный**: setup-python фактически загрузил
Python 3.12.13, bootstrap pip 26.2.1 и hash-locked wheels. Точные wire bytes этих
загрузок не измерены. Для локальных проверок отдельно получено **55 868 778 bytes**
семи wheels из того же lockfile; это также инфраструктура, не research corpus.
[Исходные ресурсы процесса](validation/groove-cap2-v2/resources.json),
[acquisition receipts](validation/groove-cap2-v2/acquisition.json),
[execution/transport report](validation/groove-cap2-v2/execution.json),
[выдержка журнала](validation/groove-cap2-v2/log-excerpt.txt).

## Сохранённая модель и воспроизводимость

[model.json](validation/groove-cap2-v2/model.json) SHA-256:
`4709a87f6662d180e8ebf623f803074453c5fed98c921ddf872e2a96e2452be0`.

[artifacts.zip](validation/groove-cap2-v2/artifacts.zip) SHA-256:
`6136f79024a45f0fb7e58034fda70ba8da1b1964b8c1d2cfb825749e77f30048`.

ZIP содержит только девять allowlisted JSON: модель, метрики, новые test features
и MIDI targets, preflight, provenance, acquisition/resources/status и hashes.
Исходных WAV нет. Проверены SHA каждого JSON, побайтное соответствие извлечённых
файлов ZIP и counts из сохранённых margins, без нового fit или оценки модели.
`hashes.json` сохранён ровно как выдал runner; `delivery-hashes.json` отдельно
связывает дополнительные документы доставки. Старые weights/features/metrics,
drummer8, модельный и feature-код, lockfile побайтно не изменены.

## Вывод и следующий этап

Гипотеза о преимуществе frozen cap2 на этом независимом test **не подтвердилась**.
Ограничение отношения весов до 2 не предотвратило ухудшение. Даже uniform имеет
низкую accuracy на этой группе, поэтому результат не обосновывает качество
ритмического сходства на полноценных композициях и не устанавливает причину ошибки.

Сохранить uniform как исследовательскую точку отсчёта. Следующим разрабатывать
диагностику соответствия audio features и MIDI targets: beat/window alignment,
чувствительность к фазе и покрытие ритмических различий, используя train/validation
и контролируемые synthetic fixtures. Не подстраивать модель под уже раскрытый
drummer6 test. До следующей модели заранее выделить новые независимые группы
исполнителей/оригиналов и отдельно согласовать человеческую оценку на разрешённых
аудиоданных. Интеграция cap2 в опубликованный плеер этим результатом не обоснована.

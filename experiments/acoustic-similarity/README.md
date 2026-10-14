> **2026-10-14 — выполнен phase-independent rhythm retrieval PI-v1.**
> [Реальный Top-3 для 10/10 CC0-композиций, компоненты и ограничения](RHYTHM_PI_REPORT.md) ·
> [зафиксированная формула](RHYTHM_PI_SPEC.md) · [независимая оценка, пока NOT RUN](RHYTHM_PI_REVIEW.md).
> Поиск работает без downbeat; UNKNOWN tempo у u01 создаёт универсального соседа.
> Качество/accuracy/recall NOT RUN; новых загрузок и обучения нет.

> **2026-10-14 — проверена автоматическая применимость на десяти локальных композициях.**
> [BPM, beat/downbeat candidates, отказы и ограничения](RHYTHM_AUTO_APPLICABILITY.md):
> 2/10 устойчивых AUTO_CANDIDATE, 0/10 VERIFIED, 10/10 отказов strict Rhythm-v2.
> Новое аудио и обучение не запускались; фазонезависимый резерв пока только предложен.

> **2026-10-14 — отдельный rhythm v2, без обучения и новых аудиозагрузок.**
> [Выравнивание, подтверждённые дефекты и диагностика](RHYTHM_V2.md) ·
> [минимальный будущий опыт на полной аранжировке](RHYTHM_V2_FUTURE_EXPERIMENT.md).
> Synthetic timing checks PASS; настоящее v1/v2 train/validation сравнение NOT RUN
> без исходных GMD WAV. Cache-only балансировка: train +7,83 п.п., validation −3,64 п.п.

> **Исторический результат 2026-10-14 — cap2 обучен, улучшение FAIL.** На новом drummer6 test:
> uniform **10/29 (34,48%)**, cap2 **8/29 (27,59%)**, **−6,90 п.п.**
> [Новый отчёт, модель, provenance и ресурсы](CAP2_V2_RUN.md). Один fit, одна test-оценка;
> разрешение использовано, оба real-training jobs отключены. Ниже — история этапов.

> **Исторический runtime-only этап:** [исправление setup-python и smoke-проверка](RUNTIME_SMOKE.md).

> **Cap2: runner setup FAIL, обучение/test NOT RUN.** [Фактический запуск и причина](CAP2_RUN.md).
> Повтора не было; новые веса не созданы, training job отключён.

> **Диагностика train/validation:** [разбор ухудшения, ablations и следующий фиксированный опыт](DIAGNOSTICS.md).
> Новое удалённое обучение и загрузка аудио не запускались; результаты exploratory.

> **Новый результат: реальные CPU rhythm weights обучены, но хуже baseline.**
> Test: 72,73% learned против 88,64% baseline. [Отчёт и веса](CPU_REPORT.md).
> Ниже сохранён исходный отчёт полного multi-aspect эксперимента на HEAD `da55781`;
> он не задаёт предпосылки для первого CPU rhythm обучения.

# Acoustic Similarity Model v0.1

Изолированный исследовательский CLI для сходства звучания. Результат — ранжирование
локальных файлов по ритму/темпу, тембру и энергии/динамике. Предпочтения, реакции
Yambda, жанровая классификация и выбор следующей песни не являются задачей модели.

**Реальное обучение: NOT RUN.** Доступны только 10 проверенных CC0-записей трёх
авторских групп, без согласованных акустических triplet-меток. Владелец подтвердил,
что дополнительных данных и GPU пока нет. Реальных или демонстрационных весов в
репозитории нет. [Отчёт](REPORT.md) разделяет измерения baseline и качество поиска.

## Границы и происхождение

Ветка создана от `main` `1c83c3776de565ed57416015f32a7ddd999af29f`.
Изучены, но не слиты и не изменены:

| PR | Проверенный HEAD | Что использовано |
|---|---|---|
| [#6 Acoustic Lab](https://github.com/zinverno/yanjaro/pull/6) | `6b5f05b4d5ea3aca8b7e4b3aed7980ca46edd695` | `audio.py` скопирован побайтно как `lab_audio.py`; только константы схемы из `__init__.py`. Сессионный preference ranker не перенесён |
| [#7 Yambda](https://github.com/zinverno/yanjaro/pull/7) | `1fbeecb67e7be811983d419ff8197c0afee1d01c` | Учтены ограничения анонимизированных ID, покрытие и необходимость отдельной проверки реального обучения. Код, векторы, лайки/дизлайки не импортированы |
| [#9 Listening Study](https://github.com/zinverno/yanjaro/pull/9) | `65e3e07fe100832ed90c449049b7e4981d214fa4` | Проверены оригиналы, сохранённые страницы лицензий и хеши; сохранены фиксированные окна, неизвестные метки и независимая слуховая проверка |

Изменения находятся только в `experiments/acoustic-similarity/`. Эксперимент не
импортирует плеер, SDK Яндекс Музыки или другие экспериментальные пакеты. Root
зависимости, версии, Release, AUR и инфраструктура не меняются. Render не развёрнут.

## Установка и проверка

Проверено в отдельном Python 3.12.13 / Linux x86_64. `requirements.lock` содержит
версии и хеши всех 26 wheels; это lock именно для этой платформы. Нужен новый venv,
а не окружение опубликованного плеера. Установка Python-пакетов требует сети;
команды анализа и поиска ничего не скачивают.

```sh
cd experiments/acoustic-similarity
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/python -m pip check
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/yanjaro-similarity --help
```

`audioread`, `pooch` и `requests` — транзитивные зависимости librosa; наш decoder
вызывает только `soundfile.SoundFile`, не `librosa.load`, ffmpeg или загрузчики.

## Локальный поиск

1. Скопировать [шаблон manifest](examples/manifest.template.json) в приватный
   каталог вне Git. Для каждого файла указать реальные права, сохранённую страницу
   с её SHA-256, хеш аудио, точное окно и группы исполнителей/записей. Шаблон намеренно
   не проходит проверку прав. Наличие файла само по себе не считается разрешением.
2. Выполнить индексирование явно выбранного списка (без обхода музыкальной папки).
3. Передать один аудиофайл; получить JSON со списком путей и расстояниями компонентов.

```sh
yanjaro-similarity index --manifest /private/corpus.json --out /private/index.json
yanjaro-similarity search /private/song.wav \
  --manifest /private/corpus.json --index /private/index.json --top 10
```

Меньше distance — ближе по выбранной метрике, это не вероятность и не оценка
предпочтения. Сам файл исключается по SHA-256, порядок при равенстве стабилен по ID.
Длительность окна — 10–90 s, decoder — mono/stereo 8–96 kHz. Новому query, которого
нет в индексе, нужен `--query-manifest /private/query.json` с одной разрешённой
записью. При замене байтов аудио/страницы прав проверка завершается с ненулевым кодом.

Для frozen baseline добавить `--embeddings /private/embeddings.json`, для собственной
модели также `--model /private/model.json`. Новый query в этих режимах требует
`--query-embeddings`, полученный тем же энкодером удалённо. Тяжёлое извлечение
эмбеддингов не запускается скрытно на ноутбуке. DSP-only режим работает без модели.

Выходные файлы создаются целиком с правами 0600; существующие файлы не заменяются.
Manifest/index содержат приватные пути: не прикладывать их к PR или публичным CI
артефактам. Для публикации предусмотрен отчёт с разрешёнными полями.

## Повторение проверки десяти CC0

Новых загрузок аудио нет. Нужны прежний приватный каталог и точная публичная квитанция
PR #9. Её ожидаемый SHA-256 зафиксирован в скрипте.

```sh
git show 65e3e07fe100832ed90c449049b7e4981d214fa4:experiments/listening-study/validation/real-audio-v1.json > /private/pr9-receipt.json
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python scripts/cc0_baseline.py \
  --private-root /private/listening-study-private \
  --pr9-receipt /private/pr9-receipt.json --out /private/new-baseline-run
```

Если clone не содержит объект PR #9, сначала получить его в локальные refs через
`git fetch origin experiment/listening-study-v01`; это не слияние веток. Скрипт
отклоняет сетевые операции во время анализа и повторно извлекает признаки для
проверки детерминизма. `baseline-report.json` содержит только ID, публичные источники,
хеши, численные признаки и диагностику; записи, пути, HTML и ответы людей остаются
приватными. Индекс получен из исходного окна до нормализации громкости Listening Study.

## Обучение и оценка

[Архитектура и протокол](PROTOCOL.md), [энкодеры и лицензии](ENCODERS.md),
[расширение данных](DATA.md), [удалённый запуск и масштабирование](REMOTE.md).

На подготовленном удалённом worker, после правового и человеческого review:

```sh
yanjaro-similarity train --remote-worker --manifest /private/corpus.json \
  --index /private/index.json --embeddings /private/embeddings.json \
  --labels /private/labels.json --out /private/model.json
yanjaro-similarity evaluate --manifest /private/corpus.json --index /private/index.json \
  --embeddings /private/embeddings.json --labels /private/labels.json \
  --model /private/model.json --split validation --out /private/validation.json
yanjaro-similarity evaluate --manifest /private/corpus.json --index /private/index.json \
  --embeddings /private/embeddings.json --labels /private/labels.json \
  --model /private/model.json --split test --out /private/test.json
```

Для baseline оценки `--model` не передаётся. Собственная модель автоматически
сравнивается с baseline **на тех же DSP и frozen embeddings**, а не только с более
слабым DSP baseline. Дополнительно сохранить отдельную DSP-only оценку. `evaluate`
без reviewed triplets выдаёт `NOT RUN`, а не нулевое качество. Synthetic training
доступен только тестам через явный аргумент Python API; CLI не принимает такие веса.

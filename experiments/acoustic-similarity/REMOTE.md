# Удалённое выполнение и каталог

## Текущий статус

GPU/удалённого доступа нет. Render, облачные workers, платное хранилище, workflow
dispatch и загрузка весов/корпусов **NOT RUN**. Только лёгкий DSP десяти разрешённых
файлов и тесты малых synthetic arrays выполнялись локально.

Следующий запуск возможен на уже выделенном владельцем GPU worker. Предварительный
план — одна GPU с 16 GiB VRAM, 2 CPU threads, 8 GiB host RAM, batch=1 и окно 5 s.
Это **бюджет-кандидат для probe**, не подтверждённый минимум и не заказ ресурса.
Первый approved probe: не более 20 разрешённых 15 s окон, timeout 10 min, один
процесс. По результату измерить wall/audio seconds и peak CUDA/process memory;
затем отдельно согласовать лимит полного corpus. Нет автоматического autoscaling.

## Подготовка snapshot на worker

1. Владелец согласует конкретные веса, их NC scope, download budget и уже имеющийся
   worker; перенос аудио требует `remote=true` и прав на такой способ анализа.
2. Получить **только** файлы MERT-95M revision
   `12af15fef9d0ac838c3f475bfbbf26d2060dd4f5` из официального источника. Сохранить
   URL/revision/SHA-256 каждого; fairseq checkpoint для этого pipeline не нужен.
   Загрузка не встроена в CLI.
3. Проверить `configuration_MERT.py`, `modeling_MERT.py`, config и license/card.
   В snapshot не должно быть ссылок, выходящих за каталог, или неучтённых файлов.
4. В отдельном окружении worker безопасно конвертировать официальный tensor dict
   в safetensors. При ошибке `weights_only=True` остановиться, не переключать на
   unrestricted pickle. Сохранить source hash и converted hash в receipt.

```python
# Only on the approved worker, with an independently verified source SHA-256.
from pathlib import Path
import torch
from safetensors.torch import save_file
source = Path('/private/source/pytorch_model.bin')
state = torch.load(source, map_location='cpu', weights_only=True)
assert isinstance(state, dict) and all(isinstance(v, torch.Tensor) for v in state.values())
save_file({k: v.contiguous().clone() for k, v in state.items()},
          '/private/mert95/model.safetensors', metadata={'format': 'pt'})
```

Конверсию **не запускали**, её результат не входит в PR. Перед загрузкой требуется
полный receipt со следующими полями: `id`, 40-hex `revision`,
`weights_license="CC-BY-NC-4.0"`, `reviewed_code=true`,
`files={relative_path: sha256}` всех snapshot-файлов (включая config, processor,
код, card/license и converted weights), а также отдельное описание conversion
input/output/toolchain. Receipt хранится вне snapshot; его hash идентифицирует
энкодер в embeddings/model. Флаг reviewed_code проставляет проверяющий после review.

Предлагаемое отдельное окружение: Python 3.12, DSP lock, torch 2.7.1,
transformers 4.38.2, safetensors 0.5.3, nnAudio 0.3.3. GPU wheel/runtime/driver
фиксируются на выбранном worker после smoke. Этот remote набор **не является
проверенным lock**; перед реальным извлечением требуется dependency check,
GPU probe, затем сохранение полного lock/образа и driver/CUDA metadata. Основной
локальный пакет не устанавливает torch/transformers.

## Pipeline на разрешённом worker

```sh
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
# Snapshot уже локален. Никаких HF download внутри команды.
timeout 10m yanjaro-similarity embed --remote-worker --trust-reviewed-code \
  --manifest /private/probe.json --snapshot /private/mert95 \
  --receipt /private/mert95-receipt.json --out /private/probe-embeddings.json
```

`embed` проверяет права всех записей, hashes snapshot и аудио; требует CUDA,
включает HF offline, determinism и выключает TF32. Он не меняет веса энкодера.
Первая версия пишет один create-only JSON после завершения ограниченного manifest;
возобновления внутри файла нет. На большом корпусе предварительно зафиксировать
небольшие manifests по shards с теми же split identities; объединение caches в v0.1
автоматически не реализовано. Для первого corpus 2000 записей подходит один
ограниченный run после probe; не запускать сразу весь каталог.

Следом CPU-команды `index`, `train`, `evaluate` из README выполняются на том же
worker. Обучение маленьких heads не требует GPU, но размещено удалённо согласно
границе владельца. Сохранить всё в приватном run directory: git SHA, lock, права,
dataset/labels hashes, snapshot receipt, features, embeddings, weights, metrics,
время и memory. Публично выносить только проверенные агрегаты и источники.

Окружение должно запрещать сеть во время обработки локальных inputs; HF offline
не является сетевым sandbox для произвольного custom Python. Не помещать токены
Яндекса/облачные credentials в процесс моделирования. Веса использовать только из
проверенной local snapshot. GPU-адаптер в этом PR статически проверен и имеет тесты
границ допуска; настоящий model forward остаётся `NOT RUN`.

## Подключение к реальным ID Яндекс Музыки

Модель принимает waveform/признаки, а не музыкальный ID. ID не содержит ритм/тембр.
PR #7 использует анонимизированные Yambda item IDs и 128-dimensional embeddings
иного пространства; подтверждённого соответствия публичным Yandex track IDs нет.
Нельзя склеить их по числу, названию, порядку строки или считать их MERT-векторами.
Лайки и дизлайки остаются предпочтениями и не используются как acoustic labels.

Для настоящей интеграции нужен отдельный подтверждённый crosswalk:
`provider + catalog ID + recording/version identity + authorized audio hash +
window + feature schema + encoder revision`. Даже совпадающий ISRC требует проверки
мастера/версии. Файл, прослушивание по подписке и доступный preview не доказывают
разрешения на массовое извлечение/хранение аудио и обучение; нужны применимые права
от правообладателя/провайдера. Этот PR не получает signed URLs, streams или аккаунты,
не меняет player и не заявляет ID coverage.

## Почти весь каталог

Нужны разрешённые источники и измеренное покрытие сначала. Текущий локальный CLI
линейно перебирает выбранный каталог и проверяет локальные hashes; это инструмент
исследования, не производственный индекс. Для масштаба потребуются отдельная
разрешённая ingestion-служба, очередь с бюджетом/повторами, immutable shards,
контроль дубликатов/версий, векторный ANN-индекс с exact reranking по компонентам,
удаление отозванных записей и независимая проверка recall/latency/coverage.

Плановая арифметика, **не измерения**: один 1536D float32 vector = 6144 bytes.
Для N=100 млн записей это ~614.4 GB только embeddings, без DSP, ANN, replication
и provenance. По 30 s аудио на запись — 3 млрд audio seconds (~95 лет real-time).
Если измеренный probe даст R audio-seconds/s, идеальное compute time будет 3e9/R
секунд, ещё без I/O/повторов. Денежную стоимость можно оценить лишь после известного
R и тарифа одобренного ресурса. Отсутствующие данные нельзя объявлять покрытыми.

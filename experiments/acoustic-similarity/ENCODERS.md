# Выбор frozen encoder

Проверка первичных источников: 2026-10-11. Это сравнение архитектур, условий весов
и опубликованных размеров, **не** проведённый benchmark качества или скорости.
Веса не скачивались. [Машинная квитанция](validation/encoder-sources.json) фиксирует
revision и размеры из Hugging Face API; время/GPU memory пока `NOT RUN`.

| Кандидат | Представление и пригодность | Условия кода и весов | Вычисления |
|---|---|---|---|
| [MERT-v1-95M](https://huggingface.co/m-a-p/MERT-v1-95M) | Music SSL, 12×768, 24 kHz; frame features пригодны для статистики тембра. Первый кандидат v0.1 | [Код Apache-2.0](https://github.com/yizhilll/MERT/blob/main/LICENSE); веса **CC BY-NC 4.0** по model card | ~95M параметров, HF weights 377,552,987 bytes. Около 380 MB только FP32 weights по расчёту 95M×4, активации сверх этого |
| [MERT-v1-330M](https://huggingface.co/m-a-p/MERT-v1-330M) | 24×1024, 24 kHz; более крупный music SSL | Код Apache-2.0; веса **CC BY-NC 4.0** | ~330M: около 1.32 GB FP32 weights по расчёту. ~3.5× параметров 95M, это **не** измеренное соотношение latency |
| [MuQ-large-msd-iter](https://huggingface.co/OpenMuQ/MuQ-large-msd-iter) | Music SSL с mel-RVQ; интересен для спектрального/тембрового сравнения. Опубликованный MSD checkpoint отличается от некоторых экспериментов статьи | [Код MIT, веса CC BY-NC 4.0](https://github.com/tencent-ailab/MuQ#license), отдельно `LICENSE_weights` | API safetensors: 333,440,416 параметров, 1,333,825,096 bytes. 24 kHz; существенно крупнее MERT-95M. Реальная VRAM/скорость неизвестны |
| [CLAP HTSAT unfused](https://huggingface.co/laion/clap-htsat-unfused) | Audio-text pretraining, audio embedding; альтернатива для семантической акустики, но текстовое обучение может усиливать жанровый shortcut | Для **этого** HF checkpoint card указывает **Apache-2.0**. [Upstream code](https://github.com/LAION-AI/CLAP) — CC0; другие checkpoints проверяются отдельно | 48 kHz audio frontend; опубликованный полный checkpoint 614,525,833 bytes, включая не нужную здесь text branch. Это размер файла, не стоимость одного audio forward |

Выбран MERT-95M: меньшая цена первого эксперимента по числу параметров и доступ к
временным признакам. Это инженерное решение для ограниченного **некоммерческого
исследования**, не заявление, что MERT превосходит MuQ. Новые данные и test-метки
потребуются, чтобы сравнить их по каждому аспекту. Факт открытого кода не снимает
ограничения NC с весов; опубликованная модель не является разрешением на обработку
всего каталога или свидетельством прав на её pretraining corpus.

## Зафиксированный кандидат

`m-a-p/MERT-v1-95M@12af15fef9d0ac838c3f475bfbbf26d2060dd4f5`.
Metadata/code/config прочитаны, checkpoint не загружен и не запущен.
Официальный [репозиторий MERT](https://github.com/yizhilll/MERT#environment-setup)
предупреждает о несовместимости более новых Transformers и рекомендует 4.38;
предлагается 4.38.2. Выбранный config имеет `feature_extractor_cqt=false`.
Совместимость всего удалённого окружения с реальным checkpoint ещё `NOT RUN`.

Этот snapshot опубликован как `pytorch_model.bin`, а runtime v0.1 принимает только
локальный safetensors. До первого remote run необходимы отдельное получение
**точного** файла, SHA-256, безопасная конверсия tensor state dict (`weights_only=True`)
и новая квитанция всех файлов. Нельзя подменить загрузку случаем `trust_remote_code`
с плавающей веткой. Код `configuration_MERT.py` и `modeling_MERT.py` должен быть
прочитан и включён в receipt, затем выполняется только из локального snapshot.

## Честное сравнение после допуска данных

Одинаковые фиксированные окна, одни splits и labels; для каждого encoder отдельно
сохранить revision, лицензии, DSP-only, frozen+DSP baseline и learned поверх этого
же frozen+DSP. На validation разрешён один заранее описанный выбор encoder, test
открывается один раз. Публиковать пары baseline/learned и интервалы по аспектам,
coverage, GPU model, precision, batch, audio seconds, wall seconds, peak allocated
и process memory. `audio_seconds / wall_seconds` — наблюдаемый throughput, который
сейчас не известен. Не сравнивать цифры из разных статей как наш результат.

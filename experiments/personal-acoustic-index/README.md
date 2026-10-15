# Personal Acoustic Index v1 — локальный прототип

Рабочая цепочка: разрешённый локальный PCM → PI-v1 + Lab → приватный индекс → Top-K. Проверено на существующих десяти CC0-файлах: **7 приняты, 3 отклонены порогом clipping/overshoot, 7 поисковых запросов выполнены**. Повторное извлечение совпадает; максимальное отклонение блоков от замороженного Acoustic Retrieval v1 — `1.9868214962137642e-08`. **Реальный live-захват NOT RUN**: среда агента не имеет доступа к desktop D-Bus/PulseAudio. Ни одного потока PCM с компьютера владельца агент не открывал.

Основа — PR #10, HEAD `35aecde3311fa302e0ac1548d9c53f336ed9c928`. Этот эксперимент не меняет player, модели, коэффициенты, SDK, PR #10/#11/#12, listening pilot, main, Release, AUR или Render. Он не интегрируется в опубликованный Yanjaro. Единственное изменение существующего DSP-кода — выделение прежнего тела `features.extract()` в `extract_pcm()`, чтобы принимать PCM без временного аудиофайла. Формулы сохранены.

## Запуск на машине владельца

Готовый checkout: `/tmp/yanjaro-personal-index`, отдельный Python 3.12 venv уже установлен. Каталог `/tmp` может быть очищен системой; для постоянной установки клонируйте ветку `experiment/personal-acoustic-index-v01` и создайте venv в своём checkout:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r experiments/personal-acoustic-index/requirements.txt
```

На Manjaro нужны уже имеющиеся `libpulse`, `pactl`, работающий пользовательский PulseAudio либо `pipewire-pulse`, и запущенный Yanjaro с MPRIS. Прототип не устанавливает системные пакеты и не запускает/перенастраивает аудиосервер. `--file` не требует desktop-сессии. Для команд ниже рабочий каталог:

```sh
cd /tmp/yanjaro-personal-index
```

Файловый режим, только для файла с подтверждённым правом анализа:

```sh
.venv/bin/python experiments/personal-acoustic-index/personal_index.py \
  --file /absolute/path/to/authorized-audio.ogg \
  --entry-id local-song-1 --rights-confirmed --start 30 --seconds 15
```

Поддерживаются только локальные regular files, декодируемые libsndfile: mono/stereo, 8–96 kHz. Интервал 10–15 секунд; короткий файл, NaN, тишина/провал и clipping отклоняются. Нет fallback на URL, ffmpeg downloader или playlist. Флаг `--rights-confirmed` — утверждение владельца о конкретном локальном файле, не юридическая проверка лицензии.

## Первый ограниченный live-тест

1. Откройте обычный терминал своей desktop-сессии. Запустите Yanjaro и воспроизведение одной песни. Оставьте больше 16 секунд до конца. Для технической проверки выбирайте звук, право на анализ которого подтверждено; обработка защищённого сервисного контента этим документом не разрешается.
2. Проверьте только metadata/маршрут; этот режим **не открывает PCM stream**:

   ```sh
   .venv/bin/python experiments/personal-acoustic-index/personal_index.py --probe
   ```

3. Узнайте исходный числовой Track ID через обычный пользовательский контекст песни. Не вставляйте URL потока или токен. Замените `123456789` своим ID:

   ```sh
   .venv/bin/python experiments/personal-acoustic-index/personal_index.py --live --track-id 123456789
   ```

4. Проверьте показанные название/исполнителя и ID. Введите **`START 123456789`**. Только после этого создаётся один recording stream для конкретного sink-input Yanjaro. Через примерно 12 секунд нажмите **Enter** для остановки. До 10 секунд измерение отклоняется; при достижении 15 секунд без остановки оно также отклоняется. **Ctrl-C отменяет измерение**. Это не фоновый сбор и не циклический обход библиотеки.
5. Только после успешной проверки всего фрагмента и извлечения профиля он сохраняется как `yandex-123456789`. Для поиска нужны минимум три отдельные записи. Каждый следующий live-фрагмент требует нового явного запуска и START.

При `DBUS_PERMISSION_DENIED` не меняйте sandbox/права и не передавайте секреты агенту: запуск предназначен для обычного терминала владельца. Если Yanjaro отсутствует в MPRIS, нет единственного sink-input с его PID или аудиобэкенд не поддерживает выбранный monitor, результат BLOCKED/REJECTED. Системный monitor и смешанный звук не используются как запасной источник.

## Идентичность и целостность

В `yanjaro/mpris.py` путь имеет вид `/org/mpris/MediaPlayer2/track_<sha256(currentId)>`. Числовой ID не опубликован. Прототип сверяет вручную введённый ID с этим алгоритмом, показывает title/artists владельцу и требует его подтверждения. Он не перебирает хеши и не читает память, конфигурацию, credentials или stream URLs Yanjaro.

В схеме сохраняются `requested_id`, `observed_id=null` с причиной `MPRIS_HASH_ONLY`, `real_id=null` с причиной `NOT_EXPOSED_NO_API_CALL`, `mpris_hash_matches`, `master_match=false`. Для CC0/локальных файлов все Yandex IDs отсутствуют. Подстановка фонограммы под прежним ID остаётся возможной, как показал PR #12: хеш MPRIS не доказывает оригинальный master. Время начала/остановки live-наблюдения фиксируется в UTC; `observed_at` указывает начало. Position — снимок до подключения monitor, с неизвестной задержкой аудиотракта, не sample-accurate master timestamp. Индексы samples внутри профиля относятся только к наблюдаемому окну.

Прототип связывает владельца MPRIS с Unix PID через локальный D-Bus, затем выбирает **ровно один** sink-input с этим PID. Используется [`pa_stream_set_monitor_stream`](https://www.freedesktop.org/software/pulseaudio/doxygen/stream_8h.html), вызванный до `pa_stream_connect_record`; выбранный input подтверждается `pa_stream_get_monitor_stream`. Возврат/ошибка этой операции проверяются, fallback на общий monitor отсутствует. Поле `monitor_source` в JSON `pactl` — имя источника, как в [официальном исходнике pactl](https://github.com/pulseaudio/pulseaudio/blob/master/src/utils/pactl.c). Сам факт работы этой схемы на desktop владельца ещё не проверен.

Во время захвата отслеживаются MPRIS-сигналы Metadata/PlaybackStatus/Volume/Rate/Seeked, смена владельца D-Bus, прогресс Position, PID/маршрут, mute/cork, input/sink gain. Pulse subscription дополнительно отклоняет события изменения sink и выбранного sink-input; это консервативно и может отклонить окно из-за изменения постороннего sink. `peek` hole, overflow/underflow, перемещение stream, suspend, остановка поступления PCM, нарушение тайминга/целостности frames и переполнение очереди событий отклоняют весь фрагмент. При ошибке частичный вектор не сохраняется.

`libmpv` в опубликованном Yanjaro работает внутри процесса, без внешнего PCM/IPC интерфейса. Получать PCM через новые mpv output-фильтры означало бы менять playback path; прототип использует внешний read-only tap. При прямом ALSA или native PipeWire-пути, который не виден/не поддерживается через Pulse bridge, прототип откажет. Он не меняет устройство вывода и не создаёт виртуальные sinks.

## Профиль и поиск

Обёртка: `yanjaro.personal-acoustic-index.v1`. Внутри неизменная схема `pi610-lab-timbre85-energy10.acoustic-v1`: четыре periodicity-гистограммы по 128, intervals 32, density 2, tempo hypotheses 64, timbre 85 и energy/dynamics 10 — **705 координат схемы**. Неизвестные блоки сохраняются как `null` с причиной, а не как фиктивный нулевой embedding. MERT, обученные Groove/cap2 и новое обучение не используются.

```sh
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --list
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --query yandex-123456789 --top 3
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --delete yandex-123456789
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --delete-all
```

Ранжирование использует прежний `acoustic_retrieval.search`: rhythm/tempo/timbre/energy имеют по 1/4 веса при полной доступности. Ответ содержит `common_distance`, вклад каждого аспекта, availability mask, coverage и пропущенные признаки. Сначала сортируется полнота общего набора признаков, затем внутри одинаковой mask — расстояние. Scores из разных masks не сопоставимы. `conditional_score` не вероятность, не музыкальная accuracy и не оценка качества рекомендаций. Self и идентичные PCM-хеши исключаются.

Громкость не нормализуется до предполагаемого master. Понижение gain меняет energy distance — это проверено тестом. Live PCM — float32 stereo 48 kHz от Pulse bridge; сервер может предварительно ресемплировать сигнал. PI использует этот rate, Lab ресемплирует в 16 kHz прежним `librosa/soxr_hq`. Player/input/sink gain сохраняются и должны оставаться стабильными. Точка tap может отличаться от физического выхода устройства; hardware gain и DSP/эквалайзер способны влиять на сравнимость. Обратного восстановления master energy и калибровки громкости нет. Сравнение file/live и разных трактов требует этой оговорки.

## Приватность и ресурсы

Индекс по умолчанию: `~/.local/share/yanjaro-personal-acoustic/v1/index.sqlite3`, каталог **0700**, файл **0600**. `--index-dir` задаёт отдельный приватный каталог вне Git checkout. Неприватные каталоги, symlinks к каталогу/базе и чужая структура базы отклоняются. В SQLite только whitelist безопасных metadata и численные блоки: нет аудио, paths исходных файлов, URL, account data, токенов или cookies. Прототип не содержит сетевых API-запросов; desktop IPC направлен только в локальные Unix sockets текущего UID.

Повторный идентичный профиль даёт `UNCHANGED`. Другое наблюдение того же ID требует явного `--replace`; оно атомарно заменяет предыдущий профиль, не накапливая скрытую историю. Удаление использует `secure_delete` и `VACUUM`; `--delete-all` очищает все строки и оставляет пустую схему. Копии в backup/snapshots пользователя это не удаляет.

PCM остаётся в RAM: libsndfile/file read либо libpulse callback → ограниченный numpy-буфер → DSP → обнуление собственных PCM-буферов и завершение процесса. Сырой PCM не сериализуется. Внутренние временные массивы библиотек освобождаются; гарантии forensic zeroization всех копий RAM/OS swap не заявляются. Core dumps отключены.

CPU affinity ограничена двумя доступными CPU, численные библиотеки — **одним потоком**. `RLIMIT_AS` ограничивает всё адресное пространство процесса 1 GiB, то есть строже лимита RSS; исчерпание лимита завершает операцию без нового вектора. Никаких GPU, paid APIs или фонового daemon. Прототип ограничен **1000 записями** и линейным поиском; массовая индексация не реализована.

## Воспроизводимая проверка CC0

В этом сеансе использованы исходные 10 файлов и rights/evidence hashes из прежнего локального manifest, без скачивания или копирования аудио. Окна — прежние 15 секунд. `validate_cc0.py` сначала проверяет все source/evidence hashes и CC0, затем выполняет извлечение, сохранение, повторное извлечение и Top-K. Пример отдельного повторного запуска владельцем с **новыми** приватными путями:

```sh
.venv/bin/python experiments/personal-acoustic-index/validate_cc0.py \
  --manifest /home/zinvernix/projects/yanjaro-music/acoustic-similarity-private/run-v01/manifest.json \
  --index-dir /home/zinvernix/projects/yanjaro-music/personal-acoustic-private/cc0-repeat \
  --report /home/zinvernix/projects/yanjaro-music/personal-acoustic-private/cc0-repeat-report.json
```

Фактический приватный результат этого запуска: `personal-acoustic-private/cc0-v1-report.json`, индекс `personal-acoustic-private/cc0-v1/`. Они находятся вне экспериментального checkout и не отправляются в GitHub. В репозитории только агрегаты [validation.json](validation.json), без векторов и персонального listening history.

| Проверка | Результат |
|---|---|
| Источники/права/hash | 10 существующих CC0, проверены до декодирования |
| audio → features → index | 7/10 приняты; s03, s04, o01 отклонены CLIPPING |
| Повторная экстракция | 7/7 совпали, запись `UNCHANGED` |
| Frozen Acoustic Retrieval v1 | max block error `1.99e-8`, допуск `1e-6` |
| Top-K | 7 запросов по приватному индексу выполнены |
| Время основного CC0 run | 15.535 s; измерение на этой машине, не прогноз |
| Пиковый RSS основного run | 466152 KiB ≈ 455.2 MiB |
| CLI `--file` и `--query` | Реальные команды прошли; дополнительное чтение s01 вернуло UNCHANGED |
| Live preflight | REJECTED / DBUS_PERMISSION_DENIED; 0 PCM streams |
| Desktop isolation/latency/owner STOP | NOT RUN на реальном аудиосервере |
| Музыкальная accuracy/прослушивание | NOT RUN |

CLIPPING — технический порог: peak > 1.001 либо доля `abs(sample) >= .999` > .001. Декодер lossy-формата может дать overshoot; эти значения не доказывают повреждённый master. Порог задан до прогона и не ослаблялся ради покрытия. Аналогично RMS ≤ 1e-5 в любом 100 ms блоке консервативно отклоняет intentional silence.

Тесты без desktop capture, audio files и credentials:

```sh
.venv/bin/python -m unittest discover -s experiments/personal-acoustic-index/tests -v
```

Прошли 14 тестов прототипа. Проверены 705-dimensional schema, повтор/обнуление PCM, hash/ID mismatch, pause/switch/seek/gain, потеря сигналов/данных и переполнение, ручной START/cancel, исключение других процессов, minimum-three search, вклад аспектов/missing tempo, replace/delete/delete-all, права filesystem, отсутствие аудио/секретов в сохранённом результате и ресурсные лимиты. Дополнительно прошли 9 существующих PI-v1 тестов. Hardware acceptance остаётся отдельным локальным тестом владельца.

## Правовые границы

Личное некоммерческое назначение не является автоматическим разрешением анализировать поток Яндекса. В [условиях Яндекс Музыки](https://yandex.ru/legal/music_termsofuse/ru/) §§2.1, 2.6–2.8 отдельно регулируются права на фонограммы/базу, личное использование и копирование/переработка. Использование output monitor вместо API download само по себе этих условий не меняет. Подтверждённого разрешения сервиса/правообладателя на live-анализ его контента и хранение derived features в этом исследовании нет. Обход DRM и получение секретов не реализованы.

Для CC0-проверки есть существующие hash-bound свидетельства прав; этот вывод не переносится на музыкальную библиотеку владельца. Следующий минимальный шаг — один явный локальный live-тест с правомерно анализируемым воспроизведением, проверка единственного input, ручной STOP и отсутствия вектора после смены/паузы. Для сервисного контента вопрос разрешения остаётся отдельным от технической работоспособности.

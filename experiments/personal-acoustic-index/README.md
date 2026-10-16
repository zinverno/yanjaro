# Personal Acoustic Index v1 — локальный прототип

Рабочая цепочка: разрешённый локальный PCM → PI-v1 + Lab → приватный индекс → Top-K. Проверено на существующих десяти CC0-файлах: **7 приняты, 3 отклонены порогом clipping/overshoot, 7 поисковых запросов выполнены**. Повторное извлечение совпадает; максимальное отклонение блоков от замороженного Acoustic Retrieval v1 — `1.9868214962137642e-08`. По сообщению владельца, `--probe` на реальном Manjaro прошёл, но live-попытка после START завершилась `PULSE_ROUTE_OR_GAIN_EVENT`. **Успешный live-захват после исправления: NOT RUN**. Агент проверяет синтетические события, без открытия desktop PCM владельца.

Основа — PR #10, HEAD `35aecde3311fa302e0ac1548d9c53f336ed9c928`. Этот эксперимент не меняет player, модели, коэффициенты, SDK, PR #10/#11/#12, listening pilot, main, Release, AUR или Render. Он не интегрируется в опубликованный Yanjaro. Единственное изменение существующего DSP-кода — выделение прежнего тела `features.extract()` в `extract_pcm()`, чтобы принимать PCM без временного аудиофайла. Формулы сохранены.

## Запуск на машине владельца

Используйте отдельный checkout ветки `experiment/personal-acoustic-index-v01` из Draft PR #13. В своём чистом checkout обновите именно эту ветку через `git pull --ff-only` и проверьте `git rev-parse HEAD` по последнему commit PR. При локальных изменениях/расхождении остановитесь, не сбрасывайте их. Для новой установки создайте отдельный Python 3.12 venv:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r experiments/personal-acoustic-index/requirements.txt
```

На Manjaro нужны уже имеющиеся `libpulse`, `pactl`, работающий пользовательский PulseAudio либо `pipewire-pulse`, и запущенный Yanjaro с MPRIS. Прототип не устанавливает системные пакеты и не запускает/перенастраивает аудиосервер. `--file` не требует desktop-сессии. Для команд ниже рабочий каталог:

```sh
cd /path/to/your/yanjaro-personal-index
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

### Повторная проверка Pulse-событий на Manjaro

Сообщённая владельцем попытка на HEAD `333d1ba96c32a6b00ef06a62189753e3532d82c4`: MPRIS распознал песню и ручной START, затем немедленный `PULSE_ROUTE_OR_GAIN_EVENT`. В старом callback **любой** sink вызывал отказ независимо от index; этот дефект воспроизведён синтетически. Какой именно объект вызвал отказ владельца, неизвестно: прежний вывод не содержал facility/index/type. Событие при создании monitor — гипотеза. Отдельный прежний `MPRIS_REQUEST_FAILED` не устанавливает причину Pulse-отказа.

После обновления выполните `--probe`, затем один ручной запуск из терминала. Для повторения сообщённого случая (при подтверждённом праве анализа):

```sh
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --probe
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --live --track-id 149359136
```

Сверьте текущие ID/title/artists, введите `START 149359136`, нажмите Enter около 12 секунд PCM. Успех — завершённый ручной STOP и результат `INSERTED`/`UNCHANGED` с 705 координатами, без REJECTED. Если запись уже существует и отличается, повторное измерение требует отдельного явного `--replace`; для первого теста можно указать новый приватный `--index-dir` вне Git. Один успех не проверяет изоляцию от чужого звука или качество similarity.

Отдельными ручными запусками проверьте отрицательные случаи: смена input/sink gain, mute, маршрута или песни должна отклонять окно и оставлять индекс без новой/изменённой записи; Ctrl-C также отменяет окно. Изменение **другого** sink должно дать `PULSE_UNRELATED_OBJECT`/`IGNORE`, если оно действительно не изменило выбранный тракт. Для каждого запуска сверяйте `--list` до/после в том же приватном каталоге. Не публикуйте индекс или содержимое `--list`.

Диагностика `PULSE_EVENT` выводится только в stderr: facility, `NEW`/`CHANGE`/`REMOVE` (либо `UNKNOWN`), числовой object index, фаза, решение и фиксированный reason code. Нет PCM, PID, имён устройств/приложений, metadata песни, URL, токенов или сырых исключений. Программа не пишет эти события в файл, индекс или GitHub. Для разбора отказа достаточно соответствующей строки `PULSE_EVENT` и итогового reason; весь вывод терминала, где показывается песня, не нужен.

Пример с **синтетическими**, не закреплёнными в коде индексами:

```json
{"event":"PULSE_EVENT","facility":"SINK","type":"CHANGE","index":8,"phase":"initialization","decision":"IGNORE","reason":"PULSE_UNRELATED_OBJECT"}
```

Если повторится `PULSE_SELECTED_SINK_CHANGE` в `initialization`, это наблюдение выбранного sink, а не доказательство изменения gain или безопасного служебного события. Не отключайте защиту и не повторяйте автоматически: для разрешения такого события нужны дополнительные доказательства его причины.

## Идентичность и целостность

В `yanjaro/mpris.py` путь имеет вид `/org/mpris/MediaPlayer2/track_<sha256(currentId)>`. Числовой ID не опубликован. Прототип сверяет вручную введённый ID с этим алгоритмом, показывает title/artists владельцу и требует его подтверждения. Он не перебирает хеши и не читает память, конфигурацию, credentials или stream URLs Yanjaro.

В схеме сохраняются `requested_id`, `observed_id=null` с причиной `MPRIS_HASH_ONLY`, `real_id=null` с причиной `NOT_EXPOSED_NO_API_CALL`, `mpris_hash_matches`, `master_match=false`. Для CC0/локальных файлов все Yandex IDs отсутствуют. Подстановка фонограммы под прежним ID остаётся возможной, как показал PR #12: хеш MPRIS не доказывает оригинальный master. Время начала/остановки live-наблюдения фиксируется в UTC; `observed_at` указывает начало. Position — снимок до подключения monitor, с неизвестной задержкой аудиотракта, не sample-accurate master timestamp. Индексы samples внутри профиля относятся только к наблюдаемому окну.

Прототип получает ожидаемый Unix PID через `GetConnectionUnixProcessID` владельца Yanjaro MPRIS. Read-only команды `pactl -f json list sink-inputs`, `list sinks` и `list clients` выполняются на локальном Pulse server. Поле `sink-input.client` связывается с `client.index`: если у самого sink-input нет `application.process.id`, используется PID связанного клиента. Если оба PID опубликованы, они должны совпадать. Выбирается **ровно один** поток ожидаемого процесса; имена `mpv`, `python` или приложения не являются доказательством принадлежности. PID и индексы сеанса не зафиксированы в коде.

`pulse.object_id()` строго нормализует `sink-input.index`, `sink-input.client`, `sink-input.sink`, `client.index` и `sink.index` в Python `int`. Принимаются неотрицательные `int` и непустые строки только из ASCII-цифр `[0-9]` (ведущие нули допустимы). Допустимые object IDs: `0…4294967294`; `4294967295` зарезервирован как [`PA_INVALID_INDEX`](https://github.com/pulseaudio/pulseaudio/blob/master/src/pulse/def.h). `bool`, float, отрицательные значения, пробелы/знаки, Unicode-цифры, пустые/произвольные строки и выход за uint32 отклоняются до открытия PCM. Ошибка ID в прочитанных metadata приводит к отказу всей проверки; ID не угадываются и не исправляются. Отсутствующий/`null` client означает отсутствие связи и не превращается в числовой ID.

Например, `client="247"` связывается с `client.index=247` или `"247"`, а `sink="57"` — с `sink.index=57`. В снимке маршрута и в `pa_stream_set_monitor_stream` используется числовой input index; результат `pa_stream_get_monitor_stream` сверяется с тем же числом. На границе `Capture` действует та же проверка ID до вызова libpulse. Чередование строк/чисел для одного ID после START, во время захвата или после STOP не считается сменой маршрута; другая числовая привязка или PID по-прежнему отклоняются. Нормализация object IDs не изменяет проверки принадлежности процесса.

| Код отказа | Причина |
|---|---|
| `INVALID_PULSE_OBJECT_ID` | Некорректный тип/формат/диапазон ID либо служебный `PA_INVALID_INDEX` |
| `YANJARO_AUDIO_STREAM_NOT_FOUND` | Ни одного потока с подтверждённым ожидаемым PID; в том числе недоступен PID клиента при отсутствии прямого PID |
| `YANJARO_AUDIO_STREAM_NOT_UNIQUE` | Подходят несколько sink-input, выбор неоднозначен |
| `AUDIO_PROCESS_ID_CONFLICT` | Один из PID указывает на Yanjaro, но прямой PID и PID клиента противоречат друг другу |
| `AUDIO_CLIENT_UNAVAILABLE` | Прямой PID подходит, но связанный client отсутствует, неизвестен или неоднозначен; полной цепочки нет |
| `AUDIO_ROUTE_OR_GAIN_CHANGED` | Изменился выбранный sink-input, client, один из PID, sink/monitor или gain |

Связанный client должен существовать даже при наличии прямого PID; его собственный PID в этом случае может отсутствовать. Снимок маршрута содержит оба PID и client index только в оперативной памяти. Та же цепочка повторно проверяется после START до открытия PCM, каждые примерно 200 ms во время захвата и после STOP до принятия фрагмента. При исчезновении/конфликте/неоднозначности действует соответствующий код отказа из таблицы. Чтения `pactl` не атомарны; исчезновение клиента между ними приводит к отказу. Краткие изменения client metadata между периодическими проверками могут остаться незамеченными.

Используется [`pa_stream_set_monitor_stream`](https://www.freedesktop.org/software/pulseaudio/doxygen/stream_8h.html), вызванный до `pa_stream_connect_record`; выбранный input подтверждается `pa_stream_get_monitor_stream`. Возврат/ошибка этой операции проверяются, fallback на общий monitor отсутствует. Поле `monitor_source` в JSON `pactl` — имя источника, как в [официальном исходнике pactl](https://github.com/pulseaudio/pulseaudio/blob/master/src/utils/pactl.c). Сам факт работы этой схемы на desktop владельца ещё не проверен. `--probe` использует тот же выбор маршрута, но не открывает PCM, не извлекает признаки и не открывает индекс. `LOCAL_METADATA_READY` подтверждает только доступность metadata, а не live-capture PASS.

Во время захвата отслеживаются MPRIS-сигналы Metadata/PlaybackStatus/Volume/Rate/Seeked, смена владельца D-Bus, прогресс Position, PID/маршрут, mute/cork, input/sink gain. `Capture` получает **оба числовых индекса** выбранного sink и sink-input из PID-привязанного маршрута. Подписка остаётся `SINK | SINK_INPUT` (mask `5`); объект определяется парой facility/index, а не только числом и не именем приложения. [Контракт libpulse](https://github.com/pulseaudio/pulseaudio/blob/master/src/pulse/subscribe.h) передаёт тип события и индекс, без перечня изменённых полей.

| Событие | `initialization` | `active_capture` |
|---|---|---|
| `NEW`/`CHANGE`/`REMOVE` другого sink или sink-input | `IGNORE`, `PULSE_UNRELATED_OBJECT` | То же |
| `NEW` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_NEW`: неожиданный жизненный цикл/переиспользование ID | То же |
| `CHANGE` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_CHANGE`: причина изменения неизвестна | То же |
| `REMOVE` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_REMOVE`: объект исчез | То же |
| Неизвестный тип/facility, лишние биты или `PA_INVALID_INDEX` | Отказ `PULSE_UNEXPECTED_EVENT` | То же |

`initialization` начинается до подписки и включает создание/подключение monitor. `active_capture` наступает только после READY, подтверждения monitor target и обработки Pulse callback без ошибки. Инициализация не является периодом отключённой защиты: ни один тип события **выбранного** объекта не разрешён автоматически. Даже неизменный снимок metadata после `CHANGE` не исключает краткого изменения и возврата gain/маршрута, переиспользования ID или изменения непроверяемого поля. Служебное событие собственного monitor не считается доказанно безопасным по одному времени его появления; консервативный отказ здесь всё ещё возможен.

После ручного STOP ещё проверяются Pulse callbacks до копирования PCM; число принимаемых frames фиксируется в момент STOP. `peek` hole, overflow/underflow, перемещение stream, suspend, остановка поступления PCM, нарушение тайминга/целостности frames и переполнение очереди MPRIS отклоняют весь фрагмент. Ошибка диагностического callback даёт фиксированный `PULSE_EVENT_CALLBACK_FAILED`. При отказе закрываются stream/context/mainloop, собственный PCM обнуляется, частичный вектор не сохраняется.

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
PYTHONPATH=experiments/personal-acoustic-index .venv/bin/python -c \
  'import runtime; runtime.configure(); import core, unittest; unittest.main(module=None, argv=["unittest", "discover", "-s", "experiments/acoustic-similarity/tests", "-p", "test_rhythm_pi.py", "-v"])'
```

После исправления нормализации Pulse IDs прошли **38 тестов: прежний 31 и 7 новых (14 прототипа + 15 Pulse-binding + 9 PI-v1)**. Прежние тесты проверяют 705-dimensional schema, повтор/обнуление PCM, hash/ID mismatch, pause/switch/seek/gain, потерю сигналов/данных и переполнение, ручной START/cancel, исключение других процессов, minimum-three search, вклад аспектов/missing tempo, replace/delete/delete-all, права filesystem, отсутствие аудио/секретов в сохранённом результате и ресурсные лимиты.

Новые тесты используют синтетические metadata с произвольными PID/индексами: прямой PID, fallback через client, чужой PID, конфликт, несколько кандидатов, неизвестный/отсутствующий/неоднозначный client, смена каждого звена до/во время/после захвата. Проверено закрытие mock capture, обнуление буфера и отсутствие вектора при отказе; отдельный CLI-тест проверяет read-only команды и отсутствие PCM/индекса/извлечения в `--probe`. Это не измерения реального desktop PCM. Исторический CC0 [validation.json](validation.json) не перезаписан. Hardware acceptance остаётся отдельным локальным тестом владельца.

Регрессии нормализации покрывают смешанные строковые/числовые ID, все пять полей, границы uint32 и `PA_INVALID_INDEX`, отсутствие клиента, конфликт PID, неоднозначность, неизменность маршрута при смене представления ID и отказ при реальной смене привязки. В тесте с подставленной libpulse проверены числовой аргумент и отказ при несовпадении возвращённого monitor target. `--probe` проверен на строковых ID; ошибка metadata-запроса не запускает повтор, PCM или индекс. Автоматических повторов нет.

После исправления фильтра Pulse-событий: **38 тестов прототипа PASS** (14 основных + 15 binding с расширенными cases + 9 новых Pulse-event), **9 PI-v1 PASS**. Полный offline runtime smoke акустического эксперимента: **118 PASS**, включая эти 9 PI-v1; загрузок dataset, обучения и реального held-out evaluation нет. Тесты приложения: **80 PASS** в offscreen-режиме; packaging scripts: **4 PASS**. `pip check`, совпадение установленных версий с locks, libpulse ABI bind без открытия stream и `git diff --check`: PASS. В sandbox тесты запускались с `NUMBA_CACHE_DIR=/tmp/yanjaro-pr13-numba`, чтобы не писать cache в установленный venv.

Новые регрессии используют подставленную libpulse с настоящими ctypes callbacks: чужие sink/input и совпадающие индексы разных facilities; выбранные `NEW`/`CHANGE`/`REMOVE` при подписке, создании stream, READY и активном захвате; неизменные metadata не отменяют выбранный `CHANGE`; неизвестные события; безопасный набор диагностических полей; ошибка вывода диагностики; cleanup/обнуление при отказе конструктора, активного захвата и после STOP; финальные callbacks не продлевают PCM после STOP. Binding-регрессии дополнены настоящими изменениями gain, mute/cork, monitor и исчезновением input до/во время/после capture. **Owner live acceptance после этого изменения NOT RUN**, источник прежнего реального Pulse-события не установлен. Исторический CC0 `validation.json` остаётся прежним результатом.

## Правовые границы

Личное некоммерческое назначение не является автоматическим разрешением анализировать поток Яндекса. В [условиях Яндекс Музыки](https://yandex.ru/legal/music_termsofuse/ru/) §§2.1, 2.6–2.8 отдельно регулируются права на фонограммы/базу, личное использование и копирование/переработка. Использование output monitor вместо API download само по себе этих условий не меняет. Подтверждённого разрешения сервиса/правообладателя на live-анализ его контента и хранение derived features в этом исследовании нет. Обход DRM и получение секретов не реализованы.

Для CC0-проверки есть существующие hash-bound свидетельства прав; этот вывод не переносится на музыкальную библиотеку владельца. Следующий минимальный шаг — один явный локальный live-тест с правомерно анализируемым воспроизведением, проверка единственного input, ручной STOP и отсутствия вектора после смены/паузы. Для сервисного контента вопрос разрешения остаётся отдельным от технической работоспособности.

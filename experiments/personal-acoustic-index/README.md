# Personal Acoustic Index v1 — локальный прототип

Рабочая цепочка: разрешённый локальный PCM → PI-v1 + Lab → приватный индекс → Top-K. Проверено на существующих десяти CC0-файлах: **7 приняты, 3 отклонены порогом clipping/overshoot, 7 поисковых запросов выполнены**. Повторное извлечение совпадает; максимальное отклонение блоков от замороженного Acoustic Retrieval v1 — `1.9868214962137642e-08`. По сообщению владельца, `--probe` на Manjaro с **pipewire-pulse** возвращает `LOCAL_METADATA_READY`; две live-попытки на HEAD `2800534842ad106b7441fb0d1ae134bc69dd0d85` после START отклонены с `PULSE_SELECTED_SINK_INPUT_CHANGE`, фаза `initialization`. **Успешное принятое live-измерение и новый диагностический запуск на desktop: NOT RUN**. Агент проверяет синтетические события, без открытия desktop PCM владельца.

Основа — PR #10, HEAD `35aecde3311fa302e0ac1548d9c53f336ed9c928`. Этот эксперимент не меняет player, модели, коэффициенты, SDK, PR #10/#11/#12, listening pilot, main, Release, AUR или Render. Он не интегрируется в опубликованный Yanjaro. Единственное изменение существующего DSP-кода — выделение прежнего тела `features.extract()` в `extract_pcm()`, чтобы принимать PCM без временного аудиофайла. Формулы сохранены.

Новый `--yandex-stream` обрабатывает один явно выбранный трек через существующий авторизованный SDK без PipeWire, MPRIS и системного воспроизведения. Владелец сообщил о разрешении использовать поток для своего эксперимента; это не утверждение о разрешении на массовый коммерческий каталог. Первый запуск на Manjaro на HEAD `afb20dbade475fec591ca88855cd7e6e3a61874c` получил правильные metadata трека `149359136`, но после START завершился `STREAM_REDIRECT_REJECTED`. **Успешный реальный Yandex Track ID → индекс: NOT RUN**.

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

## Прямой поток: один Track ID на Manjaro

Нужны Python 3.12, локальный `ffmpeg` и уже сохранённый вход Yanjaro в разблокированном Secret Service. Если вход только сеансовый или хранилище закрыто, CLI откажет: сохраните вход/разблокируйте его обычным интерфейсом Yanjaro. Токен не нужно копировать, вводить в CLI, environment или файл; новый режим не создаёт и не удаляет credentials. Воспроизведение песни и запущенный player не нужны. Проверить декодер можно командой `ffmpeg -version`; если его нет, установите штатный пакет Manjaro `ffmpeg` самостоятельно.

Из чистого checkout `experiment/personal-acoustic-index-v01`, обновлённого через `git pull --ff-only`, подготовьте отдельное окружение **вне Git**:

```sh
python3.12 -m venv ~/.venvs/yanjaro-stream
~/.venvs/yanjaro-stream/bin/python -m pip install --require-hashes --only-binary=:all: \
  -r experiments/personal-acoustic-index/requirements-yandex.lock
~/.venvs/yanjaro-stream/bin/python experiments/personal-acoustic-index/personal_index.py \
  --yandex-stream --track-id 149359136 --start 30 --seconds 12
```

CLI прочитает существующий Secret Service item через `SecretStore.read()`, восстановит авторизацию через `MusicApi.restore()` и покажет фактически полученные ID, название, исполнителей, длительность и альбом. После проверки введите **`START 149359136`**. Это подтверждает один запуск в пределах указанного владельцем разрешения. До подтверждения сжатое аудио не загружается; Ctrl-C отменяет операцию. Режим сам завершает окно 30–42 s, ручной STOP системного воспроизведения не требуется.

После START используется неизменённый `MusicApi.stream()`: повторное чтение трека → `tracks_download_info()` → выбор полного MP3/AAC → `get_direct_link()`. Повторные metadata должны совпасть с показанными. Preview, недоступный трек или другой возвращённый ID отклоняются до загрузки аудио. SDK-вариант, реально использованный `MusicApi.stream`, определяет сохранённые codec/bitrate; выбирать другую фонограмму по названию запрещено. URL получается после подтверждения, чтобы не ждать владельца с уже истекающей ссылкой. HTTP 410 даёт `STREAM_LINK_EXPIRED`, 401/403 — `STREAM_ACCESS_DENIED_OR_EXPIRED`; автоматического refresh/retry нет, для новой попытки нужен новый явный запуск.

### Ручной HTTP 308 и безопасная диагностика

Владелец повторил запрос на HEAD `c1fb2acbbfed0836ef4eaa358db75ce47a50da08`: установлен `media_get`, GET, HTTP **308**, `api.music.yandex.net` → `strm-n9-155.strm.yandex.net`, `followed: false`. Metadata и START прошли; отказ возник при запросе сжатого аудио. Теперь разрешён ручной **308 только для media GET**, максимум два перехода и три GET. Конкретный CDN-хост не закреплён в коде; используется прежняя allowlist поддоменов `yandex.net`/`yandex.ru`. Metadata API, POST и XML продолжают отклонять любой 3xx; media 302/307 тоже отклоняются. Успешный реальный PCM → индекс пока не подтверждён.

| `stage` | Запрос | Когда |
|---|---|---|
| `metadata_api` | GET account/status, POST tracks | Восстановление входа/metadata до START; повторный POST tracks после START |
| `tracks_download_info` | GET вариантов потока | После START |
| `download_info_xml` | GET XML через SDK `retrieve()` | После выбора варианта |
| `media_get` | GET сжатого аудио | После получения ссылки и проверки metadata |

На каждом 3xx CLI пишет в **stderr одну JSON-строку `event: STREAM_REDIRECT`**: `stage`, `method`, `http_status`, `source_hostname`, `target_hostname`, `classification`, `followed`. Значение `true` означает решение выполнить следующий GET после проверки и закрытия предыдущего ответа, а не успешное получение аудио; отказ/исчерпание лимита дают `false`. Только DNS hostnames; URL, path, query, signed link, userinfo, headers и cookies не выводятся. Некорректный/отсутствующий hostname обозначается `null`. Отдельный лог-файл не создаётся.

Экспериментальная HTTP-сессия отключает подготовку `Response.next`: стандартный Requests при `allow_redirects=False` всё равно читает тело 3xx перед возвратом ответа ([исходный код Requests](https://requests.readthedocs.io/en/latest/_modules/requests/sessions/)). Тело 308 не читается; предыдущие response и session закрываются **до** следующего GET. Каждый GET использует новую сессию без OAuth, cookies, Referer, netrc или environment proxies, включая первый запрос к API-host. Авторизация metadata не передаётся в media-транспорт. `trust_env=False`, проверка TLS и `allow_redirects=False` сохранены. Таймер 60 s охватывает всю цепочку и декодирование, не перезапускается на переходах; лимиты 8 MiB, PCM и FFmpeg сохранены.

Каждый исходный Location проверяется до разрешения относительного адреса, затем полный URL проверяется прежним валидатором с усиленными проверками синтаксиса. Допускаются только HTTPS и порт 443; userinfo (включая пустое), fragments (включая пустой `#`), backslash, control chars, ошибочные percent escapes, некорректный authority, неизвестные домены и HTTP downgrade отклоняются. Path/query сохраняются только в RAM для следующего GET. Циклы сравниваются по адресу, нормализованному Requests, с учётом hostname, порта, path и query. Классификация `WITHIN_ALLOWLIST` сама по себе не разрешает переход: дополнительно нужны корректный полный URL, отсутствие цикла и свободный лимит. Причины `STREAM_REDIRECT_LOOP`/`STREAM_REDIRECT_LIMIT` различают цикл и третий переход; прочий недопустимый redirect даёт `STREAM_REDIRECT_REJECTED`.

Для одного реального повтора обновите эту ветку через `git pull --ff-only` и выполните команду `--yandex-stream --track-id 149359136 --start 30 --seconds 12` выше с уже установленным окружением. Проверьте metadata и введите `START 149359136` один раз. Ожидаемый успешный итог — `INSERTED`/`UNCHANGED`, `source: yandex_stream`, `dimensions: 705`, `entry_id: yandex-stream-149359136`. При отказе передайте **только строки `STREAM_REDIRECT` и фиксированный reason**, без полного stdout, индекса, токена или ссылки. При успехе достаточно указанных полей результата. Автоматических повторов и refresh истёкшей ссылки нет.

Если потребуется домен за пределами текущего списка, сначала требуется отдельное подтверждение владельца; allowlist не расширена. POST metadata не воспроизводится как GET. Агент не выполняет реальный запрос к Яндексу; синтетический E2E не заменяет проверку владельцем на Manjaro.

HTTP-клиент передаёт сжатые порции в stdin FFmpeg, а PCM читает непосредственно в ограниченный writable NumPy-буфер. В argv FFmpeg только `pipe:0`/`pipe:1`, числовые параметры и фиксированные форматы — без URL, token или headers. FFmpeg получает только pipe protocol и MP3 либо AAC/MP4 demuxer/decoder, без внешних playlist/file/network sources, DRM-ключей и fallback на плеер. AAC в контейнере, требующем недоступного seek по stdin, будет отклонён; полный файл на диск для обхода этого ограничения не сохраняется. [Документация FFmpeg](https://ffmpeg.org/ffmpeg.html) описывает output `-ss` как декодирование и пропуск префикса; [pipe protocol](https://ffmpeg.org/ffmpeg-protocols.html#pipe) передаёт данные через дескрипторы.

Поток stdin не поддерживает произвольный seek, поэтому сначала читается ограниченный префикс до конца выбранного окна с небольшим read-ahead. Это **не обещание загрузить только байты 30–42 s**. После завершения декодера HTTP-соединение закрывается, остаток композиции не дочитывается. Принятие требует ровно запрошенного числа PCM-frames и успешного exit FFmpeg; неполное декодирование, обрыв, clipping, silence/dropout или отмена не создают запись.

| Ограничение | Значение |
|---|---|
| Один запуск | Один числовой Track ID; до двух media 308 и трёх media GET; без очереди/каталога |
| Окно | `0 ≤ start ≤ 60`, `10 ≤ seconds ≤ 15`; не за пределами длительности трека |
| Сжатое аудио | До 8 MiB прочитанных байтов, порции 16 KiB, без накопления полного трека |
| Metadata HTTP | До 8 запросов, до 1 MiB на ответ; по 30 s до/после ручного подтверждения; вместе с media — до 11 HTTP-запросов |
| Сеть/декодирование | 60 s wall timer с SIGALRM, connect/read timeout 3 s; Ctrl-C отменяет |
| Адреса | HTTPS, порт 443, только поддомены `yandex.net`/`yandex.ru`; строгая проверка исходного Location и полного URL; только media GET 308 |
| Авторизация | OAuth только `api.music.yandex.net`; media GET без OAuth, cookies, netrc и environment proxies |
| PCM | Float32 stereo 48 kHz, максимум 15 s ≈ 5.76 MB; owned PCM обнуляется после DSP/отказа |
| Процессы | Python: 1 GiB address space; FFmpeg: 768 MiB, 30 CPU s, запрет записи regular files/core dumps; не более двух CPU affinity |

Зависимости нового lock повторяют численный стек акустического эксперимента и существующие SDK/auth/HTTP зависимости Yanjaro. Прежний lock и DSP не изменены. До импорта HTTP-библиотек удаляется process-local `SSLKEYLOGFILE`, чтобы не создавать TLS secrets log. FFmpeg не получает environment владельца с возможными секретами/`FFREPORT`, stderr декодера не публикуется. Это не гарантия стирания внутренних immutable bytes библиотек или системного swap; исходный аудиофайл программой не создаётся.

При успехе выводится `INSERTED`/`UNCHANGED`, `source: yandex_stream`, `dimensions: 705`, ключ `yandex-stream-149359136`. Приватный каталог по умолчанию прежний: `~/.local/share/yanjaro-personal-acoustic/v1`; другой можно задать `--index-dir` вне Git. Для новой версии наблюдения нужен явный `--replace`. Ключ отличается от `yandex-149359136` системного live-режима, поэтому источники не подменяют друг друга.

Новая запись имеет schema `yanjaro.personal-acoustic-index.v2` и строгую allowlist: `source=yandex_stream`, запрошенный и фактически возвращённый API ID, title/artists/album/duration, codec/bitrate, время загрузки UTC, начало/длительность декодированного фрагмента, объём прочитанных байтов и `extractor_schema`. Тот же 705-координатный профиль остаётся `pi610-lab-timbre85-energy10.acoustic-v1`. `real_id=null`, `master_match=false`: API ID не доказывает исходный master. Время фрагмента относится к декодированному потоку, а не к подтверждённому master timestamp; delay/padding/ресемплинг кодека могут влиять на сопоставление.

Существующие v1 file/live записи читаются без переписывания. SQLite `user_version` меняется с 1 на 2 атомарно с первой вставкой stream-записи; прежний checkout после этого отвергнет БД как несовместимую. Исходное аудио, URL, headers, cookies и OAuth не входят в схему/индекс/GitHub. Не публикуйте индекс, полный stdout с личными metadata или source URL; для первого результата достаточно status/source/dimensions и фиксированного reason при отказе.

Тесты нового режима запускаются без настоящего аккаунта:

```sh
~/.venvs/yanjaro-stream/bin/python -m unittest discover \
  -s experiments/personal-acoustic-index/tests -p test_yandex_stream.py -v
```

HTTP fixture генерирует MP3/AAC в RAM, требует синтетическую авторизацию для API metadata и использует реальный localhost HTTP → FFmpeg → DSP → SQLite. Python audit hook запрещает внешние соединения/DNS, Secret Service подставлен, численный extractor настоящий. CI `Personal acoustic index synthetic HTTP` выполняет эти тесты в PR #13 без secrets и без загрузки audio/index artifacts. В sandbox агента loopback sockets запрещены; локальный прогон с HTTP не считается PASS. Итог CI и owner E2E учитываются отдельно.

В [CI run 38913069511](https://github.com/zinverno/yanjaro/actions/runs/38913069511) прошли **49 прежних + 9 новых тестов**, затем **118 acoustic runtime regressions**. Два полных синтетических CLI-запуска дали одинаковые признаки и `INSERTED` → `UNCHANGED`. Проверены MP3/AAC, раннее закрытие до конца полного трека, обрыв/неполный PCM, 410/403, redirect/URL, несовпадение ID до и после подтверждения, byte/metadata/memory/time limits, clipping, cancel/cleanup, отсутствие secrets/audio в индексе и сохранение v1/v2 validation. Локально также прошли **80 тестов приложения и 4 packaging tests**. HTTP-группа запускается отдельно от прежних suites, как новый CLI-процесс, при прежнем лимите 1 GiB. **Реальный Yandex Track ID → индекс на Manjaro: NOT RUN**.

Stream suite теперь содержит **22 теста**. Сохранены проверки диагностики 302/307 на каждом этапе; 308 в metadata/POST/XML не следует дальше. Новые сценарии проверяют полный синтетический CLI: API-host → 308 → другой разрешённый хост → 200 MP3 → FFmpeg → 12 s PCM → 705 признаков → SQLite, а также второй переход на третий хост с идентичным профилем. Проверяются точные path/query на сервере, отсутствие OAuth/cookies/proxy auth, отсутствие аудиофайлов и секретов в индексе, цикл, третий переход, истечение/отказ доступа, byte limit и неполный PCM без открытия индекса. Тесты настоящего `requests.Session.send` с подставленным adapter проверяют закрытие предыдущего response до следующего GET, запрет чтения тела 302/307/308 и `Response.next`, TLS-error, отмену и общий deadline с обнулением PCM. Настоящий TLS отказ моделируется исключением библиотеки; реальный Yandex E2E остаётся отдельной проверкой владельца.

## Первый ограниченный live-тест (альтернативный Pulse-режим)

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

### Один ограниченный диагностический запуск на Manjaro

Ранее любой sink вызывал отказ независимо от index; этот дефект исправлен и воспроизведён синтетически. Новые два отказа относятся уже к **выбранному sink-input**, а не постороннему устройству. Отдельное наблюдение `timeout 12s pactl subscribe` при обычном воспроизведении не дало событий и завершилось по таймауту. Это поддерживает гипотезу подключения monitor, но не доказывает её. Прежний `MPRIS_REQUEST_FAILED` не устанавливает причину Pulse-отказа.

Чтобы проверить доставку первых PCM-буферов и этап события, после обновления ветки выполните **один** явно запускаемый тест из обычного терминала (при подтверждённом праве анализа):

```sh
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --probe
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --diagnose-pulse --track-id 149359136
```

Сверьте ID/title/artists, введите `START 149359136`, оставьте песню/громкость/маршрут неизменными. Сначала идут две секунды подписки **без monitor**, затем один monitor подключается к выбранному input. После примерно трёх секунд доставленных PCM-frames тест сам останавливается; Enter останавливает раньше, Ctrl-C отменяет. Лимит 12 секунд от начала `Capture` проверяется между операциями; это **не жёсткий wall-clock таймер**: уже выполняющийся IPC-вызов может задержать отказ до возврата/собственного таймаута. Повторов и фонового сбора нет.

Режим считает frames через размер `pa_stream_peek` и освобождает буфер `pa_stream_drop`, **не разыменовывая и не копируя PCM**. Собственный PCM-массив не выделяется, DSP не вызывается, индекс не открывается. Выбранный `CHANGE` разрешён только как `OBSERVE_ONLY` при диагностической инициализации; он не объявляется безопасным. `NEW`/`REMOVE`, неизвестное событие, обнаруженное изменение PID/client/route/gain/mute, MPRIS track/pause/seek/volume и ошибки доставки по-прежнему отклоняют тест. Полная цепочка и MPRIS проверяются до monitor, после READY, примерно каждые 200 ms и после STOP. После READY и этой проверки фаза становится `diagnostic`, **никогда `active_capture`**; выбранный `CHANGE` снова приводит к отказу, включая финальную проверку после STOP.

`DIAGNOSTIC_ONLY` с `pcm_delivery: OBSERVED`, `accepted_capture: false`, `vector_saved: false` подтверждает только доставку непустых буферов. Это не принятое измерение, не оценка содержимого/изоляции PCM и не live PASS. До появления буфера ранний Enter даёт `DIAGNOSTIC_NO_PCM`.

Для разбора достаточно строк `PULSE_STAGE`, `PULSE_EVENT`, `PULSE_PCM` и итогового статуса/reason. Не присылайте полный stdout с песней, raw `pactl`/PipeWire dumps, индекс или аудио. В stderr только фиксированные этапы/коды, facility, `NEW`/`CHANGE`/`REMOVE` (либо `UNKNOWN`), числовой object index, фаза/решение и относительные миллисекунды. Нет PCM, PID, названий устройств/приложений, metadata песни, URL, токенов, абсолютных timestamps или сырых исключений; программа не сохраняет лог в файл/GitHub.

| Этап `stage` | Что выполняется |
|---|---|
| `context_connection` | Создание локального Pulse context и ожидание подключения |
| `subscription` | Установка callback, подписка `SINK \| SINK_INPUT`, ожидание подтверждения |
| `subscription_baseline` | Только диагностика: 2 s событий без monitor, повторные проверки цепочки/MPRIS |
| `stream_creation` | `pa_stream_new` |
| `monitor_binding` | `pa_stream_set_monitor_stream`, установка callbacks |
| `record_connection` | `pa_stream_connect_record` и ожидание READY |
| `ready` | READY получен, чтение локальной привязки monitor и обработка callbacks |
| `route_revalidation` | Только диагностика: полная повторная проверка цепочки/MPRIS после READY |
| `active_capture` / `diagnostic_observation` | Обычное измерение / доставка с немедленным освобождением буферов |
| `after_stop` | Последние проверки перед результатом и cleanup |

`PULSE_STAGE` отмечает вход в этап. В `PULSE_EVENT` поле `observed_ms` — время доставки callback от начала Capture, `stage_ms` — от входа в текущий этап. **Это не время возникновения события на сервере**: пока выполняется другой вызов, доставка может задержаться до следующего mainloop iterate. `PULSE_PCM` отмечает первый непустой диагностический буфер с `DISCARDED_NO_COPY`. Пример с **синтетическими**, не закреплёнными в коде числами:

```json
{"event":"PULSE_EVENT","phase":"initialization","stage":"record_connection","observed_ms":2031.2,"stage_ms":4.5,"facility":"SINK_INPUT","type":"CHANGE","index":41,"decision":"OBSERVE_ONLY","reason":"PULSE_SELECTED_SINK_INPUT_CHANGE"}
```

Если событие приходит ещё на `subscription_baseline`, его нельзя приписывать исключительно monitor. Событие при `record_connection`/`ready`, затем `PULSE_PCM` и отсутствие выбранных CHANGE в `diagnostic_observation` поддержат гипотезу служебного подключения; они не докажут её. Повторные выбранные CHANGE после инициализации требуют дальнейшего разбора, а не разрешения таких событий в live. Отказ до первого буфера означает, что доставка PCM пока не подтверждена.

В [libpulse v17 `stream.c`](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulse/stream.c) `pa_stream_new` и установка monitor — локальная подготовка; `get_monitor_stream` возвращает сохранённый клиентский index. В [PipeWire `pulse-server.c`](https://github.com/PipeWire/pipewire/blob/master/src/modules/module-protocol-pulse/pulse-server.c) `do_create_record_stream` использует `direct_on_input_idx` как target, а обновление объекта вызывает общее CHANGE. В [PipeWire `manager.c`](https://github.com/PipeWire/pipewire/blob/master/src/modules/module-protocol-pulse/manager.c) `node_event_info` учитывает в изменениях также `SPA_PARAM_Latency`, с комментарием о подключении stream. **Вывод-гипотеза:** подключение monitor/согласование latency может порождать наблюдаемый CHANGE при неизменных gain/route. Версия PipeWire владельца не установлена; исходники upstream не доказывают причину его конкретного события.

### Почему подписка пока остаётся до monitor

Перенос подписки за READY с повторной проверкой полной цепочки рассмотрен, но не включён в `--live`. Между последним снимком до подключения и подтверждением поздней подписки было бы слепое окно: краткий gain/route/PID/client change-and-revert либо переиспользование ID может не попасть в снимки. Чтения MPRIS и трёх списков `pactl` последовательны и не атомарны. Уже пришедший PCM может относиться к времени до подписки/повторной проверки. **Совпадение снимков не доказывает отсутствия кратковременных изменений.** Ранняя подписка также не делает снимки атомарными и не устраняет задержки доставки событий; особенно краткие client-only изменения остаются ограничением.

Для отдельного принимаемого окна после READY потребовалось бы обосновать границу PCM: исключить все предыдущие данные, подтвердить подписку и flush/cork-переход, повторно проверить цепочку/MPRIS и отклонять выбранные события во всём принимаемом окне. Простого переноса `subscribe`, очистки ошибки или сравнения metadata недостаточно. Диагностический режим собирает недостающие свидетельства, ничего не принимает в индекс и не является обходным способом сохранить профиль.

### Проверка настоящего live-захвата

После разбора диагностики обычный запуск остаётся явным:

```sh
.venv/bin/python experiments/personal-acoustic-index/personal_index.py --live --track-id 149359136
```

Сверьте песню/ID, введите `START 149359136`, нажмите Enter около 12 секунд PCM. Успех — завершённый ручной STOP и `INSERTED`/`UNCHANGED` с 705 координатами, без REJECTED. Инициализационный выбранный CHANGE в этом режиме **по-прежнему отклоняется**; диагностический результат сам по себе не разрешает его. Если запись существует и отличается, замена требует явного `--replace`; для первого измерения можно использовать новый приватный `--index-dir` вне Git.

Отдельные ручные отрицательные проверки: смена input/sink gain, mute, маршрута или песни должна отклонять окно без новой/изменённой записи; Ctrl-C также отменяет. Изменение **другого** sink должно дать `PULSE_UNRELATED_OBJECT`/`IGNORE`, если выбранный тракт не изменился. Сверяйте `--list` до/после в одном приватном каталоге, не публикуйте его содержимое. Один успешный live-тест не устанавливает изоляцию от чужого звука, точность latency или качество similarity.

## Идентичность и целостность Pulse-режима

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

Используется [`pa_stream_set_monitor_stream`](https://www.freedesktop.org/software/pulseaudio/doxygen/stream_8h.html), вызванный до `pa_stream_connect_record`; `pa_stream_get_monitor_stream` сверяет локальную клиентскую привязку, **не является независимым подтверждением server-side target**. Возврат/ошибка операции и READY проверяются, fallback на общий monitor отсутствует. Поле `monitor_source` в JSON `pactl` — имя источника, как в [официальном исходнике pactl](https://github.com/pulseaudio/pulseaudio/blob/master/src/utils/pactl.c). Сам факт работы этой схемы на desktop владельца ещё не проверен. `--probe` использует тот же выбор маршрута, но не открывает PCM, не извлекает признаки и не открывает индекс. `LOCAL_METADATA_READY` подтверждает только доступность metadata, а не live-capture PASS.

Во время захвата отслеживаются MPRIS-сигналы Metadata/PlaybackStatus/Volume/Rate/Seeked, смена владельца D-Bus, прогресс Position, PID/маршрут, mute/cork, input/sink gain. `Capture` получает **оба числовых индекса** выбранного sink и sink-input из PID-привязанного маршрута. Подписка остаётся `SINK | SINK_INPUT` (mask `5`); объект определяется парой facility/index, а не только числом и не именем приложения. [Контракт libpulse](https://github.com/pulseaudio/pulseaudio/blob/master/src/pulse/subscribe.h) передаёт тип события и индекс, без перечня изменённых полей.

Политика обычного `--live`:

| Событие | `initialization` | `active_capture` и `after_stop` |
|---|---|---|
| `NEW`/`CHANGE`/`REMOVE` другого sink или sink-input | `IGNORE`, `PULSE_UNRELATED_OBJECT` | То же |
| `NEW` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_NEW`: неожиданный жизненный цикл/переиспользование ID | То же |
| `CHANGE` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_CHANGE`: причина изменения неизвестна | То же |
| `REMOVE` выбранного объекта | Отказ `PULSE_SELECTED_{SINK,SINK_INPUT}_REMOVE`: объект исчез | То же |
| Неизвестный тип/facility, лишние биты или `PA_INVALID_INDEX` | Отказ `PULSE_UNEXPECTED_EVENT` | То же |

`initialization` начинается до подписки и включает создание/подключение monitor. `active_capture` наступает только после READY, чтения локальной привязки monitor и обработки Pulse callback без ошибки. Для `--live` ни один тип события **выбранного** объекта не разрешён автоматически. Даже неизменный снимок metadata после `CHANGE` не исключает краткого изменения и возврата gain/маршрута, переиспользования ID или изменения непроверяемого поля. Служебное событие собственного monitor не считается доказанно безопасным по одному времени его появления; консервативный отказ здесь всё ещё возможен. Единственное исключение — описанный выше `OBSERVE_ONLY` в инициализации отдельного `--diagnose-pulse`, который ничего не принимает и не сохраняет.

После ручного STOP ещё проверяются Pulse callbacks до копирования принятого PCM; число принимаемых frames фиксируется в момент STOP, поздние PCM-буферы освобождаются без копирования. `peek` hole, overflow/underflow, перемещение stream, suspend, остановка поступления PCM, нарушение тайминга/целостности frames и переполнение очереди MPRIS отклоняют весь фрагмент. Ошибка вывода диагностики даёт фиксированный `PULSE_EVENT_CALLBACK_FAILED`. При отказе закрываются stream/context/mainloop, собственный PCM обнуляется, частичный вектор не сохраняется.

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

PCM остаётся в RAM: libsndfile/file read, libpulse callback либо FFmpeg stdout → ограниченный numpy-буфер → DSP → обнуление собственных PCM-буферов и завершение процесса. Сырой PCM не сериализуется. Внутренние временные массивы библиотек освобождаются; гарантии forensic zeroization всех копий RAM/OS swap не заявляются. Core dumps отключены.

CPU affinity ограничена двумя доступными CPU, численные библиотеки — **одним потоком**. `RLIMIT_AS` ограничивает всё адресное пространство процесса 1 GiB, то есть строже лимита RSS; исчерпание лимита завершает операцию без нового вектора. Никаких GPU, paid APIs или фонового daemon. Прототип ограничен **1000 записями** и линейным поиском; массовая индексация не реализована.

## Воспроизводимая проверка CC0

В историческом CC0-прогоне использованы исходные 10 файлов и rights/evidence hashes из прежнего локального manifest, без скачивания или копирования аудио. Для нового stream-режима этот прогон не повторялся. Окна — прежние 15 секунд. `validate_cc0.py` сначала проверяет все source/evidence hashes и CC0, затем выполняет извлечение, сохранение, повторное извлечение и Top-K. Пример отдельного повторного запуска владельцем с **новыми** приватными путями:

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
PYTHONPATH=experiments/personal-acoustic-index/tests ~/.venvs/yanjaro-stream/bin/python \
  -m unittest test_personal test_audio_binding test_pulse_events -v
PYTHONPATH=experiments/personal-acoustic-index ~/.venvs/yanjaro-stream/bin/python -c \
  'import runtime; runtime.configure(); import core, unittest; unittest.main(module=None, argv=["unittest", "discover", "-s", "experiments/acoustic-similarity/tests", "-p", "test_rhythm_pi.py", "-v"])'
```

После исправления нормализации Pulse IDs прошли **38 тестов: прежний 31 и 7 новых (14 прототипа + 15 Pulse-binding + 9 PI-v1)**. Прежние тесты проверяют 705-dimensional schema, повтор/обнуление PCM, hash/ID mismatch, pause/switch/seek/gain, потерю сигналов/данных и переполнение, ручной START/cancel, исключение других процессов, minimum-three search, вклад аспектов/missing tempo, replace/delete/delete-all, права filesystem, отсутствие аудио/секретов в сохранённом результате и ресурсные лимиты.

Новые тесты используют синтетические metadata с произвольными PID/индексами: прямой PID, fallback через client, чужой PID, конфликт, несколько кандидатов, неизвестный/отсутствующий/неоднозначный client, смена каждого звена до/во время/после захвата. Проверено закрытие mock capture, обнуление буфера и отсутствие вектора при отказе; отдельный CLI-тест проверяет read-only команды и отсутствие PCM/индекса/извлечения в `--probe`. Это не измерения реального desktop PCM. Исторический CC0 [validation.json](validation.json) не перезаписан. Hardware acceptance остаётся отдельным локальным тестом владельца.

Регрессии нормализации покрывают смешанные строковые/числовые ID, все пять полей, границы uint32 и `PA_INVALID_INDEX`, отсутствие клиента, конфликт PID, неоднозначность, неизменность маршрута при смене представления ID и отказ при реальной смене привязки. В тесте с подставленной libpulse проверены числовой аргумент и отказ при несовпадении возвращённого monitor target. `--probe` проверен на строковых ID; ошибка metadata-запроса не запускает повтор, PCM или индекс. Автоматических повторов нет.

После добавления этапов и отдельной диагностики: **49 тестов прототипа PASS** (14 основных + 15 binding + 20 Pulse-event/diagnostic). Полный offline runtime smoke акустического эксперимента: **118 PASS**, включая 9 PI-v1; загрузок dataset, обучения и реального held-out evaluation нет. Тесты приложения: **80 PASS** в offscreen-режиме; packaging scripts: **4 PASS** — всего **251 отдельный тест**. `pip check`, совпадение установленных версий с locks, CLI help, libpulse ABI bind без открытия context/stream и `git diff --check`: PASS. В sandbox тесты запускались с `NUMBA_CACHE_DIR=/tmp/yanjaro-pr13-numba`, чтобы не писать cache в установленный venv.

Регрессии используют подставленную libpulse с настоящими ctypes callbacks: чужие sink/input и совпадающие индексы разных facilities; выбранные `NEW`/`CHANGE`/`REMOVE` при подписке, создании stream, monitor binding, подключении записи, READY и active capture; безопасные поля этапа/времени; неизвестные события и ошибка вывода; cleanup/обнуление при отказе конструктора, захвата и после STOP. Настоящий read callback после STOP освобождает буфер без копирования. Диагностические тесты проверяют отсутствие PCM allocation/копирования/DSP/индекса, ранний START/cancel, автоматический и ручной STOP, deadline, запрет выбранных событий после READY/STOP, отказы на hole/alignment/drop и повторную проверку PID/client/route/gain/track/pause после monitor READY. Binding-регрессии сохраняют случаи реальных изменений gain, mute/cork, monitor и исчезновения input в синтетических metadata. **Новый owner diagnostic и успешное live acceptance: NOT RUN**. Источник реального Pulse-события пока не установлен; исторический CC0 `validation.json` не перезаписан.

## Правовые границы

Владелец сообщил, что получил разрешение использовать аудиопоток Яндекс Музыки для своего эксперимента. `--yandex-stream` реализован в этих заявленных пределах: один выбранный ID после ручного подтверждения, штатная авторизация, без обхода DRM или ограничений доступа. Текст/объём разрешения здесь не публикуется; разрешение на массовый коммерческий каталог отдельно не подтверждено и не предполагается.

Исторические hash-bound свидетельства CC0 относятся только к тем тестовым файлам. Успешный технический тест не расширяет заявленные права и не устанавливает идентичность исходного master. Реальный запрос к Яндексу агент не выполнял; следующий шаг — один явный запуск владельцем на Manjaro.

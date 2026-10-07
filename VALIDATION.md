# Проверки 0.2.0rc2 — 2026-10-07

Исходный независимый осмотр: HEAD `6296f657d8c4edeef5d583c4e212392ad556928f`, `feature/desktop-ui-and-packaging`, чистые tracked-файлы. Remote подтвердил тот же HEAD. Основной `.git` защищён, история ведётся в существующем клоне `/tmp/yanjaro-git`, новая ветка `feature/player-polish-and-discovery`. Установленный на основной системе исходный пакет — `0.2.0rc1-3`.

Baseline: 29 тестов PASS до изменений. Не сбрасывались новые изменения, reset/force-push/merge/tag/публичная публикация не выполнялись. [Ход работы и тематические изменения](docs/WORK-rc2.md). [Предыдущие доказательства rc1](docs/VALIDATION-rc1.md) сохранены отдельно и не заменяют приёмку rc2.

| Этап / сценарий | Автоматически в rc2 | Установленный rc2 / реальный аккаунт | Осталось |
|---|---|---|---|
| A: play/pause | PASS: fail-before воспроизведение rc1 с mpv/QML; snapshot наблюдаемых свойств и ID файла; реальная иконка/текст, новый трек после паузы, rapid A→C, пауза загрузки, error, EOF | NOT RUN | Сопоставить слышимый звук с кнопкой после разных способов запуска |
| A: центр и клики | PASS: центр панели и границы, длинные названия; настоящий QTest single/Enter/drag/right-click/inline action; double-click текущего без нового stream; виртуализация 500 строк | NOT RUN | Маленькое/большое окно, очередь открыта, масштаб пользователя |
| A: repeat/shuffle | PASS: полные 60 ID любимого, без смены current; shuffle-off, фактический Previous/forward; empty/single/last, EOF vs ручной Next; radio off и возврат предпочтений | NOT RUN | Repeat-one при естественном конце, переходы со звуком |
| A: сохранение входа | PASS: изолированный fake store — save/restore/delete, blocked, cancelled, network retry, 401≠403, late account, отсутствие auto-play и plaintext | NOT RUN | Настоящий Secret Service: вход→закрытие→меню, logout→запуск, новый сеанс ОС, обновление, тестовая заблокированная запись |
| A: MPRIS | PASS: XML introspection, настоящая сериализация/разбор D-Bus сообщений, o/x/as/a{sv}, команды общего контроллера, PropertiesChanged без Position ticks, Seeked, ограниченные capability flags | BLOCKED в sandbox; NOT RUN в desktop-сеансе | Карточка ОС, обложка, Play/Pause/Next/Previous, сворачивание, отсутствие дубликатов |
| B: станции | PASS: ID/parent группы, unknown→Другие, дочерняя региональная станция для детей, pins/hidden/filter; SVG fallback и ограниченный Qt cache | NOT RUN | Реальные Station.icon, разумность групп/верхнего порядка, сохранение pins аккаунта |
| B: поиск / страницы | PASS: закреплённые SDK de_json модели all/artist/album, лучший результат, вкладки, пагинация/поздний ответ, пустые результаты, Back/scroll, inline link; multi-artist/multi-disc/unavailable | NOT RUN | Исполнитель→альбом→песня→назад на аккаунте; ограничения регионов |
| Регрессия радио | PASS: не менее трёх партий, дедупликация, single-flight, bounded error/retry, старый station/stream не перехватывает очередь; skip/finished/started однократны | rc2 NOT RUN; rc1 три партии ранее подтверждены отдельно | rc2 ≥3 различных сыгранных партий и звук, MPRIS Next не дублирует feedback |
| C: эксперимент | PASS: seed-детерминизм, исключения/разнообразие/оценка, малый/пустой пул, ограничение запросов, сбой источника, выключение в полёте, без radio/history, observed listening и retention | NOT RUN | Реальный микс и несколько сравнительных сессий с shuffle; качество не блокирует A/B |
| Сеть/ошибки | PASS: безопасные ошибки, async GUI, stale account/search/station guards; error одного раздела не останавливает плеер | NOT RUN | Реальная потеря сети/восстановление и повтор подгрузки; сетевой namespace sandbox запрещён |
| Размеры/масштаб | PASS: 1024×700, 1366×768, 1920×1080 при 1/1.25/1.5, также уменьшенная логическая область физических экранов; помеченные SYNTHETIC снимки | NOT RUN | Настоящий Wayland scale и keyboard/screen-reader приёмка |
| Пакет | PASS: полный makepkg/check(), 48 тестов, wheel/sdist, состав/ресурсы/зависимости/исключение секретов; pacman rc1-3→rc2-1 в изолированном root, launcher из другого cwd | NOT RUN на основной системе | Согласованное обновление, реальный launcher/меню, повторный запуск/закрытие |

## Автоматические результаты

48 unittest-проверок PASS в изолированной `.venv` (Python 3.13.13, PySide6 6.11.2, python-mpv 1.0.8, libmpv 0.41, SDK 3.2.0). Реальный libmpv использует локальный WAV и `ao=null`: это не слышимый звук. Secret Service и API в этих тестах заменены явными синтетическими объектами. Контракт D-Bus проверяется фактическим wire-format, но не передачей на настоящей шине.

QML lint и desktop-file-validate PASS. Геометрия проверяет центр относительно окна, непересечение с метаданными/громкостью и доступность основных кнопок. Старые реальные PNG в README прямо помечены как rc1; новых реальных снимков rc2 пока нет. GNOME-карточка не нарисована и не выдана за системный скриншот.

## Сборка и изолированная установка

Полный `makepkg --force --cleanbuild` завершился успешно, включая 48 тестов `check()` на Python 3.14.7. `--nodeps`/`--nocheck` не применялись. Объявленные SecretStorage/Jeepney распакованы только в `/tmp`; копия package database и отдельный build-venv обеспечили проверку зависимостей. Это накладка на текущую Manjaro Stable, а не чистая ОС.

В выводе fakeroot была строка `libfakeroot internal error: payload not recognized!`. Завершение сборки — 0; отдельно проверены все 470 записей архива: UID/GID 0, отсутствие записи для group/other, точные ресурсы приложения и метаданные. Эта диагностика не скрыта и подлежит повторной проверке в чистой среде.

Namcap: **0 ошибок, 40 предупреждений** для рецепта и пакета. [Разбор](docs/NAMCAP.md): необязательные extras неизменённого SDK, динамические Qt/mpv зависимости и ограничение изолированного пути SecretStorage/Jeepney. AppStream metainfo отсутствует — N/A, не PASS.

Настоящий pacman выполнил rc1-3→rc2-1 в отдельном root `/tmp/yanjaro-rc2-installed`. Синтетическая XDG-настройка сохранилась. Установленная команда запустила собственные QML/SDK/libmpv из постороннего cwd и закрылась. IPC и Secret Service в этом smoke заменены тестовыми объектами; ни пользовательский секрет, ни слышимый звук не проверялись. Основной пакет на момент этой проверки оставался rc1-3, новая установка требует отдельного согласования.

Контрольные суммы, точные артефакты и воспроизводимые команды — в [ARTIFACTS-rc2.md](docs/ARTIFACTS-rc2.md). Отчёт о результатах написан после сборки; содержимое замороженных артефактов не менялось ради добавления отчёта.

Wheel отдельно установлен в новый Python 3.13 venv с полным offline lock/hash-набором зависимостей. Его реальный entry point из `/tmp` загрузил установленные QML/SDK/libmpv и закрыл окно: PASS. Editable install и путь исходников для импортов не использовались; IPC/Secret Service в smoke — test doubles.

## Ограничения среды

Попытка отдельной тестовой D-Bus: BLOCKED, `Failed to bind socket: Operation not permitted`. Недоступность sandbox не означает отсутствия session bus на ноутбуке. Скрытая шина в приложение не добавлена. Реальная потеря сети: NOT RUN; обход ограничения сетевых namespace не выполняется.

Чистая Manjaro Stable VM / чистый Arch chroot: NOT RUN, такой среды нет. Очищенный каталог makepkg и изолированная накладка зависимостей не называются чистой ОС. Системные пакеты не изменяются без нового отдельного согласования.

## Зависимости и публикация

В локальной базе Manjaro Stable найдены python-secretstorage 3.5.0-1 и python-jeepney 0.9.0-3; они также подтверждены на официальных страницах [Arch SecretStorage](https://archlinux.org/packages/extra/any/python-secretstorage/) и [Arch Jeepney](https://archlinux.org/packages/extra/any/python-jeepney/). SecretStorage использует уже доступные cryptography/cffi. Точные Python wheels закреплены в requirements.lock, SHA-256 проверяется. MPRIS использует Qt QSocketNotifier и Jeepney; почему выбран этот вариант после проверки QtDBus — в DESKTOP-INTEGRATION.md.

PKGBUILD требует mpv>=0.41 для подтверждения playlist_entry_id при loadfile. Нативные зависимости не берутся из случайной dev-venv. SDK неизменённый и отдельно закреплённый. AUR-зависимостей нет. Публичный исходник/тег не выдумывается: рецепт ссылается на локальный snapshot с SHA-256. `.SRCINFO` генерируется makepkg.

История Яндекса, offline, lossless, Ynison, публичность/Release/AUR/merge остаются вне задания. PAMAC-поиск до публикации NOT RUN. Лицензия GPL-3.0-or-later сохранена. Установка rc1 не считается разрешением установить rc2.

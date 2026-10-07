# 0.2.0rc2 — этапы A / B / C

Исходный HEAD: `6296f657d8c4edeef5d583c4e212392ad556928f`, ветка `feature/desktop-ui-and-packaging`, чистый checkout `/tmp/yanjaro-git`. Файлы основной рабочей папки совпали побайтно с tracked-файлами Git; её защищённая `.git` не изменяется. Remote подтвердил тот же HEAD. Установлен `0.2.0rc1-3`. До изменений прошли 29 тестов; исходники сохранены `/tmp/yanjaro-before-rc2.tar.gz`. Новая ветка: `feature/player-polish-and-discovery`.

План небольших проверяемых изменений:

1. A: исправить наблюдаемое состояние mpv и общую модель команд; затем центрирование/один клик, конечные очереди, Secret Service и MPRIS.
2. B: классификация и локальный порядок станций, поиск сущностей и страницы исполнителей/альбомов с возвратом.
3. C: явно включаемый конечный экспериментальный микс, ограниченные запросы и локальные сигналы; качество отдельно от готовности A/B.
4. Кандидат, полная сборка, отдельная согласованная приёмка установленного приложения. Ни публикации, ни установки на основной системе без нового согласования.

## Причина play/pause

В rc1 `Controller._load_track` вызывал `Player.stop()`, который присваивал `paused=True`, не меняя свойство mpv `pause`. Если движок уже имел `pause=False`, следующая команда `set pause no` не создавала нового уведомления. Получался звук при оставшемся UI-состоянии паузы. Проверка с настоящим libmpv/WAV/`ao=null` и настоящим QML воспроизвела ошибку до исправления; это не проверка слышимого звука аккаунта.

Исправление: исходная синхронизация наблюдаемых свойств на `file-loaded`, отсутствие выдуманной паузы в `stop()`, Qt queued signals и привязка file lifecycle к `playlist_entry_id`. Сетевые поколения запроса сохранены отдельно. `loadfile` в фактическом mpv 0.41 возвращает ID до загрузки файла; подтверждено локальным probe без аккаунта/URL в выводе.

Контракты: [mpv](https://mpv.io/manual/stable/), [MPRIS Player](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html), [MPRIS root](https://specifications.freedesktop.org/mpris/latest/Media_Player.html), [QtDBus](https://doc.qt.io/qtforpython-6/PySide6/QtDBus/index.html), [Secret Service](https://specifications.freedesktop.org/secret-service/latest/), [keyring](https://keyring.readthedocs.io/en/stable/).
